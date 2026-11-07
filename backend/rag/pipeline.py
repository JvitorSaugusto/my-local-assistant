"""Ingestão incremental: varrer → comparar hashes → chunk → resumo → embedding → gravar."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .chunker import chunk_file
from .providers import Embedder, Summarizer
from .scanner import read_text, scan
from .store_base import VectorStore


@dataclass
class Progress:
    phase: str = "scan"
    files_total: int = 0
    files_done: int = 0
    chunks_done: int = 0
    current_file: str = ""
    skipped: dict[str, int] = field(default_factory=dict)


class IngestCancelled(Exception):
    pass


async def _notify(cb, progress: Progress) -> None:
    if cb is None:
        return
    result = cb(progress)
    if inspect.isawaitable(result):
        await result


async def ingest(
    store: VectorStore,
    embedder: Embedder,
    summarizer: Summarizer,
    source_id: int,
    root: str,
    *,
    max_file_bytes: int = 400_000,
    max_chunk_lines: int = 200,
    embed_batch: int = 16,
    force: bool = False,
    on_progress: Callable[[Progress], Awaitable[None] | None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Indexa `root` no `source_id`. Só reprocessa arquivos novos ou alterados."""
    progress = Progress()
    await _notify(on_progress, progress)

    files, skipped = await asyncio.to_thread(scan, root, max_file_bytes)
    progress.skipped = skipped
    known = {} if force else await store.file_hashes(source_id)
    current = {f.path: f for f in files}

    removed = [p for p in (await store.file_hashes(source_id)) if p not in current]
    if removed:
        await store.delete_files(source_id, removed)

    todo = [f for f in files if known.get(f.path) != f.sha1]
    progress.phase = "index"
    progress.files_total = len(todo)
    await _notify(on_progress, progress)

    chunks_total = 0
    for info in todo:
        if is_cancelled and is_cancelled():
            raise IngestCancelled()
        progress.current_file = info.path
        await _notify(on_progress, progress)

        text = await asyncio.to_thread(read_text, info.abs_path)
        chunks = chunk_file(info.path, text, info.language, max_chunk_lines)

        cached = await store.get_summaries([c.content_hash for c in chunks])
        for chunk in chunks:
            summary = cached.get(chunk.content_hash)
            if not summary:
                summary = await asyncio.to_thread(summarizer.summarize, chunk)
                cached[chunk.content_hash] = summary
            chunk.summary = summary

        vectors: list[list[float]] = []
        for i in range(0, len(chunks), embed_batch):
            batch = [c.embed_text() for c in chunks[i : i + embed_batch]]
            vectors.extend(await asyncio.to_thread(embedder.embed, batch))

        rows = [
            {
                "path": c.path, "language": c.language, "kind": c.kind, "qualname": c.qualname,
                "parent": c.parent, "start_line": c.start_line, "end_line": c.end_line,
                "part": c.part, "parts": c.parts, "content": c.code, "content_hash": c.content_hash,
                "summary": c.summary, "tag": c.tag(), "embedding": vec,
            }
            for c, vec in zip(chunks, vectors)
        ]
        await store.replace_file_chunks(source_id, info.path, info.sha1, info.language, rows)
        chunks_total += len(rows)
        progress.files_done += 1
        progress.chunks_done = chunks_total
        await _notify(on_progress, progress)

    progress.phase = "done"
    progress.current_file = ""
    await _notify(on_progress, progress)
    return {
        "files_scanned": len(files),
        "files_indexed": len(todo),
        "files_removed": len(removed),
        "chunks": chunks_total,
        "skipped": skipped,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }

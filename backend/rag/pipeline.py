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
    summary_concurrency: int = 2,
    force: bool = False,
    resummarize: bool = False,
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

    stale: set[str] = set()
    ai_kind = getattr(summarizer, "kind", "heuristic")
    if resummarize and not force and ai_kind != "heuristic":
        stale = set(await store.paths_with_other_summaries(source_id, ai_kind))
    todo = [f for f in files if known.get(f.path) != f.sha1 or f.path in stale]
    resummarized = [f.path for f in todo if f.path in stale and known.get(f.path) == f.sha1]
    progress.phase = "index"
    progress.files_total = len(todo)
    await _notify(on_progress, progress)

    summarizer_kind = getattr(summarizer, "kind", "heuristic")
    stats = {"new": 0, "cached": 0, "llm": 0, "fallback": 0}
    chunks_total = 0
    for info in todo:
        if is_cancelled and is_cancelled():
            raise IngestCancelled()
        progress.current_file = info.path
        await _notify(on_progress, progress)

        text = await asyncio.to_thread(read_text, info.abs_path)
        chunks = chunk_file(info.path, text, info.language, max_chunk_lines)

        # Resumo: reaproveita o que já existe do tipo atual (heurístico ou IA) e gera só o que falta,
        # com alguns resumos em paralelo. Um símbolo dividido em partes é resumido uma única vez.
        resolved: dict[str, tuple[str, str]] = dict(
            await store.get_summaries(list(dict.fromkeys(c.content_hash for c in chunks)), summarizer_kind)
        )
        stats["cached"] += len(resolved)
        missing = {c.content_hash: c for c in chunks if c.content_hash not in resolved}
        if missing:
            gate = asyncio.Semaphore(max(1, summary_concurrency))

            async def summarize_one(digest: str, chunk) -> None:
                async with gate:
                    text = await asyncio.to_thread(summarizer.summarize, chunk)
                    resolved[digest] = (str(text), getattr(text, "kind", summarizer_kind))

            await asyncio.gather(*(summarize_one(h, c) for h, c in missing.items()))
            for digest in missing:
                stats["new"] += 1
                if resolved[digest][1].startswith("llm:"):
                    stats["llm"] += 1
                elif summarizer_kind != "heuristic":
                    stats["fallback"] += 1
        for chunk in chunks:
            chunk.summary = resolved[chunk.content_hash][0]

        vectors: list[list[float]] = []
        for i in range(0, len(chunks), embed_batch):
            batch = [c.embed_text() for c in chunks[i : i + embed_batch]]
            vectors.extend(await asyncio.to_thread(embedder.embed, batch))

        rows = [
            {
                "path": c.path, "language": c.language, "kind": c.kind, "qualname": c.qualname,
                "parent": c.parent, "start_line": c.start_line, "end_line": c.end_line,
                "part": c.part, "parts": c.parts, "content": c.code, "content_hash": c.content_hash,
                "summary": c.summary, "summary_kind": resolved[c.content_hash][1],
                "tag": c.tag(), "embedding": vec,
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
        "summaries": {
            "kind": summarizer_kind, **stats, "resummarized_files": len(resummarized),
            "last_error": getattr(summarizer, "last_error", "") if stats["fallback"] else "",
        },
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }



def format_summary_note(info: dict) -> str:
    """Mensagem curta sobre os resumos de uma ingestão (aparece no job)."""
    text = f"Resumos ({info.get('kind', 'heuristic')}): {info.get('new', 0)} novos, {info.get('cached', 0)} reaproveitados."
    if info.get("llm"):
        text += f" {info['llm']} escritos pela IA."
    if info.get("resummarized_files"):
        text += f" {info['resummarized_files']} arquivo(s) sem alteração foram refeitos porque os resumos não eram da IA."
    if info.get("fallback"):
        text += f" ATENÇÃO: {info['fallback']} caíram para o resumo heurístico porque a IA falhou."
        if info.get("last_error"):
            text += f" Último erro: {info['last_error']}"
    return text[:900]

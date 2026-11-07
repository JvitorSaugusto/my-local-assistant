"""Fachada do RAG: a ÚNICA porta de entrada que o resto do sistema deve usar."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path

from .config import RagConfig, load_config
from .entities import SearchHit
from .pipeline import IngestCancelled, Progress, ingest
from .providers import Embedder, HeuristicSummarizer, OllamaEmbedder, OllamaSummarizer, Summarizer
from .repo_map import build_repo_map
from .search import format_hits, hybrid_search
from .store_base import VectorStore
from .zip_utils import safe_extract_zip, single_top_folder

ACTIVE = {"queued", "running"}


class RagUnavailable(RuntimeError):
    pass


def _norm(path: str) -> str:
    return str(Path(path).expanduser().resolve())


class RagService:
    def __init__(
        self,
        cfg: RagConfig | None = None,
        store: VectorStore | None = None,
        embedder: Embedder | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        self.cfg = cfg or load_config()
        self._store = store
        self._embedder = embedder
        self._summarizer = summarizer
        self._ready = False
        self._reason = ""
        self._tasks: set[asyncio.Task] = set()
        self._cancel: dict[int, bool] = {}

    # ── componentes (criados sob demanda) ────────────────────────────────
    @property
    def store(self) -> VectorStore:
        if self._store is None:
            from .store_pg import PgVectorStore

            self._store = PgVectorStore(self.cfg.database_url, self.cfg.embed_dim)
        return self._store

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = OllamaEmbedder(self.cfg.ollama_url, self.cfg.embed_model, self.cfg.embed_dim)
        return self._embedder

    @property
    def summarizer(self) -> Summarizer:
        if self._summarizer is None:
            self._summarizer = (
                OllamaSummarizer(self.cfg.ollama_url, self.cfg.summary_model)
                if self.cfg.summary_model
                else HeuristicSummarizer()
            )
        return self._summarizer

    # ── ciclo de vida ────────────────────────────────────────────────────
    async def startup(self) -> bool:
        await self._ensure_ready()
        stale = await self.store.fail_stale_jobs()
        if stale:
            print(f"ℹ️ [RAG] {stale} ingestão(ões) interrompida(s) por reinício do servidor.")
        return True

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        try:
            await self.store.ensure_schema()
        except Exception as exc:  # noqa: BLE001
            self._reason = str(exc)
            raise RagUnavailable(self._reason) from exc
        self._ready = True

    # ── ingestão ─────────────────────────────────────────────────────────
    async def ingest_workspace(self, path: str, name: str | None = None, force: bool = False) -> dict:
        root = Path(path).expanduser()
        if not root.is_dir():
            raise ValueError(f"Pasta não encontrada: {path}")
        resolved = _norm(str(root))
        await self._ensure_ready()
        existing = await self.store.find_source(root_path=resolved)
        source_name = (existing["name"] if existing else None) or (name or "").strip() or root.resolve().name
        source_id = await self.store.upsert_source(source_name, "workspace", resolved)
        return await self._start(source_id, resolved, force=force)

    async def ingest_zip(self, zip_path: str, name: str, force: bool = False) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("Informe um nome para a fonte.")
        await self._ensure_ready()
        work = Path(self.cfg.work_dir).resolve() / uuid.uuid4().hex
        try:
            await asyncio.to_thread(safe_extract_zip, zip_path, str(work), self.cfg.zip_max_bytes, self.cfg.zip_max_files)
        except Exception:
            shutil.rmtree(work, ignore_errors=True)
            Path(zip_path).unlink(missing_ok=True)
            raise
        Path(zip_path).unlink(missing_ok=True)
        root = single_top_folder(str(work))
        source_id = await self.store.upsert_source(name, "zip", None)
        return await self._start(source_id, root, force=force, cleanup=lambda: shutil.rmtree(work, ignore_errors=True))

    async def _start(self, source_id: int, root: str, force: bool, cleanup=None) -> dict:
        last = await self.store.latest_job(source_id)
        if last and last["status"] in ACTIVE and any(not t.done() for t in self._tasks):
            if cleanup:
                cleanup()
            raise ValueError("Já existe uma ingestão em andamento para esta fonte.")
        job_id = await self.store.create_job(source_id)
        task = asyncio.create_task(self._run_job(job_id, source_id, root, force, cleanup))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return {"source_id": source_id, "job_id": job_id}

    async def _run_job(self, job_id: int, source_id: int, root: str, force: bool, cleanup) -> None:
        store = self.store

        async def on_progress(p: Progress) -> None:
            await store.update_job(job_id, status="running", phase=p.phase, files_total=p.files_total,
                                   files_done=p.files_done, chunks_done=p.chunks_done, current_file=p.current_file)

        try:
            await store.update_job(job_id, status="running", phase="scan")
            await ingest(
                store, self.embedder, self.summarizer, source_id, root,
                max_file_bytes=self.cfg.max_file_bytes, max_chunk_lines=self.cfg.max_chunk_lines,
                embed_batch=self.cfg.embed_batch, force=force, on_progress=on_progress,
                is_cancelled=lambda: self._cancel.get(job_id, False),
            )
            await store.update_job(job_id, status="done", phase="done", current_file="", error=None)
        except IngestCancelled:
            await store.update_job(job_id, status="cancelled", current_file="")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ [RAG] ingestão {job_id} falhou: {exc}")
            await store.update_job(job_id, status="failed", error=str(exc)[:2000])
        finally:
            self._cancel.pop(job_id, None)
            if cleanup:
                cleanup()

    async def cancel(self, job_id: int) -> bool:
        job = await self.store.get_job(job_id)
        if not job or job["status"] not in ACTIVE:
            return False
        self._cancel[job_id] = True
        return True

    # ── consulta ─────────────────────────────────────────────────────────
    async def list_sources(self) -> list[dict]:
        await self._ensure_ready()
        return await self.store.list_sources()

    async def status(self, source_id: int) -> dict | None:
        await self._ensure_ready()
        sources = {s["id"]: s for s in await self.store.list_sources()}
        source = sources.get(source_id)
        if not source:
            return None
        return {"source": source, "job": await self.store.latest_job(source_id)}

    async def delete_source(self, source_id: int) -> None:
        await self._ensure_ready()
        await self.store.delete_source(source_id)

    async def repo_map(self, source_id: int) -> str:
        await self._ensure_ready()
        return build_repo_map(await self.store.outline(source_id))

    async def find_source_for_workspace(self, workspace: str) -> dict | None:
        await self._ensure_ready()
        return await self.store.find_source(root_path=_norm(workspace))

    async def search(
        self, query: str, source_id: int | None = None, workspace: str | None = None,
        limit: int = 8, path_prefix: str | None = None,
    ) -> list[SearchHit]:
        await self._ensure_ready()
        if source_id is not None:
            ids = [source_id]
        elif workspace:
            source = await self.store.find_source(root_path=_norm(workspace))
            ids = [source["id"]] if source else []
        else:
            ids = [s["id"] for s in await self.store.list_sources()]
        return await hybrid_search(self.store, self.embedder, query, ids, limit=limit, path_prefix=path_prefix)

    async def context_for_workspace(self, workspace: str, query: str, limit: int = 6, max_chars: int = 6000) -> str:
        """Texto pronto para o prompt do agente; vazio se o workspace não foi indexado."""
        source = await self.find_source_for_workspace(workspace)
        if not source:
            return ""
        hits = await hybrid_search(self.store, self.embedder, query, [source["id"]], limit=limit)
        return format_hits(hits, max_chars=max_chars) if hits else ""


_service: RagService | None = None


def get_service() -> RagService:
    global _service
    if _service is None:
        _service = RagService()
    return _service


def new_upload_path(work_dir: str) -> str:
    folder = Path(work_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    handle, path = tempfile.mkstemp(suffix=".zip", dir=str(folder))
    import os

    os.close(handle)
    return path

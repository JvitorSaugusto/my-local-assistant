"""Fachada do RAG: a ÚNICA porta de entrada que o resto do sistema deve usar."""

from __future__ import annotations

import asyncio
import shutil
import time
import tempfile
import uuid
from pathlib import Path

from .config import RagConfig, load_config
from .entities import SearchHit
from .pipeline import IngestCancelled, Progress, format_summary_note, ingest
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
        self._last_refresh: dict[str, float] = {}
        self._refreshing: set[str] = set()

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
                OllamaSummarizer(
                    self.cfg.ollama_url, self.cfg.summary_model, self.cfg.summary_timeout, self.cfg.summary_think
                )
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
        info = await self.summarizer_info()
        if info["mode"] == "ia":
            print(f"ℹ️ [RAG] resumos escritos por IA: {info['kind']} (think={info.get('think')})")
        else:
            print("ℹ️ [RAG] resumos HEURÍSTICOS (RAG_SUMMARY_MODEL vazio: sem IA)")
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
            warning = await self._probe_summarizer()
            if warning:
                await store.update_job(job_id, note=warning)
            result = await ingest(
                store, self.embedder, self.summarizer, source_id, root,
                max_file_bytes=self.cfg.max_file_bytes, max_chunk_lines=self.cfg.max_chunk_lines,
                embed_batch=self.cfg.embed_batch, summary_concurrency=self.cfg.summary_concurrency,
                force=force, resummarize=True, on_progress=on_progress,
                is_cancelled=lambda: self._cancel.get(job_id, False),
            )
            note = format_summary_note(result["summaries"])
            if warning:
                note = f"{warning} {note}"
            if result["summaries"].get("fallback") or warning:
                print(f"⚠️ [RAG] {note}")
            await store.update_job(job_id, status="done", phase="done", current_file="", error=None, note=note)
        except IngestCancelled:
            await store.update_job(job_id, status="cancelled", current_file="")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ [RAG] ingestão {job_id} falhou: {exc}")
            await store.update_job(job_id, status="failed", error=str(exc)[:2000])
        finally:
            self._cancel.pop(job_id, None)
            if cleanup:
                cleanup()

    async def _probe_summarizer(self) -> str:
        """Antes de ingerir: se a IA de resumos está configurada mas não responde, avisa e a desliga nesta rodada."""
        summarizer = self.summarizer
        reset = getattr(summarizer, "reset", None)
        if reset:
            reset()
        probe = getattr(summarizer, "probe", None)
        if not probe:
            return ""
        ok, message = await asyncio.to_thread(probe)
        if ok:
            return ""
        summarizer.disabled = True  # type: ignore[attr-defined]
        return (
            f"⚠️ IA de resumos indisponível ({message}). Esta ingestão usou o resumo heurístico; "
            "corrija a configuração e clique em Reindexar."
        )

    async def summarizer_info(self) -> dict:
        summarizer = self.summarizer
        describe = getattr(summarizer, "describe", None)
        info = describe() if describe else {"kind": getattr(summarizer, "kind", "heuristic")}
        info["mode"] = "ia" if str(info.get("kind", "")).startswith("llm:") else "heuristico"
        return info

    async def test_summarizer(self) -> dict:
        """Teste ao vivo do resumidor (usado pelo botão 'Testar resumidor')."""
        info = await self.summarizer_info()
        if info["mode"] != "ia":
            info["ok"] = False
            info["message"] = "RAG_SUMMARY_MODEL está vazio: só o resumo heurístico é usado. Defina a variável no .env e reinicie o servidor."
            return info
        ok, message = await asyncio.to_thread(self.summarizer.probe)  # type: ignore[attr-defined]
        info["ok"] = ok
        info["message"] = "A IA respondeu normalmente." if ok else message
        return info

    async def cancel(self, job_id: int) -> bool:
        job = await self.store.get_job(job_id)
        if not job or job["status"] not in ACTIVE:
            return False
        self._cancel[job_id] = True
        return True

    # ── consulta ─────────────────────────────────────────────────────────
    async def list_sources(self, with_summaries: bool = False) -> list[dict]:
        await self._ensure_ready()
        sources = await self.store.list_sources()
        if with_summaries:
            for source in sources:
                source["summaries"] = await self.store.summary_counts(source["id"])
        return sources

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
        """Texto pronto para o prompt do agente (escopo padrão do projeto); vazio se não houver fonte nem trecho."""
        sources, _label = await self.resolve_scope(workspace)
        if not sources:
            return ""
        hits = await hybrid_search(self.store, self.embedder, query, [s["id"] for s in sources], limit=limit)
        return format_hits(hits, max_chars=max_chars) if hits else ""

    # ── escopo: QUAIS fontes o agente consulta ───────────────────────────
    async def _source_by_name(self, name: str) -> dict | None:
        wanted = name.strip().lower()
        for source in await self.store.list_sources():
            if source["name"].lower() == wanted:
                return source
        return None

    async def resolve_scope(self, workspace: str | None, source: str | None = None) -> tuple[list[dict], str]:
        """(fontes, descrição). `source` vazio = projeto ativo + fontes vinculadas; 'all' = todas; senão, o NOME de uma fonte."""
        await self._ensure_ready()
        sources = await self.store.list_sources()
        key = (source or "").strip()
        if key.lower() in {"all", "todas", "*"}:
            return sources, "todas as fontes indexadas"
        if key:
            found = await self._source_by_name(key)
            if not found:
                names = ", ".join(f"'{s['name']}'" for s in sources) or "nenhuma"
                raise ValueError(f"Fonte '{key}' não existe. Fontes disponíveis: {names}.")
            return [found], f"fonte '{found['name']}'"

        chosen: list[dict] = []
        if workspace:
            root = _norm(workspace)
            own = await self.store.find_source(root_path=root)
            if own:
                chosen.append(own)
            by_id = {s["id"]: s for s in sources}
            for linked_id in await self.store.get_workspace_links(root):
                if linked_id in by_id and all(c["id"] != linked_id for c in chosen):
                    chosen.append(by_id[linked_id])
        return chosen, "projeto ativo" + (" + fontes vinculadas" if len(chosen) > 1 else "")

    async def search_scoped(
        self, query: str, workspace: str | None = None, source: str | None = None,
        limit: int = 8, path_prefix: str | None = None,
    ) -> tuple[list[SearchHit], str, list[dict]]:
        sources, label = await self.resolve_scope(workspace, source)
        hits = await hybrid_search(
            self.store, self.embedder, query, [s["id"] for s in sources], limit=limit, path_prefix=path_prefix
        )
        return hits, label, sources

    async def overview(self, workspace: str | None) -> str:
        """Lista curta das fontes: o agente fica sabendo o que existe e o que é consultado por padrão."""
        sources = await self.list_sources()
        if not sources:
            return ""
        default_ids = {s["id"] for s in (await self.resolve_scope(workspace))[0]}
        lines = []
        for s in sources:
            note = "consultada por padrão" if s["id"] in default_ids else f'para consultar use source="{s["name"]}"'
            lines.append(f"- {s['name']} ({s['kind']}, {s['files']} arquivos): {note}")
        return "\n".join(lines)

    async def set_links(self, workspace: str, source_ids: list[int]) -> list[int]:
        await self._ensure_ready()
        root = _norm(workspace)
        valid = {s["id"] for s in await self.store.list_sources()}
        own = await self.store.find_source(root_path=root)
        ids = [i for i in dict.fromkeys(source_ids) if i in valid and not (own and own["id"] == i)]
        await self.store.set_workspace_links(root, ids)
        return ids

    async def get_links(self, workspace: str) -> list[int]:
        await self._ensure_ready()
        return await self.store.get_workspace_links(_norm(workspace))

    async def scope_info(self, workspace: str | None) -> dict:
        """Tudo que o seletor de fontes precisa: fonte do projeto, vínculos e todas as fontes."""
        await self._ensure_ready()
        sources = await self.store.list_sources()
        own = None
        linked: list[int] = []
        if workspace and workspace.strip():
            root = _norm(workspace)
            own_row = await self.store.find_source(root_path=root)
            if own_row:
                own = {"id": own_row["id"], "name": own_row["name"]}
            valid = {s["id"] for s in sources}
            linked = [
                i for i in await self.store.get_workspace_links(root)
                if i in valid and not (own and own["id"] == i)
            ]
        return {
            "own": own,
            "linked_ids": linked,
            "sources": [
                {"id": s["id"], "name": s["name"], "kind": s["kind"], "files": s["files"], "chunks": s["chunks"]}
                for s in sorted(sources, key=lambda s: s["name"].lower())
            ],
        }

    # ── manter o índice atualizado ───────────────────────────────────────
    async def refresh_workspace(self, workspace: str, min_interval: float = 60.0, timeout: float = 25.0) -> dict | None:
        """Atualização incremental e SÍNCRONA do índice do workspace (só o que mudou).

        Tem trava de intervalo (no máximo 1 varredura por `min_interval` s), não sobrepõe uma ingestão em
        andamento, respeita um tempo limite e nunca levanta erro. Devolve o resumo ou None se nada foi feito.
        """
        try:
            root = _norm(workspace)
            now = time.monotonic()
            if root in self._refreshing or now - self._last_refresh.get(root, -1e9) < min_interval:
                return None
            await self._ensure_ready()
            source = await self.store.find_source(root_path=root)
            if not source or not Path(root).is_dir():
                return None
            last = await self.store.latest_job(source["id"])
            if last and last["status"] in ACTIVE and any(not t.done() for t in self._tasks):
                return None
            self._refreshing.add(root)
            self._last_refresh[root] = now
            try:
                return await asyncio.wait_for(
                    ingest(
                        self.store, self.embedder, self.summarizer, source["id"], root,
                        max_file_bytes=self.cfg.max_file_bytes, max_chunk_lines=self.cfg.max_chunk_lines,
                        embed_batch=self.cfg.embed_batch, summary_concurrency=self.cfg.summary_concurrency,
                    ),
                    timeout,
                )
            finally:
                self._refreshing.discard(root)
        except asyncio.TimeoutError:
            print("ℹ️ [RAG] a atualização do índice passou do tempo limite; continua na próxima consulta.")
            return None
        except Exception as exc:  # noqa: BLE001
            print(f"ℹ️ [RAG] não foi possível atualizar o índice: {exc}")
            return None


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

"""Orquestrador sequencial em asyncio para a Fila Rápida (por thread_id).

Roda os comandos estritamente um por vez no mesmo `thread_id`, reutilizando `run_graph_live`
(pensamento ao vivo + cancelamento) e respeitando `preset`, arquivos vinculados e `stop_on_error`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig

from backend.api.live_thoughts import run_graph_live
from backend.graph.config import State
from backend.graph.node_helpers import now_iso

_IGNORED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compose_queue_prompt(prompt: str, files: list[str] | None = None) -> str:
    """Combina o texto do comando com os arquivos vinculados (workspace ou uploads globais)."""
    base = str(prompt or "").strip()
    clean_files = [str(f).strip() for f in (files or []) if str(f).strip()]
    if not clean_files:
        return base
    global_only = all(f.startswith("@global/") for f in clean_files)
    hint = (
        "leia com read_attachment"
        if global_only
        else "leia com read_file_content, read_file_chunk ou read_attachment"
    )
    listing = "\n".join(f"- {path}" for path in clean_files)
    return f"{base}\n\n[Arquivos vinculados a este passo] ({hint}):\n{listing}"


def list_workspace_files(workspace_path: str, query: str = "", limit: int = 80) -> list[str]:
    """Lista arquivos relativos do workspace (filtrados por substring) para o seletor da Fila Rápida."""
    if not workspace_path or not str(workspace_path).strip():
        return []
    root = Path(workspace_path).expanduser().resolve()
    if not root.is_dir():
        return []

    q = str(query or "").strip().lower()
    results: list[str] = []
    stack = [root]
    while stack and len(results) < limit:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            continue
        dirs_to_visit: list[Path] = []
        for entry in entries:
            name = entry.name
            if entry.is_dir():
                if name in _IGNORED_DIRS or name.startswith("."):
                    continue
                dirs_to_visit.append(entry)
            elif entry.is_file():
                rel = entry.relative_to(root).as_posix()
                if not q or q in rel.lower():
                    results.append(rel)
                    if len(results) >= limit:
                        break
        for d in reversed(dirs_to_visit):
            stack.append(d)
    return results


@dataclass
class QueueItemState:
    index: int
    prompt: str
    files: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed | cancelled
    elapsed_seconds: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "prompt": self.prompt,
            "files": list(self.files),
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
        }


@dataclass
class QueueRunState:
    thread_id: str
    workspace_path: str
    preset: str = "default"
    stop_on_error: bool = True
    running: bool = False
    stop_requested: bool = False
    started_at: str = field(default_factory=_utc_iso)
    finished_at: str | None = None
    items: list[QueueItemState] = field(default_factory=list)
    runner_task: asyncio.Task | None = None
    current_graph_task: asyncio.Task | None = None

    def to_dict(self) -> dict[str, Any]:
        total = len(self.items)
        done = sum(1 for i in self.items if i.status == "done")
        failed = sum(1 for i in self.items if i.status == "failed")
        cancelled = sum(1 for i in self.items if i.status == "cancelled")
        running_idx = next((i.index for i in self.items if i.status == "running"), None)
        return {
            "thread_id": self.thread_id,
            "running": self.running,
            "stop_on_error": self.stop_on_error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": total,
            "done": done,
            "failed": failed,
            "cancelled": cancelled,
            "running_index": running_idx,
            "items": [i.to_dict() for i in self.items],
        }


class QuickQueueManager:
    def __init__(self) -> None:
        self._runs: dict[str, QueueRunState] = {}

    def get_status(self, thread_id: str) -> dict[str, Any]:
        run = self._runs.get(thread_id)
        if not run:
            return {
                "thread_id": thread_id,
                "running": False,
                "total": 0,
                "done": 0,
                "failed": 0,
                "cancelled": 0,
                "running_index": None,
                "items": [],
            }
        return run.to_dict()

    def is_running(self, thread_id: str) -> bool:
        run = self._runs.get(thread_id)
        return bool(run and run.running)

    async def start(
        self,
        app_graph: Any,
        thread_id: str,
        items: list[dict[str, Any]],
        workspace_path: str,
        preset: str = "default",
        stop_on_error: bool = True,
        running_registry: dict[str, asyncio.Task] | None = None,
    ) -> dict[str, Any]:
        if self.is_running(thread_id):
            raise ValueError("Já existe uma Fila Rápida em execução nesta conversa. Pare a atual antes de iniciar outra.")

        clean_items: list[QueueItemState] = []
        for idx, raw in enumerate(items):
            prompt = str(raw.get("prompt", "")).strip()
            files = [str(f).strip() for f in (raw.get("files") or []) if str(f).strip()]
            if not prompt:
                continue
            clean_items.append(QueueItemState(index=idx, prompt=prompt, files=files))

        if not clean_items:
            raise ValueError("Nenhum comando válido na fila.")

        run = QueueRunState(
            thread_id=thread_id,
            workspace_path=workspace_path,
            preset=preset or "default",
            stop_on_error=stop_on_error,
            running=True,
            items=clean_items,
        )
        self._runs[thread_id] = run
        run.runner_task = asyncio.create_task(self._execute_loop(app_graph, run, running_registry))
        return run.to_dict()

    async def stop(self, thread_id: str) -> dict[str, Any]:
        run = self._runs.get(thread_id)
        if not run or not run.running:
            return {"stopped": False, "queue": self.get_status(thread_id)}
        run.stop_requested = True
        if run.current_graph_task and not run.current_graph_task.done():
            run.current_graph_task.cancel()
        if run.runner_task and not run.runner_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(run.runner_task), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
        return {"stopped": True, "queue": run.to_dict()}

    async def _execute_loop(
        self,
        app_graph: Any,
        run: QueueRunState,
        running_registry: dict[str, asyncio.Task] | None = None,
    ) -> None:
        config: RunnableConfig = {"configurable": {"thread_id": run.thread_id}}
        try:
            for item in run.items:
                if run.stop_requested:
                    item.status = "cancelled"
                    continue

                item.status = "running"
                started = time.perf_counter()
                full_message = compose_queue_prompt(item.prompt, item.files)
                inputs = cast(
                    State,
                    {
                        "messages": [
                            HumanMessage(
                                content=full_message,
                                additional_kwargs={"created_at": now_iso()},
                            )
                        ],
                        "thread_id": run.thread_id,
                        "workspace_path": run.workspace_path,
                        "preset": run.preset,
                    },
                )

                task = asyncio.create_task(run_graph_live(app_graph, inputs, config, run.thread_id))
                run.current_graph_task = task
                if running_registry is not None:
                    running_registry[run.thread_id] = task

                try:
                    await task
                    item.elapsed_seconds = round(time.perf_counter() - started, 1)
                    item.status = "done"
                except asyncio.CancelledError:
                    item.elapsed_seconds = round(time.perf_counter() - started, 1)
                    item.status = "cancelled"
                    run.stop_requested = True
                except Exception as exc:  # noqa: BLE001
                    item.elapsed_seconds = round(time.perf_counter() - started, 1)
                    item.status = "failed"
                    item.error = str(exc)[:500]
                    if run.stop_on_error:
                        for remaining in run.items:
                            if remaining.status == "pending":
                                remaining.status = "cancelled"
                        break
                finally:
                    if running_registry is not None and running_registry.get(run.thread_id) is task:
                        running_registry.pop(run.thread_id, None)
                    run.current_graph_task = None
        finally:
            run.running = False
            run.finished_at = _utc_iso()


quick_queue_manager = QuickQueueManager()

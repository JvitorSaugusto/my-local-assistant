"""Gerenciador assíncrono isolado de execuções em segundo plano do Modo Autônomo.

Mantém no máximo 1 loop ativo por missão e por workspace (evitando conflito de branches Git),
executa cada ciclo determinístico em thread separada (`asyncio.to_thread`) para nunca travar
o event loop do FastAPI e reconcilia missões interrompidas no startup/shutdown.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Callable

from .runner import AutonomousEngine
from .schemas import MissionConfig, MissionMode, MissionRecord, MissionStatus
from .state_machine import TERMINAL_STATUSES, calculate_progress


class MissionConflictError(RuntimeError):
    """Lançada quando já existe uma execução ativa para a mesma missão ou workspace."""


class AutonomousManager:
    """Coordena execução em segundo plano, pausa cooperativa e recuperação no startup."""

    def __init__(self, engine: AutonomousEngine | None = None) -> None:
        self.engine = engine or AutonomousEngine()
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_by_workspace: dict[str, str] = {}
        self._stop_flags: dict[str, threading.Event] = {}

    def _ws_key(self, workspace_path: str) -> str:
        return str(Path(workspace_path).expanduser().resolve()).lower()

    def is_running(self, mission_id: str) -> bool:
        task = self._tasks.get(mission_id)
        return bool(task and not task.done())

    def active_mission_ids(self) -> list[str]:
        return [mid for mid, task in list(self._tasks.items()) if not task.done()]

    def startup_reconcile(self) -> list[str]:
        """Pausa com segurança missões que ficaram ativas após queda/reinício do servidor."""
        return self.engine.reconcile_interrupted_missions()

    async def shutdown(self) -> None:
        """Sinaliza pausa cooperativa e aguarda o encerramento limpo das tasks ativas."""
        for mid in list(self._tasks.keys()):
            flag = self._stop_flags.get(mid)
            if flag:
                flag.set()
            try:
                self.engine.pause_mission(mid)
            except Exception:  # noqa: BLE001
                pass
        pending = [t for t in self._tasks.values() if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def create_and_preflight(
        self,
        *,
        title: str,
        objective: str,
        workspace_path: str,
        business_rules: list[str] | None = None,
        conventions: list[str] | None = None,
        mode: MissionMode | None = None,
        config: MissionConfig | None = None,
        auto_apply_mode: bool = True,
    ) -> MissionRecord:
        mission = self.engine.create_mission(
            title=title,
            objective=objective,
            workspace_path=workspace_path,
            business_rules=business_rules,
            conventions=conventions,
            mode=mode,
            config=config,
        )
        return self.engine.run_preflight(mission.id, auto_apply_mode=auto_apply_mode)

    def start_background(self, mission_id: str, *, max_loop_ticks: int = 200) -> MissionRecord:
        """Inicia o loop determinístico em segundo plano para a missão."""
        mission = self.engine.store.get(mission_id)
        if mission is None:
            raise KeyError(f"Missão '{mission_id}' não encontrada.")

        if mission.status in TERMINAL_STATUSES:
            raise ValueError(f"Missão já encerrada em '{mission.status.value}'.")
        if mission.status == MissionStatus.WAITING_CONFIRMATION:
            raise ValueError("Missão aguarda confirmação do Pre-flight antes de iniciar.")
        if mission.status == MissionStatus.PHASE_GATE:
            raise ValueError("Missão aguarda aprovação do Phase Gate antes de continuar.")
        if mission.status == MissionStatus.PAUSED:
            mission = self.engine.resume_mission(mission_id)

        if self.is_running(mission_id):
            return mission

        ws_key = self._ws_key(mission.workspace_path)
        other_id = self._active_by_workspace.get(ws_key)
        if other_id and other_id != mission_id and self.is_running(other_id):
            raise MissionConflictError(
                f"Já existe outra missão ativa ('{other_id}') neste mesmo workspace. "
                "Pause ou aguarde o término antes de iniciar outra."
            )

        stop_event = threading.Event()
        self._stop_flags[mission_id] = stop_event
        self._active_by_workspace[ws_key] = mission_id

        loop = asyncio.get_running_loop()
        task = loop.create_task(
            self._run_loop_async(mission_id, ws_key, stop_event, max_loop_ticks=max_loop_ticks),
            name=f"autonomous-{mission_id}",
        )
        self._tasks[mission_id] = task
        return mission

    async def _run_loop_async(
        self,
        mission_id: str,
        ws_key: str,
        stop_event: threading.Event,
        *,
        max_loop_ticks: int = 200,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._run_loop_sync,
                mission_id,
                stop_event,
                max_loop_ticks,
            )
        except Exception as exc:  # noqa: BLE001 - nunca derruba o servidor
            mission = self.engine.store.get(mission_id)
            if mission is not None and mission.status not in TERMINAL_STATUSES:
                mission.last_error = f"Erro inesperado no worker autônomo: {exc}"
                self.engine.store.save(mission)
                self.engine.store.append_event(
                    mission_id,
                    "worker_error",
                    f"Execução interrompida por erro inesperado: {exc}",
                )
        finally:
            if self._active_by_workspace.get(ws_key) == mission_id:
                self._active_by_workspace.pop(ws_key, None)
            self._stop_flags.pop(mission_id, None)
            current = self._tasks.get(mission_id)
            if current is asyncio.current_task():
                self._tasks.pop(mission_id, None)

    def _run_loop_sync(
        self,
        mission_id: str,
        stop_event: threading.Event,
        max_loop_ticks: int,
    ) -> MissionRecord:
        stop_statuses = {
            MissionStatus.PAUSED,
            MissionStatus.WAITING_CONFIRMATION,
            MissionStatus.PHASE_GATE,
        }
        for _ in range(max_loop_ticks):
            if stop_event.is_set():
                break
            mission = self.engine.store.get(mission_id)
            if mission is None or mission.status in stop_statuses or mission.status in TERMINAL_STATUSES:
                break
            before_prog = calculate_progress(mission)
            before_sig = (
                mission.status,
                mission.tasks_executed,
                mission.review_cycles_used,
                len(mission.phases),
                before_prog.done_items,
                before_prog.blocked_items,
            )
            after = self.engine.step_once(mission_id)
            after_prog = calculate_progress(after)
            after_sig = (
                after.status,
                after.tasks_executed,
                after.review_cycles_used,
                len(after.phases),
                after_prog.done_items,
                after_prog.blocked_items,
            )
            if after_sig == before_sig:
                break
        final = self.engine.store.get(mission_id)
        if final is None:
            raise KeyError(f"Missão '{mission_id}' não encontrada.")
        return final

    def pause(self, mission_id: str) -> MissionRecord:
        flag = self._stop_flags.get(mission_id)
        if flag:
            flag.set()
        return self.engine.pause_mission(mission_id)

    def cancel(self, mission_id: str) -> MissionRecord:
        flag = self._stop_flags.get(mission_id)
        if flag:
            flag.set()
        return self.engine.cancel_mission(mission_id)

    def delete(self, mission_id: str) -> bool:
        if self.is_running(mission_id):
            raise MissionConflictError("Pause ou cancele a missão antes de excluí-la.")
        return self.engine.store.delete(mission_id)

    async def wait_mission(self, mission_id: str, timeout: float = 10.0) -> MissionRecord | None:
        """Utilitário para testes/diagnóstico aguardarem o término de uma execução ativa."""
        task = self._tasks.get(mission_id)
        if task and not task.done():
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return self.engine.store.get(mission_id)


autonomous_manager = AutonomousManager()

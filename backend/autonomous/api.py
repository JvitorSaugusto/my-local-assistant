"""Endpoints FastAPI isolados do Modo Autônomo (`/api/autonomous`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from .manager import AutonomousManager, MissionConflictError, autonomous_manager
from .schemas import MissionConfig, MissionMode, MissionRecord, MissionStatus
from .state_machine import InvalidTransitionError, calculate_progress


class CreateMissionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=160)
    objective: str = Field(min_length=5)
    workspace_path: str = Field(min_length=1)
    business_rules: list[str] = Field(default_factory=list)
    conventions: list[str] = Field(default_factory=list)
    mode: MissionMode | None = None
    auto_apply_mode: bool = True
    auto_start: bool = False
    config: MissionConfig = Field(default_factory=MissionConfig)


class ConfirmPreflightPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_mode: MissionMode | None = None
    extra_business_rules: list[str] = Field(default_factory=list)
    extra_conventions: list[str] = Field(default_factory=list)
    auto_start: bool = True


class ActionStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_start: bool = True


def _serialize_mission(mission: MissionRecord, manager: AutonomousManager) -> dict[str, Any]:
    progress = calculate_progress(mission)
    data = mission.model_dump(mode="json")
    data["progress"] = progress.model_dump(mode="json")
    data["is_running"] = manager.is_running(mission.id)
    data["has_report"] = bool(mission.report_path and Path(mission.report_path).is_file())
    return data


def create_autonomous_router(manager: AutonomousManager | None = None) -> APIRouter:
    """Factory do router (permite injeção de manager isolado em testes)."""
    mgr = manager or autonomous_manager
    router = APIRouter()

    @router.get("/missions")
    async def list_missions(
        workspace_path: str | None = Query(default=None),
        status: MissionStatus | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        resolved_ws = str(Path(workspace_path).expanduser().resolve()) if workspace_path else None
        missions = mgr.engine.store.list_missions(
            workspace_path=resolved_ws,
            status=status,
            limit=limit,
        )
        return {
            "missions": [_serialize_mission(m, mgr) for m in missions],
            "active_ids": mgr.active_mission_ids(),
        }

    @router.post("/missions")
    async def create_mission(payload: CreateMissionPayload):
        mission = mgr.create_and_preflight(
            title=payload.title,
            objective=payload.objective,
            workspace_path=payload.workspace_path,
            business_rules=payload.business_rules,
            conventions=payload.conventions,
            mode=payload.mode,
            config=payload.config,
            auto_apply_mode=payload.auto_apply_mode if payload.mode is None else False,
        )
        if payload.auto_start and mission.status == MissionStatus.PLANNING:
            try:
                mission = mgr.start_background(mission.id)
            except MissionConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.get("/missions/{mission_id}")
    async def get_mission(mission_id: str):
        mission = mgr.engine.store.get(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Missão não encontrada.")
        return _serialize_mission(mission, mgr)

    @router.get("/missions/{mission_id}/events")
    async def get_mission_events(mission_id: str, limit: int = Query(default=100, ge=1, le=500)):
        mission = mgr.engine.store.get(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Missão não encontrada.")
        return {"events": mgr.engine.store.list_events(mission_id, limit=limit)}

    @router.get("/missions/{mission_id}/report")
    async def get_mission_report(mission_id: str, raw: bool = Query(default=False)):
        mission = mgr.engine.store.get(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Missão não encontrada.")
        if not mission.report_path or not Path(mission.report_path).is_file():
            raise HTTPException(status_code=404, detail="Relatório ainda não foi gerado para esta missão.")
        content = Path(mission.report_path).read_text(encoding="utf-8", errors="replace")
        if raw:
            return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
        return {
            "mission_id": mission.id,
            "filename": Path(mission.report_path).name,
            "content": content,
        }

    @router.post("/missions/{mission_id}/preflight")
    async def rerun_preflight(mission_id: str):
        try:
            mission = mgr.engine.run_preflight(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.post("/missions/{mission_id}/confirm")
    async def confirm_preflight(mission_id: str, payload: ConfirmPreflightPayload):
        try:
            mission = mgr.engine.confirm_preflight(
                mission_id,
                override_mode=payload.override_mode,
                extra_business_rules=payload.extra_business_rules,
                extra_conventions=payload.extra_conventions,
            )
            if payload.auto_start and mission.status == MissionStatus.PLANNING:
                mission = mgr.start_background(mission.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidTransitionError, MissionConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.post("/missions/{mission_id}/start")
    async def start_mission(mission_id: str):
        try:
            mission = mgr.start_background(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidTransitionError, MissionConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.post("/missions/{mission_id}/pause")
    async def pause_mission(mission_id: str):
        try:
            mission = mgr.pause(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.post("/missions/{mission_id}/resume")
    async def resume_mission(mission_id: str, payload: ActionStartPayload | None = None):
        should_start = True if payload is None else payload.auto_start
        try:
            mission = mgr.engine.resume_mission(mission_id)
            if should_start and mission.status not in (
                MissionStatus.WAITING_CONFIRMATION,
                MissionStatus.PHASE_GATE,
            ):
                mission = mgr.start_background(mission.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidTransitionError, MissionConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.post("/missions/{mission_id}/approve-phase")
    async def approve_phase(mission_id: str, payload: ActionStartPayload | None = None):
        should_start = True if payload is None else payload.auto_start
        try:
            mission = mgr.engine.approve_phase_gate(mission_id)
            if should_start and mission.status in (MissionStatus.EXECUTING, MissionStatus.FINAL_REVIEW):
                mission = mgr.start_background(mission.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidTransitionError, MissionConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.post("/missions/{mission_id}/cancel")
    async def cancel_mission(mission_id: str):
        try:
            mission = mgr.cancel(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.delete("/missions/{mission_id}")
    async def delete_mission(mission_id: str):
        try:
            deleted = mgr.delete(mission_id)
        except MissionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Missão não encontrada.")
        return {"deleted": True, "id": mission_id}

    @router.get("/missions/{mission_id}/diff")
    async def get_mission_diff(mission_id: str, max_chars: int = Query(default=40000, ge=1000, le=200000)):
        from .guards import GitMissionSandbox, GitSandboxError

        mission = mgr.engine.store.get(mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Missão não encontrada.")
        if not mission.base_commit:
            return {"branch": mission.branch_name, "diff": "", "pending_files": [], "commits": []}
        try:
            sandbox = GitMissionSandbox(mission.workspace_path)
            diff_text = sandbox.diff_from_base(mission.base_commit, max_chars=max_chars)
            pending_files = sandbox.changed_files()
            commits = sandbox.recent_commits(mission.base_commit)
        except GitSandboxError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "branch": mission.branch_name,
            "base_commit": mission.base_commit,
            "diff": diff_text,
            "pending_files": pending_files,
            "commits": commits,
        }

    @router.post("/missions/{mission_id}/items/{item_id}/retry")
    async def retry_item(mission_id: str, item_id: str, payload: ActionStartPayload | None = None):
        should_start = True if payload is None else payload.auto_start
        try:
            mission = mgr.engine.retry_blocked_item(mission_id, item_id)
            if should_start:
                mission = mgr.start_background(mission.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidTransitionError, MissionConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_mission(mission, mgr)

    @router.post("/missions/{mission_id}/commit")
    async def commit_pending(mission_id: str):
        from .guards import GitSandboxError

        try:
            sha = mgr.engine.commit_pending_changes(mission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GitSandboxError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        mission = mgr.engine.store.get(mission_id)
        assert mission is not None
        data = _serialize_mission(mission, mgr)
        data["commit_sha"] = sha
        return data

    return router


autonomous_router = create_autonomous_router()

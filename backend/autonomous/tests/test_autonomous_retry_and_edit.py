"""Testes para os botões/endpoints de Tentar Novamente e Editar Missão no Modo Autônomo."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.autonomous import (
    AutonomousEngine,
    ChecklistItem,
    ItemStatus,
    MissionConfig,
    MissionMode,
    MissionPhase,
    MissionStatus,
    MissionStore,
    StepExecutionOutcome,
    transition_mission,
)
from backend.autonomous.adapters import DefaultRepoInspector
from backend.autonomous.api import create_autonomous_router
from backend.autonomous.manager import AutonomousManager


class _NoopInspector(DefaultRepoInspector):
    def run_pytest(self, workspace_path: str, target: str = "") -> tuple[bool, str]:
        return True, "ok"

    def run_ruff(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
        return True, "ok"


class _NoopExecutor:
    def execute(self, task_payload: dict[str, Any], workspace_path: str) -> StepExecutionOutcome:
        return StepExecutionOutcome(ok=True, report="ok")


def _make_app(tmp_path: Path) -> tuple[FastAPI, AutonomousManager]:
    engine = AutonomousEngine(
        store=MissionStore(tmp_path / "missions.db"),
        executor=_NoopExecutor(),
        inspector=_NoopInspector(),
        reports_dir=tmp_path / "reports",
    )
    mgr = AutonomousManager(engine=engine)
    app = FastAPI()
    app.include_router(create_autonomous_router(mgr), prefix="/api/autonomous")
    return app, mgr


def test_retry_failed_mission_without_plan_reopens_to_planning(tmp_path):
    ws = tmp_path / "repo"
    (ws / ".git").mkdir(parents=True)

    app, mgr = _make_app(tmp_path)
    with TestClient(app) as client:
        r_create = client.post(
            "/api/autonomous/missions",
            json={
                "title": "Padronizar rotas",
                "objective": "Corrigir todas as rotas em app/routers/ garantindo códigos HTTP consistentes e testes pytest.",
                "business_rules": ["Nunca alterar URLs existentes."],
                "workspace_path": str(ws),
                "auto_start": False,
            },
        )
        assert r_create.status_code == 200
        mid = r_create.json()["id"]

        # Simula falha no sandbox Git (ex.: worktree suja antes do plano existir)
        m = mgr.engine.store.get(mid)
        assert m is not None
        transition_mission(m, MissionStatus.FAILED, error="Workspace com alterações não commitadas.")
        mgr.engine.store.save(m)

        # Tentar novamente (auto_start=False para testar transição limpa)
        r_retry = client.post(
            f"/api/autonomous/missions/{mid}/retry",
            json={"reset_plan": False, "auto_start": False},
        )
        assert r_retry.status_code == 200
        data = r_retry.json()
        assert data["status"] == MissionStatus.PLANNING.value
        assert data["last_error"] is None
        assert data["finished_at"] is None


def test_retry_done_with_blockers_requeues_blocked_items_and_resumes_executing(tmp_path):
    ws = tmp_path / "repo2"
    ws.mkdir()

    app, mgr = _make_app(tmp_path)
    m = mgr.engine.create_mission(
        title="Com bloqueios",
        objective="Padronizar rotas com testes pytest.",
        business_rules=["Manter compatibilidade."],
        workspace_path=str(ws),
        mode=MissionMode.DIAGNOSTIC_ONLY,
    )
    transition_mission(m, MissionStatus.PREFLIGHT)
    transition_mission(m, MissionStatus.PLANNING)
    transition_mission(m, MissionStatus.EXECUTING)
    m.phases = [
        MissionPhase(
            id="p1",
            order=1,
            title="Fase 1",
            items=[
                ChecklistItem(id="i1", phase_id="p1", title="Ok", status=ItemStatus.DONE, attempts=1),
                ChecklistItem(
                    id="i2",
                    phase_id="p1",
                    title="Falhou",
                    status=ItemStatus.BLOCKED,
                    attempts=3,
                    last_error="erro anterior",
                ),
            ],
        )
    ]
    transition_mission(m, MissionStatus.DONE_WITH_BLOCKERS)
    mgr.engine.store.save(m)

    with TestClient(app) as client:
        r_retry = client.post(
            f"/api/autonomous/missions/{m.id}/retry",
            json={"reset_plan": False, "auto_start": False},
        )
        assert r_retry.status_code == 200
        data = r_retry.json()
        assert data["status"] == MissionStatus.EXECUTING.value
        items = data["phases"][0]["items"]
        assert items[0]["status"] == ItemStatus.DONE.value
        assert items[1]["status"] == ItemStatus.PENDING.value
        assert items[1]["attempts"] == 0
        assert items[1]["last_error"] is None


def test_edit_mission_updates_fields_preserves_or_resets_plan_and_blocks_done(tmp_path):
    ws1 = tmp_path / "ws1"
    ws2 = tmp_path / "ws2"
    (ws1 / ".git").mkdir(parents=True)
    (ws2 / ".git").mkdir(parents=True)

    app, mgr = _make_app(tmp_path)
    with TestClient(app) as client:
        r_create = client.post(
            "/api/autonomous/missions",
            json={
                "title": "Titulo inicial",
                "objective": "Objetivo curto",
                "workspace_path": str(ws1),
                "auto_start": False,
            },
        )
        assert r_create.status_code == 200
        created = r_create.json()
        mid = created["id"]
        assert created["status"] == MissionStatus.WAITING_CONFIRMATION.value

        # Edita completando escopo e regras -> pre-flight passa e vai direto para PLANNING
        r_edit = client.patch(
            f"/api/autonomous/missions/{mid}",
            json={
                "title": "Padronizar tratamento de erros",
                "objective": "Auditar todas as rotas em app/routers/ e garantir respostas HTTP 400/404/422 com testes pytest.",
                "business_rules": ["Nunca alterar URLs existentes."],
                "conventions": ["Usar tipagem explícita."],
                "mode": "edit",
                "config": MissionConfig(max_total_tasks=15, auto_commit=True).model_dump(),
                "rerun_preflight": True,
            },
        )
        assert r_edit.status_code == 200
        edited = r_edit.json()
        assert edited["title"] == "Padronizar tratamento de erros"
        assert edited["status"] == MissionStatus.PLANNING.value
        assert edited["config"]["max_total_tasks"] == 15

        # Simula missão pausada com fases já criadas e edita apenas regras -> preserva fases
        m = mgr.engine.store.get(mid)
        assert m is not None
        m.phases = [
            MissionPhase(
                id="p1",
                order=1,
                title="Fase 1",
                items=[ChecklistItem(id="i1", phase_id="p1", title="Rota A", status=ItemStatus.DONE)],
            )
        ]
        transition_mission(m, MissionStatus.EXECUTING)
        transition_mission(m, MissionStatus.PAUSED)
        mgr.engine.store.save(m)

        r_edit_rules = client.patch(
            f"/api/autonomous/missions/{mid}",
            json={"business_rules": ["Regra 1", "Regra 2"], "reset_plan": False},
        )
        assert r_edit_rules.status_code == 200
        assert len(r_edit_rules.json()["phases"]) == 1
        assert r_edit_rules.json()["business_rules"] == ["Regra 1", "Regra 2"]

        # Trocar workspace força reset do plano e limpa branch
        r_edit_ws = client.patch(
            f"/api/autonomous/missions/{mid}",
            json={"workspace_path": str(ws2)},
        )
        assert r_edit_ws.status_code == 200
        assert r_edit_ws.json()["phases"] == []
        assert r_edit_ws.json()["branch_name"] is None

        # Missão DONE não pode ser editada nem retentada
        m_done = mgr.engine.store.get(mid)
        assert m_done is not None
        transition_mission(m_done, MissionStatus.EXECUTING)
        transition_mission(m_done, MissionStatus.FINAL_REVIEW)
        transition_mission(m_done, MissionStatus.DONE)
        mgr.engine.store.save(m_done)

        assert client.patch(f"/api/autonomous/missions/{mid}", json={"title": "Novo"}).status_code == 400
        assert client.post(f"/api/autonomous/missions/{mid}/retry").status_code == 400


def test_autonomous_js_has_retry_and_edit_buttons_with_svg_only():
    js_path = Path("backend/static/autonomous.js")
    assert js_path.is_file()
    content = js_path.read_text(encoding="utf-8")
    assert "auto-btn-retry-mission" in content
    assert "auto-btn-edit" in content
    assert "auto-edit-form" in content
    emojis = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", content)
    assert emojis == [], f"Emojis encontrados: {emojis}"

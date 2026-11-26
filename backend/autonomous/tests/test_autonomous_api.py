"""Testes da Fase 3 do Modo Autônomo (AutonomousManager + endpoints FastAPI isolados)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.autonomous import (
    AutonomousEngine,
    MissionStatus,
    MissionStore,
    StepExecutionOutcome,
)
from backend.autonomous.adapters import DefaultRepoInspector
from backend.autonomous.api import create_autonomous_router
from backend.autonomous.manager import AutonomousManager


class _StubInspector(DefaultRepoInspector):
    def run_pytest(self, workspace_path: str, target: str = "") -> tuple[bool, str]:
        return True, "1 passed"

    def run_ruff(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
        return True, "ruff OK."


class _StubExecutor:
    def execute(self, task_payload: dict[str, Any], workspace_path: str) -> StepExecutionOutcome:
        return StepExecutionOutcome(ok=True, report="ok")


class _StubLLM:
    def __init__(self, responses: dict[str, list[str]]) -> None:
        self.responses = {k: list(v) for k, v in responses.items()}

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
        queue = self.responses.get(role) or []
        if not queue:
            raise RuntimeError(f"Sem resposta stub para role={role}")
        return queue.pop(0)


def _build_test_app(tmp_path: Path, llm: _StubLLM) -> tuple[FastAPI, AutonomousManager]:
    engine = AutonomousEngine(
        store=MissionStore(tmp_path / "missions.db"),
        llm=llm,
        executor=_StubExecutor(),
        inspector=_StubInspector(),
        reports_dir=tmp_path / "reports",
    )
    manager = AutonomousManager(engine=engine)
    app = FastAPI()
    app.include_router(create_autonomous_router(manager), prefix="/api/autonomous")
    return app, manager


def test_api_diagnostic_mission_preflight_confirm_run_and_report(tmp_path):
    ws = tmp_path / "sample_repo"
    ws.mkdir()
    (ws / "calc.py").write_text("def div(a, b):\n    return a / b\n", encoding="utf-8")

    llm = _StubLLM(
        {
            "planner": [
                json.dumps(
                    {
                        "phases": [
                            {
                                "id": "p1",
                                "title": "Diagnóstico",
                                "items": [
                                    {
                                        "id": "d1",
                                        "title": "Revisar calc.py",
                                        "target_files": ["calc.py"],
                                        "acceptance_criteria": ["Apontar riscos reais"],
                                    }
                                ],
                            }
                        ]
                    }
                )
            ],
            "diagnostic": [
                json.dumps(
                    {
                        "summary": "Falta validação de b == 0.",
                        "findings": ["calc.py:2 sem checagem de divisão por zero."],
                        "decision_summary": "Risco confirmado.",
                    }
                )
            ],
            "judge": [
                json.dumps(
                    {
                        "approved": True,
                        "summary": "Diagnóstico concluído com clareza.",
                        "findings": ["calc.py:2 divisão por zero possível."],
                        "follow_up_items": [],
                    }
                )
            ],
        }
    )

    app, manager = _build_test_app(tmp_path, llm)
    with TestClient(app) as client:
        # 1. Criar missão ambígua -> cai em WAITING_CONFIRMATION
        r_create = client.post(
            "/api/autonomous/missions",
            json={
                "title": "Auditar calc.py",
                "objective": "Procure erros e falhas de lógica no projeto.",
                "workspace_path": str(ws),
                "auto_start": True,
            },
        )
        assert r_create.status_code == 200
        created = r_create.json()
        mid = created["id"]
        assert created["status"] == MissionStatus.WAITING_CONFIRMATION.value
        assert created["mode"] == "diagnostic_only"

        # 2. Tentar iniciar sem confirmar deve retornar 400
        r_bad_start = client.post(f"/api/autonomous/missions/{mid}/start")
        assert r_bad_start.status_code == 400

        # 3. Confirmar sem auto_start e executar ciclo completo via manager
        r_conf = client.post(
            f"/api/autonomous/missions/{mid}/confirm",
            json={"override_mode": "diagnostic_only", "auto_start": False},
        )
        assert r_conf.status_code == 200
        assert r_conf.json()["status"] == MissionStatus.PLANNING.value

        # Executa diretamente no engine para determinismo instantâneo e consulta endpoints
        manager.engine.run_until_stop(mid)

        r_get = client.get(f"/api/autonomous/missions/{mid}")
        assert r_get.status_code == 200
        detail = r_get.json()
        assert detail["status"] == MissionStatus.DONE.value
        assert detail["has_report"] is True
        assert detail["progress"]["effective_pct"] == 100.0

        r_events = client.get(f"/api/autonomous/missions/{mid}/events")
        assert r_events.status_code == 200
        assert len(r_events.json()["events"]) >= 4

        r_report = client.get(f"/api/autonomous/missions/{mid}/report")
        assert r_report.status_code == 200
        assert "calc.py:2" in r_report.json()["content"]

        r_report_raw = client.get(f"/api/autonomous/missions/{mid}/report?raw=true")
        assert r_report_raw.status_code == 200
        assert "# Relatório da Missão Autônoma" in r_report_raw.text

        # 4. Listagem e exclusão limpa
        r_list = client.get("/api/autonomous/missions", params={"workspace_path": str(ws)})
        assert r_list.status_code == 200
        assert len(r_list.json()["missions"]) == 1

        r_del = client.delete(f"/api/autonomous/missions/{mid}")
        assert r_del.status_code == 200 and r_del.json()["deleted"] is True


def test_api_pause_resume_and_cancel_endpoints(tmp_path):
    ws = tmp_path / "ws_ctrl"
    ws.mkdir()

    app, manager = _build_test_app(tmp_path, _StubLLM({}))
    with TestClient(app) as client:
        r_create = client.post(
            "/api/autonomous/missions",
            json={
                "title": "Teste controle",
                "objective": "Procure bugs no projeto inteiro.",
                "workspace_path": str(ws),
                "auto_start": False,
            },
        )
        mid = r_create.json()["id"]

        r_pause = client.post(f"/api/autonomous/missions/{mid}/pause")
        assert r_pause.status_code == 200
        assert r_pause.json()["status"] == MissionStatus.PAUSED.value

        r_resume = client.post(f"/api/autonomous/missions/{mid}/resume", json={"auto_start": False})
        assert r_resume.status_code == 200
        assert r_resume.json()["status"] == MissionStatus.WAITING_CONFIRMATION.value

        r_cancel = client.post(f"/api/autonomous/missions/{mid}/cancel")
        assert r_cancel.status_code == 200
        assert r_cancel.json()["status"] == MissionStatus.CANCELLED.value

        assert manager.startup_reconcile() == []

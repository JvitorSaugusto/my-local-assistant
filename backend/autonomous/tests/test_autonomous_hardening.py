"""Testes da Fase 4 (hardening pré-teste): dirty tree guard, AST route map, auto_commit=False, retry item, diff API e UI sem emojis."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.autonomous import (
    AutonomousEngine,
    ChecklistItem,
    GitMissionSandbox,
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
from backend.autonomous.guards import GitSandboxError
from backend.autonomous.manager import AutonomousManager


def _init_git_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Bot"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bot@test.local"], cwd=str(repo_dir), check=True, capture_output=True)
    (repo_dir / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.post('/api/auth/jwt/')\n"
        "async def jwt_login():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: init"], cwd=str(repo_dir), check=True, capture_output=True)


def test_repo_overview_extracts_ast_routes_and_discovers_related_files(tmp_path):
    app = tmp_path / "app"
    (app / "routers").mkdir(parents=True)
    (app / "schemas").mkdir(parents=True)
    (app / "tests").mkdir(parents=True)

    (app / "schemas" / "auth.py").write_text("class LoginIn:\n    pass\n", encoding="utf-8")
    (app / "routers" / "auth.py").write_text(
        "from app.schemas.auth import LoginIn\n\n"
        "@router.post('/api/auth/jwt/')\n"
        "async def jwt_login(payload: LoginIn):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    (app / "tests" / "test_auth.py").write_text("def test_jwt():\n    assert True\n", encoding="utf-8")

    inspector = DefaultRepoInspector()
    overview = inspector.repo_overview(str(tmp_path))
    assert "jwt_login() [POST /api/auth/jwt/]" in overview
    assert "class LoginIn" in overview

    related = inspector.discover_related_files(str(tmp_path), ["app/routers/auth.py"])
    assert "app/tests/test_auth.py" in related
    assert "app/schemas/auth.py" in related


@pytest.mark.skipif(shutil.which("git") is None, reason="git não disponível no ambiente")
def test_branch_guard_blocks_dirty_workspace_before_creating_mission_branch(tmp_path):
    repo = tmp_path / "dirty_repo"
    _init_git_repo(repo)
    (repo / "routes.py").write_text("# alteração local não commitada\n", encoding="utf-8")

    sandbox = GitMissionSandbox(repo)
    with pytest.raises(GitSandboxError, match="alterações não commitadas"):
        sandbox.ensure_mission_branch("m1", "Corrigir Rotas")
    assert sandbox.current_branch() == "main"


@pytest.mark.skipif(shutil.which("git") is None, reason="git não disponível no ambiente")
def test_auto_commit_false_keeps_changes_uncommitted_until_manual_commit(tmp_path):
    repo = tmp_path / "no_autocommit_repo"
    _init_git_repo(repo)

    class _LLM:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
            if role == "planner":
                return json.dumps(
                    {
                        "phases": [
                            {
                                "id": "p1",
                                "title": "Fase 1",
                                "items": [{"id": "i1", "title": "Ajustar routes.py", "target_files": ["routes.py"]}],
                            }
                        ]
                    }
                )
            if role == "coder":
                return json.dumps(
                    {
                        "steps": [{"op": "replace_text", "path": "routes.py", "old": "return {'ok': True}", "new": "return {'ok': True, 'v': 2}"}],
                        "verify": [],
                        "decision_summary": "Atualizado sem auto-commit.",
                    }
                )
            return json.dumps({"approved": True, "summary": "OK", "findings": [], "follow_up_items": []})

    class _Exec:
        def execute(self, task_payload: dict[str, Any], workspace_path: str) -> StepExecutionOutcome:
            p = Path(workspace_path) / "routes.py"
            txt = p.read_text(encoding="utf-8")
            p.write_text(txt.replace("return {'ok': True}", "return {'ok': True, 'v': 2}"), encoding="utf-8")
            return StepExecutionOutcome(ok=True, report="ok")

    class _Insp(DefaultRepoInspector):
        def run_pytest(self, workspace_path: str, target: str = "") -> tuple[bool, str]:
            return True, "ok"

        def run_ruff(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
            return True, "ok"

    engine = AutonomousEngine(
        store=MissionStore(tmp_path / "m.db"),
        llm=_LLM(),
        executor=_Exec(),
        inspector=_Insp(),
        reports_dir=tmp_path / "reports",
    )
    m = engine.create_mission(
        title="Sem autocommit",
        objective="Atualizar routes.py para retornar v=2 mantendo testes pytest verdes.",
        business_rules=["Manter ok=True."],
        workspace_path=str(repo),
        config=MissionConfig(auto_commit=False),
    )
    done = engine.run_until_stop(m.id)
    assert done.status == MissionStatus.DONE
    assert done.phases[0].items[0].commit_sha is None

    sandbox = GitMissionSandbox(repo)
    assert "routes.py" in sandbox.changed_files()

    sha = engine.commit_pending_changes(m.id)
    assert sha is not None
    assert sandbox.is_clean()


def test_retry_blocked_item_and_diff_api_endpoints(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = MissionStore(tmp_path / "m.db")
    engine = AutonomousEngine(store=store, reports_dir=tmp_path / "reports")
    m = engine.create_mission(
        title="Retry API",
        objective="Testar reexecução de item bloqueado.",
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
            items=[ChecklistItem(id="i1", phase_id="p1", title="Item 1", status=ItemStatus.BLOCKED, attempts=3, last_error="boom")],
        )
    ]
    transition_mission(m, MissionStatus.DONE_WITH_BLOCKERS)
    store.save(m)

    app = FastAPI()
    mgr = AutonomousManager(engine=engine)
    app.include_router(create_autonomous_router(mgr), prefix="/api/autonomous")

    with TestClient(app) as client:
        r_diff = client.get(f"/api/autonomous/missions/{m.id}/diff")
        assert r_diff.status_code == 200
        assert r_diff.json()["diff"] == ""

        r_retry = client.post(f"/api/autonomous/missions/{m.id}/items/i1/retry", json={"auto_start": False})
        assert r_retry.status_code == 200
        data = r_retry.json()
        assert data["status"] == MissionStatus.PAUSED.value
        assert data["phases"][0]["items"][0]["status"] == ItemStatus.PENDING.value
        assert data["phases"][0]["items"][0]["attempts"] == 0


def test_autonomous_js_contains_only_svg_icons_and_no_emojis():
    js_path = Path("backend/static/autonomous.js")
    assert js_path.is_file()
    content = js_path.read_text(encoding="utf-8")
    emojis = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", content)
    assert emojis == [], f"Emojis encontrados em autonomous.js: {emojis}"
    assert "<svg " in content

"""Testes da Fase 5: Conventional Commits, suporte JS/TS/React (overview, anti-trapaça, auditoria) e micro-loop de investigação."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend.autonomous import (
    AutonomousEngine,
    GitMissionSandbox,
    MissionConfig,
    MissionMode,
    MissionStatus,
    MissionStore,
    StepExecutionOutcome,
    detect_test_tampering,
    format_conventional_commit,
    run_objective_audit,
)
from backend.autonomous.adapters import DefaultRepoInspector
from backend.autonomous.guards import is_test_file_path


def test_format_conventional_commit_infers_types_scopes_and_preserves_valid_headers():
    msg1 = format_conventional_commit(
        "Corrigir validação de tenant nas rotas",
        changed_files=["god-backend/app/routers/portal_internal.py"],
    )
    assert msg1.startswith("fix(routers): ")
    assert len(msg1) <= 72

    msg2 = format_conventional_commit(
        "Adicionar testes unitários para LoginCard",
        changed_files=["src/components/LoginCard.test.tsx"],
    )
    assert msg2.startswith("test(components): ")

    msg3 = format_conventional_commit(
        "feat(auth): suportar refresh token no App OS",
        changed_files=["src/auth/token.ts"],
    )
    assert msg3 == "feat(auth): suportar refresh token no App OS"

    msg4 = format_conventional_commit(
        "Criar componente de filtro",
        changed_files=["src/components/FilterBar.tsx"],
        commit_type="feat",
        commit_scope="ui",
    )
    assert msg4 == "feat(ui): criar componente de filtro"


def test_js_ts_react_test_detection_and_anti_tampering():
    assert is_test_file_path("src/components/Button.test.tsx") is True
    assert is_test_file_path("src/hooks/useAuth.spec.ts") is True
    assert is_test_file_path("src/__tests__/api.test.js") is True
    assert is_test_file_path("src/components/Button.tsx") is False

    before_tsx = (
        "import { render, screen } from '@testing-library/react';\n"
        "test('renders submit button', () => {\n"
        "  expect(screen.getByRole('button')).toBeInTheDocument();\n"
        "  expect(1 + 1).toBe(2);\n"
        "});\n"
        "it('handles click', () => {\n"
        "  expect(true).toBe(true);\n"
        "});\n"
    )
    weakened_tsx = (
        "import { render, screen } from '@testing-library/react';\n"
        "test('renders submit button', () => {\n"
        "  expect(screen.getByRole('button')).toBeInTheDocument();\n"
        "});\n"
    )
    report = detect_test_tampering(
        {"src/components/Button.test.tsx": before_tsx},
        {"src/components/Button.test.tsx": weakened_tsx},
    )
    assert not report.ok
    assert any("handles click" in v for v in report.violations)
    assert any("asserções diminuiu" in v for v in report.violations)


def test_js_ts_react_overview_related_files_stack_detection_and_syntax_check(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "demo-ui",
                "dependencies": {"react": "^19.0.0", "react-dom": "^19.0.0"},
                "devDependencies": {"typescript": "^5.0.0"},
                "scripts": {"test": 'echo "Error: no test specified" && exit 1'},
            }
        ),
        encoding="utf-8",
    )
    src = tmp_path / "src"
    (src / "components").mkdir(parents=True)
    (src / "hooks").mkdir(parents=True)

    (src / "hooks" / "useUsers.ts").write_text(
        "export function useUsers() {\n  return [];\n}\n",
        encoding="utf-8",
    )
    (src / "components" / "UserList.tsx").write_text(
        "import { useUsers } from '@/hooks/useUsers';\n\n"
        "export const UserList = () => {\n"
        "  const users = useUsers();\n"
        "  return <div>{users.length}</div>;\n"
        "};\n",
        encoding="utf-8",
    )
    (src / "components" / "UserList.test.tsx").write_text(
        "test('renders list', () => { expect(true).toBe(true); });\n",
        encoding="utf-8",
    )

    insp = DefaultRepoInspector()
    stacks = insp.detect_project_stacks(str(tmp_path))
    assert {"js", "ts", "react"}.issubset(stacks)

    overview = insp.repo_overview(str(tmp_path))
    assert "<UserList />" in overview
    assert "hook useUsers()" in overview

    related = insp.discover_related_files(str(tmp_path), ["src/components/UserList.tsx"])
    assert "src/components/UserList.test.tsx" in related
    assert "src/hooks/useUsers.ts" in related

    hits = insp.search_text(str(tmp_path), ["useUsers"])
    assert "src/components/UserList.tsx" in hits

    ok, msg = insp.run_js_ts_syntax(str(tmp_path), ["src/components/UserList.tsx"])
    assert ok, msg

    # Arquivo TSX quebrado (chave não fechada) deve ser barrado
    (src / "components" / "Broken.tsx").write_text("export const Broken = () => {\n  return <div />;\n", encoding="utf-8")
    ok_bad, msg_bad = insp.run_js_ts_syntax(str(tmp_path), ["src/components/Broken.tsx"])
    assert not ok_bad and "não foi fechado" in msg_bad


def test_coder_investigative_micro_loop_loads_needed_files_before_editing(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "schemas.py").write_text("class Payload:\n    origin: str = 'portal_landing'\n", encoding="utf-8")
    (ws / "service.py").write_text("def handle():\n    return 'old'\n", encoding="utf-8")

    seen_coder_prompts: list[str] = []

    class _LLM:
        def __init__(self) -> None:
            self.coder_round = 0

        def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
            if role == "planner":
                return json.dumps(
                    {
                        "phases": [
                            {
                                "id": "p1",
                                "title": "Fase 1",
                                "items": [
                                    {
                                        "id": "i1",
                                        "title": "Usar origin de schemas.py em service.py",
                                        "target_files": ["service.py"],
                                    }
                                ],
                            }
                        ]
                    }
                )
            if role == "coder":
                seen_coder_prompts.append(user_prompt)
                self.coder_round += 1
                if self.coder_round == 1:
                    # Rodada 1: pede para ler schemas.py e buscar 'portal_landing' antes de editar
                    return json.dumps(
                        {
                            "steps": [],
                            "need_files": ["schemas.py"],
                            "search_queries": ["portal_landing"],
                        }
                    )
                # Rodada 2: agora com schemas.py no prompt, devolve os steps finais
                assert "portal_landing" in user_prompt
                return json.dumps(
                    {
                        "steps": [
                            {
                                "op": "replace_text",
                                "path": "service.py",
                                "old": "return 'old'",
                                "new": "return 'portal_landing'",
                            }
                        ],
                        "verify": [],
                        "commit_type": "fix",
                        "commit_scope": "service",
                        "decision_summary": "Alinhado com schemas.Payload.origin.",
                    }
                )
            return json.dumps({"approved": True, "summary": "OK", "findings": [], "follow_up_items": []})

    class _Exec:
        def execute(self, task_payload: dict[str, Any], workspace_path: str) -> StepExecutionOutcome:
            p = Path(workspace_path) / "service.py"
            txt = p.read_text(encoding="utf-8")
            p.write_text(txt.replace("return 'old'", "return 'portal_landing'"), encoding="utf-8")
            return StepExecutionOutcome(ok=True, report="ok")

    class _Insp(DefaultRepoInspector):
        def run_pytest(self, workspace_path: str, target: str = "") -> tuple[bool, str]:
            return True, "ok"

        def run_ruff(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
            return True, "ok"

    # Usa modo diagnóstico? Não — mocka GitMissionSandbox apenas neste teste para rodar mesmo sem git no PATH
    import backend.autonomous.runner as runner_mod

    class _MockSandbox:
        def __init__(self, path):
            self.repo = Path(path)
            self._branch = "auto/test-1"
            self.last_commit_kwargs: dict[str, Any] = {}

        def current_branch(self):
            return self._branch

        def head_commit(self):
            return "abc12345"

        def is_clean(self):
            return True

        def ensure_mission_branch(self, mission_id, title, prefix="auto", **kw):
            return self._branch, "abc12345"

        def changed_files(self):
            return ["service.py"]

        def snapshot_working_files(self, rel_paths):
            return {}

        def commit_item(self, item_id, title, **kw):
            self.last_commit_kwargs = {"item_id": item_id, "title": title, **kw}
            return "def67890"

        def rollback_working_tree(self):
            pass

        def diff_from_base(self, base_commit, max_chars=24000):
            return "+return 'portal_landing'"

        def _run_git(self, *args, check=True, timeout=30):
            return type("R", (), {"returncode": 0, "stdout": "service.py\n", "stderr": ""})()

    orig_sb = runner_mod.GitMissionSandbox
    runner_mod.GitMissionSandbox = _MockSandbox
    try:
        engine = AutonomousEngine(
            store=MissionStore(tmp_path / "m.db"),
            llm=_LLM(),
            executor=_Exec(),
            inspector=_Insp(),
            reports_dir=tmp_path / "reports",
        )
        m = engine.create_mission(
            title="Alinhar origin",
            objective="Garantir que service.py retorne o valor padrão de origin definido em schemas.py com testes pytest.",
            business_rules=["Usar exatamente o valor de schemas.Payload.origin."],
            workspace_path=str(ws),
            config=MissionConfig(run_audit_per_phase=False),
        )
        done = engine.run_until_stop(m.id)
        assert done.status == MissionStatus.DONE
        assert len(seen_coder_prompts) == 2
        assert "portal_landing" in (ws / "service.py").read_text(encoding="utf-8")
    finally:
        runner_mod.GitMissionSandbox = orig_sb


@pytest.mark.skipif(shutil.which("git") is None, reason="git não disponível no ambiente")
def test_git_commit_item_writes_real_conventional_commit_header_and_trailer(tmp_path):
    repo = tmp_path / "conv_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Auto"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "auto@test.local"], cwd=str(repo), check=True, capture_output=True)
    (repo / "routers").mkdir()
    (repo / "routers" / "auth.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: initial"], cwd=str(repo), check=True, capture_output=True)

    sb = GitMissionSandbox(repo)
    sb.ensure_mission_branch("m99", "Rotas Auth")
    (repo / "routers" / "auth.py").write_text("x = 2\n", encoding="utf-8")
    sb.commit_item("p1_i1", "Corrigir validação de token", commit_type="fix", commit_scope="auth")

    msg = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert msg.splitlines()[0] == "fix(auth): corrigir validação de token"
    assert "Autonomous-Item: p1_i1" in msg

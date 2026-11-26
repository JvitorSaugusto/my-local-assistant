"""Testes da Fase 2 do Modo Autônomo (adapters, planner, auditor, judge e runner end-to-end)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend.autonomous import (
    AutonomousEngine,
    ItemStatus,
    MissionConfig,
    MissionMode,
    MissionStatus,
    MissionStore,
    StepExecutionOutcome,
    calculate_progress,
    extract_json_payload,
)
from backend.autonomous.adapters import DefaultRepoInspector


def _init_git_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Auto Bot"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "auto@test.local"], cwd=str(repo_dir), check=True, capture_output=True)
    (repo_dir / "routes.py").write_text("def route_a():\n    return 200\n", encoding="utf-8")
    (repo_dir / "test_routes.py").write_text(
        "from routes import route_a\n\n"
        "def test_route_a():\n"
        "    assert route_a() == 200\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: initial"], cwd=str(repo_dir), check=True, capture_output=True)


class FakeRepoInspector(DefaultRepoInspector):
    def __init__(self, *, pytest_ok: bool = True, pytest_msg: str = "2 passed") -> None:
        self.pytest_ok = pytest_ok
        self.pytest_msg = pytest_msg

    def run_pytest(self, workspace_path: str, target: str = "") -> tuple[bool, str]:
        return self.pytest_ok, self.pytest_msg

    def run_ruff(self, workspace_path: str, rel_paths: list[str]) -> tuple[bool, str]:
        return True, "ruff OK."


class FakeStepExecutor:
    """Aplica operações simples de create_file/replace_text ou simula falhas controladas."""

    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def execute(self, task_payload: dict[str, Any], workspace_path: str) -> StepExecutionOutcome:
        self.calls += 1
        if self.calls <= self.fail_times:
            return StepExecutionOutcome(ok=False, error=f"Falha simulada #{self.calls}")

        root = Path(workspace_path)
        for step in task_payload.get("steps") or []:
            op = step.get("op")
            rel = step.get("path", "")
            target = root / rel
            if op == "create_file":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(step["content"], encoding="utf-8")
            elif op == "replace_text":
                text = target.read_text(encoding="utf-8")
                target.write_text(text.replace(step["old"], step["new"], 1), encoding="utf-8")
        return StepExecutionOutcome(ok=True, report="passo 1/1 ok")


class ScriptedLLM:
    def __init__(self, responses_by_role: dict[str, list[str]]) -> None:
        self.responses = {k: list(v) for k, v in responses_by_role.items()}
        self.seen_prompts: list[tuple[str, str]] = []

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
        self.seen_prompts.append((role, user_prompt))
        queue = self.responses.get(role) or []
        if not queue:
            raise RuntimeError(f"Sem resposta configurada para role='{role}'")
        return queue.pop(0)


def test_extract_json_payload_handles_think_tags_and_markdown_fences():
    raw = (
        "<think>vou raciocinar aqui antes de responder {json falso}</think>\n"
        "Aqui está o resultado:\n"
        "```json\n"
        '{"approved": true, "summary": "Tudo certo", "findings": [], "follow_up_items": []}\n'
        "```"
    )
    parsed = extract_json_payload(raw)
    assert parsed["approved"] is True
    assert parsed["summary"] == "Tudo certo"


def test_diagnostic_only_flow_waits_confirmation_and_never_modifies_files(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "service.py").write_text("def calc(x):\n    return x / 0\n", encoding="utf-8")

    llm = ScriptedLLM(
        {
            "planner": [
                json.dumps(
                    {
                        "phases": [
                            {
                                "id": "p1",
                                "title": "Diagnóstico de lógica",
                                "items": [
                                    {
                                        "id": "d1",
                                        "title": "Inspecionar service.py",
                                        "target_files": ["service.py"],
                                        "acceptance_criteria": ["Listar bugs com evidência"],
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
                        "summary": "Divisão por zero em calc().",
                        "findings": ["service.py:2 divisão literal por zero."],
                        "decision_summary": "Bug real confirmado sem editar arquivo.",
                    }
                )
            ],
            "judge": [
                json.dumps(
                    {
                        "approved": True,
                        "summary": "Diagnóstico completo e fundamentado.",
                        "findings": ["service.py:2 divisão literal por zero."],
                        "follow_up_items": [],
                    }
                )
            ],
        }
    )

    engine = AutonomousEngine(
        store=MissionStore(tmp_path / "missions.db"),
        llm=llm,
        executor=FakeStepExecutor(),
        inspector=FakeRepoInspector(),
        reports_dir=tmp_path / "reports",
    )

    m = engine.create_mission(
        title="Buscar bugs",
        objective="Procure erros e falhas de lógica no projeto.",
        workspace_path=str(ws),
    )
    m = engine.run_preflight(m.id)
    assert m.status == MissionStatus.WAITING_CONFIRMATION
    assert m.mode == MissionMode.DIAGNOSTIC_ONLY

    engine.confirm_preflight(m.id)
    done = engine.run_until_stop(m.id)
    assert done.status == MissionStatus.DONE
    assert done.report_path and Path(done.report_path).is_file()
    assert "Divisão literal por zero" in Path(done.report_path).read_text(encoding="utf-8") or "service.py:2" in Path(done.report_path).read_text(encoding="utf-8")
    # Arquivo original permanece intacto
    assert "return x / 0" in (ws / "service.py").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="git não disponível no ambiente")
def test_full_phased_execution_with_phase_gate_pause_resume_and_review_cycle(tmp_path):
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    llm = ScriptedLLM(
        {
            "planner": [
                json.dumps(
                    {
                        "phases": [
                            {
                                "id": "p1",
                                "title": "Fase 1 — Rotas",
                                "items": [
                                    {
                                        "id": "p1_i1",
                                        "title": "Atualizar retorno de route_a",
                                        "target_files": ["routes.py"],
                                        "acceptance_criteria": ["Manter status 200"],
                                    }
                                ],
                            },
                            {
                                "id": "p2",
                                "title": "Fase 2 — Utilitário",
                                "items": [
                                    {
                                        "id": "p2_i1",
                                        "title": "Criar helper.py",
                                        "target_files": ["helper.py"],
                                        "acceptance_criteria": ["Arquivo criado"],
                                    }
                                ],
                            },
                        ]
                    }
                )
            ],
            "coder": [
                json.dumps(
                    {
                        "steps": [
                            {
                                "op": "replace_text",
                                "path": "routes.py",
                                "old": "def route_a():\n    return 200",
                                "new": "def route_a():\n    \"\"\"Rota padronizada.\"\"\"\n    return 200",
                            }
                        ],
                        "verify": [],
                        "decision_summary": "Docstring adicionada em route_a.",
                        "evidence": ["routes.py atualizado"],
                    }
                ),
                json.dumps(
                    {
                        "steps": [
                            {
                                "op": "create_file",
                                "path": "helper.py",
                                "content": "def ping():\n    return 'pong'\n",
                            }
                        ],
                        "verify": [],
                        "decision_summary": "helper.py criado.",
                        "evidence": ["helper.py criado"],
                    }
                ),
                # Ciclo de correção disparado pelo Juiz Final
                json.dumps(
                    {
                        "steps": [
                            {
                                "op": "replace_text",
                                "path": "helper.py",
                                "old": "def ping():\n    return 'pong'",
                                "new": "def ping() -> str:\n    return 'pong'",
                            }
                        ],
                        "verify": [],
                        "decision_summary": "Type hint adicionado em ping().",
                        "evidence": ["tipagem adicionada"],
                    }
                ),
            ],
            "judge": [
                # Ciclo 1: reprova e pede follow-up concreto
                json.dumps(
                    {
                        "approved": False,
                        "summary": "Faltou type hint em helper.py.",
                        "findings": ["helper.py sem retorno tipado"],
                        "follow_up_items": ["Adicionar type hint -> str em helper.py"],
                    }
                ),
                # Ciclo 2: aprova
                json.dumps(
                    {
                        "approved": True,
                        "summary": "Todas as fases e revisões atendidas.",
                        "findings": [],
                        "follow_up_items": [],
                    }
                ),
            ],
        }
    )

    engine = AutonomousEngine(
        store=MissionStore(tmp_path / "missions.db"),
        llm=llm,
        executor=FakeStepExecutor(),
        inspector=FakeRepoInspector(),
        reports_dir=tmp_path / "reports",
    )

    m = engine.create_mission(
        title="Padronizar rotas",
        objective="Padronizar routes.py e adicionar helper.py garantindo testes pytest verdes.",
        business_rules=["Manter status 200 em route_a."],
        conventions=["Tipar funções públicas."],
        workspace_path=str(repo),
        config=MissionConfig(require_phase_approval=True, max_review_cycles=2),
    )

    # Executa até o phase gate da Fase 1
    m = engine.run_until_stop(m.id)
    assert m.status == MissionStatus.PHASE_GATE
    assert m.branch_name and m.branch_name.startswith("auto/")
    assert calculate_progress(m).done_items == 1

    # Pausa no phase gate e retoma depois
    m = engine.pause_mission(m.id)
    assert m.status == MissionStatus.PAUSED
    m = engine.resume_mission(m.id)
    assert m.status == MissionStatus.PHASE_GATE

    # Aprova avanço para Fase 2 -> executa -> juiz ciclo 1 cria rev1 -> executa rev1 -> juiz ciclo 2 aprova
    engine.approve_phase_gate(m.id)
    final = engine.run_until_stop(m.id)
    assert final.status == MissionStatus.DONE
    assert final.review_cycles_used == 2
    assert len(final.reviews) == 2 and final.reviews[-1].approved is True
    assert final.report_path and Path(final.report_path).is_file()
    assert "def ping() -> str:" in (repo / "helper.py").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="git não disponível no ambiente")
def test_blocked_item_after_max_retries_allows_next_item_and_marks_done_with_blockers(tmp_path):
    repo = tmp_path / "repo_fail"
    _init_git_repo(repo)

    llm = ScriptedLLM(
        {
            "planner": [
                json.dumps(
                    {
                        "phases": [
                            {
                                "id": "p1",
                                "title": "Fase única",
                                "items": [
                                    {"id": "i1", "title": "Item que falha", "target_files": ["routes.py"]},
                                    {"id": "i2", "title": "Item que passa", "target_files": ["ok.py"]},
                                ],
                            }
                        ]
                    }
                )
            ],
            "coder": [
                # Tentativa 1 e 2 de i1 falham no executor
                json.dumps({"steps": [{"op": "create_file", "path": "x.py", "content": "x=1\n"}], "verify": []}),
                json.dumps({"steps": [{"op": "create_file", "path": "x.py", "content": "x=1\n"}], "verify": []}),
                # i2 passa
                json.dumps({"steps": [{"op": "create_file", "path": "ok.py", "content": "OK = True\n"}], "verify": []}),
            ],
            "judge": [
                json.dumps(
                    {
                        "approved": False,
                        "summary": "Item i1 bloqueado, i2 concluído.",
                        "findings": ["i1 falhou após 2 tentativas"],
                        "follow_up_items": [],
                    }
                )
            ],
        }
    )

    engine = AutonomousEngine(
        store=MissionStore(tmp_path / "missions.db"),
        llm=llm,
        executor=FakeStepExecutor(fail_times=2),
        inspector=FakeRepoInspector(),
        reports_dir=tmp_path / "reports",
    )

    m = engine.create_mission(
        title="Teste bloqueio",
        objective="Ajustar routes.py e criar ok.py garantindo testes pytest verdes.",
        business_rules=["Não quebrar testes existentes."],
        workspace_path=str(repo),
        config=MissionConfig(max_retries_per_item=2, max_review_cycles=1),
    )

    final = engine.run_until_stop(m.id)
    assert final.status == MissionStatus.DONE_WITH_BLOCKERS
    items = [it for p in final.phases for it in p.items]
    assert items[0].status == ItemStatus.BLOCKED and items[0].attempts == 2
    assert items[1].status == ItemStatus.DONE
    assert (repo / "ok.py").is_file()
    prog = calculate_progress(final)
    assert prog.effective_pct == 50.0
def test_reconcile_interrupted_missions_pauses_active_and_resets_in_progress(tmp_path):
    store = MissionStore(tmp_path / "missions.db")
    engine = AutonomousEngine(
        store=store,
        llm=ScriptedLLM({}),
        executor=FakeStepExecutor(),
        inspector=FakeRepoInspector(),
        reports_dir=tmp_path / "reports",
    )
    m = engine.create_mission(
        title="Queda do servidor",
        objective="Simular reinício do uvicorn durante uma missão em andamento.",
        workspace_path=str(tmp_path),
        mode=MissionMode.DIAGNOSTIC_ONLY,
    )
    from backend.autonomous import ChecklistItem, MissionPhase, transition_mission

    transition_mission(m, MissionStatus.PREFLIGHT)
    transition_mission(m, MissionStatus.PLANNING)
    m.phases = [
        MissionPhase(
            id="p1",
            order=1,
            title="Fase 1",
            items=[ChecklistItem(id="i1", phase_id="p1", title="Item", status=ItemStatus.IN_PROGRESS)],
        )
    ]
    transition_mission(m, MissionStatus.EXECUTING)
    store.save(m)

    recovered = engine.reconcile_interrupted_missions()
    assert recovered == [m.id]

    reloaded = store.get(m.id)
    assert reloaded is not None
    assert reloaded.status == MissionStatus.PAUSED
    assert reloaded.paused_from_status == MissionStatus.EXECUTING
    assert reloaded.phases[0].items[0].status == ItemStatus.PENDING

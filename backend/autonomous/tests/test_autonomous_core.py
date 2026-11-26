"""Testes da Fase 1 do Modo Autônomo isolado (máquina de estados, SQLite WAL, Git sandbox e pre-flight)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from backend.autonomous import (
    ChecklistItem,
    DecisionEntry,
    GitMissionSandbox,
    InvalidTransitionError,
    ItemStatus,
    MissionConfig,
    MissionMode,
    MissionPhase,
    MissionRecord,
    MissionStatus,
    MissionStore,
    PhaseStatus,
    ScopeClarity,
    analyze_scope_preflight,
    build_clean_context_brief,
    calculate_progress,
    can_continue_mission,
    detect_test_tampering,
    is_protected_relative_path,
    transition_mission,
)
from backend.autonomous.guards import GitSandboxError
from backend.autonomous.state_machine import next_pending_item, resume_target_status


def _init_git_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Bot"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bot@test.local"], cwd=str(repo_dir), check=True, capture_output=True)
    (repo_dir / "app.py").write_text("def health():\n    return {'ok': True}\n", encoding="utf-8")
    (repo_dir / "test_app.py").write_text(
        "from app import health\n\n"
        "def test_health():\n"
        "    assert health() == {'ok': True}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: initial"], cwd=str(repo_dir), check=True, capture_output=True)


def test_state_machine_transitions_and_pause_resume():
    mission = MissionRecord(
        title="Corrigir rotas",
        objective="Padronizar respostas de erro em todas as rotas de backend/routers/.",
        workspace_path="/tmp/ws",
    )
    assert mission.status == MissionStatus.CREATED

    with pytest.raises(InvalidTransitionError):
        transition_mission(mission, MissionStatus.DONE)

    transition_mission(mission, MissionStatus.PREFLIGHT)
    transition_mission(mission, MissionStatus.PLANNING)
    transition_mission(mission, MissionStatus.EXECUTING)
    assert mission.started_at is not None

    transition_mission(mission, MissionStatus.PAUSED)
    assert mission.paused_from_status == MissionStatus.EXECUTING
    ok, reason = can_continue_mission(mission)
    assert not ok and "pausada" in (reason or "").lower()

    target = resume_target_status(mission)
    assert target == MissionStatus.EXECUTING
    transition_mission(mission, target)
    assert mission.paused_from_status is None
    assert can_continue_mission(mission) == (True, None)

    transition_mission(mission, MissionStatus.FINAL_REVIEW)
    transition_mission(mission, MissionStatus.DONE)
    assert mission.finished_at is not None

    with pytest.raises(InvalidTransitionError):
        transition_mission(mission, MissionStatus.EXECUTING)


def test_objective_progress_and_budget_enforcement():
    mission = MissionRecord(
        title="Padronizar rotas",
        objective="Corrigir rotas da API.",
        workspace_path="/tmp/ws",
        status=MissionStatus.EXECUTING,
        config=MissionConfig(max_total_tasks=2),
        phases=[
            MissionPhase(
                id="p1",
                order=1,
                title="Fase 1",
                items=[
                    ChecklistItem(id="i1", phase_id="p1", title="Rota A", status=ItemStatus.DONE),
                    ChecklistItem(id="i2", phase_id="p1", title="Rota B", status=ItemStatus.BLOCKED, last_error="falhou 3x"),
                ],
            ),
            MissionPhase(
                id="p2",
                order=2,
                title="Fase 2",
                items=[
                    ChecklistItem(id="i3", phase_id="p2", title="Rota C", status=ItemStatus.PENDING),
                    ChecklistItem(id="i4", phase_id="p2", title="Rota D", status=ItemStatus.SKIPPED),
                ],
            ),
        ],
    )
    prog = calculate_progress(mission)
    assert prog.total_items == 4
    assert prog.done_items == 1
    assert prog.blocked_items == 1
    assert prog.pending_items == 1
    assert prog.skipped_items == 1
    # 3 itens acionáveis (exclui skipped): 1/3 efetivo = 33.3%, 2/3 processados = 66.7%
    assert prog.effective_pct == 33.3
    assert prog.completion_pct == 66.7
    assert mission.phases[0].status == PhaseStatus.BLOCKED

    nxt = next_pending_item(mission)
    assert nxt is not None and nxt[1].id == "i3"

    mission.tasks_executed = 2
    ok, reason = can_continue_mission(mission)
    assert not ok and "limite máximo" in (reason or "").lower()


def test_sqlite_store_persistence_events_and_clean_context_brief(tmp_path):
    store = MissionStore(tmp_path / "missions.db")
    mission = MissionRecord(
        title="Migrar rotas",
        objective="Garantir que todas as rotas em app/routers/ validem tenant_id.",
        business_rules=["Nunca alterar conta Root interna.", "Retornar 403 em tenant inválido."],
        conventions=["Usar FastAPI Depends", "Cobrir com pytest"],
        workspace_path=str(tmp_path),
        phases=[
            MissionPhase(
                id="f1",
                order=1,
                title="Auditoria e correção",
                items=[
                    ChecklistItem(
                        id="t1",
                        phase_id="f1",
                        title="Validar tenant em users.py",
                        target_files=["app/routers/users.py"],
                        acceptance_criteria=["Retornar 403 sem tenant válido"],
                    )
                ],
            )
        ],
        decisions=[DecisionEntry(phase_id="f1", item_id="t1", summary="Manter compatibilidade com token legado.")],
    )

    store.save(mission)
    event_id = store.append_event(mission.id, "created", "Missão criada", {"source": "test"})
    assert event_id > 0

    loaded = store.get(mission.id)
    assert loaded is not None
    assert loaded.title == "Migrar rotas"
    assert loaded.business_rules == mission.business_rules

    listed = store.list_missions(workspace_path=str(tmp_path))
    assert len(listed) == 1 and listed[0].id == mission.id

    events = store.list_events(mission.id)
    assert len(events) == 1 and events[0]["event_type"] == "created"

    brief = build_clean_context_brief(loaded)
    assert "Regras de Negócio (imutáveis)" in brief
    assert "Próximo Alvo: Fase 1 · `t1`" in brief
    assert "Manter compatibilidade com token legado." in brief

    assert store.delete(mission.id) is True
    assert store.get(mission.id) is None


def test_test_tampering_and_protected_path_guards():
    assert is_protected_relative_path(".env") is True
    assert is_protected_relative_path(".env.production") is True
    assert is_protected_relative_path(".env.example") is False
    assert is_protected_relative_path("../fora.py") is True
    assert is_protected_relative_path(".git/config") is True
    assert is_protected_relative_path("backend/routers/auth.py") is False

    original_test = (
        "def test_a():\n"
        "    assert 1 == 1\n"
        "    assert 2 == 2\n\n"
        "def test_b():\n"
        "    assert True\n"
    )
    weakened_test = (
        "def test_a():\n"
        "    assert 1 == 1\n"
    )
    report = detect_test_tampering({"tests/test_x.py": original_test}, {"tests/test_x.py": weakened_test})
    assert not report.ok
    assert any("test_b" in v for v in report.violations)
    assert any("asserções diminuiu" in v for v in report.violations)

    deleted_report = detect_test_tampering({"tests/test_x.py": original_test}, {"tests/test_x.py": None})
    assert not deleted_report.ok

    allowed_report = detect_test_tampering(
        {"tests/test_x.py": original_test},
        {"tests/test_x.py": None},
        allow_test_deletion=True,
    )
    assert allowed_report.ok


@pytest.mark.skipif(shutil.which("git") is None, reason="git não disponível no ambiente")
def test_git_mission_sandbox_branch_commit_tamper_block_and_rollback(tmp_path):
    repo_dir = tmp_path / "repo"
    _init_git_repo(repo_dir)

    sandbox = GitMissionSandbox(repo_dir)
    base_sha = sandbox.head_commit()
    branch, _ = sandbox.ensure_mission_branch("abc123", "Corrigir Rotas")
    assert branch == "auto/corrigir-rotas-abc123"
    assert sandbox.current_branch() == branch

    # Edição válida + commit atômico do item
    (repo_dir / "app.py").write_text("def health():\n    return {'ok': True, 'v': 2}\n", encoding="utf-8")
    commit_sha = sandbox.commit_item("t1", "Atualiza resposta de health")
    assert commit_sha is not None and commit_sha != base_sha
    assert sandbox.is_clean()
    assert "'v': 2" in sandbox.diff_from_base(base_sha)

    # Tentativa de trapaça apagando um teste deve ser bloqueada
    (repo_dir / "test_app.py").write_text("# removido\n", encoding="utf-8")
    with pytest.raises(GitSandboxError, match="anti-trapaça"):
        sandbox.commit_item("t2", "Remove teste falhando")

    # Rollback cirúrgico restaura working tree limpo (incluindo arquivos untracked)
    (repo_dir / "temp_lixo.py").write_text("x = 1\n", encoding="utf-8")
    sandbox.rollback_working_tree()
    assert sandbox.is_clean()
    assert not (repo_dir / "temp_lixo.py").exists()
    assert "def test_health" in (repo_dir / "test_app.py").read_text(encoding="utf-8")


def test_preflight_classifies_clear_ambiguous_and_greenfield_scopes(tmp_path):
    repo_dir = tmp_path / "proj"
    (repo_dir / ".git").mkdir(parents=True)

    # 1. Escopo claro e verificável
    clear = analyze_scope_preflight(
        "Corrigir todas as rotas em app/routers/ para validar tenant_id e retornar status 403 quando inválido, mantendo testes pytest verdes.",
        str(repo_dir),
        business_rules=["Nunca alterar conta Root interna."],
        conventions=["Usar FastAPI Depends"],
    )
    assert clear.clarity == ScopeClarity.HIGH
    assert clear.recommended_mode == MissionMode.EDIT
    assert clear.requires_confirmation is False
    assert "app/routers/" in clear.detected_targets

    # 2. Escopo aberto/ambíguo -> recomenda modo diagnóstico somente leitura e pede confirmação
    ambig = analyze_scope_preflight(
        "Procure erros e falhas de lógica no projeto inteiro.",
        str(repo_dir),
    )
    assert ambig.recommended_mode == MissionMode.DIAGNOSTIC_ONLY
    assert ambig.requires_confirmation is True
    assert ambig.clarity == ScopeClarity.LOW

    # 3. Projeto do zero -> recomenda modo greenfield por fases
    green = analyze_scope_preflight(
        "Criar um novo projeto do zero de gestão de estoque em FastAPI com autenticação JWT e testes pytest.",
        str(repo_dir),
        business_rules=["Somente admin pode excluir item."],
    )
    assert green.recommended_mode == MissionMode.GREENFIELD_PHASED
    assert green.requires_confirmation is False or len(green.missing_info) >= 1

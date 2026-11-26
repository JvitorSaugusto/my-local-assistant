"""Motor determinístico do Modo Autônomo: loop por fases com contexto zerado, pause/resume e rollback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .adapters import (
    DefaultLLMClient,
    DefaultRepoInspector,
    DefaultStepExecutor,
    LLMTextClient,
    RepoInspectorPort,
    StepExecutorPort,
    invoke_structured_json,
)
from .auditor import AuditReport, run_objective_audit
from .guards import GitMissionSandbox, GitSandboxError, is_test_file_path
from .judge import evaluate_final_review, write_mission_report
from .planner import build_mission_plan
from .preflight import analyze_scope_preflight
from .schemas import (
    ChecklistItem,
    DecisionEntry,
    ItemStatus,
    MissionConfig,
    MissionMode,
    MissionPhase,
    MissionRecord,
    MissionStatus,
    PhaseStatus,
    utc_now_iso,
)
from .state_machine import (
    TERMINAL_STATUSES,
    calculate_progress,
    can_continue_mission,
    next_pending_item,
    resume_target_status,
    sync_phase_statuses,
    transition_mission,
)
from .store import MissionStore, build_clean_context_brief


class _ItemExecutionDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    steps: list[dict[str, Any]] = Field(default_factory=list)
    verify: list[dict[str, Any]] = Field(default_factory=list)
    need_files: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    commit_type: str = ""
    commit_scope: str = ""
    decision_summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    no_changes_needed: bool = False


class _DiagnosticItemDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    need_files: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    decision_summary: str = ""


_CODER_SYSTEM_PROMPT = """Você executa UM ÚNICO item atômico do checklist do Modo Autônomo (Python, JS, TS ou React).
Seu trabalho é produzir passos determinísticos compatíveis com o executor (`create_file`, `replace_text`, `append`, `write_markdown`) e verificações (`file_exists`, `python_syntax`, `ts_check`, `contains`, `pytest`).

Regras rígidas:
1. Foque APENAS no item alvo atual. Não refatore código fora do escopo.
2. Nunca edite arquivos protegidos (.env, .git, venv, node_modules) e nunca remova testes existentes nem afrouxe assertions (`assert`/`expect`).
2.1. Respeite todas as convenções listadas e crie/atualize testes (`pytest` ou `vitest`/`jest`) quando alterar comportamento.
3. Em `replace_text`, copie `old` EXATAMENTE como está no arquivo atual fornecido.
4. INVESTIGAÇÃO ANTES DE EDITAR (MUITO IMPORTANTE): se precisar ler outro arquivo do projeto ou buscar onde um símbolo/componente/rota está definido para NÃO chutar, devolva `"steps": []` com `"need_files": ["caminho/arquivo"]` e/ou `"search_queries": ["termo"]` (até 2 rodadas de leitura rápida antes da edição final).
5. Preencha `commit_type` (`feat`, `fix`, `refactor`, `test`, `docs`, `style`, `perf`, `chore`) e `commit_scope` (ex.: `auth`, `routers`, `components`) no padrão Conventional Commits.
6. Responda EXCLUSIVAMENTE com JSON válido:
{
  "steps": [
    {"op": "replace_text", "path": "app/a.py", "old": "...", "new": "...", "occurrences": "one"}
  ],
  "verify": [
    {"type": "python_syntax", "path": "app/a.py"}
  ],
  "need_files": [],
  "search_queries": [],
  "commit_type": "fix",
  "commit_scope": "routers",
  "decision_summary": "Resumo de 1 frase do que foi feito",
  "evidence": ["Evidência objetiva"],
  "no_changes_needed": false
}"""

_DIAGNOSTIC_SYSTEM_PROMPT = """Você está em MODO DIAGNÓSTICO (SOMENTE LEITURA) do Modo Autônomo.
Analise os arquivos fornecidos buscando apenas evidências reais relacionadas ao item atual.
Se precisar abrir outro arquivo ou buscar um termo antes de concluir, retorne `need_files` e/ou `search_queries` (até 2 rodadas).
Não invente problemas nem proponha edições cegas.
Responda EXCLUSIVAMENTE com JSON válido:
{
  "summary": "Conclusão objetiva deste item",
  "findings": ["arquivo.py: evidência concreta encontrada"],
  "need_files": [],
  "search_queries": [],
  "decision_summary": "Resumo de 1 frase"
}"""


class AutonomousEngine:
    """Orquestra missões autônomas com contexto limpo a cada item, persistência em SQLite e sandbox Git."""

    def __init__(
        self,
        store: MissionStore | None = None,
        llm: LLMTextClient | None = None,
        executor: StepExecutorPort | None = None,
        inspector: RepoInspectorPort | None = None,
        reports_dir: str | Path | None = None,
    ) -> None:
        self.store = store or MissionStore()
        self.llm = llm or DefaultLLMClient()
        self.executor = executor or DefaultStepExecutor()
        self.inspector = inspector or DefaultRepoInspector()
        self.reports_dir = Path(reports_dir).expanduser().resolve() if reports_dir else None

    def create_mission(
        self,
        *,
        title: str,
        objective: str,
        workspace_path: str,
        business_rules: list[str] | None = None,
        conventions: list[str] | None = None,
        mode: MissionMode | None = None,
        config: MissionConfig | None = None,
    ) -> MissionRecord:
        mission = MissionRecord(
            title=title.strip(),
            objective=objective.strip(),
            business_rules=[r.strip() for r in (business_rules or []) if str(r).strip()],
            conventions=[c.strip() for c in (conventions or []) if str(c).strip()],
            workspace_path=str(Path(workspace_path).expanduser().resolve()),
            mode=mode or MissionMode.EDIT,
            config=config or MissionConfig(),
        )
        self.store.save(mission)
        self.store.append_event(mission.id, "created", f"Missão criada: {mission.title}")
        return mission

    def run_preflight(self, mission_id: str, *, auto_apply_mode: bool = True) -> MissionRecord:
        mission = self._require(mission_id)
        if mission.status == MissionStatus.CREATED:
            transition_mission(mission, MissionStatus.PREFLIGHT)

        report = analyze_scope_preflight(
            mission.objective,
            mission.workspace_path,
            business_rules=mission.business_rules,
            conventions=mission.conventions,
        )
        mission.preflight = report
        if auto_apply_mode:
            mission.mode = report.recommended_mode
            if report.recommended_mode == MissionMode.GREENFIELD_PHASED:
                mission.config.require_phase_approval = True

        if report.requires_confirmation:
            transition_mission(mission, MissionStatus.WAITING_CONFIRMATION)
            self.store.append_event(
                mission.id,
                "preflight_waiting",
                f"Pre-flight requer confirmação (clareza={report.clarity.value}, modo={mission.mode.value}).",
                {"missing_info": report.missing_info, "warnings": report.warnings},
            )
        else:
            transition_mission(mission, MissionStatus.PLANNING)
            self.store.append_event(
                mission.id,
                "preflight_ok",
                f"Pre-flight aprovado (clareza={report.clarity.value}, modo={mission.mode.value}).",
            )
        return self.store.save(mission)

    def confirm_preflight(
        self,
        mission_id: str,
        *,
        override_mode: MissionMode | None = None,
        extra_business_rules: list[str] | None = None,
        extra_conventions: list[str] | None = None,
    ) -> MissionRecord:
        mission = self._require(mission_id)
        if override_mode is not None:
            mission.mode = override_mode
        if extra_business_rules:
            mission.business_rules.extend(r.strip() for r in extra_business_rules if str(r).strip())
        if extra_conventions:
            mission.conventions.extend(c.strip() for c in extra_conventions if str(c).strip())

        if mission.status == MissionStatus.WAITING_CONFIRMATION:
            transition_mission(mission, MissionStatus.PLANNING)
            self.store.append_event(
                mission.id,
                "preflight_confirmed",
                f"Usuário confirmou início da missão no modo '{mission.mode.value}'.",
            )
            self.store.save(mission)
        return mission

    def reconcile_interrupted_missions(self) -> list[str]:
        """Converte missões interrompidas por queda/reinício do servidor em PAUSED para retomada segura."""
        active_statuses = {
            MissionStatus.PREFLIGHT,
            MissionStatus.PLANNING,
            MissionStatus.EXECUTING,
            MissionStatus.AUDITING,
            MissionStatus.FINAL_REVIEW,
        }
        reconciled: list[str] = []
        for mission in self.store.list_missions(limit=200):
            if mission.status not in active_statuses:
                continue
            for phase in mission.phases:
                for item in phase.items:
                    if item.status == ItemStatus.IN_PROGRESS:
                        item.status = ItemStatus.PENDING
            if mission.mode != MissionMode.DIAGNOSTIC_ONLY:
                sandbox = self._try_sandbox(mission)
                if sandbox is not None and mission.branch_name and sandbox.current_branch() == mission.branch_name:
                    try:
                        sandbox.rollback_working_tree()
                    except GitSandboxError:
                        pass
            transition_mission(mission, MissionStatus.PAUSED)
            self.store.save(mission)
            self.store.append_event(
                mission.id,
                "recovered_to_paused",
                "Servidor reiniciado durante execução; missão pausada com segurança para retomada.",
            )
            reconciled.append(mission.id)
        return reconciled

    def pause_mission(self, mission_id: str) -> MissionRecord:
        mission = self._require(mission_id)
        if mission.status != MissionStatus.PAUSED and mission.status not in TERMINAL_STATUSES:
            transition_mission(mission, MissionStatus.PAUSED)
            self.store.save(mission)
            self.store.append_event(mission.id, "paused", "Missão pausada pelo usuário.")
            self._maybe_unload_vram(mission)
        return mission

    def resume_mission(self, mission_id: str) -> MissionRecord:
        mission = self._require(mission_id)
        target = resume_target_status(mission)

        # Recuperação limpa caso a execução anterior tenha sido interrompida no meio de um item
        reset_any = False
        for phase in mission.phases:
            for item in phase.items:
                if item.status == ItemStatus.IN_PROGRESS:
                    item.status = ItemStatus.PENDING
                    reset_any = True
        if reset_any and mission.mode != MissionMode.DIAGNOSTIC_ONLY:
            sandbox = self._try_sandbox(mission)
            if sandbox is not None and sandbox.current_branch() == mission.branch_name:
                sandbox.rollback_working_tree()

        transition_mission(mission, target)
        self.store.save(mission)
        self.store.append_event(mission.id, "resumed", f"Missão retomada em '{target.value}'.")
        return mission

    def approve_phase_gate(self, mission_id: str) -> MissionRecord:
        mission = self._require(mission_id)
        if mission.status == MissionStatus.PHASE_GATE:
            nxt = next_pending_item(mission)
            target = MissionStatus.EXECUTING if nxt is not None else MissionStatus.FINAL_REVIEW
            transition_mission(mission, target)
            self.store.save(mission)
            self.store.append_event(mission.id, "phase_approved", f"Phase gate aprovado -> '{target.value}'.")
        return mission

    def update_mission(
        self,
        mission_id: str,
        *,
        title: str | None = None,
        objective: str | None = None,
        workspace_path: str | None = None,
        business_rules: list[str] | None = None,
        conventions: list[str] | None = None,
        mode: MissionMode | None = None,
        config: MissionConfig | None = None,
        rerun_preflight: bool = True,
        reset_plan: bool = False,
    ) -> MissionRecord:
        """Edita os parâmetros de uma missão parada/falha/pausada preservando histórico ou resetando o plano."""
        mission = self._require(mission_id)
        if mission.status == MissionStatus.DONE:
            raise ValueError("Missões já concluídas não podem ser editadas. Crie uma nova missão.")

        changed_fields: list[str] = []
        if title is not None and title.strip() and title.strip() != mission.title:
            mission.title = title.strip()
            changed_fields.append("title")
        if objective is not None and objective.strip() and objective.strip() != mission.objective:
            mission.objective = objective.strip()
            changed_fields.append("objective")

        workspace_changed = False
        if workspace_path is not None and workspace_path.strip():
            resolved_ws = str(Path(workspace_path).expanduser().resolve())
            if resolved_ws != mission.workspace_path:
                mission.workspace_path = resolved_ws
                changed_fields.append("workspace_path")
                workspace_changed = True

        if business_rules is not None:
            clean_rules = [r.strip() for r in business_rules if str(r).strip()]
            if clean_rules != mission.business_rules:
                mission.business_rules = clean_rules
                changed_fields.append("business_rules")
        if conventions is not None:
            clean_convs = [c.strip() for c in conventions if str(c).strip()]
            if clean_convs != mission.conventions:
                mission.conventions = clean_convs
                changed_fields.append("conventions")
        if mode is not None and mode != mission.mode:
            mission.mode = mode
            changed_fields.append("mode")
        if config is not None and config != mission.config:
            mission.config = config
            changed_fields.append("config")

        if workspace_changed:
            reset_plan = True
            mission.branch_name = None
            mission.base_commit = None

        if reset_plan:
            mission.phases = []
            mission.reviews = []
            mission.review_cycles_used = 0
            mission.tasks_executed = 0
            mission.report_path = None
            mission.last_error = None
            mission.finished_at = None
            mission.paused_from_status = None
            if not workspace_changed:
                mission.branch_name = None
                mission.base_commit = None
            changed_fields.append("reset_plan")

        should_preflight = rerun_preflight and (
            reset_plan
            or not mission.phases
            or mission.status
            in {
                MissionStatus.CREATED,
                MissionStatus.PREFLIGHT,
                MissionStatus.WAITING_CONFIRMATION,
                MissionStatus.PLANNING,
                MissionStatus.FAILED,
                MissionStatus.CANCELLED,
            }
        )
        if should_preflight:
            report = analyze_scope_preflight(
                mission.objective,
                mission.workspace_path,
                business_rules=mission.business_rules,
                conventions=mission.conventions,
            )
            mission.preflight = report
            mission.last_error = None
            mission.finished_at = None
            mission.paused_from_status = None
            mission.status = (
                MissionStatus.WAITING_CONFIRMATION
                if report.requires_confirmation
                else MissionStatus.PLANNING
            )
        elif mission.status in {
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.DONE_WITH_BLOCKERS,
        }:
            mission.last_error = None
            mission.finished_at = None
            mission.paused_from_status = MissionStatus.EXECUTING if mission.phases else MissionStatus.PLANNING
            mission.status = MissionStatus.PAUSED

        mission.updated_at = utc_now_iso()
        self.store.save(mission)
        fields_txt = ", ".join(changed_fields) if changed_fields else "sem alterações"
        self.store.append_event(
            mission.id,
            "edited",
            f"Missão editada ({fields_txt}). Status atual: '{mission.status.value}'.",
            {"changed_fields": changed_fields, "reset_plan": reset_plan},
        )
        return mission

    def retry_mission(self, mission_id: str, *, reset_plan: bool = False) -> MissionRecord:
        """Reabre e prepara uma missão falha, cancelada ou com bloqueios para nova execução."""
        mission = self._require(mission_id)
        if mission.status == MissionStatus.DONE:
            raise ValueError("Missão já concluída com sucesso.")

        mission.last_error = None
        mission.finished_at = None
        mission.paused_from_status = None
        mission.started_at = utc_now_iso()

        if reset_plan or not mission.phases:
            mission.phases = []
            mission.reviews = []
            mission.review_cycles_used = 0
            mission.tasks_executed = 0
            mission.report_path = None
            mission.branch_name = None
            mission.base_commit = None

            report = analyze_scope_preflight(
                mission.objective,
                mission.workspace_path,
                business_rules=mission.business_rules,
                conventions=mission.conventions,
            )
            mission.preflight = report
            if not Path(mission.workspace_path).is_dir():
                mission.status = MissionStatus.WAITING_CONFIRMATION
            else:
                mission.status = MissionStatus.PLANNING
            mission.updated_at = utc_now_iso()
            self.store.save(mission)
            self.store.append_event(
                mission.id,
                "retried",
                f"Missão reiniciada para '{mission.status.value}' (reset_plan={reset_plan}).",
            )
            return mission

        # Já possui plano por fases: reabilita itens bloqueados ou interrompidos
        reset_in_progress = False
        requeued_ids: list[str] = []
        for phase in mission.phases:
            for item in phase.items:
                if item.status in (ItemStatus.BLOCKED, ItemStatus.IN_PROGRESS):
                    if item.status == ItemStatus.IN_PROGRESS:
                        reset_in_progress = True
                    item.status = ItemStatus.PENDING
                    item.attempts = 0
                    item.last_error = None
                    item.updated_at = utc_now_iso()
                    requeued_ids.append(item.id)

        if reset_in_progress and mission.mode != MissionMode.DIAGNOSTIC_ONLY and mission.config.auto_commit:
            sandbox = self._try_sandbox(mission)
            if sandbox is not None and mission.branch_name and sandbox.current_branch() == mission.branch_name:
                try:
                    sandbox.rollback_working_tree()
                except GitSandboxError:
                    pass

        sync_phase_statuses(mission)
        nxt = next_pending_item(mission)
        if nxt is not None:
            if mission.tasks_executed >= mission.config.max_total_tasks:
                raise ValueError(
                    f"Limite máximo de tarefas já atingido ({mission.tasks_executed}/{mission.config.max_total_tasks}). "
                    "Edite a missão para aumentar o limite ou marque 'Resetar plano'."
                )
            transition_mission(mission, MissionStatus.EXECUTING)
        else:
            if mission.config.run_final_judge and mission.review_cycles_used >= mission.config.max_review_cycles:
                mission.review_cycles_used = max(0, mission.config.max_review_cycles - 1)
            target_status = (
                MissionStatus.FINAL_REVIEW if mission.config.run_final_judge else MissionStatus.AUDITING
            )
            transition_mission(mission, target_status)

        mission.updated_at = utc_now_iso()
        self.store.save(mission)
        extra = f" ({len(requeued_ids)} item(ns) recolocado(s) na fila)" if requeued_ids else ""
        self.store.append_event(
            mission.id,
            "retried",
            f"Missão retomada para '{mission.status.value}'{extra}.",
            {"requeued_items": requeued_ids},
        )
        return mission

    def retry_blocked_item(self, mission_id: str, item_id: str) -> MissionRecord:
        """Reagenda um item bloqueado para nova tentativa (inclusive em missões DONE_WITH_BLOCKERS)."""
        mission = self._require(mission_id)
        found_item = None
        for phase in mission.phases:
            for item in phase.items:
                if item.id == item_id:
                    found_item = item
                    break
        if found_item is None:
            raise KeyError(f"Item '{item_id}' não encontrado na missão '{mission_id}'.")

        found_item.status = ItemStatus.PENDING
        found_item.attempts = 0
        found_item.last_error = None
        found_item.updated_at = utc_now_iso()
        sync_phase_statuses(mission)

        if mission.status == MissionStatus.DONE_WITH_BLOCKERS:
            mission.status = MissionStatus.PAUSED
            mission.paused_from_status = MissionStatus.EXECUTING
            mission.finished_at = None
        mission.updated_at = utc_now_iso()
        self.store.save(mission)
        self.store.append_event(mission.id, "item_requeued", f"Item '{item_id}' recolocado na fila pelo usuário.")
        return mission

    def commit_pending_changes(self, mission_id: str, message: str | None = None) -> str | None:
        """Commita manualmente alterações pendentes na branch da missão (útil com auto_commit=False)."""
        mission = self._require(mission_id)
        sandbox = GitMissionSandbox(mission.workspace_path)
        if mission.branch_name and sandbox.current_branch() != mission.branch_name:
            raise GitSandboxError(
                f"Branch atual '{sandbox.current_branch()}' difere da branch da missão '{mission.branch_name}'."
            )
        sha = sandbox.commit_item(
            mission.id,
            message or f"Consolidar alterações da missão {mission.title}",
            allow_test_deletion=mission.config.allow_test_deletion,
        )
        if sha:
            self.store.append_event(mission.id, "manual_commit", f"Commit manual criado ({sha[:8]}).")
        return sha

    def _maybe_unload_vram(self, mission: MissionRecord) -> None:
        if not mission.config.unload_model_on_phase_switch:
            return
        unloader = getattr(self.llm, "unload_model", None)
        if callable(unloader):
            try:
                unloader()
            except Exception:  # noqa: BLE001
                pass

    def cancel_mission(self, mission_id: str) -> MissionRecord:
        mission = self._require(mission_id)
        if mission.status not in TERMINAL_STATUSES:
            if mission.mode != MissionMode.DIAGNOSTIC_ONLY:
                sandbox = self._try_sandbox(mission)
                if sandbox is not None and mission.branch_name and sandbox.current_branch() == mission.branch_name:
                    sandbox.rollback_working_tree()
            transition_mission(mission, MissionStatus.CANCELLED)
            self.store.save(mission)
            self.store.append_event(mission.id, "cancelled", "Missão cancelada pelo usuário.")
        return mission

    def step_once(self, mission_id: str) -> MissionRecord:
        """Avança exatamente 1 etapa determinística da máquina de estados com contexto zerado."""
        mission = self._require(mission_id)

        if mission.status == MissionStatus.CREATED:
            return self.run_preflight(mission.id)

        can_go, stop_reason = can_continue_mission(mission)
        if not can_go:
            if stop_reason and ("Limite máximo" in stop_reason or "Tempo máximo" in stop_reason):
                return self._finalize_mission(mission, audit=None, extra_note=stop_reason)
            return mission

        if mission.status == MissionStatus.PREFLIGHT:
            return self.run_preflight(mission.id)

        if mission.status == MissionStatus.PLANNING:
            return self._do_planning(mission)

        if mission.status == MissionStatus.EXECUTING:
            return self._do_execute_next_item(mission)

        if mission.status == MissionStatus.AUDITING:
            return self._do_phase_audit(mission)

        if mission.status == MissionStatus.FINAL_REVIEW:
            return self._do_final_review(mission)

        return mission

    def run_until_stop(self, mission_id: str, *, max_loop_ticks: int = 200) -> MissionRecord:
        """Executa ciclos consecutivos (cada um com contexto zerado) até pausar, pedir gate ou concluir."""
        mission = self._require(mission_id)
        for _ in range(max_loop_ticks):
            mission = self._require(mission_id)
            if mission.status in (
                MissionStatus.PAUSED,
                MissionStatus.WAITING_CONFIRMATION,
                MissionStatus.PHASE_GATE,
            ) or mission.status in TERMINAL_STATUSES:
                break
            before_sig = (
                mission.status,
                mission.tasks_executed,
                mission.review_cycles_used,
                len(mission.phases),
                calculate_progress(mission).done_items,
                calculate_progress(mission).blocked_items,
            )
            mission = self.step_once(mission_id)
            after_sig = (
                mission.status,
                mission.tasks_executed,
                mission.review_cycles_used,
                len(mission.phases),
                calculate_progress(mission).done_items,
                calculate_progress(mission).blocked_items,
            )
            if after_sig == before_sig:
                break
        return self._require(mission_id)

    def _require(self, mission_id: str) -> MissionRecord:
        mission = self.store.get(mission_id)
        if mission is None:
            raise KeyError(f"Missão '{mission_id}' não encontrada.")
        return mission

    def _gather_extra_investigation(
        self,
        workspace_path: str,
        need_files: list[str],
        search_queries: list[str],
    ) -> str:
        """Executa leitura extra solicitada pelo Coder/Diagnostic sem efeitos colaterais."""
        sections: list[str] = []
        clean_files = [str(p).strip().replace("\\", "/") for p in (need_files or []) if str(p).strip()][:5]
        if clean_files:
            loaded = self.inspector.read_files(workspace_path, clean_files, max_chars_per_file=5000)
            for rel, txt in loaded.items():
                sections.append(f"=== ARQUIVO SOLICITADO: {rel} ===\n{txt}")
        search_fn = getattr(self.inspector, "search_text", None)
        if callable(search_fn) and search_queries:
            hits = search_fn(workspace_path, search_queries[:5], max_hits=25)
            if hits:
                sections.append(f"=== RESULTADOS DA BUSCA ({', '.join(search_queries[:5])}) ===\n{hits}")
        return "\n\n".join(sections)

    def _try_sandbox(self, mission: MissionRecord) -> GitMissionSandbox | None:
        try:
            return GitMissionSandbox(mission.workspace_path)
        except GitSandboxError:
            return None

    def _do_planning(self, mission: MissionRecord) -> MissionRecord:
        if mission.mode != MissionMode.DIAGNOSTIC_ONLY:
            try:
                sandbox = GitMissionSandbox(mission.workspace_path)
                if not mission.base_commit:
                    mission.base_commit = sandbox.head_commit()
                branch, _ = sandbox.ensure_mission_branch(
                    mission.id,
                    mission.title,
                    prefix=mission.config.branch_prefix,
                )
                mission.branch_name = branch
            except GitSandboxError as exc:
                transition_mission(mission, MissionStatus.FAILED, error=str(exc))
                self.store.save(mission)
                self.store.append_event(mission.id, "failed", f"Sandbox Git falhou: {exc}")
                return mission

        try:
            phases, notes = build_mission_plan(mission, self.llm, self.inspector)
        except Exception as exc:  # noqa: BLE001
            transition_mission(mission, MissionStatus.FAILED, error=f"Falha no planejamento: {exc}")
            self.store.save(mission)
            self.store.append_event(mission.id, "planning_failed", str(exc))
            return mission

        mission.phases = phases
        for note in notes[:5]:
            mission.decisions.append(DecisionEntry(summary=f"[Plano] {note}"))

        transition_mission(mission, MissionStatus.EXECUTING)
        self.store.save(mission)
        total_items = sum(len(p.items) for p in phases)
        self.store.append_event(
            mission.id,
            "planned",
            f"Plano criado com {len(phases)} fase(s) e {total_items} item(ns).",
        )
        return mission

    def _do_execute_next_item(self, mission: MissionRecord) -> MissionRecord:
        nxt = next_pending_item(mission)
        if nxt is None:
            transition_mission(
                mission,
                MissionStatus.FINAL_REVIEW if mission.config.run_final_judge else MissionStatus.AUDITING,
            )
            return self.store.save(mission)

        phase, item = nxt
        item.status = ItemStatus.IN_PROGRESS
        item.attempts += 1
        item.updated_at = utc_now_iso()
        mission.tasks_executed += 1
        sync_phase_statuses(mission)
        self.store.save(mission)
        self.store.append_event(
            mission.id,
            "item_started",
            f"Iniciando {item.id} (tentativa {item.attempts}/{mission.config.max_retries_per_item}): {item.title}",
        )

        # Contexto 100% zerado a cada item (inclui arquivos-alvo + referências de imports/testes próximos)
        brief = build_clean_context_brief(mission)
        target_contents = self.inspector.read_files(mission.workspace_path, item.target_files)
        files_block = "\n\n".join(
            f"=== ARQUIVO ALVO: {p} ===\n{txt}" for p, txt in target_contents.items()
        ) or "(arquivos alvo ainda não existem ou não foram especificados)"

        discover_fn = getattr(self.inspector, "discover_related_files", None)
        if callable(discover_fn) and item.target_files:
            related_paths = discover_fn(mission.workspace_path, item.target_files)
            if related_paths:
                rel_contents = self.inspector.read_files(
                    mission.workspace_path, related_paths, max_chars_per_file=4000
                )
                if rel_contents:
                    ref_block = "\n\n".join(
                        f"=== REFERÊNCIA (somente leitura/contexto): {p} ===\n{txt}"
                        for p, txt in rel_contents.items()
                    )
                    files_block = f"{files_block}\n\n{ref_block}"

        if mission.mode == MissionMode.DIAGNOSTIC_ONLY:
            return self._execute_diagnostic_item(mission, phase, item, brief, files_block)
        return self._execute_edit_item(mission, phase, item, brief, files_block)

    def _execute_diagnostic_item(
        self,
        mission: MissionRecord,
        phase: MissionPhase,
        item: ChecklistItem,
        brief: str,
        files_block: str,
    ) -> MissionRecord:
        sandbox = self._try_sandbox(mission)
        try:
            current_files_block = files_block
            draft: _DiagnosticItemDraft | None = None
            for inv_round in range(3):
                extra_note = (
                    "\n\nATENÇÃO: última rodada de diagnóstico — conclua agora com `summary` e `findings` (sem `need_files`)."
                    if inv_round == 2
                    else ""
                )
                draft = invoke_structured_json(
                    self.llm,
                    role="diagnostic",
                    system_prompt=_DIAGNOSTIC_SYSTEM_PROMPT,
                    user_prompt=f"{brief}\n\n## Conteúdo dos Arquivos Alvo\n{current_files_block}{extra_note}",
                    schema_cls=_DiagnosticItemDraft,
                )
                if inv_round < 2 and not draft.summary and (draft.need_files or draft.search_queries):
                    extra_ctx = self._gather_extra_investigation(
                        mission.workspace_path, draft.need_files, draft.search_queries
                    )
                    if extra_ctx:
                        current_files_block = f"{current_files_block}\n\n{extra_ctx}"
                        continue
                break
            assert draft is not None
            if sandbox is not None and not sandbox.is_clean():
                sandbox.rollback_working_tree()
            item.status = ItemStatus.DONE
            item.last_error = None
            item.evidence.extend(draft.findings[:5] or [draft.summary])
            if draft.decision_summary:
                mission.decisions.append(
                    DecisionEntry(phase_id=phase.id, item_id=item.id, summary=draft.decision_summary)
                )
            self.store.append_event(mission.id, "item_done", f"[Diagnóstico] {item.id}: {draft.summary}")
        except Exception as exc:  # noqa: BLE001
            self._handle_item_failure(mission, item, f"Erro no diagnóstico: {exc}", sandbox=None)

        return self._after_item_transition(mission, phase)

    def _execute_edit_item(
        self,
        mission: MissionRecord,
        phase: MissionPhase,
        item: ChecklistItem,
        brief: str,
        files_block: str,
    ) -> MissionRecord:
        try:
            sandbox = GitMissionSandbox(mission.workspace_path)
            if mission.branch_name and sandbox.current_branch() != mission.branch_name:
                sandbox.ensure_mission_branch(mission.id, mission.title, prefix=mission.config.branch_prefix)
        except GitSandboxError as exc:
            transition_mission(mission, MissionStatus.FAILED, error=str(exc))
            self.store.save(mission)
            self.store.append_event(mission.id, "failed", str(exc))
            return mission

        retry_hint = (
            f"\n\n## Erro da tentativa anterior (corrija este problema):\n{item.last_error}"
            if item.last_error
            else ""
        )
        user_prompt = f"{brief}\n\n## Conteúdo Atual dos Arquivos Alvo\n{files_block}{retry_hint}"

        try:
            current_files_block = files_block
            draft: _ItemExecutionDraft | None = None
            for inv_round in range(3):
                final_round_hint = (
                    "\n\nATENÇÃO: limite de investigação atingido — entregue AGORA os `steps` finais (ou `no_changes_needed: true`)."
                    if inv_round == 2
                    else ""
                )
                round_prompt = (
                    f"{brief}\n\n## Conteúdo Atual dos Arquivos Alvo\n"
                    f"{current_files_block}{retry_hint}{final_round_hint}"
                )
                draft = invoke_structured_json(
                    self.llm,
                    role="coder",
                    system_prompt=_CODER_SYSTEM_PROMPT,
                    user_prompt=round_prompt,
                    schema_cls=_ItemExecutionDraft,
                )
                wants_more = (
                    inv_round < 2
                    and not draft.steps
                    and not draft.no_changes_needed
                    and bool(draft.need_files or draft.search_queries)
                )
                if wants_more:
                    extra_ctx = self._gather_extra_investigation(
                        mission.workspace_path, draft.need_files, draft.search_queries
                    )
                    if extra_ctx:
                        self.store.append_event(
                            mission.id,
                            "item_investigate",
                            f"{item.id} pediu contexto extra (rodada {inv_round + 1}): "
                            + ", ".join((draft.need_files + draft.search_queries)[:4]),
                        )
                        current_files_block = f"{current_files_block}\n\n{extra_ctx}"
                        continue
                break
            assert draft is not None
        except Exception as exc:  # noqa: BLE001
            self._handle_item_failure(mission, item, f"Falha ao gerar passos do item: {exc}", sandbox=sandbox)
            return self._after_item_transition(mission, phase)

        if draft.no_changes_needed and not draft.steps:
            item.status = ItemStatus.DONE
            item.last_error = None
            item.evidence.extend(draft.evidence or ["Sem alterações necessárias."])
            if draft.decision_summary:
                mission.decisions.append(
                    DecisionEntry(phase_id=phase.id, item_id=item.id, summary=draft.decision_summary)
                )
            self.store.append_event(mission.id, "item_done", f"{item.id} concluído sem alterações.")
            return self._after_item_transition(mission, phase)

        verify_checks = list(draft.verify)
        existing_pairs = {
            (c.get("type"), c.get("path")) for c in verify_checks if isinstance(c, dict)
        }
        ws_root = Path(mission.workspace_path).expanduser().resolve()
        has_tsconfig = (ws_root / "tsconfig.json").is_file()
        ts_check_added = any(t == "ts_check" for t, _ in existing_pairs)

        for step in draft.steps:
            if not isinstance(step, dict):
                continue
            step_path = str(step.get("path") or step.get("destination") or "").strip()
            if not step_path:
                continue
            if step_path.endswith(".py"):
                if ("python_syntax", step_path) not in existing_pairs:
                    verify_checks.append({"type": "python_syntax", "path": step_path})
                    existing_pairs.add(("python_syntax", step_path))
                if is_test_file_path(step_path) and ("pytest", step_path) not in existing_pairs:
                    verify_checks.append({"type": "pytest", "path": step_path})
                    existing_pairs.add(("pytest", step_path))
            elif step_path.lower().endswith((".ts", ".tsx")) and has_tsconfig and not ts_check_added:
                verify_checks.append({"type": "ts_check", "path": step_path})
                ts_check_added = True

        outcome = self.executor.execute(
            {"steps": draft.steps, "verify": verify_checks},
            mission.workspace_path,
        )
        if not outcome.ok:
            self._handle_item_failure(
                mission,
                item,
                outcome.error or "Execução determinística falhou.",
                sandbox=sandbox,
            )
            return self._after_item_transition(mission, phase)

        try:
            if mission.config.auto_commit:
                commit_sha = sandbox.commit_item(
                    item.id,
                    item.title,
                    allow_test_deletion=mission.config.allow_test_deletion,
                    commit_type=draft.commit_type or None,
                    commit_scope=draft.commit_scope or None,
                )
            else:
                sandbox.validate_working_changes(
                    allow_test_deletion=mission.config.allow_test_deletion
                )
                commit_sha = None
        except GitSandboxError as exc:
            self._handle_item_failure(mission, item, str(exc), sandbox=sandbox)
            return self._after_item_transition(mission, phase)

        item.status = ItemStatus.DONE
        item.last_error = None
        item.commit_sha = commit_sha
        item.updated_at = utc_now_iso()
        if draft.evidence:
            item.evidence.extend(draft.evidence[:4])
        elif outcome.report:
            item.evidence.append(outcome.report.splitlines()[0][:200])
        if draft.decision_summary:
            mission.decisions.append(
                DecisionEntry(phase_id=phase.id, item_id=item.id, summary=draft.decision_summary)
            )
        self.store.append_event(
            mission.id,
            "item_done",
            f"{item.id} concluído" + (f" (commit {commit_sha[:8]})" if commit_sha else ""),
        )
        return self._after_item_transition(mission, phase)

    def _handle_item_failure(
        self,
        mission: MissionRecord,
        item: ChecklistItem,
        error_msg: str,
        *,
        sandbox: GitMissionSandbox | None,
    ) -> None:
        # Com auto_commit=True, rollback Git limpa o item com segurança;
        # com auto_commit=False, evita apagar itens anteriores já concluídos (executor já fez FileSnapshot rollback).
        if sandbox is not None and mission.config.auto_commit:
            try:
                sandbox.rollback_working_tree()
            except GitSandboxError:
                pass
        item.last_error = error_msg[:1000]
        item.updated_at = utc_now_iso()
        if item.attempts >= mission.config.max_retries_per_item:
            item.status = ItemStatus.BLOCKED
            self.store.append_event(
                mission.id,
                "item_blocked",
                f"{item.id} bloqueado após {item.attempts} tentativa(s): {item.last_error[:180]}",
            )
        else:
            item.status = ItemStatus.PENDING
            self.store.append_event(
                mission.id,
                "item_retry",
                f"{item.id} falhou (tentativa {item.attempts}); rollback aplicado e reagendado.",
            )

    def _after_item_transition(self, mission: MissionRecord, current_phase: MissionPhase) -> MissionRecord:
        # Re-lê status atual do banco para honrar pause/cancel concorrente imediatamente
        fresh = self.store.get(mission.id)
        if fresh and fresh.status in (MissionStatus.PAUSED, MissionStatus.CANCELLED):
            mission.status = fresh.status
            mission.paused_from_status = fresh.paused_from_status
            return self.store.save(mission)

        sync_phase_statuses(mission)
        phase_finished = current_phase.status in (PhaseStatus.COMPLETED, PhaseStatus.BLOCKED)
        if phase_finished:
            if mission.config.run_audit_per_phase:
                transition_mission(mission, MissionStatus.AUDITING)
            elif mission.config.require_phase_approval and next_pending_item(mission) is not None:
                transition_mission(mission, MissionStatus.PHASE_GATE)
            elif next_pending_item(mission) is None:
                transition_mission(
                    mission,
                    MissionStatus.FINAL_REVIEW if mission.config.run_final_judge else MissionStatus.DONE,
                )
        return self.store.save(mission)

    def _do_phase_audit(self, mission: MissionRecord) -> MissionRecord:
        sandbox = self._try_sandbox(mission)
        audit = run_objective_audit(mission, self.inspector, sandbox)

        # Registra resumo na última fase concluída/bloqueada sem audit_summary
        for phase in reversed(sorted(mission.phases, key=lambda p: p.order)):
            if phase.status in (PhaseStatus.COMPLETED, PhaseStatus.BLOCKED) and not phase.audit_summary:
                phase.audit_summary = audit.to_short_text()
                break

        self.store.append_event(
            mission.id,
            "phase_audited",
            f"Auditoria da fase: {'OK' if audit.passed else 'FALHAS'}",
            {"blocking": audit.blocking_issues, "warnings": audit.warnings},
        )

        nxt = next_pending_item(mission)
        if nxt is not None:
            if mission.config.require_phase_approval:
                transition_mission(mission, MissionStatus.PHASE_GATE)
                self.store.append_event(
                    mission.id,
                    "phase_gate",
                    "Aguardando aprovação do usuário para iniciar a próxima fase.",
                )
            else:
                transition_mission(mission, MissionStatus.EXECUTING)
            return self.store.save(mission)

        if mission.config.run_final_judge:
            transition_mission(mission, MissionStatus.FINAL_REVIEW)
            return self.store.save(mission)

        return self._finalize_mission(mission, audit=audit)

    def _do_final_review(self, mission: MissionRecord) -> MissionRecord:
        self._maybe_unload_vram(mission)
        sandbox = self._try_sandbox(mission)
        audit = run_objective_audit(mission, self.inspector, sandbox)
        diff_text = (
            sandbox.diff_from_base(mission.base_commit)
            if (sandbox is not None and mission.base_commit and mission.mode != MissionMode.DIAGNOSTIC_ONLY)
            else ""
        )

        mission.review_cycles_used += 1
        cycle = mission.review_cycles_used
        verdict = evaluate_final_review(mission, audit, diff_text, self.llm, cycle=cycle)
        mission.reviews.append(verdict)
        self.store.append_event(
            mission.id,
            "final_review",
            f"Juiz Final ciclo {cycle}: {'APROVADO' if verdict.approved else 'PENDÊNCIAS'} "
            f"({verdict.score_objective_pct:.1f}% efetivo).",
            {"findings": verdict.findings, "follow_up_items": verdict.follow_up_items},
        )

        if (
            not verdict.approved
            and verdict.follow_up_items
            and mission.mode != MissionMode.DIAGNOSTIC_ONLY
            and mission.review_cycles_used < mission.config.max_review_cycles
            and mission.tasks_executed < mission.config.max_total_tasks
        ):
            new_order = len(mission.phases) + 1
            phase_id = f"rev{cycle}"
            fix_items = [
                ChecklistItem(
                    id=f"{phase_id}_i{idx}",
                    phase_id=phase_id,
                    title=text[:120],
                    description=text,
                    acceptance_criteria=["Resolver pendência apontada pelo Juiz Final e manter testes verdes."],
                )
                for idx, text in enumerate(verdict.follow_up_items[:5], start=1)
            ]
            mission.phases.append(
                MissionPhase(
                    id=phase_id,
                    order=new_order,
                    title=f"Correções do Ciclo de Revisão {cycle}",
                    goal="Resolver pendências identificadas na revisão final.",
                    items=fix_items,
                )
            )
            transition_mission(mission, MissionStatus.EXECUTING)
            return self.store.save(mission)

        return self._finalize_mission(mission, audit=audit)

    def _finalize_mission(
        self,
        mission: MissionRecord,
        *,
        audit: AuditReport | None,
        extra_note: str | None = None,
    ) -> MissionRecord:
        if extra_note:
            mission.decisions.append(DecisionEntry(summary=f"[Encerramento] {extra_note}"))
        progress = calculate_progress(mission)
        has_blockers = (
            progress.blocked_items > 0
            or progress.pending_items > 0
            or (audit is not None and not audit.passed)
        )
        final_status = MissionStatus.DONE_WITH_BLOCKERS if has_blockers else MissionStatus.DONE
        transition_mission(mission, final_status)
        report_file = write_mission_report(mission, audit=audit, reports_dir=self.reports_dir)
        mission.report_path = str(report_file)
        self.store.save(mission)
        self.store.append_event(
            mission.id,
            "finished",
            f"Missão encerrada em '{final_status.value}' ({progress.effective_pct:.1f}% efetivo). Relatório: {report_file.name}",
        )
        return mission

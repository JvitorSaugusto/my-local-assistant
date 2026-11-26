"""Modo Autônomo isolado para o my-local-assistant.

Arquitetura em fases com foco em confiabilidade máxima:
- Máquina de estados determinística (sem controle solto no LLM);
- Persistência isolada em SQLite WAL (zero acoplamento com migrations do banco principal);
- Isolamento em branch Git própria com commit por item e rollback cirúrgico;
- Guardas anti-trapaça em testes, auditoria objetiva e Juiz Final isolado.
"""

from .adapters import (
    DefaultLLMClient,
    DefaultRepoInspector,
    DefaultStepExecutor,
    StepExecutionOutcome,
    extract_json_payload,
    invoke_structured_json,
)
from .auditor import AuditReport, run_objective_audit
from .guards import (
    GitMissionSandbox,
    TestTamperingReport,
    detect_test_tampering,
    format_conventional_commit,
    is_protected_relative_path,
)
from .judge import evaluate_final_review, write_mission_report
from .planner import build_mission_plan
from .preflight import analyze_scope_preflight
from .runner import AutonomousEngine
from .schemas import (
    ChecklistItem,
    DecisionEntry,
    ItemStatus,
    MissionConfig,
    MissionMode,
    MissionPhase,
    MissionProgress,
    MissionRecord,
    MissionStatus,
    PhaseStatus,
    PreflightReport,
    ReviewVerdict,
    ScopeClarity,
)
from .state_machine import (
    InvalidTransitionError,
    VALID_TRANSITIONS,
    calculate_progress,
    can_continue_mission,
    check_budget_exceeded,
    transition_mission,
)
from .store import MissionStore, build_clean_context_brief

__all__ = [
    "AuditReport",
    "AutonomousEngine",
    "ChecklistItem",
    "DecisionEntry",
    "DefaultLLMClient",
    "DefaultRepoInspector",
    "DefaultStepExecutor",
    "GitMissionSandbox",
    "InvalidTransitionError",
    "ItemStatus",
    "MissionConfig",
    "MissionMode",
    "MissionPhase",
    "MissionProgress",
    "MissionRecord",
    "MissionStatus",
    "MissionStore",
    "PhaseStatus",
    "PreflightReport",
    "ReviewVerdict",
    "ScopeClarity",
    "StepExecutionOutcome",
    "TestTamperingReport",
    "VALID_TRANSITIONS",
    "analyze_scope_preflight",
    "build_clean_context_brief",
    "build_mission_plan",
    "calculate_progress",
    "can_continue_mission",
    "check_budget_exceeded",
    "detect_test_tampering",
    "evaluate_final_review",
    "extract_json_payload",
    "format_conventional_commit",
    "invoke_structured_json",
    "is_protected_relative_path",
    "run_objective_audit",
    "transition_mission",
    "write_mission_report",
]

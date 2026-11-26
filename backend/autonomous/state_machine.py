"""Máquina de estados determinística, cálculo objetivo de progresso e controle de budgets."""

from __future__ import annotations

from datetime import datetime, timezone

from .schemas import (
    ChecklistItem,
    ItemStatus,
    MissionPhase,
    MissionProgress,
    MissionRecord,
    MissionStatus,
    PhaseStatus,
    utc_now_iso,
)


class InvalidTransitionError(ValueError):
    """Lançada quando uma transição de status viola a máquina de estados da missão."""


TERMINAL_STATUSES: frozenset[MissionStatus] = frozenset(
    {
        MissionStatus.DONE,
        MissionStatus.DONE_WITH_BLOCKERS,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
    }
)

PAUSABLE_STATUSES: frozenset[MissionStatus] = frozenset(
    {
        MissionStatus.PREFLIGHT,
        MissionStatus.WAITING_CONFIRMATION,
        MissionStatus.PLANNING,
        MissionStatus.EXECUTING,
        MissionStatus.PHASE_GATE,
        MissionStatus.AUDITING,
        MissionStatus.FINAL_REVIEW,
    }
)

VALID_TRANSITIONS: dict[MissionStatus, frozenset[MissionStatus]] = {
    MissionStatus.CREATED: frozenset(
        {
            MissionStatus.PREFLIGHT,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.PREFLIGHT: frozenset(
        {
            MissionStatus.WAITING_CONFIRMATION,
            MissionStatus.PLANNING,
            MissionStatus.PAUSED,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.WAITING_CONFIRMATION: frozenset(
        {
            MissionStatus.PREFLIGHT,
            MissionStatus.PLANNING,
            MissionStatus.PAUSED,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.PLANNING: frozenset(
        {
            MissionStatus.EXECUTING,
            MissionStatus.WAITING_CONFIRMATION,
            MissionStatus.PAUSED,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.EXECUTING: frozenset(
        {
            MissionStatus.PHASE_GATE,
            MissionStatus.AUDITING,
            MissionStatus.FINAL_REVIEW,
            MissionStatus.PAUSED,
            MissionStatus.DONE,
            MissionStatus.DONE_WITH_BLOCKERS,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.PHASE_GATE: frozenset(
        {
            MissionStatus.EXECUTING,
            MissionStatus.AUDITING,
            MissionStatus.FINAL_REVIEW,
            MissionStatus.PAUSED,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.AUDITING: frozenset(
        {
            MissionStatus.EXECUTING,
            MissionStatus.PHASE_GATE,
            MissionStatus.FINAL_REVIEW,
            MissionStatus.PAUSED,
            MissionStatus.DONE,
            MissionStatus.DONE_WITH_BLOCKERS,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.FINAL_REVIEW: frozenset(
        {
            MissionStatus.EXECUTING,
            MissionStatus.DONE,
            MissionStatus.DONE_WITH_BLOCKERS,
            MissionStatus.PAUSED,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.PAUSED: frozenset(
        {
            MissionStatus.PREFLIGHT,
            MissionStatus.WAITING_CONFIRMATION,
            MissionStatus.PLANNING,
            MissionStatus.EXECUTING,
            MissionStatus.PHASE_GATE,
            MissionStatus.AUDITING,
            MissionStatus.FINAL_REVIEW,
            MissionStatus.CANCELLED,
            MissionStatus.FAILED,
        }
    ),
    MissionStatus.DONE: frozenset(),
    MissionStatus.DONE_WITH_BLOCKERS: frozenset(),
    MissionStatus.FAILED: frozenset(),
    MissionStatus.CANCELLED: frozenset(),
}


def transition_mission(
    mission: MissionRecord,
    target: MissionStatus,
    *,
    error: str | None = None,
) -> MissionRecord:
    """Aplica uma transição validada na missão, preservando estado para pause/resume."""
    current = mission.status
    if current == target:
        return mission

    allowed = VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Transição inválida na missão '{mission.id}': {current.value} -> {target.value}"
        )

    now = utc_now_iso()
    if target == MissionStatus.PAUSED:
        if current not in PAUSABLE_STATUSES:
            raise InvalidTransitionError(
                f"Estado '{current.value}' não pode ser pausado."
            )
        mission.paused_from_status = current
    elif current == MissionStatus.PAUSED and target != MissionStatus.CANCELLED:
        mission.paused_from_status = None

    if target == MissionStatus.EXECUTING and mission.started_at is None:
        mission.started_at = now
    if target in TERMINAL_STATUSES:
        mission.finished_at = now
    if error is not None:
        mission.last_error = error

    mission.status = target
    mission.updated_at = now
    return mission


def resume_target_status(mission: MissionRecord) -> MissionStatus:
    """Retorna o status exato para retomar uma missão pausada."""
    if mission.status != MissionStatus.PAUSED:
        raise InvalidTransitionError(
            f"Missão '{mission.id}' não está pausada (status atual: {mission.status.value})."
        )
    return mission.paused_from_status or MissionStatus.EXECUTING


def sync_phase_statuses(mission: MissionRecord) -> None:
    """Recalcula deterministicamente o status de cada fase a partir dos itens dela."""
    for phase in mission.phases:
        if not phase.items:
            continue
        statuses = {item.status for item in phase.items}
        if ItemStatus.IN_PROGRESS in statuses:
            phase.status = PhaseStatus.IN_PROGRESS
        elif statuses.issubset({ItemStatus.DONE, ItemStatus.SKIPPED}):
            phase.status = PhaseStatus.COMPLETED
        elif ItemStatus.PENDING not in statuses and ItemStatus.BLOCKED in statuses:
            phase.status = PhaseStatus.BLOCKED
        elif any(s in statuses for s in (ItemStatus.DONE, ItemStatus.BLOCKED, ItemStatus.SKIPPED)):
            phase.status = PhaseStatus.IN_PROGRESS
        else:
            phase.status = PhaseStatus.PENDING


def next_pending_item(mission: MissionRecord) -> tuple[MissionPhase, ChecklistItem] | None:
    """Retorna o próximo item elegível respeitando estritamente a ordem das fases."""
    ordered_phases = sorted(mission.phases, key=lambda p: p.order)
    for phase in ordered_phases:
        for item in phase.items:
            if item.status == ItemStatus.PENDING:
                return phase, item
    return None


def calculate_progress(mission: MissionRecord) -> MissionProgress:
    """Calcula progresso 100% objetivo a partir dos itens validados (nunca estimativa subjetiva)."""
    sync_phase_statuses(mission)
    all_items = [item for phase in mission.phases for item in phase.items]
    total = len(all_items)
    done = sum(1 for i in all_items if i.status == ItemStatus.DONE)
    blocked = sum(1 for i in all_items if i.status == ItemStatus.BLOCKED)
    pending = sum(1 for i in all_items if i.status == ItemStatus.PENDING)
    in_progress = sum(1 for i in all_items if i.status == ItemStatus.IN_PROGRESS)
    skipped = sum(1 for i in all_items if i.status == ItemStatus.SKIPPED)

    actionable = max(0, total - skipped)
    if actionable == 0:
        completion_pct = 100.0 if total > 0 else 0.0
        effective_pct = completion_pct
    else:
        completion_pct = round(((done + blocked) / actionable) * 100.0, 1)
        effective_pct = round((done / actionable) * 100.0, 1)

    total_phases = len(mission.phases)
    completed_phases = sum(1 for p in mission.phases if p.status == PhaseStatus.COMPLETED)

    return MissionProgress(
        total_items=total,
        done_items=done,
        blocked_items=blocked,
        pending_items=pending,
        in_progress_items=in_progress,
        skipped_items=skipped,
        completion_pct=completion_pct,
        effective_pct=effective_pct,
        total_phases=total_phases,
        completed_phases=completed_phases,
    )


def check_budget_exceeded(mission: MissionRecord) -> str | None:
    """Verifica budgets rígidos (tasks executadas, ciclos de revisão, tempo máximo)."""
    if mission.tasks_executed >= mission.config.max_total_tasks:
        return (
            f"Limite máximo de tarefas atingido "
            f"({mission.tasks_executed}/{mission.config.max_total_tasks})."
        )
    if mission.review_cycles_used > mission.config.max_review_cycles:
        return (
            f"Limite máximo de ciclos de revisão atingido "
            f"({mission.review_cycles_used}/{mission.config.max_review_cycles})."
        )
    if mission.started_at:
        try:
            started = datetime.fromisoformat(mission.started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60.0
            if elapsed_min >= mission.config.max_runtime_minutes:
                return (
                    f"Tempo máximo de execução atingido "
                    f"({elapsed_min:.1f}/{mission.config.max_runtime_minutes} min)."
                )
        except ValueError:
            pass
    return None


def can_continue_mission(mission: MissionRecord) -> tuple[bool, str | None]:
    """Determina se o loop autônomo pode avançar para o próximo ciclo."""
    if mission.status in TERMINAL_STATUSES:
        return False, f"Missão já encerrada em '{mission.status.value}'."
    if mission.status == MissionStatus.PAUSED:
        return False, "Missão pausada pelo usuário."
    if mission.status == MissionStatus.WAITING_CONFIRMATION:
        return False, "Aguardando confirmação do usuário no Pre-flight."
    if mission.status == MissionStatus.PHASE_GATE:
        return False, "Aguardando aprovação para avançar para a próxima fase."
    budget_reason = check_budget_exceeded(mission)
    if budget_reason:
        return False, budget_reason
    return True, None

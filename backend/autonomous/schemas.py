"""Modelos Pydantic v2 estritos do Modo Autônomo."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MissionStatus(str, Enum):
    CREATED = "created"
    PREFLIGHT = "preflight"
    WAITING_CONFIRMATION = "waiting_confirmation"
    PLANNING = "planning"
    EXECUTING = "executing"
    PHASE_GATE = "phase_gate"
    AUDITING = "auditing"
    FINAL_REVIEW = "final_review"
    PAUSED = "paused"
    DONE = "done"
    DONE_WITH_BLOCKERS = "done_with_blockers"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MissionMode(str, Enum):
    EDIT = "edit"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    GREENFIELD_PHASED = "greenfield_phased"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class ItemStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class ScopeClarity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MissionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_total_tasks: int = Field(default=30, ge=1, le=200)
    max_retries_per_item: int = Field(default=3, ge=1, le=10)
    max_review_cycles: int = Field(default=2, ge=0, le=5)
    max_runtime_minutes: int = Field(default=180, ge=5, le=1440)
    require_phase_approval: bool = False
    allow_test_deletion: bool = False
    run_audit_per_phase: bool = True
    run_final_judge: bool = True
    auto_commit: bool = True
    unload_model_on_phase_switch: bool = True
    branch_prefix: str = "auto"


class PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarity: ScopeClarity
    recommended_mode: MissionMode
    estimated_success_band: Literal["alta", "media", "baixa"]
    requires_confirmation: bool = False
    missing_info: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    detected_targets: list[str] = Field(default_factory=list)
    questions_for_user: list[str] = Field(default_factory=list)
    checked_at: str = Field(default_factory=utc_now_iso)


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    phase_id: str
    title: str
    description: str = ""
    target_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: ItemStatus = ItemStatus.PENDING
    attempts: int = 0
    commit_sha: str | None = None
    last_error: str | None = None
    evidence: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)


class MissionPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int
    title: str
    goal: str = ""
    status: PhaseStatus = PhaseStatus.PENDING
    items: list[ChecklistItem] = Field(default_factory=list)
    audit_summary: str | None = None


class DecisionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(default_factory=utc_now_iso)
    phase_id: str | None = None
    item_id: str | None = None
    summary: str


class ReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle: int
    approved: bool
    score_objective_pct: float = Field(ge=0.0, le=100.0)
    summary: str
    findings: list[str] = Field(default_factory=list)
    follow_up_items: list[str] = Field(default_factory=list)
    reviewed_at: str = Field(default_factory=utc_now_iso)


class MissionProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_items: int
    done_items: int
    blocked_items: int
    pending_items: int
    in_progress_items: int
    skipped_items: int
    completion_pct: float
    effective_pct: float
    total_phases: int
    completed_phases: int


class MissionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str
    objective: str
    business_rules: list[str] = Field(default_factory=list)
    conventions: list[str] = Field(default_factory=list)
    workspace_path: str
    mode: MissionMode = MissionMode.EDIT
    status: MissionStatus = MissionStatus.CREATED
    paused_from_status: MissionStatus | None = None
    branch_name: str | None = None
    base_commit: str | None = None
    config: MissionConfig = Field(default_factory=MissionConfig)
    preflight: PreflightReport | None = None
    phases: list[MissionPhase] = Field(default_factory=list)
    decisions: list[DecisionEntry] = Field(default_factory=list)
    reviews: list[ReviewVerdict] = Field(default_factory=list)
    tasks_executed: int = 0
    review_cycles_used: int = 0
    report_path: str | None = None
    last_error: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None

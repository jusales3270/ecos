"""Typed contracts for the operational API layer."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class OperationalModel(BaseModel):
    """Base operational model."""

    model_config = ConfigDict(str_strip_whitespace=True)


class OperationalSessionStatus(StrEnum):
    """Operational session statuses shown to users."""

    CREATED = "created"
    PROCESSING = "processing"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    """Human approval lifecycle states."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionStatus(StrEnum):
    """Operational execution lifecycle states."""

    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TimelineEntry(OperationalModel):
    """Safe operational timeline entry."""

    sequence: int = Field(ge=1)
    event_type: str
    message: str
    occurred_at: datetime = Field(default_factory=utc_now)
    actor_id: UUID | None = None
    correlation_id: UUID
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationView(OperationalModel):
    """Recommendation summary safe for UI display."""

    recommendation_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    risks: tuple[str, ...] = Field(default_factory=tuple)
    evidence: tuple[str, ...] = Field(default_factory=tuple)
    plan: tuple[str, ...] = Field(default_factory=tuple)
    reasoning: str | None = None
    debate: str | None = None
    simulation: str | None = None
    decision: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("risks", "evidence", "plan", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[str, ...]:
        return tuple(str(item) for item in (value or ()))


class ApprovalView(OperationalModel):
    """Human approval request exposed by the API."""

    approval_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    session_id: UUID
    recommendation_id: UUID
    requester_id: UUID
    requester_email: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    risks: tuple[str, ...] = Field(default_factory=tuple)
    plan: tuple[str, ...] = Field(default_factory=tuple)
    required_independent_approver: bool = True
    decided_by: UUID | None = None
    decided_by_email: str | None = None
    decided_at: datetime | None = None
    rejection_reason: str | None = None
    correlation_id: UUID
    created_at: datetime = Field(default_factory=utc_now)


class ExecutionView(OperationalModel):
    """Execution record shown by the operational UI."""

    execution_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    session_id: UUID
    approval_id: UUID | None = None
    status: ExecutionStatus = ExecutionStatus.BLOCKED
    approved_plan: tuple[str, ...] = Field(default_factory=tuple)
    attempts: int = 0
    connector_id: str = "memory.dry_run"
    dry_run: bool = True
    result: str | None = None
    error: str | None = None
    observations: tuple[str, ...] = Field(default_factory=tuple)
    feedback: tuple[str, ...] = Field(default_factory=tuple)
    learning: tuple[str, ...] = Field(default_factory=tuple)
    history: tuple[TimelineEntry, ...] = Field(default_factory=tuple)
    correlation_id: UUID
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OperationalSessionView(OperationalModel):
    """Complete operational session view."""

    session_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    created_by: UUID
    created_by_email: str
    objective: str
    description: str | None = None
    status: OperationalSessionStatus = OperationalSessionStatus.CREATED
    context: dict[str, Any] = Field(default_factory=dict)
    stages: tuple[str, ...] = Field(default_factory=tuple)
    recommendation: RecommendationView | None = None
    approval: ApprovalView | None = None
    execution: ExecutionView | None = None
    timeline: tuple[TimelineEntry, ...] = Field(default_factory=tuple)
    correlation_id: UUID
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OrganizationOverview(OperationalModel):
    """Dashboard data scoped to one organization."""

    organization: dict[str, Any]
    user: dict[str, Any]
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    recent_sessions: tuple[OperationalSessionView, ...]
    sessions_by_status: dict[str, int]
    pending_approvals: int
    running_executions: int
    approval_rate: float
    execution_success_rate: float
    average_recommendation_confidence: float
    recent_events: tuple[dict[str, Any], ...]
    component_health: tuple[dict[str, Any], ...]
    observability: dict[str, Any]


class OperationalMetrics(OperationalModel):
    """Operational counters safe for API and text exposition."""

    requests_total: int = 0
    errors_total: int = 0
    sessions_started: int = 0
    sessions_completed: int = 0
    approvals: int = 0
    rejections: int = 0
    executions: int = 0
    execution_failures: int = 0
    access_denied: int = 0
    cross_tenant_attempts: int = 0
    login_throttled: int = 0
    login_blocked: int = 0
    rate_limit_hits: int = 0
    jwt_validation_failures: int = 0
    revoked_sessions: int = 0
    outbox_pending: int = 0
    outbox_delivered: int = 0
    outbox_failed: int = 0
    reconciliation_checks: int = 0
    latency_seconds_total: float = 0.0

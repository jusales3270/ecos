"""Immutable models for persistent events, audit and observability."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.events.models import Event


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class ObservabilityModel(BaseModel):
    """Base immutable model for observability records."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


class RetentionClass(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    COLD = "cold"
    HISTORICAL = "historical"


class IntegrityStatus(StrEnum):
    VALID = "valid"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"
    FAILED = "failed"


class StoredEvent(ObservabilityModel):
    """Append-only persisted wrapper around an immutable Event."""

    event: Event
    stored_sequence: int = Field(gt=0)
    stored_at: datetime = Field(default_factory=utc_now)
    fingerprint: str = Field(min_length=64, max_length=64)
    storage_version: int = Field(default=1, gt=0)
    retention_class: RetentionClass = RetentionClass.ACTIVE
    integrity_status: IntegrityStatus = IntegrityStatus.VALID
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_stored_at(self) -> Self:
        if self.stored_at.tzinfo is None:
            raise ValueError("stored_at must be timezone-aware")
        return self


class EventQuery(ObservabilityModel):
    """Composable safe filters for event queries."""

    organization_id: UUID
    session_id: UUID | None = None
    correlation_id: UUID | None = None
    event_types: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    source_component: str | None = None
    retention_class: RetentionClass | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    sequence_after: int | None = Field(default=None, ge=0)
    sequence_from: int | None = Field(default=None, ge=1)
    sequence_to: int | None = Field(default=None, ge=1)
    limit: int = Field(default=100, ge=1, le=1000)

    @field_validator("event_types", "categories", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[str, ...]:
        return tuple(str(item) for item in (value or ()))

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time cannot be after end_time")
        if (
            self.sequence_from
            and self.sequence_to
            and self.sequence_from > self.sequence_to
        ):
            raise ValueError("sequence_from cannot be greater than sequence_to")
        return self


class EventDeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


class EventDeliveryRecord(ObservabilityModel):
    delivery_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    consumer_id: str = Field(min_length=1)
    status: EventDeliveryStatus
    attempt: int = Field(default=1, ge=1)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    safe_error: str | None = None
    reason_codes: tuple[str, ...] = ()
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class AuditDecision(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    REQUESTED = "requested"
    RECORDED = "recorded"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class AuditRecord(ObservabilityModel):
    """Persistent append-only audit record projected from a source event."""

    audit_id: UUID = Field(default_factory=uuid4)
    source_event_id: UUID
    governance_id: UUID | None = None
    execution_id: UUID | None = None
    organization_id: UUID
    session_id: UUID | None = None
    plan_id: UUID | None = None
    correlation_id: UUID | None = None
    timestamp: datetime
    sequence: int = Field(gt=0)
    actor_id: str | None = None
    actor_role: str | None = None
    component: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource_type: str | None = None
    resource_reference: str | None = None
    decision: AuditDecision = AuditDecision.NOT_APPLICABLE
    outcome: str | None = None
    policy_references: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    previous_state_reference: str | None = None
    new_state_reference: str | None = None
    fingerprint: str = Field(min_length=64, max_length=64)
    previous_record_hash: str | None = None
    record_hash: str | None = None
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("policy_references", "reason_codes", mode="before")
    @classmethod
    def tuple_fields(cls, value: object) -> tuple[str, ...]:
        return tuple(str(item) for item in (value or ()))


class MetricType(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    DURATION = "duration"
    RATIO = "ratio"
    SCORE = "score"
    COST_UNITS = "cost_units"


class ObservabilityLevel(StrEnum):
    INFRASTRUCTURE = "infrastructure"
    PLATFORM = "platform"
    COGNITIVE = "cognitive"
    ORGANIZATIONAL = "organizational"


class MetricRecord(ObservabilityModel):
    metric_id: UUID = Field(default_factory=uuid4)
    metric_name: str = Field(min_length=1)
    metric_type: MetricType
    level: ObservabilityLevel
    organization_id: UUID
    session_id: UUID | None = None
    correlation_id: UUID | None = None
    component: str = Field(min_length=1)
    value: float
    unit: str | None = None
    occurred_at: datetime
    recorded_at: datetime = Field(default_factory=utc_now)
    dimensions: dict[str, str] = Field(default_factory=dict)
    source_event_id: UUID
    reason_codes: tuple[str, ...] = ()
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        if not isfinite(self.value):
            raise ValueError("metric value must be finite")
        if self.metric_type in {MetricType.RATIO, MetricType.SCORE} and not (
            0.0 <= self.value <= 1.0
        ):
            raise ValueError("ratio and score metrics must be between 0 and 1")
        if (
            self.metric_type in {MetricType.COUNTER, MetricType.DURATION}
            and self.value < 0
        ):
            raise ValueError("counter and duration metrics cannot be negative")
        return self


class LogSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class StructuredLogRecord(ObservabilityModel):
    log_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utc_now)
    severity: LogSeverity
    organization_id: UUID
    session_id: UUID | None = None
    correlation_id: UUID | None = None
    component: str = Field(min_length=1)
    event_id: UUID | None = None
    message_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1, max_length=500)
    classification: str = "internal"
    reason_codes: tuple[str, ...] = ()
    dimensions: dict[str, str] = Field(default_factory=dict)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class TraceStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


class TraceSpan(ObservabilityModel):
    span_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID
    parent_span_id: UUID | None = None
    component: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    stage_id: str | None = None
    engine: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration: float | None = Field(default=None, ge=0)
    status: TraceStatus = TraceStatus.PENDING
    attempt: int = Field(default=1, ge=1)
    source_event_ids: tuple[UUID, ...] = ()
    reason_codes: tuple[str, ...] = ()
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_completed_span(self) -> Self:
        if self.status is TraceStatus.COMPLETED and self.started_at is None:
            raise ValueError("completed span requires started_at")
        return self


class TraceRecord(ObservabilityModel):
    trace_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    session_id: UUID | None = None
    correlation_id: UUID
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration: float | None = Field(default=None, ge=0)
    status: TraceStatus
    spans: tuple[TraceSpan, ...] = ()
    root_component: str | None = None
    event_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthSnapshot(ObservabilityModel):
    health_id: UUID = Field(default_factory=uuid4)
    component: str = Field(min_length=1)
    version: str = "1"
    status: HealthStatus
    checked_at: datetime = Field(default_factory=utc_now)
    latency_seconds: float | None = Field(default=None, ge=0)
    load: float | None = Field(default=None, ge=0)
    availability: bool | None = None
    dependencies: dict[str, str] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class AlertSignal(ObservabilityModel):
    alert_id: UUID = Field(default_factory=uuid4)
    rule_id: str = Field(min_length=1)
    organization_id: UUID
    session_id: UUID | None = None
    correlation_id: UUID | None = None
    severity: AlertSeverity
    component: str = Field(min_length=1)
    source_event_id: UUID
    status: AlertStatus = AlertStatus.OPEN
    detected_at: datetime = Field(default_factory=utc_now)
    threshold: float | str | None = None
    observed_value: float | str | None = None
    reason_codes: tuple[str, ...] = ()
    safe_message: str = Field(min_length=1, max_length=500)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class SessionTrace(ObservabilityModel):
    """Read-only reconstructed session view from events."""

    organization_id: UUID
    session_id: UUID
    correlation_id: UUID | None = None
    events: tuple[StoredEvent, ...]
    components: tuple[str, ...]
    stages: tuple[str, ...]
    timeline: tuple[dict[str, Any], ...]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration: float | None = None
    final_status: str = "incomplete"
    failures: tuple[dict[str, Any], ...] = ()
    approvals: tuple[dict[str, Any], ...] = ()
    executions: tuple[dict[str, Any], ...] = ()
    observations: tuple[dict[str, Any], ...] = ()
    learning: tuple[dict[str, Any], ...] = ()
    missing_transitions: tuple[str, ...] = ()
    integrity_warnings: tuple[str, ...] = ()

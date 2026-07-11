"""Pydantic models for the ECOS Event Bus architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EventPayloadValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class EventType(StrEnum):
    """Supported event categories emitted by ECOS modules."""

    PLANNING_STARTED = "PLANNING_STARTED"
    OBJECTIVE_CLASSIFIED = "OBJECTIVE_CLASSIFIED"
    COMPLEXITY_CALCULATED = "COMPLEXITY_CALCULATED"
    PIPELINE_GENERATED = "PIPELINE_GENERATED"
    SPECIALISTS_SELECTED = "SPECIALISTS_SELECTED"
    PLANNING_COMPLETED = "PLANNING_COMPLETED"
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_UPDATED = "SESSION_UPDATED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    CONTEXT_REQUESTED = "CONTEXT_REQUESTED"
    CONTEXT_CREATED = "CONTEXT_CREATED"
    CONTEXT_MISSING = "CONTEXT_MISSING"
    REASONING_STARTED = "REASONING_STARTED"
    REASONING_COMPLETED = "REASONING_COMPLETED"
    SPECIALIST_CONTRIBUTED = "SPECIALIST_CONTRIBUTED"
    DEBATE_STARTED = "DEBATE_STARTED"
    DEBATE_COMPLETED = "DEBATE_COMPLETED"
    SIMULATION_STARTED = "SIMULATION_STARTED"
    SIMULATION_COMPLETED = "SIMULATION_COMPLETED"
    RECOMMENDATION_STARTED = "RECOMMENDATION_STARTED"
    RECOMMENDATION_CREATED = "RECOMMENDATION_CREATED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    EXECUTION_PLANNED = "EXECUTION_PLANNED"
    EXECUTION_VALIDATION_STARTED = "EXECUTION_VALIDATION_STARTED"
    EXECUTION_AUTHORIZATION_VALIDATED = "EXECUTION_AUTHORIZATION_VALIDATED"
    EXECUTION_AUTHORIZATION_REJECTED = "EXECUTION_AUTHORIZATION_REJECTED"
    EXECUTION_WAITING = "EXECUTION_WAITING"
    EXECUTION_PAUSED = "EXECUTION_PAUSED"
    EXECUTION_RESUMED = "EXECUTION_RESUMED"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    STEP_READY = "STEP_READY"
    STEP_STARTED = "STEP_STARTED"
    STEP_RETRYING = "STEP_RETRYING"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_SKIPPED = "STEP_SKIPPED"
    STEP_FAILED = "STEP_FAILED"
    STEP_TIMED_OUT = "STEP_TIMED_OUT"
    CONNECTOR_SELECTED = "CONNECTOR_SELECTED"
    CONNECTOR_INVOKED = "CONNECTOR_INVOKED"
    CONNECTOR_FAILED = "CONNECTOR_FAILED"
    CONNECTOR_FALLBACK_SELECTED = "CONNECTOR_FALLBACK_SELECTED"
    HUMAN_TASK_CREATED = "HUMAN_TASK_CREATED"
    HUMAN_TASK_COMPLETED = "HUMAN_TASK_COMPLETED"
    HUMAN_TASK_REJECTED = "HUMAN_TASK_REJECTED"
    ROLLBACK_STARTED = "ROLLBACK_STARTED"
    ROLLBACK_STEP_COMPLETED = "ROLLBACK_STEP_COMPLETED"
    ROLLBACK_STEP_FAILED = "ROLLBACK_STEP_FAILED"
    EXECUTION_ROLLED_BACK = "EXECUTION_ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    ARTIFACT_GENERATED = "ARTIFACT_GENERATED"
    IDEMPOTENCY_HIT = "IDEMPOTENCY_HIT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    LEARNING_STARTED = "LEARNING_STARTED"
    LEARNING_VALIDATED = "LEARNING_VALIDATED"
    LEARNING_COMPLETED = "LEARNING_COMPLETED"
    PIPELINE_VALIDATION_STARTED = "PIPELINE_VALIDATION_STARTED"
    PIPELINE_STARTED = "PIPELINE_STARTED"
    STAGE_READY = "STAGE_READY"
    ENGINE_INVOKED = "ENGINE_INVOKED"
    ENGINE_RETRYING = "ENGINE_RETRYING"
    ENGINE_TIMED_OUT = "ENGINE_TIMED_OUT"
    ENGINE_COMPLETED = "ENGINE_COMPLETED"
    ENGINE_FAILED = "ENGINE_FAILED"
    STAGE_SKIPPED = "STAGE_SKIPPED"
    PIPELINE_WAITING_APPROVAL = "PIPELINE_WAITING_APPROVAL"
    PIPELINE_BLOCKED = "PIPELINE_BLOCKED"
    PIPELINE_RESUMED = "PIPELINE_RESUMED"
    PIPELINE_COMPLETED = "PIPELINE_COMPLETED"
    PIPELINE_FAILED = "PIPELINE_FAILED"
    PIPELINE_CANCELLED = "PIPELINE_CANCELLED"
    REPLANNING_REQUESTED = "REPLANNING_REQUESTED"
    GOVERNANCE_STARTED = "GOVERNANCE_STARTED"
    IDENTITY_VALIDATED = "IDENTITY_VALIDATED"
    IDENTITY_REJECTED = "IDENTITY_REJECTED"
    POLICY_EVALUATION_STARTED = "POLICY_EVALUATION_STARTED"
    POLICY_VALIDATED = "POLICY_VALIDATED"
    POLICY_VIOLATION_DETECTED = "POLICY_VIOLATION_DETECTED"
    COMPLIANCE_PASSED = "COMPLIANCE_PASSED"
    COMPLIANCE_FAILED = "COMPLIANCE_FAILED"
    EXPLAINABILITY_VALIDATED = "EXPLAINABILITY_VALIDATED"
    EXPLAINABILITY_FAILED = "EXPLAINABILITY_FAILED"
    AUTHORIZATION_GRANTED = "AUTHORIZATION_GRANTED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_PARTIALLY_GRANTED = "APPROVAL_PARTIALLY_GRANTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    AUDIT_RECORDED = "AUDIT_RECORDED"
    GOVERNANCE_COMPLETED = "GOVERNANCE_COMPLETED"
    GOVERNANCE_FAILED = "GOVERNANCE_FAILED"


class EventPriority(StrEnum):
    """Supported event priority levels."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventModel(BaseModel):
    """Base event model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique event model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for event model creation.",
    )

    @model_validator(mode="after")
    def validate_created_at(self) -> Self:
        """Ensure created_at is timezone-aware UTC."""
        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() != UTC.utcoffset(self.created_at)
        ):
            msg = "created_at must be timezone-aware and in UTC"
            raise ValueError(msg)
        return self


class EventMetadata(BaseModel):
    """Metadata associated with an event."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    correlation_id: UUID | None = Field(
        default=None,
        description="Optional correlation identifier.",
    )
    causation_id: UUID | None = Field(
        default=None,
        description="Optional causation event identifier.",
    )
    attributes: dict[str, EventPayloadValue] = Field(
        default_factory=dict,
        description="Structured event metadata attributes.",
    )

    @field_validator("attributes")
    @classmethod
    def validate_attributes(
        cls,
        value: dict[str, EventPayloadValue],
    ) -> dict[str, EventPayloadValue]:
        """Reject blank metadata attribute keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata attribute keys cannot be blank"
            raise ValueError(msg)
        return value


class Event(EventModel):
    """Event emitted by an ECOS module."""

    event_type: EventType = Field(description="Event category.")
    source: str = Field(
        min_length=1,
        max_length=200,
        description="Module or component that emitted the event.",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Optional cognitive session identifier.",
    )
    payload: dict[str, EventPayloadValue] = Field(
        default_factory=dict,
        description="Structured event payload.",
    )
    metadata: EventMetadata = Field(
        default_factory=EventMetadata,
        description="Event metadata.",
    )
    priority: EventPriority = Field(
        default=EventPriority.NORMAL,
        description="Event priority.",
    )

    @field_validator("payload")
    @classmethod
    def validate_payload(
        cls,
        value: dict[str, EventPayloadValue],
    ) -> dict[str, EventPayloadValue]:
        """Reject blank payload keys."""
        if any(key.strip() == "" for key in value):
            msg = "payload keys cannot be blank"
            raise ValueError(msg)
        return value


class EventEnvelope(EventModel):
    """Envelope used to move an event through the Event Bus boundary."""

    event: Event = Field(description="Event carried by the envelope.")
    headers: dict[str, EventPayloadValue] = Field(
        default_factory=dict,
        description="Transport-neutral envelope headers.",
    )

    @field_validator("headers")
    @classmethod
    def validate_headers(
        cls,
        value: dict[str, EventPayloadValue],
    ) -> dict[str, EventPayloadValue]:
        """Reject blank header keys."""
        if any(key.strip() == "" for key in value):
            msg = "header keys cannot be blank"
            raise ValueError(msg)
        return value


class EventHandler(EventModel):
    """Declarative handler registered for event delivery."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Handler name.",
    )
    event_types: list[EventType] = Field(
        default_factory=list,
        description="Event types handled by this handler.",
    )
    active: bool = Field(
        default=True,
        description="Whether the handler is active.",
    )

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, value: list[EventType]) -> list[EventType]:
        """Ensure handler event types are unique."""
        if len(value) != len(set(value)):
            msg = "handler event types must be unique"
            raise ValueError(msg)
        return value


class EventSubscription(EventModel):
    """Subscription connecting a handler to event types."""

    handler: EventHandler = Field(description="Subscribed event handler.")
    event_types: list[EventType] = Field(
        description="Event types subscribed by the handler.",
    )
    active: bool = Field(
        default=True,
        description="Whether the subscription is active.",
    )

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, value: list[EventType]) -> list[EventType]:
        """Ensure subscription event types are unique and non-empty."""
        if not value:
            msg = "subscription event types cannot be empty"
            raise ValueError(msg)
        if len(value) != len(set(value)):
            msg = "subscription event types must be unique"
            raise ValueError(msg)
        return value

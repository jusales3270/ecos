"""Pydantic models for the ECOS Event Bus architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
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
    OUTCOME_EVALUATED = "OUTCOME_EVALUATED"
    LEARNING_CANDIDATE_CREATED = "LEARNING_CANDIDATE_CREATED"
    PATTERN_DETECTED = "PATTERN_DETECTED"
    CONFIDENCE_CALIBRATED = "CONFIDENCE_CALIBRATED"
    LEARNING_VALIDATED = "LEARNING_VALIDATED"
    LEARNING_REJECTED = "LEARNING_REJECTED"
    LEARNING_HUMAN_REVIEW_REQUIRED = "LEARNING_HUMAN_REVIEW_REQUIRED"
    MEMORY_UPDATE_PROPOSED = "MEMORY_UPDATE_PROPOSED"
    MEMORY_IMPROVED = "MEMORY_IMPROVED"
    LEARNING_COMPLETED = "LEARNING_COMPLETED"
    LEARNING_FAILED = "LEARNING_FAILED"
    OBSERVATION_STARTED = "OBSERVATION_STARTED"
    MEASUREMENT_COLLECTED = "MEASUREMENT_COLLECTED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    FEEDBACK_RECORDED = "FEEDBACK_RECORDED"
    OUTCOME_COMPARED = "OUTCOME_COMPARED"
    DEVIATION_DETECTED = "DEVIATION_DETECTED"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    OBSERVATION_INCONCLUSIVE = "OBSERVATION_INCONCLUSIVE"
    OBSERVATION_COMPLETED = "OBSERVATION_COMPLETED"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"
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
    PIPELINE_WAITING_HUMAN_REVIEW = "PIPELINE_WAITING_HUMAN_REVIEW"
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
    EVENT_VALIDATED = "EVENT_VALIDATED"
    EVENT_STORED = "EVENT_STORED"
    EVENT_PUBLISHED = "EVENT_PUBLISHED"
    EVENT_DELIVERY_FAILED = "EVENT_DELIVERY_FAILED"
    EVENT_REPLAY_STARTED = "EVENT_REPLAY_STARTED"
    EVENT_REPLAY_COMPLETED = "EVENT_REPLAY_COMPLETED"
    EVENT_REPLAY_FAILED = "EVENT_REPLAY_FAILED"
    AUDIT_RECORD_STORED = "AUDIT_RECORD_STORED"
    AUDIT_INTEGRITY_VALIDATED = "AUDIT_INTEGRITY_VALIDATED"
    AUDIT_INTEGRITY_FAILED = "AUDIT_INTEGRITY_FAILED"
    METRIC_COLLECTED = "METRIC_COLLECTED"
    TRACE_STARTED = "TRACE_STARTED"
    TRACE_COMPLETED = "TRACE_COMPLETED"
    TRACE_INCOMPLETE = "TRACE_INCOMPLETE"
    HEALTH_CHANGED = "HEALTH_CHANGED"
    ALERT_GENERATED = "ALERT_GENERATED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    OBSERVABILITY_DEGRADED = "OBSERVABILITY_DEGRADED"
    OBSERVABILITY_RECOVERED = "OBSERVABILITY_RECOVERED"
    KNOWLEDGE_ENTITY_CREATED = "KNOWLEDGE_ENTITY_CREATED"
    KNOWLEDGE_ENTITY_VERSIONED = "KNOWLEDGE_ENTITY_VERSIONED"
    KNOWLEDGE_ENTITY_ARCHIVED = "KNOWLEDGE_ENTITY_ARCHIVED"
    KNOWLEDGE_ENTITY_MERGED = "KNOWLEDGE_ENTITY_MERGED"
    KNOWLEDGE_RELATIONSHIP_CREATED = "KNOWLEDGE_RELATIONSHIP_CREATED"
    KNOWLEDGE_RELATIONSHIP_VERSIONED = "KNOWLEDGE_RELATIONSHIP_VERSIONED"
    KNOWLEDGE_RELATIONSHIP_ARCHIVED = "KNOWLEDGE_RELATIONSHIP_ARCHIVED"
    KNOWLEDGE_LINKED = "KNOWLEDGE_LINKED"
    SEMANTIC_SEARCH_COMPLETED = "SEMANTIC_SEARCH_COMPLETED"
    CONTEXT_EXPANSION_STARTED = "CONTEXT_EXPANSION_STARTED"
    CONTEXT_EXPANDED = "CONTEXT_EXPANDED"
    GRAPH_INTEGRITY_VALIDATED = "GRAPH_INTEGRITY_VALIDATED"
    GRAPH_INTEGRITY_FAILED = "GRAPH_INTEGRITY_FAILED"
    KNOWLEDGE_PROJECTION_COMPLETED = "KNOWLEDGE_PROJECTION_COMPLETED"
    KNOWLEDGE_PROJECTION_FAILED = "KNOWLEDGE_PROJECTION_FAILED"
    AUTHENTICATION_SUCCEEDED = "AUTHENTICATION_SUCCEEDED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    ACCESS_DENIED = "ACCESS_DENIED"
    CROSS_TENANT_ACCESS_ATTEMPTED = "CROSS_TENANT_ACCESS_ATTEMPTED"
    AUTH_SESSION_CREATED = "AUTH_SESSION_CREATED"
    AUTH_SESSION_REVOKED = "AUTH_SESSION_REVOKED"
    SECURITY_ROLE_CHANGED = "SECURITY_ROLE_CHANGED"
    PRIVILEGED_EXECUTION_REQUESTED = "PRIVILEGED_EXECUTION_REQUESTED"


class EventPriority(StrEnum):
    """Supported event priority levels."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventCategory(StrEnum):
    """Canonical event categories used for storage and projection."""

    DOMAIN = "domain"
    INFRASTRUCTURE = "infrastructure"
    PLATFORM = "platform"
    COGNITIVE = "cognitive"
    ORGANIZATIONAL = "organizational"
    SECURITY = "security"


class EventClassification(StrEnum):
    """Safe event information classifications."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class EventSecurityLevel(StrEnum):
    """Event security levels prepared for future access-control work."""

    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"
    CRITICAL = "critical"


class EventModel(BaseModel):
    """Base event model with identity and UTC creation timestamp."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

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

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    correlation_id: UUID | None = Field(
        default=None,
        description="Optional correlation identifier.",
    )
    causation_id: UUID | None = Field(
        default=None,
        description="Optional causation event identifier.",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured event metadata attributes.",
    )

    @field_validator("attributes")
    @classmethod
    def validate_attributes(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        """Reject blank metadata attribute keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata attribute keys cannot be blank"
            raise ValueError(msg)
        return value


class Event(EventModel):
    """Event emitted by an ECOS module."""

    event_type: EventType = Field(description="Event category.")
    category: EventCategory = Field(
        default=EventCategory.DOMAIN,
        description="Canonical event category.",
    )
    source: str = Field(
        min_length=1,
        max_length=200,
        description="Module or component that emitted the event.",
    )
    source_version: str = Field(
        default="1",
        min_length=1,
        max_length=50,
        description="Version of the source component contract.",
    )
    organization_id: UUID | None = Field(
        default=None,
        description="Organization scope for organizational events.",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Optional cognitive session identifier.",
    )
    payload: dict[str, Any] = Field(
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
    event_version: int = Field(default=1, gt=0)
    schema_version: int = Field(default=1, gt=0)
    classification: EventClassification = EventClassification.INTERNAL
    security_level: EventSecurityLevel = EventSecurityLevel.STANDARD
    environment: str | None = Field(default=None, max_length=100)
    actor_reference: str | None = Field(default=None, max_length=200)
    trace_reference: str | None = Field(default=None, max_length=200)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("payload")
    @classmethod
    def validate_payload(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        """Reject blank payload keys."""
        if any(key.strip() == "" for key in value):
            msg = "payload keys cannot be blank"
            raise ValueError(msg)
        return value

    @field_validator("reason_codes", mode="before")
    @classmethod
    def tuple_reason_codes(cls, value: object) -> tuple[str, ...]:
        """Normalize reason codes to an immutable tuple."""
        return tuple(value or ())

    @model_validator(mode="after")
    def infer_organization_id(self) -> Self:
        """Infer organization scope from safe legacy payload/metadata fields."""
        if self.organization_id is not None:
            return self
        candidate = self.payload.get("organization_id") or self.metadata.attributes.get(
            "organization_id"
        )
        if candidate is None:
            return self
        object.__setattr__(self, "organization_id", UUID(str(candidate)))
        return self

    @property
    def event_id(self) -> UUID:
        """Canonical event identifier alias."""
        return self.id

    @property
    def occurred_at(self) -> datetime:
        """Canonical occurrence timestamp alias."""
        return self.created_at

    @property
    def source_component(self) -> str:
        """Canonical source component alias."""
        return self.source

    @property
    def correlation_id(self) -> UUID | None:
        """Canonical correlation identifier alias."""
        return self.metadata.correlation_id

    @property
    def causation_id(self) -> UUID | None:
        """Canonical causation identifier alias."""
        return self.metadata.causation_id


class EventEnvelope(EventModel):
    """Envelope used to move an event through the Event Bus boundary."""

    event: Event = Field(description="Event carried by the envelope.")
    headers: dict[str, Any] = Field(
        default_factory=dict,
        description="Transport-neutral envelope headers.",
    )

    @field_validator("headers")
    @classmethod
    def validate_headers(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
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

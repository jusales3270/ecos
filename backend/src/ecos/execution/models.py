"""Typed immutable models for the ECOS Execution Layer."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExecutionMetadataValue = str | int | float | bool | None
SafePayload = dict[str, Any]


class ExecutionModel(BaseModel):
    """Base immutable execution model."""

    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )


class ExecutionType(StrEnum):
    """Supported operational execution types."""

    HUMAN = "human"
    SYSTEM = "system"
    API = "api"
    AGENT = "agent"
    BROWSER = "browser"
    MCP = "mcp"


class ExecutionMode(StrEnum):
    """Execution effect mode."""

    DRY_RUN = "dry_run"
    LIVE = "live"


class ExecutionStatus(StrEnum):
    """Execution lifecycle states."""

    PLANNED = "planned"
    VALIDATING = "validating"
    WAITING = "waiting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class ExecutionStepStatus(StrEnum):
    """Execution step lifecycle states."""

    PENDING = "pending"
    READY = "ready"
    WAITING = "waiting"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    PAUSED = "paused"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class FailureClassification(StrEnum):
    """Typed execution failure classes."""

    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    APPROVAL = "approval"
    POLICY = "policy"
    RESOURCE = "resource"
    UNAVAILABLE = "unavailable"
    TARGET = "target"
    TIMEOUT = "timeout"
    RECOVERABLE = "recoverable"
    IDEMPOTENCY = "idempotency"
    CONNECTOR = "connector"
    OUTPUT_VALIDATION = "output_validation"
    CANCELLED = "cancelled"
    ROLLBACK = "rollback"
    NON_RECOVERABLE = "non_recoverable"
    INTERNAL = "internal"


class ConnectorHealth(StrEnum):
    """Connector health states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class TimelineEntryType(StrEnum):
    """Execution timeline entry kinds."""

    EXECUTION = "execution"
    STEP = "step"
    ATTEMPT = "attempt"
    CONNECTOR = "connector"
    HUMAN_TASK = "human_task"
    ROLLBACK = "rollback"
    ARTIFACT = "artifact"
    FAILURE = "failure"


class HumanTaskStatus(StrEnum):
    """Human task lifecycle states."""

    WAITING = "waiting"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class IdempotencyRecordStatus(StrEnum):
    """In-memory idempotency record states."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RetryPolicy(ExecutionModel):
    """Retry policy for connector invocation."""

    max_attempts: int = Field(default=1, ge=1)
    backoff_seconds: float = Field(default=0.0, ge=0.0)


class StructuredCondition(ExecutionModel):
    """Non-executable structured precondition or validation rule."""

    operator: str = Field(min_length=1)
    field: str | None = None
    value: Any = None
    conditions: tuple[StructuredCondition, ...] = Field(default_factory=tuple)

    @field_validator("conditions", mode="before")
    @classmethod
    def tuple_conditions(cls, value: object) -> tuple[StructuredCondition, ...]:
        return tuple(value or ())


class ExecutionWindow(ExecutionModel):
    """Allowed execution window."""

    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        for name in ("starts_at", "ends_at"):
            value = getattr(self, name)
            if value.tzinfo is None:
                msg = f"{name} must be timezone-aware"
                raise ValueError(msg)
        if self.ends_at <= self.starts_at:
            msg = "execution window end must be after start"
            raise ValueError(msg)
        return self


class ExecutionConstraint(ExecutionModel):
    """Safe execution constraint."""

    name: str = Field(min_length=1)
    value: ExecutionMetadataValue


class ResourceRequirement(ExecutionModel):
    """Declared resource requirement."""

    resource_type: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    required: bool = True
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ConnectorCapability(ExecutionModel):
    """Connector capability descriptor."""

    name: str = Field(min_length=1)
    description: str = Field(default="")


class ConnectorDescriptor(ExecutionModel):
    """Safe public connector descriptor."""

    connector_id: str = Field(min_length=1)
    connector_type: str = Field(min_length=1)
    supported_execution_types: tuple[ExecutionType, ...]
    capabilities: tuple[ConnectorCapability, ...]
    available: bool = True
    health: ConnectorHealth = ConnectorHealth.HEALTHY
    supports_dry_run: bool = True
    supports_live: bool = False
    supports_idempotency: bool = True
    supports_rollback: bool = False
    priority: int = Field(default=100, ge=0)
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)

    @field_validator("supported_execution_types", "capabilities", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[object, ...]:
        return tuple(value or ())

    @model_validator(mode="after")
    def validate_descriptor(self) -> Self:
        if not self.supported_execution_types:
            msg = "connector must support at least one execution type"
            raise ValueError(msg)
        if not self.capabilities:
            msg = "connector must declare at least one capability"
            raise ValueError(msg)
        capability_names = [item.name for item in self.capabilities]
        if len(capability_names) != len(set(capability_names)):
            msg = "connector capabilities must be unique"
            raise ValueError(msg)
        return self


class RollbackAction(ExecutionModel):
    """Explicit rollback action for a completed step."""

    rollback_action_id: UUID
    original_step_id: UUID
    connector_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    parameters: SafePayload = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    idempotency_key: str = Field(min_length=8)
    expected_result: str | None = None
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class ExecutionStep(ExecutionModel):
    """Single operational step inside an approved ExecutionPlan."""

    step_id: UUID
    order: int = Field(ge=1)
    name: str = Field(min_length=1)
    execution_type: ExecutionType
    connector_id: str | None = None
    required_capability: str | None = None
    action: str = Field(min_length=1)
    parameters: SafePayload = Field(default_factory=dict)
    dependencies: tuple[UUID, ...] = Field(default_factory=tuple)
    required: bool = True
    timeout_seconds: float | None = Field(default=None, gt=0.0)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    fallback_connector_ids: tuple[str, ...] = Field(default_factory=tuple)
    resource_requirements: tuple[ResourceRequirement, ...] = Field(
        default_factory=tuple
    )
    preconditions: tuple[StructuredCondition, ...] = Field(default_factory=tuple)
    expected_output: str | None = None
    validation_rules: tuple[StructuredCondition, ...] = Field(default_factory=tuple)
    rollback_action: RollbackAction | None = None
    idempotency_scope: str = Field(min_length=1)
    status: ExecutionStepStatus = ExecutionStepStatus.PENDING
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)

    @field_validator(
        "dependencies",
        "fallback_connector_ids",
        "resource_requirements",
        "preconditions",
        "validation_rules",
        "reason_codes",
        mode="before",
    )
    @classmethod
    def tuple_fields(cls, value: object) -> tuple[object, ...]:
        return tuple(value or ())

    @model_validator(mode="after")
    def validate_step(self) -> Self:
        if self.step_id in self.dependencies:
            msg = "step cannot depend on itself"
            raise ValueError(msg)
        if not self.connector_id and not self.required_capability:
            msg = "connector_id or required_capability is required"
            raise ValueError(msg)
        _validate_safe_mapping(self.parameters, "parameters")
        _validate_safe_mapping(self.safe_metadata, "safe_metadata")
        return self


class ExecutionAuthorization(ExecutionModel):
    """Execution-scoped authorization derived from Governance."""

    authorization_id: UUID
    governance_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    execution_plan_id: UUID | None = None
    action_scope: str = Field(min_length=1)
    approved_action: str = Field(min_length=1)
    allowed_execution_types: tuple[ExecutionType, ...]
    allowed_connector_ids: tuple[str, ...] = Field(default_factory=tuple)
    allowed_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    constraints: tuple[ExecutionConstraint, ...] = Field(default_factory=tuple)
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    approval_evidence: tuple[str, ...] = Field(default_factory=tuple)
    valid_from: datetime
    valid_until: datetime
    revoked: bool = False
    denied: bool = False
    execution_authorized: bool = False
    live_authorized: bool = False
    rollback_authorized: bool = False
    issued_at: datetime
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)

    @field_validator(
        "allowed_execution_types",
        "allowed_connector_ids",
        "allowed_capabilities",
        "constraints",
        "policy_references",
        "approval_evidence",
        mode="before",
    )
    @classmethod
    def tuple_values(cls, value: object) -> tuple[object, ...]:
        return tuple(value or ())


class ExecutionPlan(ExecutionModel):
    """Explicit approved operational plan."""

    execution_plan_id: UUID
    organization_id: UUID
    session_id: UUID
    cognitive_plan_id: UUID
    authorization_id: UUID
    action_scope: str = Field(min_length=1)
    execution_type: ExecutionType
    steps: tuple[ExecutionStep, ...]
    constraints: tuple[ExecutionConstraint, ...] = Field(default_factory=tuple)
    resources: tuple[ResourceRequirement, ...] = Field(default_factory=tuple)
    execution_window: ExecutionWindow | None = None
    rollback_policy: str = "explicit"
    maximum_duration_seconds: float = Field(default=60.0, gt=0.0)
    maximum_cost_units: float | None = Field(default=None, ge=0.0)
    version: str = Field(default="17b.1", min_length=1)
    created_at: datetime
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)

    @field_validator("steps", "constraints", "resources", "reason_codes", mode="before")
    @classmethod
    def tuple_fields(cls, value: object) -> tuple[object, ...]:
        return tuple(value or ())

    @model_validator(mode="after")
    def validate_steps(self) -> Self:
        if not self.steps:
            msg = "execution plan cannot be empty"
            raise ValueError(msg)
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            msg = "duplicate execution step id"
            raise ValueError(msg)
        orders = [step.order for step in self.steps]
        if len(orders) != len(set(orders)):
            msg = "duplicate execution step order"
            raise ValueError(msg)
        step_order = {step.step_id: step.order for step in self.steps}
        for step in self.steps:
            for dependency in step.dependencies:
                if dependency not in step_order:
                    msg = "step depends on unknown step"
                    raise ValueError(msg)
                if step_order[dependency] >= step.order:
                    msg = "step depends on a future step"
                    raise ValueError(msg)
        return self


class ConnectorInvocation(ExecutionModel):
    """Safe connector invocation payload."""

    invocation_id: UUID
    execution_id: UUID
    execution_request_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    execution_plan_id: UUID
    step_id: UUID
    connector_id: str
    execution_type: ExecutionType
    action: str
    parameters: SafePayload = Field(default_factory=dict)
    mode: ExecutionMode = ExecutionMode.DRY_RUN
    idempotency_key: str = Field(min_length=8)
    attempt: int = Field(ge=1)
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ExecutionArtifact(ExecutionModel):
    """Reference to an artifact produced by a connector."""

    artifact_id: UUID
    execution_id: UUID
    step_id: UUID
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    content_reference: str = Field(min_length=1)
    checksum: str | None = None
    size: int | None = Field(default=None, ge=0)
    media_type: str | None = None
    created_at: datetime
    sensitive: bool = False
    retention_hint: str | None = None
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ConnectorResult(ExecutionModel):
    """Structured result returned by a connector."""

    connector_id: str
    step_id: UUID
    status: ExecutionStepStatus
    output: SafePayload = Field(default_factory=dict)
    artifacts: tuple[ExecutionArtifact, ...] = Field(default_factory=tuple)
    metrics: dict[str, float] = Field(default_factory=dict)
    recoverable: bool = False
    safe_message: str | None = None
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)

    @field_validator("artifacts", mode="before")
    @classmethod
    def tuple_artifacts(cls, value: object) -> tuple[ExecutionArtifact, ...]:
        return tuple(value or ())


class ExecutionMetric(ExecutionModel):
    """Structured execution metric."""

    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ExecutionLogEntry(ExecutionModel):
    """Safe structured execution log."""

    sequence: int = Field(ge=1)
    occurred_at: datetime
    level: str = Field(min_length=1)
    message: str = Field(min_length=1)
    step_id: UUID | None = None
    connector_id: str | None = None
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ExecutionTimelineEntry(ExecutionModel):
    """Append-only execution timeline entry."""

    sequence: int = Field(ge=1)
    entry_type: TimelineEntryType
    status: str = Field(min_length=1)
    occurred_at: datetime
    step_id: UUID | None = None
    connector_id: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    reason_code: str | None = None
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ExecutionFailure(ExecutionModel):
    """Safe execution failure report."""

    failure_id: UUID
    execution_id: UUID
    execution_plan_id: UUID
    step_id: UUID | None = None
    connector_id: str | None = None
    classification: FailureClassification
    recoverable: bool
    attempt: int = Field(default=1, ge=1)
    occurred_at: datetime
    safe_message: str
    cause_type: str
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    affected_dependents: tuple[UUID, ...] = Field(default_factory=tuple)
    rollback_required: bool = False
    rollback_status: ExecutionStatus | None = None
    human_escalation_required: bool = False
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ExecutionStepResult(ExecutionModel):
    """Final result for one execution step."""

    step_id: UUID
    connector_id: str | None
    status: ExecutionStepStatus
    started_at: datetime
    completed_at: datetime
    duration: float = Field(ge=0.0)
    attempts: int = Field(ge=1)
    output: SafePayload = Field(default_factory=dict)
    artifacts: tuple[ExecutionArtifact, ...] = Field(default_factory=tuple)
    metrics: tuple[ExecutionMetric, ...] = Field(default_factory=tuple)
    failure: ExecutionFailure | None = None
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class RollbackResult(ExecutionModel):
    """Result of one rollback action."""

    rollback_action_id: UUID
    original_step_id: UUID
    connector_id: str
    status: ExecutionStepStatus
    started_at: datetime
    completed_at: datetime
    duration: float = Field(ge=0.0)
    attempts: int = Field(ge=1)
    failure: ExecutionFailure | None = None
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class HumanTask(ExecutionModel):
    """Typed in-memory human task."""

    task_id: UUID
    execution_id: UUID
    step_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    assigned_to: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    status: HumanTaskStatus = HumanTaskStatus.WAITING
    due_at: datetime | None = None
    evidence_required: bool = False
    evidence: str | None = None
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


class ExecutionResumeState(ExecutionModel):
    """Returned state used to resume paused execution without persistence."""

    execution_id: UUID
    execution_plan_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    status: ExecutionStatus
    current_step: UUID | None
    completed_steps: tuple[UUID, ...] = Field(default_factory=tuple)
    skipped_steps: tuple[UUID, ...] = Field(default_factory=tuple)
    paused_steps: tuple[UUID, ...] = Field(default_factory=tuple)
    attempts: dict[UUID, int] = Field(default_factory=dict)
    outputs: dict[UUID, SafePayload] = Field(default_factory=dict)
    artifacts: tuple[ExecutionArtifact, ...] = Field(default_factory=tuple)
    timeline: tuple[ExecutionTimelineEntry, ...] = Field(default_factory=tuple)
    idempotency_references: tuple[str, ...] = Field(default_factory=tuple)
    human_tasks: tuple[HumanTask, ...] = Field(default_factory=tuple)
    authorization_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int = Field(default=1, ge=1)


class ExecutionRequest(ExecutionModel):
    """Input accepted by the ExecutionEngine."""

    execution_request_id: UUID
    execution_id: UUID | None = None
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    requested_by: UUID | None = None
    approved_action: str = Field(min_length=1)
    action_scope: str = Field(min_length=1)
    execution_type: ExecutionType
    execution_plan: ExecutionPlan
    authorization: ExecutionAuthorization
    approval_evidence: tuple[str, ...] = Field(default_factory=tuple)
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    constraints: tuple[ExecutionConstraint, ...] = Field(default_factory=tuple)
    required_resources: tuple[ResourceRequirement, ...] = Field(default_factory=tuple)
    execution_window: ExecutionWindow | None = None
    rollback_required: bool = False
    dry_run: bool = True
    idempotency_key: str = Field(min_length=8)
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)
    resume_state: ExecutionResumeState | None = None

    @field_validator(
        "approval_evidence",
        "policy_references",
        "constraints",
        "required_resources",
        mode="before",
    )
    @classmethod
    def tuple_fields(cls, value: object) -> tuple[object, ...]:
        return tuple(value or ())

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        _validate_safe_mapping(self.safe_metadata, "safe_metadata")
        plan = self.execution_plan
        authorization = self.authorization
        if plan.organization_id != self.organization_id:
            msg = "execution plan organization mismatch"
            raise ValueError(msg)
        if plan.session_id != self.session_id:
            msg = "execution plan session mismatch"
            raise ValueError(msg)
        if plan.cognitive_plan_id != self.plan_id:
            msg = "execution plan cognitive plan mismatch"
            raise ValueError(msg)
        if authorization.organization_id != self.organization_id:
            msg = "authorization organization mismatch"
            raise ValueError(msg)
        if authorization.session_id != self.session_id:
            msg = "authorization session mismatch"
            raise ValueError(msg)
        if authorization.plan_id != self.plan_id:
            msg = "authorization plan mismatch"
            raise ValueError(msg)
        if authorization.action_scope != self.action_scope:
            msg = "authorization action scope mismatch"
            raise ValueError(msg)
        if authorization.approved_action != self.approved_action:
            msg = "authorization approved action mismatch"
            raise ValueError(msg)
        if plan.execution_type != self.execution_type:
            msg = "execution type mismatch"
            raise ValueError(msg)
        return self


class IdempotencyRecord(ExecutionModel):
    """Provider-agnostic idempotency record."""

    key: str
    fingerprint: str
    status: IdempotencyRecordStatus
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    execution_plan_id: UUID
    step_id: UUID | None = None
    result: Any | None = None
    created_at: datetime
    updated_at: datetime


class ExecutionResult(ExecutionModel):
    """Immutable final or paused execution result."""

    execution_id: UUID
    execution_request_id: UUID
    execution_plan_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    status: ExecutionStatus
    mode: ExecutionMode
    started_at: datetime
    completed_at: datetime | None
    duration: float = Field(ge=0.0)
    step_results: tuple[ExecutionStepResult, ...] = Field(default_factory=tuple)
    outputs_by_step: dict[UUID, SafePayload] = Field(default_factory=dict)
    outputs_by_connector: dict[str, SafePayload] = Field(default_factory=dict)
    artifacts: tuple[ExecutionArtifact, ...] = Field(default_factory=tuple)
    metrics: tuple[ExecutionMetric, ...] = Field(default_factory=tuple)
    logs: tuple[ExecutionLogEntry, ...] = Field(default_factory=tuple)
    timeline: tuple[ExecutionTimelineEntry, ...] = Field(default_factory=tuple)
    failures: tuple[ExecutionFailure, ...] = Field(default_factory=tuple)
    rollback_results: tuple[RollbackResult, ...] = Field(default_factory=tuple)
    human_tasks: tuple[HumanTask, ...] = Field(default_factory=tuple)
    resume_state: ExecutionResumeState | None = None
    idempotency_key: str
    authorization_id: UUID
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ExecutionMetadataValue] = Field(default_factory=dict)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def _validate_safe_mapping(value: dict[str, Any], field_name: str) -> None:
    secret_tokens = ("secret", "token", "password", "credential", "private_key")
    for key in value:
        normalized = key.lower()
        if not key.strip():
            msg = f"{field_name} keys cannot be blank"
            raise ValueError(msg)
        if any(token in normalized for token in secret_tokens):
            msg = f"{field_name} cannot contain secret-like keys"
            raise ValueError(msg)

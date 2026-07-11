"""Pydantic models for the ECOS Orchestrator architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.planner import CognitivePlan, PipelineStep
from ecos.session import ManagedSession

OrchestratorMetadataValue = str | int | float | bool | None
EngineOutput = Any


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ExecutionStatus(StrEnum):
    """Supported lifecycle states for orchestration execution."""

    CREATED = "CREATED"
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionMode(StrEnum):
    """Supported execution modes for an orchestration plan."""

    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL = "PARALLEL"
    CONDITIONAL = "CONDITIONAL"
    ITERATIVE = "ITERATIVE"


class PipelineExecutionStatus(StrEnum):
    """Runtime lifecycle states for a cognitive plan execution."""

    PENDING = "pending"
    VALIDATING = "validating"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageExecutionStatus(StrEnum):
    """Runtime lifecycle states for a cognitive plan stage."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class FailureClassification(StrEnum):
    """Typed failure classes emitted by orchestration."""

    VALIDATION = "validation"
    UNAVAILABLE = "unavailable"
    RECOVERABLE = "recoverable"
    TIMEOUT = "timeout"
    GOVERNANCE = "governance"
    APPROVAL = "approval"
    CANCELLED = "cancelled"
    NON_RECOVERABLE = "non_recoverable"
    INTERNAL = "internal"


class TimelineEntryType(StrEnum):
    """Kinds of immutable orchestration timeline entries."""

    PIPELINE = "pipeline"
    STAGE = "stage"
    ATTEMPT = "attempt"
    TRANSITION = "transition"
    BLOCK = "block"
    FAILURE = "failure"
    COMPLETION = "completion"


class ApprovalStatus(StrEnum):
    """Human approval state known to the Orchestrator."""

    UNKNOWN = "unknown"
    MISSING = "missing"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class OrchestrationMode(StrEnum):
    """Execution modes accepted by the real Orchestrator."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"


class OrchestratorModel(BaseModel):
    """Base orchestrator model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique orchestrator model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for orchestrator model creation.",
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


class OrchestrationConfig(BaseModel):
    """Immutable runtime policy injected into the Orchestrator."""

    model_config = ConfigDict(frozen=True)

    mode: OrchestrationMode = OrchestrationMode.SEQUENTIAL
    concurrency_limit: int = Field(default=1, ge=1)
    default_timeout_seconds: float = Field(default=60.0, gt=0.0)


class ApprovalState(BaseModel):
    """Explicit human approval state supplied by the caller."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    status: ApprovalStatus = ApprovalStatus.UNKNOWN
    organization_id: UUID | None = None
    session_id: UUID | None = None
    plan_id: UUID | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, OrchestratorMetadataValue],
    ) -> dict[str, OrchestratorMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return dict(value)


class GovernanceState(BaseModel):
    """Governance outcome supplied by governance contracts or previous execution."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    satisfied: bool = False
    organization_id: UUID | None = None
    session_id: UUID | None = None
    plan_id: UUID | None = None
    blocked: bool = False
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)

    @field_validator("reason_codes", mode="before")
    @classmethod
    def tuple_reason_codes(cls, value: object) -> tuple[str, ...]:
        """Normalize reason codes."""
        return tuple(value or ())


class OrchestrationInput(BaseModel):
    """Immutable typed input for real cognitive plan orchestration."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    cognitive_plan: CognitivePlan
    active_session: ManagedSession
    organization_id: UUID
    session_id: UUID
    correlation_id: UUID
    approval_state: ApprovalState = Field(default_factory=ApprovalState)
    governance_state: GovernanceState | None = None
    resources_available: tuple[str, ...] = Field(default_factory=tuple)
    initial_inputs: dict[str, EngineOutput] = Field(default_factory=dict)
    safe_context: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)
    safe_metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)

    @field_validator("resources_available", mode="before")
    @classmethod
    def tuple_resources(cls, value: object) -> tuple[str, ...]:
        """Normalize resource names."""
        return tuple(item.strip() for item in (value or ()) if str(item).strip())


class EngineInvocationContext(BaseModel):
    """Safe context passed to generic engine executors."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    session: ManagedSession
    plan: CognitivePlan
    stage: PipelineStep
    completed_dependencies: tuple[UUID, ...]
    dependency_outputs: dict[UUID, EngineOutput]
    accumulated_context: dict[str, EngineOutput]
    correlation_id: UUID
    attempt: int
    deadline_remaining_seconds: float
    safe_metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)


class EngineStageResult(BaseModel):
    """Generic output returned by an injected engine executor."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    stage_id: UUID
    engine: str
    status: StageExecutionStatus
    output: EngineOutput = None
    started_at: datetime
    completed_at: datetime
    duration: float = Field(ge=0.0)
    attempt: int = Field(ge=1)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Validate result timestamps and terminal status."""
        if self.status not in {
            StageExecutionStatus.COMPLETED,
            StageExecutionStatus.SKIPPED,
            StageExecutionStatus.FAILED,
            StageExecutionStatus.TIMED_OUT,
            StageExecutionStatus.BLOCKED,
            StageExecutionStatus.CANCELLED,
        }:
            msg = "engine result must use a terminal stage status"
            raise ValueError(msg)
        for field_name in ("started_at", "completed_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                msg = f"{field_name} must be timezone-aware and in UTC"
                raise ValueError(msg)
        if self.completed_at < self.started_at:
            msg = "completed_at must be greater than or equal to started_at"
            raise ValueError(msg)
        return self


class TimelineEntry(BaseModel):
    """Append-only immutable orchestration timeline entry."""

    model_config = ConfigDict(frozen=True)

    sequence: int = Field(ge=1)
    entry_type: TimelineEntryType
    status: str
    occurred_at: datetime
    stage_id: UUID | None = None
    engine: str | None = None
    attempt: int | None = Field(default=None, ge=1)
    reason_code: str | None = None
    safe_metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)


class FailureReport(BaseModel):
    """Safe public failure report for orchestration failures."""

    model_config = ConfigDict(frozen=True)

    failure_id: UUID
    session_id: UUID
    plan_id: UUID
    stage_id: UUID | None = None
    engine: str | None = None
    classification: FailureClassification
    recoverable: bool
    attempt: int = Field(default=1, ge=1)
    occurred_at: datetime
    safe_message: str
    cause_type: str
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    affected_dependents: tuple[UUID, ...] = Field(default_factory=tuple)
    pipeline_status: PipelineExecutionStatus
    human_escalation_required: bool = False
    metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)


class ReplanRequest(BaseModel):
    """Typed signal that replanning is required but not executed here."""

    model_config = ConfigDict(frozen=True)

    plan_id: UUID
    session_id: UUID
    reason_codes: tuple[str, ...]
    created_at: datetime


class ResumableOrchestrationState(BaseModel):
    """Returnable state used to resume after approval without storage."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    execution_id: UUID
    plan_id: UUID
    session_id: UUID
    organization_id: UUID
    correlation_id: UUID
    pipeline_status: PipelineExecutionStatus
    blocked_stage: UUID | None
    completed_stage_ids: tuple[UUID, ...]
    stage_results: tuple[EngineStageResult, ...]
    attempts: dict[UUID, int]
    timeline: tuple[TimelineEntry, ...]
    approval_required: bool
    governance_required: bool
    created_at: datetime
    updated_at: datetime
    version: int = Field(default=1, ge=1)


class OrchestrationResult(BaseModel):
    """Immutable final or paused result of a real orchestration run."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    execution_id: UUID
    plan_id: UUID
    session_id: UUID
    organization_id: UUID
    correlation_id: UUID
    status: PipelineExecutionStatus
    started_at: datetime
    completed_at: datetime | None = None
    duration: float = Field(default=0.0, ge=0.0)
    stage_results: tuple[EngineStageResult, ...] = Field(default_factory=tuple)
    outputs_by_stage: dict[UUID, EngineOutput] = Field(default_factory=dict)
    outputs_by_engine: dict[str, EngineOutput] = Field(default_factory=dict)
    timeline: tuple[TimelineEntry, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    failure_report: FailureReport | None = None
    blocked_stage: UUID | None = None
    approval_required: bool = False
    governance_required: bool = False
    replan_request: ReplanRequest | None = None
    resumable_state: ResumableOrchestrationState | None = None
    safe_metadata: dict[str, OrchestratorMetadataValue] = Field(default_factory=dict)


class ExecutionState(OrchestratorModel):
    """State snapshot for an execution unit."""

    status: ExecutionStatus = Field(description="Current execution status.")
    message: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional state message.",
    )
    metadata: dict[str, OrchestratorMetadataValue] = Field(
        default_factory=dict,
        description="Structured state metadata.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str | None) -> str | None:
        """Reject blank messages when provided."""
        if value == "":
            msg = "message cannot be empty when provided"
            raise ValueError(msg)
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, OrchestratorMetadataValue],
    ) -> dict[str, OrchestratorMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value


class ExecutionStep(OrchestratorModel):
    """Single execution step coordinated by the Orchestrator."""

    order: int = Field(ge=1, description="One-based step order.")
    engine: str = Field(
        min_length=1,
        max_length=100,
        description="Engine assigned to this execution step.",
    )
    depends_on: list[UUID] = Field(
        default_factory=list,
        description="Execution step identifiers this step depends on.",
    )
    state: ExecutionState = Field(description="Current execution step state.")
    retries: int = Field(
        default=0,
        ge=0,
        description="Retry count configured for the step.",
    )
    timeout: int = Field(
        default=0,
        ge=0,
        description="Timeout in seconds; zero means unspecified.",
    )
    optional: bool = Field(
        default=False,
        description="Whether this execution step is optional.",
    )


class ExecutionPlan(OrchestratorModel):
    """Plan used by the Orchestrator to coordinate engine execution."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    execution_mode: ExecutionMode = Field(description="Execution mode for the plan.")
    steps: list[ExecutionStep] = Field(
        default_factory=list,
        description="Execution steps to coordinate.",
    )
    current_step: UUID | None = Field(
        default=None,
        description="Current execution step identifier, when available.",
    )
    status: ExecutionStatus = Field(
        default=ExecutionStatus.CREATED,
        description="Current execution plan status.",
    )

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, value: list[ExecutionStep]) -> list[ExecutionStep]:
        """Ensure execution step order values are unique."""
        orders = [step.order for step in value]
        if len(orders) != len(set(orders)):
            msg = "execution step order values must be unique"
            raise ValueError(msg)
        return value


class EngineExecution(OrchestratorModel):
    """Execution attempt for a single engine."""

    execution_plan_id: UUID = Field(description="Execution plan identifier.")
    execution_step_id: UUID = Field(description="Execution step identifier.")
    engine: str = Field(
        min_length=1,
        max_length=100,
        description="Engine being executed.",
    )
    status: ExecutionStatus = Field(description="Engine execution status.")
    started_at: datetime | None = Field(
        default=None,
        description="Optional timezone-aware UTC start timestamp.",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Optional timezone-aware UTC completion timestamp.",
    )

    @model_validator(mode="after")
    def validate_execution_timestamps(self) -> Self:
        """Ensure optional execution timestamps are UTC and ordered."""
        for field_name in ("started_at", "completed_at"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                msg = f"{field_name} must be timezone-aware and in UTC"
                raise ValueError(msg)
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            msg = "completed_at must be greater than or equal to started_at"
            raise ValueError(msg)
        return self


class ExecutionResult(OrchestratorModel):
    """Result of an orchestration execution plan."""

    execution_plan_id: UUID = Field(description="Execution plan identifier.")
    status: ExecutionStatus = Field(description="Final or current result status.")
    engine_executions: list[EngineExecution] = Field(
        default_factory=list,
        description="Engine executions captured for the plan.",
    )
    summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional execution result summary.",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str | None) -> str | None:
        """Reject blank summaries when provided."""
        if value == "":
            msg = "summary cannot be empty when provided"
            raise ValueError(msg)
        return value


class ExecutionEvent(OrchestratorModel):
    """Event emitted during orchestration execution."""

    execution_plan_id: UUID = Field(description="Execution plan identifier.")
    execution_step_id: UUID | None = Field(
        default=None,
        description="Optional execution step identifier.",
    )
    status: ExecutionStatus = Field(description="Event status.")
    message: str = Field(
        min_length=1,
        max_length=2000,
        description="Event message.",
    )
    metadata: dict[str, OrchestratorMetadataValue] = Field(
        default_factory=dict,
        description="Structured event metadata.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, OrchestratorMetadataValue],
    ) -> dict[str, OrchestratorMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value

"""Pydantic models for the ECOS Orchestrator architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OrchestratorMetadataValue = str | int | float | bool | None


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

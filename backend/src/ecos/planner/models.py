"""Pydantic models for the ECOS Cognitive Planner architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.domain import Objective
from ecos.specialists import SpecialistType

PlannerMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class PlanningStrategy(StrEnum):
    """Supported planning strategies for cognitive execution."""

    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP_ANALYSIS = "DEEP_ANALYSIS"
    EXECUTIVE = "EXECUTIVE"
    CRISIS = "CRISIS"


class ComplexityLevel(StrEnum):
    """Supported objective complexity levels."""

    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"
    LEVEL_5 = "LEVEL_5"


class PlannerModel(BaseModel):
    """Base planner model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique planner model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for planner model creation.",
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


class ExecutionStrategy(PlannerModel):
    """Execution strategy selected for a cognitive plan."""

    strategy: PlanningStrategy = Field(description="Selected planning strategy.")
    rationale: str = Field(
        min_length=1,
        max_length=3000,
        description="Rationale for the selected strategy.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Execution constraints for the strategy.",
    )

    @field_validator("constraints")
    @classmethod
    def validate_constraints(cls, value: list[str]) -> list[str]:
        """Normalize constraints and reject blank values."""
        normalized = [constraint.strip() for constraint in value]
        if any(constraint == "" for constraint in normalized):
            msg = "constraints cannot contain blank values"
            raise ValueError(msg)
        return normalized


class EngineSelection(PlannerModel):
    """Engine selected for a cognitive plan."""

    engine: str = Field(
        min_length=1,
        max_length=100,
        description="Selected engine name.",
    )
    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Reason for selecting the engine.",
    )
    required: bool = Field(
        default=True,
        description="Whether the selected engine is required.",
    )


class SpecialistSelection(PlannerModel):
    """Specialist selected for a cognitive plan."""

    specialist_type: SpecialistType = Field(description="Selected specialist type.")
    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Reason for selecting the specialist.",
    )
    required: bool = Field(
        default=True,
        description="Whether the selected specialist is required.",
    )


class PipelineStep(PlannerModel):
    """Single execution step in a cognitive pipeline."""

    order: int = Field(
        ge=1,
        description="One-based step order in the pipeline.",
    )
    engine: str = Field(
        min_length=1,
        max_length=100,
        description="Engine to execute for this step.",
    )
    depends_on: list[UUID] = Field(
        default_factory=list,
        description="Pipeline step identifiers this step depends on.",
    )
    optional: bool = Field(
        default=False,
        description="Whether this pipeline step is optional.",
    )


class Pipeline(PlannerModel):
    """Ordered cognitive execution pipeline."""

    steps: list[PipelineStep] = Field(
        default_factory=list,
        description="Ordered pipeline steps.",
    )
    metadata: dict[str, PlannerMetadataValue] = Field(
        default_factory=dict,
        description="Structured pipeline metadata.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, PlannerMetadataValue],
    ) -> dict[str, PlannerMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, value: list[PipelineStep]) -> list[PipelineStep]:
        """Ensure pipeline step order values are unique."""
        orders = [step.order for step in value]
        if len(orders) != len(set(orders)):
            msg = "pipeline step order values must be unique"
            raise ValueError(msg)
        return value


class CognitivePlan(PlannerModel):
    """Plan for executing an ECOS cognitive session."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    objective: Objective = Field(description="Objective being planned.")
    complexity: ComplexityLevel = Field(description="Estimated objective complexity.")
    strategy: ExecutionStrategy = Field(description="Selected execution strategy.")
    selected_engines: list[EngineSelection] = Field(
        default_factory=list,
        description="Engines selected for execution.",
    )
    selected_specialists: list[SpecialistSelection] = Field(
        default_factory=list,
        description="Specialists selected for execution.",
    )
    pipeline: Pipeline = Field(description="Planned execution pipeline.")
    estimated_duration: int = Field(
        default=0,
        ge=0,
        description="Estimated execution duration in seconds.",
    )
    estimated_cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated execution cost.",
    )
    confidence_target: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Target confidence for the cognitive execution.",
    )

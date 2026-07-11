"""Pydantic models for the ECOS Debate Engine architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.reasoning.models import ReasoningResult
from ecos.specialists import Specialist
from ecos.specialists.models import Contribution

DebateMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class DebateStatus(StrEnum):
    """Lifecycle status values for a debate."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ConsensusLevel(StrEnum):
    """Supported levels of agreement in a debate result."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNANIMOUS = "UNANIMOUS"


class DebateModel(BaseModel):
    """Base debate model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique debate model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for debate model creation.",
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


class Argument(DebateModel):
    """Argument contributed by a specialist during debate."""

    specialist_id: UUID = Field(description="Specialist that produced the argument.")
    position: str = Field(
        min_length=1,
        max_length=200,
        description="Argument position or claim.",
    )
    content: str = Field(
        min_length=1,
        max_length=5000,
        description="Argument content.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Argument confidence from 0.0 to 1.0.",
    )
    metadata: dict[str, DebateMetadataValue] = Field(
        default_factory=dict,
        description="Structured argument metadata.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, DebateMetadataValue],
    ) -> dict[str, DebateMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value


class CounterArgument(DebateModel):
    """Counter-argument responding to a debate argument."""

    argument_id: UUID = Field(description="Argument being challenged.")
    specialist_id: UUID = Field(
        description="Specialist that produced the counter-argument.",
    )
    content: str = Field(
        min_length=1,
        max_length=5000,
        description="Counter-argument content.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Counter-argument confidence from 0.0 to 1.0.",
    )


class Consensus(DebateModel):
    """Consensus artifact produced by a debate."""

    level: ConsensusLevel = Field(description="Consensus level reached.")
    summary: str = Field(
        min_length=1,
        max_length=5000,
        description="Consensus summary.",
    )
    agreements: list[str] = Field(
        default_factory=list,
        description="Points of agreement.",
    )
    disagreements: list[str] = Field(
        default_factory=list,
        description="Points of disagreement.",
    )

    @field_validator("agreements", "disagreements")
    @classmethod
    def validate_points(cls, value: list[str]) -> list[str]:
        """Normalize consensus points and reject blank values."""
        normalized = [point.strip() for point in value]
        if any(point == "" for point in normalized):
            msg = "consensus points cannot contain blank values"
            raise ValueError(msg)
        return normalized


class Debate(DebateModel):
    """Debate coordinated across multiple cognitive specialists."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    specialists: list[Specialist] = Field(
        default_factory=list,
        description="Specialists participating in the debate.",
    )
    arguments: list[Argument] = Field(
        default_factory=list,
        description="Arguments collected during the debate.",
    )
    status: DebateStatus = Field(
        default=DebateStatus.CREATED,
        description="Current debate status.",
    )
    objective: str | None = Field(default=None, min_length=1)
    unified_context: dict[str, object] = Field(default_factory=dict)
    organizational_constraints: list[str] = Field(default_factory=list)
    relevant_policies: list[str] = Field(default_factory=list)
    reasoning_result: ReasoningResult | None = None
    contributions: list[Contribution] = Field(default_factory=list)
    correlation_id: UUID | None = None


class DebateResult(DebateModel):
    """Final architectural result of a debate."""

    debate_id: UUID = Field(description="Debate identifier.")
    consensus: Consensus = Field(description="Consensus artifact for the debate.")
    recommendations: list[str] = Field(
        default_factory=list,
        description="Recommendations produced by the debate.",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        description="Questions not resolved by the debate.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Debate result confidence from 0.0 to 1.0.",
    )
    metadata: dict[str, DebateMetadataValue] = Field(default_factory=dict)
    report: dict[str, object] = Field(default_factory=dict)

    @field_validator("recommendations", "unresolved_questions")
    @classmethod
    def validate_text_items(cls, value: list[str]) -> list[str]:
        """Normalize text lists and reject blank values."""
        normalized = [item.strip() for item in value]
        if any(item == "" for item in normalized):
            msg = "text lists cannot contain blank values"
            raise ValueError(msg)
        return normalized

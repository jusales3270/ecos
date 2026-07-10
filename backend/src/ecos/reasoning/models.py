"""Pydantic models for the ECOS Reasoning Engine architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.context import ContextObject

ReasoningMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ReasoningType(StrEnum):
    """Supported reasoning modes for the Reasoning Engine."""

    ANALYTICAL = "ANALYTICAL"
    STRATEGIC = "STRATEGIC"
    CAUSAL = "CAUSAL"
    COMPARATIVE = "COMPARATIVE"
    CONSTRAINT = "CONSTRAINT"
    RISK = "RISK"
    OPPORTUNITY = "OPPORTUNITY"


class ReasoningModel(BaseModel):
    """Base reasoning model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique reasoning model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for reasoning model creation.",
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


class ReasoningEvidence(ReasoningModel):
    """Evidence item considered by a reasoning process."""

    source: str = Field(
        min_length=1,
        max_length=500,
        description="Evidence origin or reference.",
    )
    content: str = Field(
        min_length=1,
        max_length=10000,
        description="Evidence content.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Evidence confidence score from 0.0 to 1.0.",
    )
    metadata: dict[str, ReasoningMetadataValue] = Field(
        default_factory=dict,
        description="Structured evidence metadata.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, ReasoningMetadataValue],
    ) -> dict[str, ReasoningMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value


class Hypothesis(ReasoningModel):
    """Potential explanation or path produced during reasoning."""

    statement: str = Field(
        min_length=1,
        max_length=2000,
        description="Hypothesis statement.",
    )
    rationale: str = Field(
        min_length=1,
        max_length=5000,
        description="Reasoning rationale for the hypothesis.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Hypothesis confidence score from 0.0 to 1.0.",
    )


class Alternative(ReasoningModel):
    """Candidate option evaluated by the reasoning process."""

    title: str = Field(
        min_length=1,
        max_length=200,
        description="Alternative title.",
    )
    description: str = Field(
        min_length=1,
        max_length=5000,
        description="Alternative description.",
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Alternative score from 0.0 to 1.0.",
    )


class Tradeoff(ReasoningModel):
    """Tradeoff identified between benefits, costs, or constraints."""

    dimension: str = Field(
        min_length=1,
        max_length=200,
        description="Tradeoff dimension.",
    )
    benefit: str = Field(
        min_length=1,
        max_length=2000,
        description="Expected benefit.",
    )
    cost: str = Field(
        min_length=1,
        max_length=2000,
        description="Expected cost or constraint.",
    )
    severity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Tradeoff severity from 0.0 to 1.0.",
    )


class ReasoningContext(ReasoningModel):
    """Input context for a reasoning operation."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    context: ContextObject = Field(description="Assembled context for reasoning.")
    reasoning_type: ReasoningType = Field(description="Reasoning mode to apply.")
    constraints: list[str] = Field(
        default_factory=list,
        description="Explicit constraints for the reasoning operation.",
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


class ReasoningResult(ReasoningModel):
    """Result produced by the Reasoning Engine architecture."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    reasoning_type: ReasoningType = Field(description="Reasoning mode used.")
    hypotheses: list[Hypothesis] = Field(
        default_factory=list,
        description="Hypotheses considered during reasoning.",
    )
    alternatives: list[Alternative] = Field(
        default_factory=list,
        description="Alternatives evaluated during reasoning.",
    )
    tradeoffs: list[Tradeoff] = Field(
        default_factory=list,
        description="Tradeoffs identified during reasoning.",
    )
    evidence: list[ReasoningEvidence] = Field(
        default_factory=list,
        description="Evidence considered during reasoning.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall reasoning confidence from 0.0 to 1.0.",
    )
    summary: str = Field(
        min_length=1,
        max_length=5000,
        description="Human-readable reasoning summary.",
    )

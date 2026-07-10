"""Pydantic models for the ECOS Decision Support Engine architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DecisionMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class RecommendationType(StrEnum):
    """Supported executive recommendation categories."""

    STRATEGIC = "STRATEGIC"
    OPERATIONAL = "OPERATIONAL"
    FINANCIAL = "FINANCIAL"
    TECHNOLOGY = "TECHNOLOGY"
    LEGAL = "LEGAL"
    RISK = "RISK"
    PEOPLE = "PEOPLE"
    INNOVATION = "INNOVATION"


class DecisionImpact(StrEnum):
    """Supported impact levels for a decision recommendation."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DecisionModel(BaseModel):
    """Base decision model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique decision model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for decision model creation.",
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


class RiskSummary(DecisionModel):
    """Risk summarized for executive decision support."""

    title: str = Field(
        min_length=1,
        max_length=200,
        description="Risk title.",
    )
    description: str = Field(
        min_length=1,
        max_length=2000,
        description="Risk description.",
    )
    impact: DecisionImpact = Field(description="Expected risk impact.")
    probability: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Risk probability from 0.0 to 1.0.",
    )
    mitigation: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional mitigation summary.",
    )

    @field_validator("mitigation")
    @classmethod
    def validate_mitigation(cls, value: str | None) -> str | None:
        """Reject blank mitigation when provided."""
        if value == "":
            msg = "mitigation cannot be empty when provided"
            raise ValueError(msg)
        return value


class AlternativeAnalysis(DecisionModel):
    """Analysis of an alternative considered for a recommendation."""

    title: str = Field(
        min_length=1,
        max_length=200,
        description="Alternative title.",
    )
    summary: str = Field(
        min_length=1,
        max_length=3000,
        description="Alternative summary.",
    )
    pros: list[str] = Field(
        default_factory=list,
        description="Alternative advantages.",
    )
    cons: list[str] = Field(
        default_factory=list,
        description="Alternative disadvantages.",
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Alternative score from 0.0 to 1.0.",
    )

    @field_validator("pros", "cons")
    @classmethod
    def validate_points(cls, value: list[str]) -> list[str]:
        """Normalize analysis points and reject blank values."""
        normalized = [point.strip() for point in value]
        if any(point == "" for point in normalized):
            msg = "analysis points cannot contain blank values"
            raise ValueError(msg)
        return normalized


class ExecutiveBrief(DecisionModel):
    """Executive-level summary for decision review."""

    title: str = Field(
        min_length=1,
        max_length=200,
        description="Executive brief title.",
    )
    summary: str = Field(
        min_length=1,
        max_length=5000,
        description="Executive brief summary.",
    )
    key_points: list[str] = Field(
        default_factory=list,
        description="Key points for executive review.",
    )
    decision_required: bool = Field(
        default=True,
        description="Whether executive action is required.",
    )

    @field_validator("key_points")
    @classmethod
    def validate_key_points(cls, value: list[str]) -> list[str]:
        """Normalize key points and reject blank values."""
        normalized = [point.strip() for point in value]
        if any(point == "" for point in normalized):
            msg = "key points cannot contain blank values"
            raise ValueError(msg)
        return normalized


class Recommendation(DecisionModel):
    """Executive recommendation consolidated from reasoning and debate outputs."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    recommendation_type: RecommendationType = Field(
        description="Recommendation category.",
    )
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Recommendation title.",
    )
    summary: str = Field(
        min_length=1,
        max_length=5000,
        description="Recommendation summary.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Recommendation confidence from 0.0 to 1.0.",
    )
    risks: list[RiskSummary] = Field(
        default_factory=list,
        description="Risks associated with the recommendation.",
    )
    alternatives: list[AlternativeAnalysis] = Field(
        default_factory=list,
        description="Alternatives considered for the recommendation.",
    )
    expected_impact: DecisionImpact = Field(description="Expected decision impact.")


class DecisionPackage(DecisionModel):
    """Executive package prepared for final decision review."""

    recommendation: Recommendation = Field(description="Primary recommendation.")
    executive_brief: ExecutiveBrief = Field(description="Executive brief.")
    supporting_evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence references or summaries.",
    )
    required_approvals: list[str] = Field(
        default_factory=list,
        description="Required approval groups or roles.",
    )
    metadata: dict[str, DecisionMetadataValue] = Field(
        default_factory=dict,
        description="Structured package metadata.",
    )

    @field_validator("supporting_evidence", "required_approvals")
    @classmethod
    def validate_text_lists(cls, value: list[str]) -> list[str]:
        """Normalize text list values and reject blanks."""
        normalized = [item.strip() for item in value]
        if any(item == "" for item in normalized):
            msg = "text lists cannot contain blank values"
            raise ValueError(msg)
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, DecisionMetadataValue],
    ) -> dict[str, DecisionMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value

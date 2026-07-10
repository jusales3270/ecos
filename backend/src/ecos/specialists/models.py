"""Pydantic models for the ECOS Specialist Framework architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SpecialistMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class SpecialistType(StrEnum):
    """Supported cognitive specialist categories."""

    EXECUTIVE = "EXECUTIVE"
    FINANCE = "FINANCE"
    LEGAL = "LEGAL"
    OPERATIONS = "OPERATIONS"
    TECHNOLOGY = "TECHNOLOGY"
    MARKETING = "MARKETING"
    SALES = "SALES"
    HR = "HR"
    RISK = "RISK"
    STRATEGY = "STRATEGY"


class ContributionType(StrEnum):
    """Supported cognitive specialist contribution categories."""

    OPINION = "OPINION"
    RISK = "RISK"
    OPPORTUNITY = "OPPORTUNITY"
    ASSUMPTION = "ASSUMPTION"
    QUESTION = "QUESTION"
    RECOMMENDATION = "RECOMMENDATION"


class SpecialistModel(BaseModel):
    """Base specialist model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique specialist model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for specialist model creation.",
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


class Capability(SpecialistModel):
    """Capability available to a cognitive specialist."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Capability name.",
    )
    description: str = Field(
        min_length=1,
        max_length=1000,
        description="Capability description.",
    )


class Constraint(SpecialistModel):
    """Constraint that limits a cognitive specialist."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Constraint name.",
    )
    description: str = Field(
        min_length=1,
        max_length=1000,
        description="Constraint description.",
    )


class Specialist(SpecialistModel):
    """A cognitive specialist profile available to ECOS."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Specialist display name.",
    )
    type: SpecialistType = Field(description="Specialist category.")
    description: str = Field(
        min_length=1,
        max_length=2000,
        description="Specialist role description.",
    )
    capabilities: list[Capability] = Field(
        default_factory=list,
        description="Capabilities available to the specialist.",
    )
    constraints: list[Constraint] = Field(
        default_factory=list,
        description="Constraints that limit the specialist.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the specialist can be used.",
    )
    version: str = Field(
        default="0.1.0",
        min_length=1,
        max_length=50,
        description="Specialist definition version.",
    )


class Opinion(SpecialistModel):
    """Opinion produced by a cognitive specialist."""

    specialist_id: UUID = Field(description="Specialist that produced the opinion.")
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Opinion title.",
    )
    content: str = Field(
        min_length=1,
        max_length=5000,
        description="Opinion content.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Opinion confidence from 0.0 to 1.0.",
    )


class Contribution(SpecialistModel):
    """Contribution emitted by a cognitive specialist."""

    specialist_id: UUID = Field(description="Specialist that emitted the contribution.")
    contribution_type: ContributionType = Field(description="Contribution category.")
    content: str = Field(
        min_length=1,
        max_length=5000,
        description="Contribution content.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Contribution confidence from 0.0 to 1.0.",
    )
    metadata: dict[str, SpecialistMetadataValue] = Field(
        default_factory=dict,
        description="Structured contribution metadata.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, SpecialistMetadataValue],
    ) -> dict[str, SpecialistMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value

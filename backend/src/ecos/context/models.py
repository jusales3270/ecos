"""Pydantic models for the ECOS Context Engine architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.domain import Objective

ContextMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ContextSourceType(StrEnum):
    """Supported source categories for context elements."""

    MEMORY = "MEMORY"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    USER = "USER"
    DOCUMENT = "DOCUMENT"
    POLICY = "POLICY"
    EXTERNAL = "EXTERNAL"
    SESSION = "SESSION"


class ContextPriority(StrEnum):
    """Priority levels used when assembling context."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ContextModel(BaseModel):
    """Base context model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique context model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for context model creation.",
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


class ContextSource(ContextModel):
    """Describes the origin of a context element."""

    source_type: ContextSourceType = Field(description="Source category.")
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Human-readable source name.",
    )
    reference: str | None = Field(
        default=None,
        max_length=500,
        description="Optional source reference or URI.",
    )

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        """Reject blank references when provided."""
        if value == "":
            msg = "reference cannot be empty when provided"
            raise ValueError(msg)
        return value


class ContextElement(ContextModel):
    """A single item considered while assembling ECOS context."""

    source_type: ContextSourceType = Field(description="Element source category.")
    priority: ContextPriority = Field(description="Element assembly priority.")
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Short element title.",
    )
    content: str = Field(
        min_length=1,
        max_length=10000,
        description="Context content supplied by the element.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0.",
    )
    metadata: dict[str, ContextMetadataValue] = Field(
        default_factory=dict,
        description="Structured metadata associated with the element.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, ContextMetadataValue],
    ) -> dict[str, ContextMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value


class ContextObject(ContextModel):
    """Context assembled for a cognitive session and objective."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    objective: Objective = Field(description="Objective associated with this context.")
    elements: list[ContextElement] = Field(
        default_factory=list,
        description="Context elements selected for the session.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall assembled context confidence from 0.0 to 1.0.",
    )

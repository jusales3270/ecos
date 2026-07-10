"""Pydantic models for the ECOS Memory Engine architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class MemoryType(StrEnum):
    """Supported memory categories in the ECOS Memory Engine."""

    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    STRATEGIC = "STRATEGIC"
    ORGANIZATIONAL = "ORGANIZATIONAL"


class MemoryModel(BaseModel):
    """Base memory model with strict whitespace and timestamp validation."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4, description="Unique memory model identifier.")
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for model creation.",
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for the latest model update.",
    )

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        """Ensure timestamps are timezone-aware UTC and ordered."""
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                msg = f"{field_name} must be timezone-aware and in UTC"
                raise ValueError(msg)

        if self.updated_at < self.created_at:
            msg = "updated_at must be greater than or equal to created_at"
            raise ValueError(msg)
        return self


class MemoryObject(MemoryModel):
    """A unit of memory metadata managed by the Memory Engine."""

    type: MemoryType = Field(description="Memory category.")
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Short memory title.",
    )
    description: str = Field(
        min_length=1,
        max_length=2000,
        description="Human-readable memory description.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Searchable memory tags.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0.",
    )
    source: str = Field(
        min_length=1,
        max_length=500,
        description="Origin of the memory object.",
    )

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        """Normalize tags and reject blank tag values."""
        normalized = [tag.strip() for tag in value]
        if any(tag == "" for tag in normalized):
            msg = "tags cannot contain blank values"
            raise ValueError(msg)
        return normalized


class MemoryReference(MemoryModel):
    """Reference linking a memory object to an external or internal target."""

    memory_id: UUID = Field(description="Memory object being referenced.")
    target: str = Field(
        min_length=1,
        max_length=500,
        description="Reference target identifier or URI.",
    )
    relationship: str = Field(
        min_length=1,
        max_length=100,
        description="Relationship between the memory and the target.",
    )


class MemoryContext(MemoryModel):
    """A contextual grouping of memory objects and references."""

    objective_id: UUID | None = Field(
        default=None,
        description="Optional objective associated with this memory context.",
    )
    memories: list[MemoryObject] = Field(
        default_factory=list,
        description="Memory objects available in this context.",
    )
    references: list[MemoryReference] = Field(
        default_factory=list,
        description="References associated with this context.",
    )
    summary: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional human-readable context summary.",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str | None) -> str | None:
        """Reject blank summaries when provided."""
        if value == "":
            msg = "summary cannot be empty when provided"
            raise ValueError(msg)
        return value

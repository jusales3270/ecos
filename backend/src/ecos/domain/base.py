"""Shared domain model primitives for ECOS."""

from datetime import UTC, datetime
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class DomainEntity(BaseModel):
    """Base entity with identity and audit timestamps."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4, description="Unique entity identifier.")
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for entity creation.",
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for the latest entity update.",
    )

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        """Ensure audit timestamps are timezone-aware UTC and ordered."""
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                msg = f"{field_name} must be timezone-aware and in UTC"
                raise ValueError(msg)

        if self.updated_at < self.created_at:
            msg = "updated_at must be greater than or equal to created_at"
            raise ValueError(msg)
        return self

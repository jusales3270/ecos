"""Objective domain entity."""

from uuid import UUID

from pydantic import Field, field_validator

from ecos.domain.base import DomainEntity


class Objective(DomainEntity):
    """Represents an organizational objective modeled in ECOS."""

    organization_id: UUID = Field(description="Organization that owns the objective.")
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Short objective title.",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional objective details.",
    )
    priority: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Objective priority from 1 (lowest) to 5 (highest).",
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        """Reject blank objective descriptions when provided."""
        if value == "":
            msg = "description cannot be empty when provided"
            raise ValueError(msg)
        return value

"""Organization domain entity."""

from pydantic import Field, field_validator

from ecos.domain.base import DomainEntity


class Organization(DomainEntity):
    """Represents an organization using ECOS."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Human-readable organization name.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional organization description.",
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        """Reject blank organization descriptions when provided."""
        if value == "":
            msg = "description cannot be empty when provided"
            raise ValueError(msg)
        return value

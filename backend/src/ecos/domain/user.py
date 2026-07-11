"""User domain entity."""

from uuid import UUID

from pydantic import Field, field_validator

from ecos.domain.base import DomainEntity


class User(DomainEntity):
    """Represents an ECOS user within an organization."""

    organization_id: UUID = Field(description="Organization that owns the user.")
    email: str = Field(
        min_length=3,
        max_length=320,
        description="User email address.",
    )
    full_name: str = Field(
        min_length=1,
        max_length=200,
        description="User full display name.",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the user is active in ECOS.",
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Validate and normalize the user email address."""
        normalized = value.lower()
        if (
            "@" not in normalized
            or normalized.startswith("@")
            or normalized.endswith("@")
        ):
            msg = "email must be a valid email address"
            raise ValueError(msg)
        return normalized

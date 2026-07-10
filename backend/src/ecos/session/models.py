"""Pydantic models for the ECOS Cognitive Session Manager architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.domain import CognitiveSession, Objective
from ecos.domain.enums import SessionStage

SessionMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def validate_utc_datetime(field_name: str, value: datetime) -> None:
    """Validate that a datetime value is timezone-aware UTC."""
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        msg = f"{field_name} must be timezone-aware and in UTC"
        raise ValueError(msg)


class SessionLifecycleStatus(StrEnum):
    """Supported lifecycle statuses for a cognitive session."""

    CREATED = "CREATED"
    INITIALIZED = "INITIALIZED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TransitionType(StrEnum):
    """Supported lifecycle transition types."""

    INITIALIZE = "INITIALIZE"
    START_PLANNING = "START_PLANNING"
    START_EXECUTION = "START_EXECUTION"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"
    CANCEL = "CANCEL"


class SessionModel(BaseModel):
    """Base session manager model with identity and strict whitespace handling."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique session manager model identifier.",
    )


class SessionContext(SessionModel):
    """Context associated with a managed cognitive session."""

    organization_id: UUID = Field(description="Organization that owns the session.")
    objective: Objective = Field(description="Objective associated with the session.")
    metadata: dict[str, SessionMetadataValue] = Field(
        default_factory=dict,
        description="Structured session context metadata.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, SessionMetadataValue],
    ) -> dict[str, SessionMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value


class SessionState(SessionModel):
    """Mutable state snapshot for a cognitive session lifecycle."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    lifecycle_status: SessionLifecycleStatus = Field(
        description="Current lifecycle status.",
    )
    current_stage: SessionStage = Field(description="Current cognitive session stage.")
    active_engine: str | None = Field(
        default=None,
        max_length=100,
        description="Currently active engine, when any.",
    )
    progress: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Session progress from 0.0 to 1.0.",
    )
    last_error: str | None = Field(
        default=None,
        max_length=2000,
        description="Last lifecycle error, when any.",
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for the latest state update.",
    )

    @field_validator("active_engine", "last_error")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        """Reject blank optional text fields when provided."""
        if value == "":
            msg = "optional text fields cannot be empty when provided"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_updated_at(self) -> Self:
        """Ensure updated_at is timezone-aware UTC."""
        validate_utc_datetime("updated_at", self.updated_at)
        return self


class SessionSnapshot(SessionModel):
    """Persistable snapshot of session state and context."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    state: SessionState = Field(description="Session state captured by the snapshot.")
    context: SessionContext = Field(
        description="Session context captured by the snapshot.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for snapshot creation.",
    )

    @model_validator(mode="after")
    def validate_created_at(self) -> Self:
        """Ensure created_at is timezone-aware UTC."""
        validate_utc_datetime("created_at", self.created_at)
        return self


class SessionTransition(SessionModel):
    """Recorded lifecycle transition for a cognitive session."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    transition_type: TransitionType = Field(description="Lifecycle transition type.")
    from_status: SessionLifecycleStatus = Field(
        description="Previous lifecycle status.",
    )
    to_status: SessionLifecycleStatus = Field(description="Next lifecycle status.")
    reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional transition reason.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for transition creation.",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        """Reject blank reasons when provided."""
        if value == "":
            msg = "reason cannot be empty when provided"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_created_at(self) -> Self:
        """Ensure created_at is timezone-aware UTC."""
        validate_utc_datetime("created_at", self.created_at)
        return self


class SessionResult(SessionModel):
    """Final or current result summary for a managed cognitive session."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    lifecycle_status: SessionLifecycleStatus = Field(
        description="Lifecycle status represented by this result.",
    )
    summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional session result summary.",
    )
    metadata: dict[str, SessionMetadataValue] = Field(
        default_factory=dict,
        description="Structured session result metadata.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for result creation.",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str | None) -> str | None:
        """Reject blank summaries when provided."""
        if value == "":
            msg = "summary cannot be empty when provided"
            raise ValueError(msg)
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, SessionMetadataValue],
    ) -> dict[str, SessionMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_created_at(self) -> Self:
        """Ensure created_at is timezone-aware UTC."""
        validate_utc_datetime("created_at", self.created_at)
        return self


class ManagedSession(SessionModel):
    """Aggregate root for a managed cognitive session."""

    session: CognitiveSession = Field(description="Domain cognitive session.")
    state: SessionState = Field(description="Current lifecycle state.")
    context: SessionContext = Field(description="Current session context.")

"""Persistence contracts for resumable authenticated runtime checkpoints."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ecos.orchestrator import PipelineExecutionStatus
from ecos.planner import CognitivePlan


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class RuntimeCheckpointError(RuntimeError):
    """Base error for runtime checkpoint persistence."""


class RuntimeCheckpointNotFoundError(RuntimeCheckpointError):
    """Raised when a scoped runtime checkpoint does not exist."""


class RuntimeCheckpointScopeError(RuntimeCheckpointError):
    """Raised when a checkpoint belongs to another organization."""


class RuntimeCheckpointConflictError(RuntimeCheckpointError):
    """Raised when optimistic checkpoint persistence detects a stale write."""


class RuntimeCheckpointStatus(StrEnum):
    """Persisted lifecycle states for an authenticated runtime invocation."""

    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactEnvelope(BaseModel):
    """Versioned serialized engine output."""

    model_config = ConfigDict(frozen=True)

    engine: str = Field(min_length=1, max_length=100)
    artifact_type: str = Field(min_length=1, max_length=120)
    schema_version: int = Field(ge=1)
    payload: dict[str, Any] | None = None


class SerializedStageResult(BaseModel):
    """Stage result whose output is a typed artifact envelope."""

    model_config = ConfigDict(frozen=True)

    stage_id: UUID
    engine: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=40)
    output: ArtifactEnvelope
    started_at: datetime
    completed_at: datetime
    duration: float = Field(ge=0.0)
    attempt: int = Field(ge=1)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict
    )


class SerializedResumableState(BaseModel):
    """Persistable representation of an Orchestrator resume checkpoint."""

    model_config = ConfigDict(frozen=True)

    execution_id: UUID
    plan_id: UUID
    session_id: UUID
    organization_id: UUID
    correlation_id: UUID
    pipeline_status: PipelineExecutionStatus
    blocked_stage: UUID | None = None
    completed_stage_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    stage_results: tuple[SerializedStageResult, ...] = Field(default_factory=tuple)
    attempts: dict[UUID, int] = Field(default_factory=dict)
    timeline: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    approval_required: bool
    governance_required: bool
    created_at: datetime
    updated_at: datetime
    version: int = Field(default=1, ge=1)


class RuntimeCheckpoint(BaseModel):
    """Versioned durable checkpoint for one organization-scoped runtime session."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    organization_id: UUID
    user_id: UUID
    correlation_id: UUID
    cognitive_plan: CognitivePlan
    resumable_state: SerializedResumableState | None = None
    stage_results: tuple[SerializedStageResult, ...] = Field(default_factory=tuple)
    governance_result: ArtifactEnvelope | None = None
    version: int = Field(default=1, ge=1)
    status: RuntimeCheckpointStatus
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_scope_and_state(self) -> Self:
        """Ensure every persisted runtime artifact has the same immutable scope."""
        if self.cognitive_plan.session_id != self.session_id:
            raise ValueError("checkpoint plan session_id mismatch")
        if self.cognitive_plan.organization_id != self.organization_id:
            raise ValueError("checkpoint plan organization_id mismatch")
        if self.resumable_state is not None and (
            self.resumable_state.session_id != self.session_id
            or self.resumable_state.organization_id != self.organization_id
            or self.resumable_state.plan_id != self.cognitive_plan.plan_id
        ):
            raise ValueError("checkpoint resumable state scope mismatch")
        if self.updated_at < self.created_at:
            raise ValueError("checkpoint updated_at precedes created_at")
        return self


class RuntimeCheckpointRepository(ABC):
    """Organization-scoped checkpoint repository contract."""

    @abstractmethod
    def get(self, organization_id: UUID, session_id: UUID) -> RuntimeCheckpoint | None:
        """Return a checkpoint only within the supplied organization scope."""
        raise NotImplementedError

    @abstractmethod
    def save(
        self,
        checkpoint: RuntimeCheckpoint,
        *,
        expected_version: int | None,
    ) -> RuntimeCheckpoint:
        """Create or update a checkpoint using optimistic version control."""
        raise NotImplementedError


class InMemoryRuntimeCheckpointRepository(RuntimeCheckpointRepository):
    """Thread-safe in-memory checkpoint repository for tests and local runtime."""

    def __init__(self) -> None:
        self._checkpoints: dict[UUID, RuntimeCheckpoint] = {}
        self._lock = RLock()

    def get(self, organization_id: UUID, session_id: UUID) -> RuntimeCheckpoint | None:
        with self._lock:
            checkpoint = self._checkpoints.get(session_id)
            if checkpoint is None:
                return None
            if checkpoint.organization_id != organization_id:
                raise RuntimeCheckpointScopeError("runtime checkpoint is not available")
            return checkpoint.model_copy(deep=True)

    def save(
        self,
        checkpoint: RuntimeCheckpoint,
        *,
        expected_version: int | None,
    ) -> RuntimeCheckpoint:
        with self._lock:
            current = self._checkpoints.get(checkpoint.session_id)
            if (
                current is not None
                and current.organization_id != checkpoint.organization_id
            ):
                raise RuntimeCheckpointScopeError("runtime checkpoint scope mismatch")
            current_version = None if current is None else current.version
            if current_version != expected_version:
                raise RuntimeCheckpointConflictError(
                    "runtime checkpoint version conflict"
                )
            if current is None and checkpoint.version != 1:
                raise RuntimeCheckpointConflictError("new checkpoint version must be 1")
            if current is not None and checkpoint.version != current.version + 1:
                raise RuntimeCheckpointConflictError(
                    "updated checkpoint version must increment by one"
                )
            stored = checkpoint.model_copy(deep=True)
            self._checkpoints[checkpoint.session_id] = stored
            return stored.model_copy(deep=True)

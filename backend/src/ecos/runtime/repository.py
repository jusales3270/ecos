"""Persistence contracts for resumable authenticated runtime checkpoints."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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


Clock = Callable[[], datetime]
DEFAULT_START_CLAIM_LEASE = timedelta(seconds=30)


class RuntimeCheckpointError(RuntimeError):
    """Base error for runtime checkpoint persistence."""


class RuntimeCheckpointNotFoundError(RuntimeCheckpointError):
    """Raised when a scoped runtime checkpoint does not exist."""


class RuntimeCheckpointScopeError(RuntimeCheckpointError):
    """Raised when a checkpoint belongs to another organization."""


class RuntimeCheckpointConflictError(RuntimeCheckpointError):
    """Raised when optimistic checkpoint persistence detects a stale write."""


class RuntimeAlreadyStartedError(RuntimeCheckpointConflictError):
    """Raised when another request already owns or completed runtime startup."""


class RuntimeStartLeaseLostError(RuntimeCheckpointConflictError):
    """Raised when a worker no longer owns a live runtime startup lease."""


class RuntimeStartHeartbeatShutdownError(RuntimeCheckpointError):
    """Raised when a runtime startup heartbeat does not stop within its deadline."""


class RuntimeCheckpointStatus(StrEnum):
    """Persisted lifecycle states for an authenticated runtime invocation."""

    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class RuntimeStartClaimStatus(StrEnum):
    """Persistent startup ownership states for an authenticated runtime."""

    INITIALIZING = "initializing"
    STARTED = "started"
    FAILED = "failed"


class RuntimeStartClaim(BaseModel):
    """Organization-scoped atomic claim acquired before planning begins."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    organization_id: UUID
    user_id: UUID
    correlation_id: UUID
    objective: str = Field(min_length=1, max_length=200)
    status: RuntimeStartClaimStatus
    attempt: int = Field(default=1, ge=1)
    lease_expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        """Require unambiguous timezone-aware claim timestamps."""
        timestamps = (self.lease_expires_at, self.created_at, self.updated_at)
        if any(
            value.tzinfo is None or value.utcoffset() is None for value in timestamps
        ):
            raise ValueError("runtime start claim timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("runtime start claim updated_at precedes created_at")
        if self.lease_expires_at <= self.created_at:
            raise ValueError("runtime start claim lease must expire after creation")
        return self


class RuntimeStartAcquisition(BaseModel):
    """Result of an atomic startup claim attempt."""

    model_config = ConfigDict(frozen=True)

    claim: RuntimeStartClaim
    acquired: bool


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

    @abstractmethod
    def acquire_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        user_id: UUID,
        correlation_id: UUID,
        objective: str,
    ) -> RuntimeStartAcquisition:
        """Atomically acquire startup ownership before Planner is called."""
        raise NotImplementedError

    @property
    @abstractmethod
    def start_claim_lease_duration(self) -> timedelta:
        """Return the configured duration used when acquiring and renewing leases."""
        raise NotImplementedError

    @abstractmethod
    def renew_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        """Atomically renew a live startup claim owned by the caller."""
        raise NotImplementedError

    @abstractmethod
    def mark_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
        status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        """Finalize a claim using optimistic attempt and status control."""
        raise NotImplementedError


class InMemoryRuntimeCheckpointRepository(RuntimeCheckpointRepository):
    """Thread-safe in-memory checkpoint repository for tests and local runtime."""

    def __init__(
        self,
        *,
        lease_duration: timedelta = DEFAULT_START_CLAIM_LEASE,
        clock: Clock = utc_now,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("runtime start claim lease duration must be positive")
        self._checkpoints: dict[UUID, RuntimeCheckpoint] = {}
        self._start_claims: dict[UUID, RuntimeStartClaim] = {}
        self._lock = RLock()
        self._lease_duration = lease_duration
        self._clock = clock

    @property
    def start_claim_lease_duration(self) -> timedelta:
        return self._lease_duration

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

    def acquire_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        user_id: UUID,
        correlation_id: UUID,
        objective: str,
    ) -> RuntimeStartAcquisition:
        with self._lock:
            now = self._now()
            current = self._start_claims.get(session_id)
            if current is not None:
                if current.organization_id != organization_id:
                    raise RuntimeCheckpointScopeError(
                        "runtime start claim is not available"
                    )
                if current.objective != objective:
                    raise RuntimeCheckpointConflictError(
                        "runtime start claim objective mismatch"
                    )
                recoverable = current.status is RuntimeStartClaimStatus.FAILED or (
                    current.status is RuntimeStartClaimStatus.INITIALIZING
                    and current.lease_expires_at <= now
                )
                if not recoverable:
                    return RuntimeStartAcquisition(
                        claim=current.model_copy(deep=True),
                        acquired=False,
                    )
                claim = current.model_copy(
                    update={
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "status": RuntimeStartClaimStatus.INITIALIZING,
                        "attempt": current.attempt + 1,
                        "lease_expires_at": now + self._lease_duration,
                        "updated_at": now,
                    }
                )
            else:
                claim = RuntimeStartClaim(
                    session_id=session_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    objective=objective,
                    status=RuntimeStartClaimStatus.INITIALIZING,
                    lease_expires_at=now + self._lease_duration,
                    created_at=now,
                    updated_at=now,
                )
            self._start_claims[session_id] = claim
            return RuntimeStartAcquisition(
                claim=claim.model_copy(deep=True),
                acquired=True,
            )

    def mark_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
        status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        with self._lock:
            now = self._now()
            current = self._start_claims.get(session_id)
            if current is None:
                raise RuntimeStartLeaseLostError("runtime start claim is missing")
            if current.organization_id != organization_id:
                raise RuntimeCheckpointScopeError(
                    "runtime start claim is not available"
                )
            if current.attempt != expected_attempt:
                raise RuntimeStartLeaseLostError("runtime start claim attempt conflict")
            if current.status is not expected_status:
                raise RuntimeStartLeaseLostError("runtime start claim status conflict")
            if (
                expected_status is not RuntimeStartClaimStatus.INITIALIZING
                or status
                not in {
                    RuntimeStartClaimStatus.STARTED,
                    RuntimeStartClaimStatus.FAILED,
                }
            ):
                raise RuntimeCheckpointConflictError(
                    "invalid runtime start claim transition"
                )
            if current.lease_expires_at <= now:
                raise RuntimeStartLeaseLostError("runtime start claim lease expired")
            updated = current.model_copy(update={"status": status, "updated_at": now})
            self._start_claims[session_id] = updated
            return updated.model_copy(deep=True)

    def renew_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        if expected_status is not RuntimeStartClaimStatus.INITIALIZING:
            raise RuntimeCheckpointConflictError(
                "only initializing runtime start claims can be renewed"
            )
        with self._lock:
            now = self._now()
            current = self._start_claims.get(session_id)
            if current is None:
                raise RuntimeStartLeaseLostError("runtime start claim is missing")
            if current.organization_id != organization_id:
                raise RuntimeCheckpointScopeError(
                    "runtime start claim is not available"
                )
            if current.attempt != expected_attempt:
                raise RuntimeStartLeaseLostError("runtime start claim attempt conflict")
            if current.status is not expected_status:
                raise RuntimeStartLeaseLostError("runtime start claim status conflict")
            if current.lease_expires_at <= now:
                raise RuntimeStartLeaseLostError("runtime start claim lease expired")
            renewed = current.model_copy(
                update={
                    "lease_expires_at": now + self._lease_duration,
                    "updated_at": now,
                }
            )
            self._start_claims[session_id] = renewed
            return renewed.model_copy(deep=True)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("runtime start claim clock must be timezone-aware")
        return now

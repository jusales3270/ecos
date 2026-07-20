"""Persistence contracts for claimed canonical learning runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .models import LearningResult, LearningValidation


class LearningRepositoryError(RuntimeError):
    """Base error for canonical learning persistence."""


class LearningConflictError(LearningRepositoryError):
    """Raised for divergent identity, scope, fingerprint, or stale updates."""


class LearningClaimUnavailableError(LearningRepositoryError):
    """Raised while another worker owns an unexpired learning claim."""


class LearningClaim(BaseModel):
    """A versioned exclusive lease for one logical learning run."""

    model_config = ConfigDict(frozen=True)

    learning_id: UUID
    organization_id: UUID
    observation_id: UUID
    policy_version: str
    fingerprint: str
    owner: str
    expires_at: datetime
    version: int


class LearningAcquisition(BaseModel):
    """Either an acquired claim or an already completed result."""

    model_config = ConfigDict(frozen=True)

    claim: LearningClaim | None = None
    result: LearningResult | None = None


class LearningRepository(ABC):
    """Organization-scoped learning run persistence with exclusive claims."""

    @abstractmethod
    def get(
        self, organization_id: UUID, observation_id: UUID, policy_version: str
    ) -> LearningResult | None:
        raise NotImplementedError

    @abstractmethod
    def acquire(
        self,
        *,
        learning_id: UUID,
        organization_id: UUID,
        session_id: UUID,
        execution_id: UUID | None,
        observation_id: UUID,
        correlation_id: UUID,
        policy_version: str,
        fingerprint: str,
        owner: str,
    ) -> LearningAcquisition:
        raise NotImplementedError

    @abstractmethod
    def complete(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        raise NotImplementedError


class InMemoryLearningRepository(LearningRepository):
    """Thread-safe claimed learning repository for tests and local runtime."""

    def __init__(
        self,
        *,
        lease_duration: timedelta = timedelta(seconds=30),
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._lease_duration = lease_duration
        self._clock = clock
        self._runs: dict[tuple[UUID, UUID, str], dict[str, object]] = {}
        self._lock = RLock()

    def get(
        self, organization_id: UUID, observation_id: UUID, policy_version: str
    ) -> LearningResult | None:
        with self._lock:
            run = self._runs.get((organization_id, observation_id, policy_version))
            result = None if run is None else run.get("result")
            return (
                result.model_copy(deep=True)
                if isinstance(result, LearningResult)
                else None
            )

    def acquire(
        self,
        *,
        learning_id: UUID,
        organization_id: UUID,
        session_id: UUID,
        execution_id: UUID | None,
        observation_id: UUID,
        correlation_id: UUID,
        policy_version: str,
        fingerprint: str,
        owner: str,
    ) -> LearningAcquisition:
        key = (organization_id, observation_id, policy_version)
        now = self._clock()
        with self._lock:
            run = self._runs.get(key)
            if run is None:
                claim = LearningClaim(
                    learning_id=learning_id,
                    organization_id=organization_id,
                    observation_id=observation_id,
                    policy_version=policy_version,
                    fingerprint=fingerprint,
                    owner=owner,
                    expires_at=now + self._lease_duration,
                    version=1,
                )
                self._runs[key] = {
                    "claim": claim,
                    "scope": (session_id, execution_id, correlation_id),
                    "result": None,
                }
                return LearningAcquisition(claim=claim)
            if run["scope"] != (session_id, execution_id, correlation_id):
                raise LearningConflictError("learning scope conflict")
            claim = run["claim"]
            assert isinstance(claim, LearningClaim)
            if claim.fingerprint != fingerprint:
                raise LearningConflictError("learning fingerprint conflict")
            result = run.get("result")
            if isinstance(result, LearningResult):
                return LearningAcquisition(result=result.model_copy(deep=True))
            if claim.expires_at > now and claim.owner != owner:
                raise LearningClaimUnavailableError("learning claim is already owned")
            recovered = claim.model_copy(
                update={
                    "owner": owner,
                    "expires_at": now + self._lease_duration,
                    "version": claim.version + 1,
                }
            )
            run["claim"] = recovered
            return LearningAcquisition(claim=recovered)

    def complete(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        del validations
        key = (claim.organization_id, claim.observation_id, claim.policy_version)
        with self._lock:
            run = self._runs.get(key)
            current = None if run is None else run.get("claim")
            if not isinstance(current, LearningClaim) or (
                current.owner != claim.owner or current.version != claim.version
            ):
                raise LearningConflictError("stale learning claim")
            existing = run.get("result")
            if isinstance(existing, LearningResult):
                if existing.fingerprint != result.fingerprint:
                    raise LearningConflictError("learning fingerprint conflict")
                return existing.model_copy(deep=True)
            run["result"] = result.model_copy(deep=True)
            run["claim"] = current.model_copy(update={"version": current.version + 1})
            return result.model_copy(deep=True)

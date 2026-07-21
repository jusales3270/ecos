"""Persistence contracts for claimed canonical learning runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ecos.memory import ValidatedMemoryWrite, validated_memory_fingerprint

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
    staged_result: LearningResult | None = None


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

    @abstractmethod
    def stage_validated(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        """Persist canonical candidates, validations, and proposals before memory."""
        raise NotImplementedError

    @abstractmethod
    def validate_memory_write(self, write: ValidatedMemoryWrite) -> None:
        """Reject a write not represented by canonical persisted validation."""
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
                    "staged": None,
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
            staged = run.get("staged")
            return LearningAcquisition(
                claim=recovered,
                staged_result=staged.model_copy(deep=True)
                if isinstance(staged, LearningResult)
                else None,
            )

    def stage_validated(
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
            existing = run.get("staged")
            if isinstance(existing, LearningResult):
                if existing.fingerprint != result.fingerprint:
                    raise LearningConflictError("learning fingerprint conflict")
                return existing.model_copy(deep=True)
            run["staged"] = result.model_copy(deep=True)
            return result.model_copy(deep=True)

    def validate_memory_write(self, write: ValidatedMemoryWrite) -> None:
        with self._lock:
            matching = [
                run
                for run in self._runs.values()
                if isinstance(run.get("staged"), LearningResult)
                and run["staged"].learning_id == write.learning_id
                and run["staged"].organization_id == write.organization_id
            ]
            if len(matching) != 1:
                raise LearningConflictError("canonical validated learning not found")
            _validate_write_against_result(write, matching[0]["staged"])

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
            run["staged"] = result.model_copy(deep=True)
            run["claim"] = current.model_copy(update={"version": current.version + 1})
            return result.model_copy(deep=True)


def _validate_write_against_result(
    write: ValidatedMemoryWrite, result: LearningResult
) -> None:
    """Validate all write provenance against one canonical LearningResult."""
    proposal = next(
        (
            item
            for item in result.memory_update_proposals
            if item.proposal_id == write.proposal_id
        ),
        None,
    )
    validation = next(
        (
            item
            for item in result.validations
            if item.learning_candidate_id == write.candidate_id
        ),
        None,
    )
    candidate = next(
        (
            item
            for item in result.validated_candidates
            if item.learning_candidate_id == write.candidate_id
        ),
        None,
    )
    if proposal is None or validation is None or candidate is None:
        raise LearningConflictError(
            "canonical proposal, candidate, or validation missing"
        )
    expected = validated_memory_fingerprint(
        organization_id=write.organization_id,
        session_id=write.session_id,
        execution_id=write.execution_id,
        correlation_id=write.correlation_id,
        observation_id=write.observation_id,
        learning_id=write.learning_id,
        candidate_id=write.candidate_id,
        proposal_id=write.proposal_id,
        policy_version=write.policy_version,
        validation_status=write.validation_status,
        memory_type=write.memory_type,
        content=write.content,
        tags=write.tags,
        confidence=write.confidence,
        evidence_references=write.evidence_references,
        source_references=write.source_references,
    )
    if any(
        (
            result.organization_id != write.organization_id,
            result.session_id != write.session_id,
            result.execution_id != write.execution_id,
            result.observation_id != write.observation_id,
            result.correlation_id != write.correlation_id,
            result.policy_version != write.policy_version,
            proposal.organization_id != write.organization_id,
            proposal.session_id != write.session_id,
            proposal.learning_candidate_id != write.candidate_id,
            proposal.memory_type != write.memory_type,
            proposal.content != write.content,
            proposal.confidence != write.confidence,
            proposal.evidence_references != write.evidence_references,
            proposal.source_references != write.source_references,
            proposal.validation_status.value != write.validation_status,
            write.tags
            != (
                "learning",
                "validated",
                f"v{proposal.version}",
            ),
            validation.outcome.value != "validated",
            validation.human_review_required,
            candidate.validation_status.value != "validated",
            candidate.human_review_required,
            expected != write.fingerprint,
        )
    ):
        raise LearningConflictError(
            "validated memory write diverges from canonical learning"
        )

"""Persistence contracts for claimed canonical learning runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict

from ecos.events import Event
from ecos.memory import MemoryType, ValidatedMemoryWrite, validated_memory_fingerprint
from ecos.outbox import (
    InMemoryOutboxRepository,
    message_from_event,
    validate_terminal_event,
)

from .models import (
    LearningCandidateReview,
    LearningResult,
    LearningReviewStatus,
    LearningStatus,
    LearningValidation,
    LearningValidationOutcome,
    MemoryUpdateProposal,
)


class LearningRepositoryError(RuntimeError):
    """Base error for canonical learning persistence."""


class LearningConflictError(LearningRepositoryError):
    """Raised for divergent identity, scope, fingerprint, or stale updates."""


class LearningReviewDecision(BaseModel):
    """Result of one durable candidate review decision."""

    model_config = ConfigDict(frozen=True)

    review: LearningCandidateReview
    result: LearningResult


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

    supports_transactional_outbox: bool = False

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

    def complete_terminal(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
        event: Event,
    ) -> LearningResult:
        del event
        return self.complete(claim=claim, result=result, validations=validations)

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

    @abstractmethod
    def list_by_session(
        self, organization_id: UUID, session_id: UUID
    ) -> list[LearningResult]:
        """List persisted canonical learning runs for a scoped session."""
        raise NotImplementedError

    @abstractmethod
    def list_reviews(
        self,
        organization_id: UUID,
        *,
        session_id: UUID | None = None,
        status: LearningReviewStatus | None = None,
    ) -> list[LearningCandidateReview]:
        raise NotImplementedError

    @abstractmethod
    def decide_review(
        self,
        *,
        organization_id: UUID,
        candidate_id: UUID,
        actor_id: UUID,
        status: LearningReviewStatus,
        justification: str,
        idempotency_key: str,
    ) -> LearningReviewDecision:
        raise NotImplementedError

    @abstractmethod
    def finalize_review(
        self, *, result: LearningResult, event: Event
    ) -> LearningResult:
        raise NotImplementedError


class InMemoryLearningRepository(LearningRepository):
    """Thread-safe claimed learning repository for tests and local runtime."""

    def __init__(
        self,
        *,
        lease_duration: timedelta = timedelta(seconds=30),
        clock=lambda: datetime.now(UTC),
        outbox: InMemoryOutboxRepository | None = None,
    ) -> None:
        self._lease_duration = lease_duration
        self._clock = clock
        self._runs: dict[tuple[UUID, UUID, str], dict[str, object]] = {}
        self._lock = RLock()
        self._outbox = outbox
        self.supports_transactional_outbox = outbox is not None

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

    def list_by_session(
        self, organization_id: UUID, session_id: UUID
    ) -> list[LearningResult]:
        with self._lock:
            values: list[LearningResult] = []
            for run in self._runs.values():
                result = run.get("result") or run.get("staged")
                if (
                    isinstance(result, LearningResult)
                    and result.organization_id == organization_id
                    and result.session_id == session_id
                ):
                    values.append(result.model_copy(deep=True))
            return values

    def list_reviews(
        self,
        organization_id: UUID,
        *,
        session_id: UUID | None = None,
        status: LearningReviewStatus | None = None,
    ) -> list[LearningCandidateReview]:
        with self._lock:
            reviews = getattr(self, "_reviews", {})
            return [
                item.model_copy(deep=True)
                for item in reviews.values()
                if item.organization_id == organization_id
                and (session_id is None or item.session_id == session_id)
                and (status is None or item.status is status)
            ]

    def decide_review(self, **kwargs) -> LearningReviewDecision:
        return _decide_in_memory_review(self, **kwargs)

    def finalize_review(
        self, *, result: LearningResult, event: Event
    ) -> LearningResult:
        validate_learning_terminal_event(result, event)
        with self._lock:
            for run in self._runs.values():
                staged = run.get("staged")
                if (
                    isinstance(staged, LearningResult)
                    and staged.learning_id == result.learning_id
                ):
                    run["staged"] = result.model_copy(deep=True)
                    run["result"] = result.model_copy(deep=True)
                    if self._outbox is not None:
                        self._outbox.enqueue(
                            message_from_event(
                                event,
                                actor_id=None,
                                aggregate_type="learning",
                                aggregate_id=str(result.learning_id),
                                execution_id=result.execution_id,
                                observation_id=result.observation_id,
                                learning_id=result.learning_id,
                            )
                        )
                    return result.model_copy(deep=True)
        raise LearningConflictError("learning review result is not available")

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
            reviews = getattr(self, "_reviews", None)
            if reviews is None:
                reviews = {}
                self._reviews = reviews
            for candidate in (
                result.human_review_candidates
                if result.status is LearningStatus.HUMAN_REVIEW_REQUIRED
                else ()
            ):
                review_id = uuid5(
                    NAMESPACE_URL,
                    f"ecos:learning-review:{result.organization_id}:{candidate.learning_candidate_id}",
                )
                reviews[candidate.learning_candidate_id] = LearningCandidateReview(
                    review_id=review_id,
                    organization_id=result.organization_id,
                    session_id=result.session_id,
                    learning_id=result.learning_id,
                    learning_candidate_id=candidate.learning_candidate_id,
                    status=LearningReviewStatus.PENDING,
                )
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
        if result.status not in {LearningStatus.COMPLETED, LearningStatus.FAILED}:
            raise LearningConflictError("learning completion requires terminal status")
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

    def complete_terminal(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
        event: Event,
    ) -> LearningResult:
        with self._lock:
            validate_learning_terminal_event(result, event)
            canonical = self.complete(
                claim=claim, result=result, validations=validations
            )
            if self._outbox is not None:
                self._outbox.enqueue(
                    message_from_event(
                        event,
                        actor_id=None,
                        aggregate_type="learning",
                        aggregate_id=str(result.learning_id),
                        execution_id=result.execution_id,
                        observation_id=result.observation_id,
                        learning_id=result.learning_id,
                    )
                )
            return canonical


def validate_learning_terminal_event(result: LearningResult, event: Event) -> None:
    expected_type = (
        "LEARNING_FAILED"
        if result.status is LearningStatus.FAILED
        else "LEARNING_COMPLETED"
    )
    validate_terminal_event(
        event,
        organization_id=result.organization_id,
        session_id=result.session_id,
        correlation_id=result.correlation_id,
        event_type=expected_type,
    )


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


def apply_learning_review(
    result: LearningResult,
    *,
    candidate_id: UUID,
    approved: bool,
) -> LearningResult:
    """Apply one persisted human decision to the canonical learning payload."""
    candidate = next(
        (
            item
            for item in result.human_review_candidates
            if item.learning_candidate_id == candidate_id
        ),
        None,
    )
    if candidate is None:
        raise LearningConflictError("learning candidate is not pending review")
    reviewed_candidate = candidate.model_copy(
        update={
            "validation_status": LearningStatus.VALIDATED
            if approved
            else LearningStatus.REJECTED,
            "human_review_required": False,
        }
    )
    validations = tuple(
        item.model_copy(
            update={
                "outcome": LearningValidationOutcome.VALIDATED
                if approved
                else LearningValidationOutcome.REJECTED,
                "human_review_required": False,
                "reason_codes": (
                    "human_review_approved" if approved else "human_review_rejected",
                ),
            }
        )
        if item.learning_candidate_id == candidate_id
        else item
        for item in result.validations
    )
    remaining = tuple(
        item
        for item in result.human_review_candidates
        if item.learning_candidate_id != candidate_id
    )
    proposals = result.memory_update_proposals
    if approved:
        proposals = (
            *proposals,
            MemoryUpdateProposal(
                proposal_id=uuid5(
                    NAMESPACE_URL,
                    f"ecos:learning-proposal:{result.organization_id}:{candidate_id}",
                ),
                organization_id=result.organization_id,
                session_id=result.session_id,
                learning_candidate_id=candidate_id,
                memory_type=MemoryType.EPISODIC,
                content={
                    "statement": candidate.statement,
                    "category": candidate.category.value,
                    "relationship": candidate.relationship.value,
                    **(
                        {"objective": candidate.safe_metadata["objective"]}
                        if candidate.safe_metadata.get("objective")
                        else {}
                    ),
                },
                evidence_references=candidate.evidence_references,
                source_references=candidate.source_references,
                confidence=candidate.confidence,
                validation_status=LearningValidationOutcome.VALIDATED,
                policy_references=candidate.policy_references,
                retention_hint="preserve provenance",
                reason_codes=("human_review_approved_memory_update_proposal",),
            ),
        )
    validated = (
        (*result.validated_candidates, reviewed_candidate)
        if approved
        else result.validated_candidates
    )
    rejected = (
        result.rejected_candidates
        if approved
        else (*result.rejected_candidates, reviewed_candidate)
    )
    return result.model_copy(
        update={
            "status": LearningStatus.HUMAN_REVIEW_REQUIRED
            if remaining
            else LearningStatus.VALIDATED,
            "validations": validations,
            "candidates": tuple(
                reviewed_candidate
                if item.learning_candidate_id == candidate_id
                else item
                for item in result.candidates
            ),
            "validated_candidates": validated,
            "rejected_candidates": rejected,
            "human_review_candidates": remaining,
            "memory_update_proposals": proposals,
            "validation_summary": {
                "validated": len(validated),
                "rejected": len(rejected),
                "human_review_required": len(remaining),
            },
            "reason_codes": ("human_review_pending",)
            if remaining
            else ("human_review_completed",),
        }
    )


def _decide_in_memory_review(
    repository: InMemoryLearningRepository,
    *,
    organization_id: UUID,
    candidate_id: UUID,
    actor_id: UUID,
    status: LearningReviewStatus,
    justification: str,
    idempotency_key: str,
) -> LearningReviewDecision:
    if status not in {LearningReviewStatus.APPROVED, LearningReviewStatus.REJECTED}:
        raise LearningConflictError("human review decision must be terminal")
    with repository._lock:
        reviews = getattr(repository, "_reviews", {})
        review = reviews.get(candidate_id)
        if (
            not isinstance(review, LearningCandidateReview)
            or review.organization_id != organization_id
        ):
            raise LearningConflictError("learning review is not available")
        if review.status is not LearningReviewStatus.PENDING:
            if (
                review.idempotency_key == idempotency_key
                and review.status is status
                and review.justification == justification
            ):
                result = next(
                    run.get("staged")
                    for run in repository._runs.values()
                    if isinstance(run.get("staged"), LearningResult)
                    and run["staged"].learning_id == review.learning_id
                )
                return LearningReviewDecision(review=review, result=result)
            raise LearningConflictError(
                "learning review decision conflicts with persisted decision"
            )
        run = next(
            run
            for run in repository._runs.values()
            if isinstance(run.get("staged"), LearningResult)
            and run["staged"].learning_id == review.learning_id
        )
        result = apply_learning_review(
            run["staged"],
            candidate_id=candidate_id,
            approved=status is LearningReviewStatus.APPROVED,
        )
        now = repository._clock()
        decided = review.model_copy(
            update={
                "status": status,
                "justification": justification,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
                "decided_at": now,
                "updated_at": now,
                "version": review.version + 1,
            }
        )
        reviews[candidate_id] = decided
        run["staged"] = result
        return LearningReviewDecision(review=decided, result=result)

"""Deterministic Learning Engine application service."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.memory import MemoryObject, MemoryService, MemoryType
from ecos.observation import ObservedOutcomeStatus

from .models import (
    CalibrationDirection,
    ConfidenceCalibration,
    LearningCandidate,
    LearningCategory,
    LearningObject,
    LearningRequest,
    LearningResult,
    LearningStatus,
    LearningValidation,
    LearningValidationOutcome,
    LearningValidationStatus,
    MemoryUpdateProposal,
    PatternSignal,
    RelationshipType,
)
from .provider import (
    DefaultLearningPolicyProvider,
    InMemoryLearningHistoryProvider,
    InMemoryLearningIdempotencyProvider,
    LearningHistoryProvider,
    LearningIdempotencyProvider,
    LearningPolicyProvider,
)

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]


class LearningConfig:
    """Immutable validation policy for deterministic learning."""

    def __init__(
        self,
        *,
        minimum_quality: float = 0.5,
        minimum_confidence: float = 0.5,
        minimum_evidence: int = 1,
        minimum_pattern_occurrences: int = 2,
        require_distinct_pattern_sources: bool = False,
        max_single_observation_adjustment: float = 0.1,
    ) -> None:
        self.minimum_quality = minimum_quality
        self.minimum_confidence = minimum_confidence
        self.minimum_evidence = minimum_evidence
        self.minimum_pattern_occurrences = minimum_pattern_occurrences
        self.require_distinct_pattern_sources = require_distinct_pattern_sources
        self.max_single_observation_adjustment = max_single_observation_adjustment


class LearningService:
    """Validate candidates and exclusively coordinate permanent memory writes."""

    def __init__(
        self,
        memory_service: MemoryService,
        event_service: EventService,
        *,
        history_provider: LearningHistoryProvider | None = None,
        policy_provider: LearningPolicyProvider | None = None,
        idempotency_provider: LearningIdempotencyProvider | None = None,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
        config: LearningConfig | None = None,
    ) -> None:
        self._memory_service = memory_service
        self._event_service = event_service
        self._history_provider = history_provider or InMemoryLearningHistoryProvider()
        self._policy_provider = policy_provider or DefaultLearningPolicyProvider()
        self._idempotency_provider = (
            idempotency_provider or InMemoryLearningIdempotencyProvider()
        )
        from datetime import UTC
        from uuid import uuid4

        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_generator = id_generator or uuid4
        self._config = config or LearningConfig()

    def learn(self, candidate: LearningObject) -> MemoryObject | None:
        """Validate a candidate and persist it only when approved."""
        self._publish(
            EventType.LEARNING_STARTED, candidate, {"learning_id": str(candidate.id)}
        )
        approved = candidate.confidence >= 0.5 and bool(candidate.evidence)
        status = (
            LearningValidationStatus.APPROVED
            if approved
            else LearningValidationStatus.REJECTED
        )
        reason = (
            "deterministic policy approved candidate"
            if approved
            else "confidence or evidence below policy threshold"
        )
        candidate.status = status
        candidate.validation_reason = reason
        self._publish(
            EventType.LEARNING_VALIDATED,
            candidate,
            {"status": status.value, "approved": approved},
        )
        memory: MemoryObject | None = None
        if approved:
            memory = self._memory_service.store(
                MemoryObject(
                    organization_id=candidate.organization_id,
                    type=candidate.memory_type,
                    title=candidate.title,
                    description=candidate.description,
                    tags=candidate.tags,
                    confidence=candidate.confidence,
                    source=candidate.origin,
                )
            )
            self._publish(
                EventType.MEMORY_UPDATED, candidate, {"memory_id": str(memory.id)}
            )
        self._publish(
            EventType.LEARNING_COMPLETED,
            candidate,
            {
                "status": status.value,
                "memory_id": None if memory is None else str(memory.id),
            },
        )
        return memory

    def process(self, request: LearningRequest) -> LearningResult:
        """Process ObservationResult into validated, reusable memory."""
        key = self._idempotency_key(request)
        fingerprint = self._fingerprint(request)
        existing = self._idempotency_provider.get(key)
        if existing is not None:
            existing_fingerprint, existing_result = existing
            if existing_fingerprint != fingerprint:
                self._publish_learning(
                    request,
                    EventType.IDEMPOTENCY_CONFLICT,
                    {"reason": "learning idempotency conflict"},
                )
                raise RuntimeError("learning idempotency conflict")
            self._publish_learning(request, EventType.IDEMPOTENCY_HIT, {})
            return existing_result  # type: ignore[return-value]

        started_at = self._clock()
        self._publish_learning(request, EventType.LEARNING_STARTED, {})
        candidates = self._candidates(request)
        for candidate in candidates:
            self._publish_learning(
                request,
                EventType.LEARNING_CANDIDATE_CREATED,
                {
                    "learning_candidate_id": str(candidate.learning_candidate_id),
                    "category": candidate.category.value,
                },
            )
        validations = tuple(
            self._validate_candidate(request, item) for item in candidates
        )
        validated_candidates = tuple(
            candidate.model_copy(update={"validation_status": LearningStatus.VALIDATED})
            for candidate, validation in zip(candidates, validations, strict=True)
            if validation.outcome is LearningValidationOutcome.VALIDATED
        )
        rejected_candidates = tuple(
            candidate.model_copy(update={"validation_status": LearningStatus.REJECTED})
            for candidate, validation in zip(candidates, validations, strict=True)
            if validation.outcome
            in {
                LearningValidationOutcome.REJECTED,
                LearningValidationOutcome.INSUFFICIENT_EVIDENCE,
                LearningValidationOutcome.POLICY_BLOCKED,
            }
        )
        human_review_candidates = tuple(
            candidate.model_copy(
                update={"validation_status": LearningStatus.HUMAN_REVIEW_REQUIRED}
            )
            for candidate, validation in zip(candidates, validations, strict=True)
            if validation.outcome is LearningValidationOutcome.HUMAN_REVIEW_REQUIRED
        )
        for candidate in rejected_candidates:
            self._publish_learning(
                request,
                EventType.LEARNING_REJECTED,
                {"learning_candidate_id": str(candidate.learning_candidate_id)},
            )
        for candidate in human_review_candidates:
            self._publish_learning(
                request,
                EventType.LEARNING_HUMAN_REVIEW_REQUIRED,
                {"learning_candidate_id": str(candidate.learning_candidate_id)},
            )
        for candidate in validated_candidates:
            self._publish_learning(
                request,
                EventType.LEARNING_VALIDATED,
                {"learning_candidate_id": str(candidate.learning_candidate_id)},
            )
        patterns = self._patterns(validated_candidates)
        for pattern in patterns:
            self._publish_learning(
                request,
                EventType.PATTERN_DETECTED,
                {
                    "pattern_id": pattern.pattern_id,
                    "recurrence_count": pattern.recurrence_count,
                },
            )
        calibrations = (self._calibration(request),)
        self._publish_learning(
            request,
            EventType.CONFIDENCE_CALIBRATED,
            {"direction": calibrations[0].direction.value},
        )
        proposals = tuple(
            self._proposal(request, candidate) for candidate in validated_candidates
        )
        for proposal in proposals:
            self._publish_learning(
                request,
                EventType.MEMORY_UPDATE_PROPOSED,
                {"proposal_id": str(proposal.proposal_id)},
            )
        stored = tuple(self._store_proposal(proposal) for proposal in proposals)
        for memory_id in stored:
            self._publish_learning(
                request,
                EventType.MEMORY_IMPROVED,
                {"memory_id": memory_id},
            )
        evidence_references = tuple(
            sorted(
                {
                    reference
                    for candidate in candidates
                    for reference in candidate.evidence_references
                }
            )
        )
        completed_at = self._clock()
        result = LearningResult(
            learning_id=self._id_generator(),
            learning_request_id=request.learning_request_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            correlation_id=request.correlation_id,
            execution_id=request.execution_id,
            observation_id=request.observation_result.observation_id,
            status=LearningStatus.COMPLETED,
            candidates=candidates,
            validated_candidates=validated_candidates,
            rejected_candidates=rejected_candidates,
            human_review_candidates=human_review_candidates,
            pattern_signals=patterns,
            confidence_calibrations=calibrations,
            memory_update_proposals=proposals,
            stored_memory_references=stored,
            evidence_references=evidence_references,
            validation_summary={
                "validated": len(validated_candidates),
                "rejected": len(rejected_candidates),
                "human_review_required": len(human_review_candidates),
            },
            started_at=started_at,
            completed_at=completed_at,
            duration=max((completed_at - started_at).total_seconds(), 0.0),
            reason_codes=("learning_completed",),
            warnings=request.observation_result.warnings,
            safe_metadata=dict(request.safe_metadata),
        )
        self._idempotency_provider.put(key, fingerprint, result)
        self._publish_learning(
            request,
            EventType.LEARNING_COMPLETED,
            {"learning_id": str(result.learning_id), "stored": len(stored)},
        )
        return result

    def _publish(
        self,
        event_type: EventType,
        candidate: LearningObject,
        payload: dict[str, str | bool | None],
    ) -> None:
        safe_payload: dict[str, str | bool | None] = dict(payload)
        if candidate.organization_id is not None:
            safe_payload["organization_id"] = str(candidate.organization_id)
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="learning",
                session_id=candidate.session_id,
                organization_id=candidate.organization_id,
                payload=safe_payload,
                metadata=EventMetadata(correlation_id=candidate.session_id),
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)

    def _candidates(self, request: LearningRequest) -> tuple[LearningCandidate, ...]:
        observation = request.observation_result
        candidates: list[LearningCandidate] = []
        evidence = tuple(
            item.evidence_id for item in observation.evidence if not item.sensitive
        )
        source_references = (f"observation:{observation.observation_id}",)
        execution_succeeded = self._execution_succeeded(request)
        for outcome in observation.observed_outcomes:
            if not execution_succeeded and request.execution_result is not None:
                code = "execution_failed"
                statement_status = self._execution_status(request) or "failed"
            elif outcome.status is ObservedOutcomeStatus.SUCCESSFUL:
                code = "expectation_reached"
                statement_status = "successful"
            elif outcome.status in {
                ObservedOutcomeStatus.FAILED,
                ObservedOutcomeStatus.ROLLED_BACK,
            }:
                code = "expectation_not_reached"
                statement_status = outcome.status.value
            elif outcome.status in {
                ObservedOutcomeStatus.INCONCLUSIVE,
                ObservedOutcomeStatus.NOT_OBSERVED,
            }:
                code = "data_insufficient"
                statement_status = outcome.status.value
            else:
                code = "partial_outcome_observed"
                statement_status = outcome.status.value
            candidates.append(
                LearningCandidate(
                    learning_candidate_id=self._id_generator(),
                    category=LearningCategory.OUTCOME,
                    source_references=source_references,
                    evidence_references=evidence or outcome.evidence_references,
                    statement={
                        "type": code,
                        "outcome_status": statement_status,
                        "outcome_score": observation.outcome_score,
                        "relationship": RelationshipType.ASSOCIATED_WITH.value,
                    },
                    affected_components=("observation",),
                    affected_domains=tuple(
                        request.observation_result.safe_metadata.get("domain", "")
                        for _ in ()
                        if False
                    ),
                    confidence=observation.confidence,
                    recurrence_count=1,
                    novelty_score=1.0,
                    organizational_impact=observation.outcome_score,
                    policy_references=tuple(request.applicable_policies),
                    relationship=RelationshipType.ASSOCIATED_WITH,
                    reason_codes=(code, "no_causality_inferred"),
                    safe_metadata={"observation_status": observation.status.value},
                )
            )
        recommendation = request.recommendation or getattr(
            request.decision_package, "recommendation", None
        )
        if recommendation is not None and execution_succeeded:
            candidates.append(
                LearningCandidate(
                    learning_candidate_id=self._id_generator(),
                    category=LearningCategory.DECISION,
                    source_references=source_references,
                    evidence_references=evidence,
                    statement={
                        "type": "recommendation_observed",
                        "relationship": RelationshipType.OBSERVED_TOGETHER.value,
                    },
                    affected_components=("decision",),
                    confidence=_clamp(
                        float(getattr(recommendation, "confidence", 0.0))
                    ),
                    recurrence_count=1,
                    novelty_score=1.0,
                    organizational_impact=observation.outcome_score,
                    policy_references=tuple(request.applicable_policies),
                    relationship=RelationshipType.OBSERVED_TOGETHER,
                    reason_codes=(
                        "decision_learning_candidate",
                        "no_causality_inferred",
                    ),
                )
            )
        for comparison in observation.comparisons:
            if comparison.status.value == "not_observed":
                candidates.append(
                    LearningCandidate(
                        learning_candidate_id=self._id_generator(),
                        category=LearningCategory.OPERATIONAL,
                        source_references=source_references,
                        evidence_references=evidence,
                        statement={
                            "type": "information_gap",
                            "metric_key": comparison.metric_key,
                            "relationship": RelationshipType.ASSOCIATED_WITH.value,
                        },
                        affected_components=("observation", "memory"),
                        confidence=observation.quality.completeness_score,
                        recurrence_count=1,
                        novelty_score=1.0,
                        organizational_impact=0.2,
                        policy_references=tuple(request.applicable_policies),
                        relationship=RelationshipType.ASSOCIATED_WITH,
                        reason_codes=(
                            "data_gap_learning_candidate",
                            "no_causality_inferred",
                        ),
                    )
                )
        for candidate in candidates:
            self._history_provider.record(
                self._candidate_signature(candidate),
                candidate.source_references[0],
            )
        return tuple(candidates)

    def _validate_candidate(
        self,
        request: LearningRequest,
        candidate: LearningCandidate,
    ) -> LearningValidation:
        evidence_count = len(candidate.evidence_references)
        quality = request.observation_result.quality.evidence_quality_score
        if not self._execution_succeeded(request) and self._is_positive(candidate):
            outcome = LearningValidationOutcome.POLICY_BLOCKED
        elif self._policy_provider.blocks(candidate):
            outcome = LearningValidationOutcome.POLICY_BLOCKED
        elif self._policy_provider.requires_human_review(candidate):
            outcome = LearningValidationOutcome.HUMAN_REVIEW_REQUIRED
        elif (
            candidate.category is LearningCategory.DECISION
            and not request.user_feedback
        ):
            outcome = LearningValidationOutcome.HUMAN_REVIEW_REQUIRED
        elif evidence_count < self._config.minimum_evidence:
            outcome = LearningValidationOutcome.INSUFFICIENT_EVIDENCE
        elif quality < self._config.minimum_quality:
            outcome = LearningValidationOutcome.INSUFFICIENT_EVIDENCE
        elif candidate.confidence < self._config.minimum_confidence:
            outcome = LearningValidationOutcome.REJECTED
        else:
            outcome = LearningValidationOutcome.VALIDATED
        return LearningValidation(
            learning_candidate_id=candidate.learning_candidate_id,
            outcome=outcome,
            confidence=candidate.confidence,
            evidence_count=evidence_count,
            human_review_required=outcome
            is LearningValidationOutcome.HUMAN_REVIEW_REQUIRED,
            policy_references=candidate.policy_references,
            reason_codes=(f"validation_{outcome.value}",),
        )

    def _patterns(
        self,
        candidates: tuple[LearningCandidate, ...],
    ) -> tuple[PatternSignal, ...]:
        patterns: list[PatternSignal] = []
        for candidate in candidates:
            signature = self._candidate_signature(candidate)
            recurrence = self._history_provider.recurrence_count(signature)
            distinct_sources = self._history_provider.distinct_sources(signature)
            source_requirement_met = (
                distinct_sources >= 2
                if self._config.require_distinct_pattern_sources
                else True
            )
            if (
                recurrence >= self._config.minimum_pattern_occurrences
                and source_requirement_met
            ):
                patterns.append(
                    PatternSignal(
                        pattern_id=f"pattern:{signature[:16]}",
                        signature=signature,
                        recurrence_count=recurrence,
                        distinct_sources=distinct_sources,
                        window="process-local-history",
                        evidence_references=candidate.evidence_references,
                        confidence=_clamp(candidate.confidence * 0.9),
                        reason_codes=("recurrence_threshold_met",),
                    )
                )
        return tuple(patterns)

    def _calibration(self, request: LearningRequest) -> ConfidenceCalibration:
        recommendation = request.recommendation or getattr(
            request.decision_package, "recommendation", None
        )
        predicted = getattr(recommendation, "confidence", None)
        quality = request.observation_result.quality.evidence_quality_score
        if predicted is None:
            return ConfidenceCalibration(
                observed_score=request.observation_result.outcome_score,
                direction=CalibrationDirection.INCONCLUSIVE,
                evidence_count=len(request.observation_result.evidence),
                quality_adjustment=quality,
                reason_codes=("predicted_confidence_missing",),
            )
        predicted_value = _clamp(float(predicted))
        observed = request.observation_result.outcome_score
        error = abs(predicted_value - observed)
        if quality < self._config.minimum_quality:
            direction = CalibrationDirection.INCONCLUSIVE
            proposed = predicted_value
        elif error <= 0.05:
            direction = CalibrationDirection.CALIBRATED
            proposed = predicted_value
        elif predicted_value > observed:
            direction = CalibrationDirection.OVERCONFIDENT
            proposed = max(
                observed,
                predicted_value - self._config.max_single_observation_adjustment,
            )
        else:
            direction = CalibrationDirection.UNDERCONFIDENT
            proposed = min(
                observed,
                predicted_value + self._config.max_single_observation_adjustment,
            )
        return ConfidenceCalibration(
            predicted_confidence=predicted_value,
            observed_score=observed,
            calibration_error=_clamp(error),
            direction=direction,
            prior_confidence=predicted_value,
            proposed_confidence=_clamp(proposed),
            evidence_count=len(request.observation_result.evidence),
            quality_adjustment=quality,
            reason_codes=(f"calibration_{direction.value}",),
        )

    def _proposal(
        self,
        request: LearningRequest,
        candidate: LearningCandidate,
    ) -> MemoryUpdateProposal:
        return MemoryUpdateProposal(
            proposal_id=self._id_generator(),
            organization_id=request.organization_id,
            session_id=request.session_id,
            learning_candidate_id=candidate.learning_candidate_id,
            memory_type=MemoryType.EPISODIC,
            content={
                "statement": candidate.statement,
                "category": candidate.category.value,
                "relationship": candidate.relationship.value,
            },
            evidence_references=candidate.evidence_references,
            source_references=candidate.source_references,
            confidence=candidate.confidence,
            validation_status=LearningValidationOutcome.VALIDATED,
            policy_references=candidate.policy_references,
            version=1,
            retention_hint="preserve provenance",
            sensitive=False,
            reason_codes=("validated_memory_update_proposal",),
        )

    def _store_proposal(self, proposal: MemoryUpdateProposal) -> str:
        title = f"Validated learning {proposal.learning_candidate_id}"
        description = json.dumps(proposal.content, sort_keys=True, default=str)
        memory = self._memory_service.store(
            MemoryObject(
                organization_id=proposal.organization_id,
                type=proposal.memory_type,
                title=title[:200],
                description=description[:2000],
                tags=["learning", "validated", f"v{proposal.version}"],
                confidence=proposal.confidence,
                source="learning",
            )
        )
        self._event_service.dispatch(
            self._event_service.publish(
                Event(
                    event_type=EventType.MEMORY_UPDATED,
                    source="learning",
                    session_id=proposal.session_id,
                    organization_id=proposal.organization_id,
                    payload={
                        "organization_id": str(proposal.organization_id),
                        "memory_id": str(memory.id),
                    },
                    metadata=EventMetadata(correlation_id=proposal.session_id),
                    priority=EventPriority.NORMAL,
                )
            )
        )
        return str(memory.id)

    def _publish_learning(
        self,
        request: LearningRequest,
        event_type: EventType,
        payload: dict[str, str | int | float | bool | None],
    ) -> None:
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="learning",
                session_id=request.session_id,
                organization_id=request.organization_id,
                payload={
                    "organization_id": str(request.organization_id),
                    "plan_id": str(request.plan_id),
                    "execution_id": None
                    if request.execution_id is None
                    else str(request.execution_id),
                    "observation_id": str(request.observation_result.observation_id),
                    **payload,
                },
                metadata=EventMetadata(correlation_id=request.correlation_id),
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)

    def _idempotency_key(self, request: LearningRequest) -> str:
        payload = {
            "organization_id": str(request.organization_id),
            "session_id": str(request.session_id),
            "plan_id": str(request.plan_id),
            "observation_id": str(request.observation_result.observation_id),
            "execution_id": None
            if request.execution_id is None
            else str(request.execution_id),
            "policy_version": "learning-config-v1",
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _fingerprint(self, request: LearningRequest) -> str:
        data = request.model_dump(
            mode="json",
            exclude={
                "decision_package",
                "recommendation",
                "execution_result",
                "simulation_result",
                "debate_report",
            },
        )
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _execution_status(request: LearningRequest) -> str:
        status = getattr(request.execution_result, "status", "")
        return str(getattr(status, "value", status)).lower()

    def _execution_succeeded(self, request: LearningRequest) -> bool:
        result = request.execution_result
        if result is None:
            return True
        if self._execution_status(request) != "completed":
            return False
        return not bool(
            tuple(getattr(result, "failures", ()) or ())
            or tuple(getattr(result, "rollback_results", ()) or ())
        )

    @staticmethod
    def _is_positive(candidate: LearningCandidate) -> bool:
        statement_type = str(candidate.statement.get("type", "")).lower()
        outcome_status = str(candidate.statement.get("outcome_status", "")).lower()
        positive_tokens = ("success", "expectation_reached", "effective", "efficacy")
        return any(
            token in statement_type or token in outcome_status
            for token in positive_tokens
        )

    def _candidate_signature(self, candidate: LearningCandidate) -> str:
        payload = {
            "category": candidate.category.value,
            "statement": candidate.statement,
            "relationship": candidate.relationship.value,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)

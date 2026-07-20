"""Tests for ObservationResult-driven Learning loop."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from ecos.events import EventService, EventType
from ecos.execution import ExecutionMode, ExecutionResult, ExecutionStatus
from ecos.learning import (
    InMemoryLearningHistoryProvider,
    LearningConfig,
    LearningRequest,
    LearningService,
    LearningStatus,
)
from ecos.memory import MemoryService
from ecos.observation import (
    ObservationQuality,
    ObservationResult,
    ObservationSourceType,
    ObservedOutcome,
    ObservedOutcomeStatus,
)
from ecos.runtime import FakeEventBus, FakeMemoryRepository

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def observation(*, confidence: float = 0.91) -> ObservationResult:
    """Build a successful observation result with evidence."""
    org_id = uuid4()
    session_id = uuid4()
    plan_id = uuid4()
    return ObservationResult(
        observation_id=uuid4(),
        observation_request_id=uuid4(),
        organization_id=org_id,
        session_id=session_id,
        plan_id=plan_id,
        correlation_id=uuid4(),
        source_type=ObservationSourceType.DECISION_OUTCOME,
        source_id="source:1",
        status=ObservedOutcomeStatus.SUCCESSFUL,
        observed_outcomes=(
            ObservedOutcome(
                outcome_id="outcome:1",
                status=ObservedOutcomeStatus.SUCCESSFUL,
                score=1.0,
                confidence=confidence,
                evidence_references=("evidence:1",),
            ),
        ),
        comparisons=(),
        deviations=(),
        anomalies=(),
        measurements=(),
        evidence=(),
        feedback=(),
        quality=ObservationQuality(
            completeness_score=1.0,
            evidence_quality_score=1.0,
            source_reliability_score=1.0,
            timeliness_score=1.0,
            consistency_score=1.0,
            verified_measurement_ratio=1.0,
        ),
        outcome_score=1.0,
        confidence=confidence,
        started_at=NOW,
        completed_at=NOW,
        duration=0.0,
        timeline=(),
    )


def request(result: ObservationResult) -> LearningRequest:
    """Build a learning request matching the observation identity."""
    return LearningRequest(
        learning_request_id=uuid4(),
        organization_id=result.organization_id,
        session_id=result.session_id,
        plan_id=result.plan_id,
        correlation_id=result.correlation_id,
        observation_result=result,
    )


def test_learning_stores_only_validated_observation_knowledge() -> None:
    """Validated learning creates one memory with provenance."""
    repository = FakeMemoryRepository()
    event_bus = FakeEventBus()
    service = LearningService(
        MemoryService(repository),
        EventService(event_bus),
        clock=lambda: NOW,
        id_generator=lambda: UUID("00000000-0000-0000-0000-000000000001"),
    )

    result = service.process(request(observation()))

    assert result.status is LearningStatus.COMPLETED
    assert len(result.validated_candidates) == 1
    assert len(result.stored_memory_references) == 1
    assert len(repository.list()) == 1
    assert repository.list()[0].source == "learning"
    assert EventType.MEMORY_IMPROVED in [
        envelope.event.event_type for envelope in event_bus.envelopes
    ]


def test_single_learning_occurrence_is_not_a_pattern() -> None:
    """Pattern signals require configured recurrence."""
    history = InMemoryLearningHistoryProvider()
    service = LearningService(
        MemoryService(FakeMemoryRepository()),
        EventService(FakeEventBus()),
        history_provider=history,
        config=LearningConfig(minimum_pattern_occurrences=2),
        clock=lambda: NOW,
        id_generator=uuid4,
    )

    result = service.process(request(observation()))

    assert result.pattern_signals == ()


def test_failed_execution_generates_only_negative_learning() -> None:
    """Failure knowledge may be stored, but success claims are blocked."""
    repository = FakeMemoryRepository()
    service = LearningService(
        MemoryService(repository),
        EventService(FakeEventBus()),
        clock=lambda: NOW,
        id_generator=uuid4,
    )
    observed = observation().model_copy(
        update={
            "status": ObservedOutcomeStatus.FAILED,
            "outcome_score": 0.0,
            "observed_outcomes": (
                ObservedOutcome(
                    outcome_id="outcome:failed",
                    status=ObservedOutcomeStatus.FAILED,
                    score=0.0,
                    confidence=0.91,
                    evidence_references=("execution_failure:evidence",),
                ),
            ),
        }
    )
    execution_id = uuid4()
    execution = ExecutionResult(
        execution_id=execution_id,
        execution_request_id=uuid4(),
        execution_plan_id=uuid4(),
        organization_id=observed.organization_id,
        session_id=observed.session_id,
        plan_id=observed.plan_id,
        correlation_id=observed.correlation_id,
        status=ExecutionStatus.FAILED,
        fingerprint="f" * 64,
        mode=ExecutionMode.DRY_RUN,
        started_at=NOW,
        completed_at=NOW,
        duration=0.0,
        idempotency_key="failed-learning",
        authorization_id=uuid4(),
    )
    observed = observed.model_copy(update={"execution_id": execution_id})
    learning_request = LearningRequest(
        learning_request_id=uuid4(),
        organization_id=observed.organization_id,
        session_id=observed.session_id,
        plan_id=observed.plan_id,
        correlation_id=observed.correlation_id,
        execution_id=execution_id,
        observation_id=observed.observation_id,
        observation_result=observed,
        execution_result=execution,
    )

    result = service.process(learning_request)

    assert result.execution_id == execution_id
    assert result.observation_id == observed.observation_id
    assert all(
        candidate.statement.get("type") != "expectation_reached"
        for candidate in result.candidates
    )
    assert all(
        memory.description.find("expectation_reached") == -1
        for memory in repository.list()
    )


def test_pattern_requires_recurrence() -> None:
    """Second equivalent occurrence can produce a pattern signal."""
    history = InMemoryLearningHistoryProvider()
    service = LearningService(
        MemoryService(FakeMemoryRepository()),
        EventService(FakeEventBus()),
        history_provider=history,
        config=LearningConfig(minimum_pattern_occurrences=2),
        clock=lambda: NOW,
        id_generator=uuid4,
    )

    service.process(request(observation()))
    second = service.process(request(observation()))

    assert len(second.pattern_signals) == 1

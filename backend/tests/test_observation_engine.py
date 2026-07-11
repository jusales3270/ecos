"""Tests for the deterministic Observation Engine."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ecos.events import EventService, EventType
from ecos.observation import (
    ComparisonOperator,
    ExpectedOutcome,
    InMemoryFeedbackProvider,
    InMemoryMeasurementProvider,
    InMemoryObservationIdempotencyProvider,
    Measurement,
    MeasurementSource,
    MeasurementValueType,
    ObservationConfig,
    ObservationEngine,
    ObservationIdempotencyConflictError,
    ObservationRequest,
    ObservationSourceType,
    ObservedOutcomeStatus,
)
from ecos.runtime import FakeEventBus

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def service() -> tuple[ObservationEngine, FakeEventBus]:
    """Build an observation engine with injected deterministic dependencies."""
    event_bus = FakeEventBus()
    ids = iter(
        [
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
            UUID("00000000-0000-0000-0000-000000000003"),
        ]
    )
    engine = ObservationEngine(
        measurement_provider=InMemoryMeasurementProvider(),
        feedback_provider=InMemoryFeedbackProvider(),
        idempotency_provider=InMemoryObservationIdempotencyProvider(),
        event_service=EventService(event_bus),
        clock=lambda: NOW,
        id_generator=lambda: next(ids),
        config=ObservationConfig(anomaly_relative_threshold=0.1),
    )
    return engine, event_bus


def measurement(value: float, *, metric_key: str = "quality") -> Measurement:
    """Build a verified measurement."""
    return Measurement(
        measurement_id=f"m:{metric_key}:{value}",
        metric_key=metric_key,
        value=value,
        value_type=MeasurementValueType.SCORE,
        source=MeasurementSource(
            source_type=ObservationSourceType.MANUAL_MEASUREMENT,
            source_id="manual:1",
            reliability=1.0,
            verified=True,
        ),
        observed_at=NOW,
        evidence_references=(f"e:{metric_key}:{value}",),
        confidence=0.9,
        verified=True,
    )


def request(*, measurements: tuple[Measurement, ...]) -> ObservationRequest:
    """Build a valid observation request."""
    org_id = uuid4()
    return ObservationRequest(
        observation_request_id=uuid4(),
        organization_id=org_id,
        session_id=uuid4(),
        plan_id=uuid4(),
        correlation_id=uuid4(),
        source_type=ObservationSourceType.MANUAL_MEASUREMENT,
        source_id="source:1",
        expected_outcomes=(
            ExpectedOutcome(
                expected_outcome_id="expected:quality",
                name="Quality target",
                metric_key="quality",
                expected_value=0.8,
                comparison_operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                required=True,
                source_reference="plan:test",
            ),
        ),
        observed_measurements=measurements,
    )


def test_observation_compares_expected_and_observed_without_mutation() -> None:
    """A verified metric produces successful organizational observation."""
    engine, event_bus = service()
    item = measurement(0.91)
    observation_request = request(measurements=(item,))

    result = engine.observe(observation_request)

    assert result.status is ObservedOutcomeStatus.SUCCESSFUL
    assert result.outcome_score == pytest.approx(1.0)
    assert result.confidence == pytest.approx(0.9)
    assert result.measurements == (item,)
    assert observation_request.observed_measurements == (item,)
    assert [entry.sequence for entry in result.timeline] == [1, 2]
    assert EventType.OBSERVATION_COMPLETED in [
        envelope.event.event_type for envelope in event_bus.envelopes
    ]


def test_absence_of_required_data_is_not_success() -> None:
    """Missing required metrics remain inconclusive."""
    engine, event_bus = service()

    result = engine.observe(request(measurements=()))

    assert result.status is ObservedOutcomeStatus.INCONCLUSIVE
    assert result.outcome_score == 0.0
    assert result.quality.missing_metrics == ("quality",)
    assert EventType.OBSERVATION_INCONCLUSIVE in [
        envelope.event.event_type for envelope in event_bus.envelopes
    ]


def test_observation_idempotency_hit_and_conflict() -> None:
    """Same input returns the first result; same key with new data conflicts."""
    engine, _event_bus = service()
    original = request(measurements=(measurement(0.91),))

    first = engine.observe(original)
    second = engine.observe(original)

    assert second is first
    with pytest.raises(ObservationIdempotencyConflictError):
        engine.observe(
            original.model_copy(update={"observed_measurements": (measurement(0.2),)})
        )

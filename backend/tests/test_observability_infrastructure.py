"""Tests for persistent events, audit and observability infrastructure."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ecos.events import Event, EventMetadata, EventService, EventType
from ecos.observability import (
    AlertProjector,
    AuditProjector,
    EventReplayService,
    InMemoryAuditRepository,
    InMemoryEventStore,
    InMemoryObservabilityRepository,
    MetricProjector,
    RedactionPolicy,
    ReplayMode,
    SessionTraceReconstructor,
    StructuredLogProjector,
    TraceProjector,
)
from ecos.observability.exceptions import (
    ConflictingEventError,
    ConsumerNotReplaySafeError,
    MissingOrganizationError,
)
from ecos.observability.models import EventQuery, HealthStatus, MetricRecord, MetricType
from ecos.observability.repository import event_fingerprint
from ecos.runtime import FakeEventBus

ORG_ID = UUID("22222222-2222-4222-8222-222222222222")
SESSION_ID = UUID("33333333-3333-4333-8333-333333333333")


def make_event(
    event_type: EventType = EventType.SESSION_CREATED,
    *,
    payload: dict[str, object] | None = None,
) -> Event:
    """Create a canonical persisted event."""
    return Event(
        event_type=event_type,
        source="test",
        organization_id=ORG_ID,
        session_id=SESSION_ID,
        metadata=EventMetadata(correlation_id=SESSION_ID),
        payload={"organization_id": str(ORG_ID), **(payload or {})},
        created_at=datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
    )


def test_in_memory_event_store_is_append_only_idempotent_and_ordered() -> None:
    store = InMemoryEventStore()
    first = make_event()
    second = make_event(EventType.PIPELINE_STARTED)

    stored_first = store.append(first)
    assert store.append(first) == stored_first
    stored_second = store.append(second)

    assert stored_first.stored_sequence == 1
    assert stored_second.stored_sequence == 2
    assert store.get_by_id(first.event_id) == stored_first
    assert store.exists(second.event_id)
    assert [
        item.event.event_type
        for item in store.query(EventQuery(organization_id=ORG_ID, limit=10))
    ] == [EventType.SESSION_CREATED, EventType.PIPELINE_STARTED]
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_event_store_rejects_conflicting_duplicate_event_id() -> None:
    store = InMemoryEventStore()
    event = make_event()
    store.append(event)
    conflict = event.model_copy(
        update={"payload": {"organization_id": str(ORG_ID), "x": 1}}
    )

    with pytest.raises(ConflictingEventError):
        store.append(conflict)


def test_redaction_is_recursive_and_fingerprint_is_deterministic() -> None:
    policy = RedactionPolicy(max_string_length=8)
    event = make_event(
        payload={"nested": {"token": "secret-value"}, "long": "abcdefghi"}
    )
    safe = policy.redact(event.payload)

    assert safe["nested"]["token"] == "[REDACTED]"
    assert safe["long"].endswith("[TRUNCATED]")
    assert event.payload["nested"]["token"] == "secret-value"
    assert event_fingerprint(event) == event_fingerprint(event)


def test_event_service_persists_before_publishing_and_projects_records() -> None:
    bus = FakeEventBus()
    store = InMemoryEventStore()
    audit_repo = InMemoryAuditRepository()
    observability_repo = InMemoryObservabilityRepository()
    service = EventService(
        bus,
        store,
        projectors=(
            AuditProjector(audit_repo),
            MetricProjector(observability_repo),
            TraceProjector(observability_repo),
            AlertProjector(observability_repo),
            StructuredLogProjector(observability_repo),
        ),
    )

    envelope = service.publish(make_event(EventType.AUTHORIZATION_GRANTED))
    service.dispatch(envelope)

    assert store.count(EventQuery(organization_id=ORG_ID)) == 1
    assert bus.envelopes[0].event.event_id == envelope.event.event_id
    assert audit_repo.list_by_organization(ORG_ID)[0].action == "authorization_granted"
    assert observability_repo.metrics[0].metric_name == (
        "governance.authorization_granted"
    )


def test_event_service_requires_organization_for_persistent_events() -> None:
    service = EventService(FakeEventBus(), InMemoryEventStore())
    event = Event(
        event_type=EventType.SESSION_CREATED,
        source="test",
        session_id=SESSION_ID,
        metadata=EventMetadata(correlation_id=SESSION_ID),
    )

    with pytest.raises(MissingOrganizationError):
        service.publish(event)


def test_replay_read_only_and_safe_projection_do_not_repersist_events() -> None:
    store = InMemoryEventStore()
    audit_repo = InMemoryAuditRepository()
    event = make_event(EventType.SESSION_CREATED)
    store.append(event)
    projector = AuditProjector(audit_repo)
    replay = EventReplayService(store, projectors=(projector,))

    read_only = replay.replay(organization_id=ORG_ID, mode=ReplayMode.READ_ONLY)
    projected = replay.replay(organization_id=ORG_ID, mode=ReplayMode.SAFE_PROJECTION)

    assert read_only == projected
    assert store.count(EventQuery(organization_id=ORG_ID)) == 1
    assert len(audit_repo.list_by_organization(ORG_ID)) == 1


def test_replay_rejects_non_replay_safe_projector() -> None:
    class UnsafeProjector:
        replay_safe = False

        def project(self, *_: object, **__: object) -> None:
            raise AssertionError("must not run")

    store = InMemoryEventStore()
    store.append(make_event())
    replay = EventReplayService(store, projectors=(UnsafeProjector(),))

    with pytest.raises(ConsumerNotReplaySafeError):
        replay.replay(organization_id=ORG_ID, mode=ReplayMode.SAFE_PROJECTION)


def test_session_trace_reconstructor_uses_events_only() -> None:
    store = InMemoryEventStore()
    for event_type in (
        EventType.SESSION_CREATED,
        EventType.PIPELINE_STARTED,
        EventType.PIPELINE_COMPLETED,
        EventType.SESSION_COMPLETED,
    ):
        store.append(make_event(event_type))

    trace = SessionTraceReconstructor(store).reconstruct(
        organization_id=ORG_ID,
        session_id=SESSION_ID,
    )

    assert trace.final_status == "completed"
    assert trace.components == ("test",)
    assert trace.missing_transitions == ()
    assert [item["sequence"] for item in trace.timeline] == [1, 2, 3, 4]


def test_metric_validation_and_repository_health() -> None:
    repo = InMemoryObservabilityRepository()
    metric = MetricRecord(
        metric_name="context.completeness",
        metric_type=MetricType.SCORE,
        level="cognitive",
        organization_id=ORG_ID,
        component="context",
        value=0.8,
        occurred_at=datetime.now(UTC),
        source_event_id=uuid4(),
    )

    assert repo.append_metric(metric) == metric
    assert repo.health().status is HealthStatus.HEALTHY

    with pytest.raises(ValueError):
        MetricRecord(
            metric_name="bad.score",
            metric_type=MetricType.SCORE,
            level="cognitive",
            organization_id=ORG_ID,
            component="context",
            value=1.5,
            occurred_at=datetime.now(UTC),
            source_event_id=uuid4(),
        )

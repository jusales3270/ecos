"""Unit tests for ECOS Event Bus models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ecos.events import (
    Event,
    EventBus,
    EventEnvelope,
    EventHandler,
    EventMetadata,
    EventPriority,
    EventService,
    EventSubscription,
    EventType,
)

SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")


def make_metadata() -> EventMetadata:
    """Create valid event metadata for tests."""
    return EventMetadata(
        correlation_id=uuid4(),
        causation_id=uuid4(),
        attributes={"source": "unit-test"},
    )


def make_event() -> Event:
    """Create a valid event for tests."""
    return Event(
        event_type=EventType.SESSION_CREATED,
        source="session-manager",
        session_id=SESSION_ID,
        payload={"status": "CREATED"},
        metadata=make_metadata(),
        priority=EventPriority.NORMAL,
    )


def make_handler() -> EventHandler:
    """Create a valid event handler descriptor for tests."""
    return EventHandler(
        name="session-handler",
        event_types=[EventType.SESSION_CREATED, EventType.SESSION_UPDATED],
    )


def make_subscription() -> EventSubscription:
    """Create a valid event subscription for tests."""
    return EventSubscription(
        handler=make_handler(),
        event_types=[EventType.SESSION_CREATED],
    )


def make_envelope() -> EventEnvelope:
    """Create a valid event envelope for tests."""
    return EventEnvelope(event=make_event(), headers={"schema": "v1"})


def test_event_type_values() -> None:
    """EventType exposes all supported event categories."""
    assert {event_type.value for event_type in EventType} == {
        "SESSION_CREATED",
        "SESSION_UPDATED",
        "SESSION_COMPLETED",
        "MEMORY_UPDATED",
        "CONTEXT_CREATED",
        "REASONING_STARTED",
        "REASONING_COMPLETED",
        "SPECIALIST_CONTRIBUTED",
        "DEBATE_STARTED",
        "DEBATE_COMPLETED",
        "SIMULATION_STARTED",
        "SIMULATION_COMPLETED",
        "RECOMMENDATION_STARTED",
        "RECOMMENDATION_CREATED",
        "EXECUTION_STARTED",
        "EXECUTION_COMPLETED",
        "LEARNING_STARTED",
        "LEARNING_VALIDATED",
        "LEARNING_COMPLETED",
    }


def test_event_priority_values() -> None:
    """EventPriority exposes all supported event priorities."""
    assert {priority.value for priority in EventPriority} == {
        "LOW",
        "NORMAL",
        "HIGH",
        "CRITICAL",
    }


def test_event_metadata_validates_attributes() -> None:
    """EventMetadata accepts typed attributes and rejects blank keys."""
    metadata = make_metadata()

    assert metadata.correlation_id is not None
    assert metadata.causation_id is not None
    assert metadata.attributes == {"source": "unit-test"}

    with pytest.raises(
        ValidationError,
        match="metadata attribute keys cannot be blank",
    ):
        EventMetadata(attributes={" ": "invalid"})


def test_event_contains_required_architecture_fields() -> None:
    """Event contains the required Event Bus architecture fields."""
    event = make_event()

    assert isinstance(event.id, UUID)
    assert event.event_type is EventType.SESSION_CREATED
    assert event.source == "session-manager"
    assert event.session_id == SESSION_ID
    assert event.payload == {"status": "CREATED"}
    assert event.metadata.attributes == {"source": "unit-test"}
    assert event.priority is EventPriority.NORMAL
    assert event.created_at.tzinfo is UTC


def test_event_validates_source_payload_and_created_at() -> None:
    """Event rejects blank source, blank payload keys, and non-UTC timestamps."""
    with pytest.raises(ValidationError):
        Event(event_type=EventType.SESSION_CREATED, source=" ")

    with pytest.raises(ValidationError, match="payload keys cannot be blank"):
        Event(event_type=EventType.SESSION_CREATED, source="session", payload={"": 1})

    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        Event(
            event_type=EventType.SESSION_CREATED,
            source="session",
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )

    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        Event(
            event_type=EventType.SESSION_CREATED,
            source="session",
            created_at=datetime(
                2026,
                1,
                1,
                12,
                0,
                0,
                tzinfo=timezone(timedelta(hours=-3)),
            ),
        )


def test_event_envelope_validates_event_and_headers() -> None:
    """EventEnvelope carries an event and validates header keys."""
    envelope = make_envelope()

    assert isinstance(envelope.id, UUID)
    assert envelope.event.event_type is EventType.SESSION_CREATED
    assert envelope.headers == {"schema": "v1"}
    assert envelope.created_at.tzinfo is UTC

    with pytest.raises(ValidationError, match="header keys cannot be blank"):
        EventEnvelope(event=make_event(), headers={" ": "invalid"})


def test_event_handler_validates_name_and_event_types() -> None:
    """EventHandler validates handler identity and duplicate event types."""
    handler = make_handler()

    assert isinstance(handler.id, UUID)
    assert handler.name == "session-handler"
    assert handler.event_types == [EventType.SESSION_CREATED, EventType.SESSION_UPDATED]
    assert handler.active is True

    with pytest.raises(ValidationError):
        EventHandler(name=" ")

    with pytest.raises(ValidationError, match="handler event types must be unique"):
        EventHandler(
            name="duplicate-handler",
            event_types=[EventType.SESSION_CREATED, EventType.SESSION_CREATED],
        )


def test_event_subscription_validates_handler_event_types_and_active() -> None:
    """EventSubscription validates handler and subscribed event types."""
    subscription = make_subscription()

    assert isinstance(subscription.id, UUID)
    assert subscription.handler.name == "session-handler"
    assert subscription.event_types == [EventType.SESSION_CREATED]
    assert subscription.active is True

    with pytest.raises(
        ValidationError,
        match="subscription event types cannot be empty",
    ):
        EventSubscription(handler=make_handler(), event_types=[])

    with pytest.raises(
        ValidationError,
        match="subscription event types must be unique",
    ):
        EventSubscription(
            handler=make_handler(),
            event_types=[EventType.SESSION_CREATED, EventType.SESSION_CREATED],
        )


class NotImplementedEventBus(EventBus):
    """Concrete test bus that exercises abstract NotImplementedError paths."""

    def publish(self, event: Event) -> EventEnvelope:
        """Publish through the abstract interface."""
        return super().publish(event)

    def subscribe(self, subscription: EventSubscription) -> EventSubscription:
        """Subscribe through the abstract interface."""
        return super().subscribe(subscription)

    def unsubscribe(self, subscription_id: UUID) -> None:
        """Unsubscribe through the abstract interface."""
        super().unsubscribe(subscription_id)

    def dispatch(self, envelope: EventEnvelope) -> None:
        """Dispatch through the abstract interface."""
        super().dispatch(envelope)


def test_event_bus_interface_methods_raise_not_implemented() -> None:
    """EventBus abstract operations intentionally have no implementation."""
    bus = NotImplementedEventBus()
    event = make_event()
    subscription = make_subscription()
    envelope = make_envelope()

    with pytest.raises(NotImplementedError):
        bus.publish(event)

    with pytest.raises(NotImplementedError):
        bus.subscribe(subscription)

    with pytest.raises(NotImplementedError):
        bus.unsubscribe(subscription.id)

    with pytest.raises(NotImplementedError):
        bus.dispatch(envelope)


class TestEventBus(EventBus):
    """Test double used to verify EventService delegation only."""

    def __init__(self) -> None:
        """Initialize the test double call history."""
        self.published: list[Event] = []
        self.subscriptions: list[EventSubscription] = []
        self.unsubscribed: list[UUID] = []
        self.dispatched: list[EventEnvelope] = []

    def publish(self, event: Event) -> EventEnvelope:
        """Record publication and return an envelope."""
        self.published.append(event)
        return EventEnvelope(event=event, headers={"published": True})

    def subscribe(self, subscription: EventSubscription) -> EventSubscription:
        """Record subscription."""
        self.subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription_id: UUID) -> None:
        """Record unsubscription."""
        self.unsubscribed.append(subscription_id)

    def dispatch(self, envelope: EventEnvelope) -> None:
        """Record dispatch."""
        self.dispatched.append(envelope)


def test_event_service_delegates_exclusively_to_event_bus() -> None:
    """EventService delegates publish, subscribe, unsubscribe, and dispatch."""
    bus = TestEventBus()
    service = EventService(bus)
    event = make_event()
    subscription = make_subscription()

    published = service.publish(event)
    subscribed = service.subscribe(subscription)
    service.dispatch(published)
    service.unsubscribe(subscription.id)

    assert published.event == event
    assert published.headers == {"published": True}
    assert subscribed == subscription
    assert bus.published == [event]
    assert bus.subscriptions == [subscription]
    assert bus.dispatched == [published]
    assert bus.unsubscribed == [subscription.id]

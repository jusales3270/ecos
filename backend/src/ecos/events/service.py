"""Service layer for the ECOS Event Bus architecture."""

from uuid import UUID

from ecos.events.bus import EventBus
from ecos.events.models import Event, EventEnvelope, EventSubscription


class EventService:
    """Coordinates event operations through an event bus abstraction only."""

    def __init__(self, event_bus: EventBus) -> None:
        """Initialize the service with an event bus abstraction."""
        self._event_bus = event_bus

    def publish(self, event: Event) -> EventEnvelope:
        """Publish an event through the event bus abstraction."""
        return self._event_bus.publish(event)

    def subscribe(self, subscription: EventSubscription) -> EventSubscription:
        """Subscribe through the event bus abstraction."""
        return self._event_bus.subscribe(subscription)

    def unsubscribe(self, subscription_id: UUID) -> None:
        """Unsubscribe through the event bus abstraction."""
        self._event_bus.unsubscribe(subscription_id)

    def dispatch(self, envelope: EventEnvelope) -> None:
        """Dispatch an event envelope through the event bus abstraction."""
        self._event_bus.dispatch(envelope)

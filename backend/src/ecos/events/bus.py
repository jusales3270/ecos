"""Event Bus interface for ECOS module communication."""

from abc import ABC, abstractmethod
from uuid import UUID

from ecos.events.models import Event, EventEnvelope, EventSubscription


class EventBus(ABC):
    """Abstract event bus interface for decoupled module communication."""

    @abstractmethod
    def publish(self, event: Event) -> EventEnvelope:
        """Publish an event to the bus."""
        raise NotImplementedError

    @abstractmethod
    def subscribe(self, subscription: EventSubscription) -> EventSubscription:
        """Subscribe a handler to event types."""
        raise NotImplementedError

    @abstractmethod
    def unsubscribe(self, subscription_id: UUID) -> None:
        """Unsubscribe a handler from the bus."""
        raise NotImplementedError

    @abstractmethod
    def dispatch(self, envelope: EventEnvelope) -> None:
        """Dispatch an event envelope to matching handlers."""
        raise NotImplementedError

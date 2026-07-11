"""Service layer for the ECOS Event Bus architecture."""

from uuid import UUID

from ecos.events.bus import EventBus
from ecos.events.models import Event, EventEnvelope, EventMetadata, EventSubscription
from ecos.observability.exceptions import (
    MissingCorrelationError,
    MissingOrganizationError,
    ProjectorFailedError,
)
from ecos.observability.redaction import RedactionPolicy, default_redaction_policy
from ecos.observability.repository import EventStore


class EventService:
    """Validate, persist, project and publish immutable events."""

    def __init__(
        self,
        event_bus: EventBus,
        event_store: EventStore | None = None,
        *,
        projectors: tuple[object, ...] = (),
        redaction_policy: RedactionPolicy = default_redaction_policy,
    ) -> None:
        """Initialize the service with an event bus abstraction."""
        self._event_bus = event_bus
        self._event_store = event_store
        self._projectors = projectors
        self._redaction_policy = redaction_policy
        projector_ids: set[str] = set()
        for projector in projectors:
            projector_id = str(getattr(projector, "projector_id", projector))
            if projector_id in projector_ids:
                raise ProjectorFailedError(f"duplicate projector: {projector_id}")
            projector_ids.add(projector_id)

    def publish(self, event: Event) -> EventEnvelope:
        """Persist an event before publishing it through the bus."""
        safe_event = self._safe_event(event)
        stored_sequence: int | None = None
        if self._event_store is not None:
            self._validate_persistent_event(safe_event)
            stored = self._event_store.append(safe_event)
            stored_sequence = stored.stored_sequence
            self._project(safe_event, stored_sequence)
        return self._event_bus.publish(safe_event)

    def subscribe(self, subscription: EventSubscription) -> EventSubscription:
        """Subscribe through the event bus abstraction."""
        return self._event_bus.subscribe(subscription)

    def unsubscribe(self, subscription_id: UUID) -> None:
        """Unsubscribe through the event bus abstraction."""
        self._event_bus.unsubscribe(subscription_id)

    def dispatch(self, envelope: EventEnvelope) -> None:
        """Dispatch an event envelope through the event bus abstraction."""
        self._event_bus.dispatch(envelope)

    def _safe_event(self, event: Event) -> Event:
        payload = self._redaction_policy.redact(event.payload)
        metadata_attributes = self._redaction_policy.redact(event.metadata.attributes)
        metadata = EventMetadata(
            correlation_id=event.metadata.correlation_id,
            causation_id=event.metadata.causation_id,
            attributes=metadata_attributes,
        )
        return event.model_copy(update={"payload": payload, "metadata": metadata})

    def _validate_persistent_event(self, event: Event) -> None:
        if event.organization_id is None:
            raise MissingOrganizationError(
                f"organization_id is required for event {event.event_type.value}"
            )
        if event.session_id is not None and event.correlation_id is None:
            raise MissingCorrelationError(
                f"correlation_id is required for event {event.event_type.value}"
            )

    def _project(self, event: Event, stored_sequence: int) -> None:
        for projector in self._projectors:
            try:
                projector.project(event, stored_sequence=stored_sequence)
            except Exception as error:
                projector_id = str(getattr(projector, "projector_id", projector))
                raise ProjectorFailedError(
                    f"projector failed: {projector_id}",
                    details={"event_id": str(event.event_id)},
                ) from error

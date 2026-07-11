"""Read-only event replay and session trace reconstruction services."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from ecos.events.models import EventType
from ecos.observability.exceptions import ConsumerNotReplaySafeError, InvalidReplayError
from ecos.observability.models import EventQuery, SessionTrace, StoredEvent
from ecos.observability.repository import EventStore


class ReplayMode(StrEnum):
    READ_ONLY = "read_only"
    SAFE_PROJECTION = "safe_projection"


class EventReplayService:
    """Replay immutable events without mutating historical event storage."""

    def __init__(
        self, event_store: EventStore, projectors: tuple[object, ...] = ()
    ) -> None:
        self._event_store = event_store
        self._projectors = projectors

    def replay(
        self,
        *,
        organization_id: UUID,
        mode: ReplayMode = ReplayMode.READ_ONLY,
        session_id: UUID | None = None,
        correlation_id: UUID | None = None,
        event_types: tuple[str, ...] = (),
        sequence_from: int | None = None,
        sequence_to: int | None = None,
        limit: int = 100,
    ) -> list[StoredEvent]:
        """Replay events in deterministic order under an organization scope."""
        if (
            sequence_from is not None
            and sequence_to is not None
            and sequence_from > sequence_to
        ):
            raise InvalidReplayError("invalid replay sequence range")
        events = self._event_store.query(
            EventQuery(
                organization_id=organization_id,
                session_id=session_id,
                correlation_id=correlation_id,
                event_types=event_types,
                sequence_from=sequence_from,
                sequence_to=sequence_to,
                limit=limit,
            )
        )
        if any(item.event.organization_id != organization_id for item in events):
            raise InvalidReplayError(
                "replay returned events outside organization scope"
            )
        if mode is ReplayMode.READ_ONLY:
            return events
        for projector in self._projectors:
            if not getattr(projector, "replay_safe", False):
                raise ConsumerNotReplaySafeError("projector is not replay-safe")
            for stored in events:
                projector.project(
                    stored.event,
                    stored_sequence=stored.stored_sequence,
                    is_replay=True,
                )
        return events


class SessionTraceReconstructor:
    """Reconstruct a read-only Session timeline from persisted events."""

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    def reconstruct(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        limit: int = 1000,
    ) -> SessionTrace:
        events = self._event_store.list_by_session(
            organization_id,
            session_id,
            limit=limit,
        )
        components = tuple(sorted({item.event.source_component for item in events}))
        stages = tuple(
            sorted(
                {
                    str(item.event.payload["stage_id"])
                    for item in events
                    if item.event.payload.get("stage_id") is not None
                }
            )
        )
        timeline = tuple(
            {
                "sequence": item.stored_sequence,
                "event_id": str(item.event.event_id),
                "event_type": item.event.event_type.value,
                "component": item.event.source_component,
                "occurred_at": item.event.occurred_at.isoformat(),
            }
            for item in events
        )
        started = events[0].event.occurred_at if events else None
        completed_events = [
            item
            for item in events
            if item.event.event_type
            in {EventType.SESSION_COMPLETED, EventType.PIPELINE_COMPLETED}
        ]
        failed_events = [
            item
            for item in events
            if item.event.event_type
            in {
                EventType.PIPELINE_FAILED,
                EventType.ENGINE_FAILED,
                EventType.EXECUTION_FAILED,
            }
        ]
        completed = completed_events[-1].event.occurred_at if completed_events else None
        final_status = (
            "completed" if completed_events and not failed_events else "incomplete"
        )
        if failed_events:
            final_status = "failed"
        duration = None
        if started is not None and completed is not None:
            duration = max((completed - started).total_seconds(), 0.0)
        missing: list[str] = []
        types = {item.event.event_type for item in events}
        if (
            EventType.SESSION_CREATED in types
            and EventType.SESSION_COMPLETED not in types
        ):
            missing.append("SESSION_COMPLETED")
        if EventType.PIPELINE_STARTED in types and not (
            {EventType.PIPELINE_COMPLETED, EventType.PIPELINE_FAILED} & types
        ):
            missing.append("PIPELINE_FINAL")
        return SessionTrace(
            organization_id=organization_id,
            session_id=session_id,
            correlation_id=events[0].event.correlation_id if events else None,
            events=tuple(events),
            components=components,
            stages=stages,
            timeline=timeline,
            started_at=started,
            completed_at=completed,
            duration=duration,
            final_status=final_status,
            failures=tuple(
                {
                    "event_id": str(item.event.event_id),
                    "type": item.event.event_type.value,
                }
                for item in failed_events
            ),
            approvals=tuple(
                {
                    "event_id": str(item.event.event_id),
                    "type": item.event.event_type.value,
                }
                for item in events
                if item.event.event_type.name.startswith("APPROVAL")
                or item.event.event_type
                in {EventType.AUTHORIZATION_GRANTED, EventType.AUTHORIZATION_DENIED}
            ),
            executions=tuple(
                {
                    "event_id": str(item.event.event_id),
                    "type": item.event.event_type.value,
                }
                for item in events
                if item.event.source_component == "execution"
            ),
            observations=tuple(
                {
                    "event_id": str(item.event.event_id),
                    "type": item.event.event_type.value,
                }
                for item in events
                if item.event.source_component == "observation"
            ),
            learning=tuple(
                {
                    "event_id": str(item.event.event_id),
                    "type": item.event.event_type.value,
                }
                for item in events
                if item.event.source_component == "learning"
            ),
            missing_transitions=tuple(missing),
        )

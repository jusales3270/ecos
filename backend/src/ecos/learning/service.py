"""Deterministic Learning Engine application service."""

from ecos.events import Event, EventPriority, EventService, EventType
from ecos.memory import MemoryObject, MemoryService

from .models import LearningObject, LearningValidationStatus


class LearningService:
    """Validate candidates and exclusively coordinate permanent memory writes."""

    def __init__(
        self, memory_service: MemoryService, event_service: EventService
    ) -> None:
        self._memory_service = memory_service
        self._event_service = event_service

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

    def _publish(
        self,
        event_type: EventType,
        candidate: LearningObject,
        payload: dict[str, str | bool | None],
    ) -> None:
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="learning",
                session_id=candidate.session_id,
                payload=payload,
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)

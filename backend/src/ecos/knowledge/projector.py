"""Replay-safe event projector for Knowledge Graph facts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid5

from ecos.events import Event, EventType
from ecos.knowledge.exceptions import ConflictingProjectionError, KnowledgeGraphError
from ecos.knowledge.models import (
    KnowledgeEntity,
    KnowledgeEntityType,
    KnowledgeRelationship,
    KnowledgeRelationshipType,
    KnowledgeStatus,
    stable_fingerprint,
)
from ecos.knowledge.service import KnowledgeGraphService

Clock = Callable[[], datetime]
_NAMESPACE = UUID("22222222-3333-4444-8555-666666666666")


class KnowledgeProjector:
    """Project valid immutable events into graph entities and explicit links."""

    projector_id = "knowledge"
    replay_safe = True

    def __init__(
        self,
        service: KnowledgeGraphService,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._service = service
        self._clock = clock or (lambda: datetime.now(UTC))
        self._seen: dict[str, str] = {}

    def project(
        self, event: Event, *, stored_sequence: int = 0, is_replay: bool = False
    ) -> None:
        del stored_sequence, is_replay
        if event.organization_id is None:
            return
        key = f"{event.event_id}:knowledge"
        fingerprint = stable_fingerprint(event.model_dump(mode="json"))
        existing = self._seen.get(key)
        if existing is not None:
            if existing != fingerprint:
                raise ConflictingProjectionError("projection idempotency conflict")
            return
        if event.event_type in {
            EventType.LEARNING_REJECTED,
            EventType.LEARNING_FAILED,
            EventType.OBSERVATION_FAILED,
            EventType.EXECUTION_FAILED,
        }:
            return
        projected = False
        if event.event_type is EventType.SESSION_CREATED:
            self._entity(event, KnowledgeEntityType.SESSION, "session_id")
            projected = True
        elif event.event_type is EventType.RECOMMENDATION_CREATED:
            self._entity(event, KnowledgeEntityType.RECOMMENDATION, "recommendation_id")
            projected = True
        elif event.event_type is EventType.EXECUTION_COMPLETED:
            self._entity(event, KnowledgeEntityType.EXECUTION, "execution_id")
            projected = True
        elif event.event_type is EventType.OBSERVATION_COMPLETED:
            self._entity(event, KnowledgeEntityType.OBSERVATION, "observation_id")
            projected = True
        elif event.event_type is EventType.LEARNING_VALIDATED:
            self._entity(event, KnowledgeEntityType.LEARNING, "learning_candidate_id")
            projected = True
        elif event.event_type is EventType.MEMORY_UPDATED:
            self._entity(event, KnowledgeEntityType.MEMORY, "memory_id")
            projected = True
        elif event.event_type is EventType.POLICY_VALIDATED:
            self._entity(event, KnowledgeEntityType.POLICY, "policy_id")
            projected = True
        if projected:
            self._service._publish(
                EventType.KNOWLEDGE_PROJECTION_COMPLETED,
                event.organization_id,
                {
                    "source_event_id": str(event.event_id),
                    "projection_type": "knowledge",
                },
                session_id=event.session_id,
                correlation_id=event.correlation_id,
            )
            self._seen[key] = fingerprint

    def _entity(
        self, event: Event, entity_type: KnowledgeEntityType, payload_key: str
    ) -> None:
        now = self._clock()
        raw_id = (
            event.payload.get(payload_key) or event.payload.get("id") or event.event_id
        )
        entity_id = f"{entity_type.value}:{raw_id}"
        name = f"{entity_type.value} {raw_id}"
        entity = KnowledgeEntity(
            entity_id=entity_id,
            organization_id=event.organization_id,  # type: ignore[arg-type]
            entity_type=entity_type,
            name=name,
            description=None,
            confidence=0.7,
            importance=0.5,
            status=KnowledgeStatus.ACTIVE,
            source_references=(f"event:{event.event_id}",),
            evidence_references=tuple(
                str(item) for item in event.payload.get("evidence_references", ()) or ()
            ),
            attributes={
                "source_event_id": str(event.event_id),
                "session_id": None
                if event.session_id is None
                else str(event.session_id),
                "correlation_id": None
                if event.correlation_id is None
                else str(event.correlation_id),
                "identity_event_id": str(raw_id),
            },
            valid_from=event.occurred_at,
            created_at=now,
            updated_at=now,
            reason_codes=("projected_from_event",),
        )
        self._service.append_entity(entity)
        if (
            event.session_id is not None
            and entity_type is not KnowledgeEntityType.SESSION
        ):
            session_entity_id = f"session:{event.session_id}"
            try:
                self._service.append_relationship(
                    KnowledgeRelationship(
                        relationship_id=str(
                            uuid5(
                                _NAMESPACE, f"{session_entity_id}:{entity_id}:generated"
                            )
                        ),
                        organization_id=entity.organization_id,
                        source_entity_id=session_entity_id,
                        target_entity_id=entity_id,
                        relationship_type=KnowledgeRelationshipType.GENERATED,
                        confidence=0.7,
                        weight=0.6,
                        source_references=(f"event:{event.event_id}",),
                        evidence_references=entity.evidence_references,
                        valid_from=event.occurred_at,
                        created_at=now,
                        updated_at=now,
                        reason_codes=("explicit_event_session_link",),
                    )
                )
            except KnowledgeGraphError:
                # Session entity may not have been projected yet.
                return

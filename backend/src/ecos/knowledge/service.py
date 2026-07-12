"""Application services for Knowledge Graph operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.knowledge.models import (
    GraphPath,
    KnowledgeContextExpansion,
    KnowledgeContextExpansionRequest,
    KnowledgeEntity,
    KnowledgeQueryResult,
    KnowledgeRelationship,
    KnowledgeRelationshipType,
    KnowledgeStatus,
    RepositoryHealth,
    SemanticQuery,
)
from ecos.knowledge.repository import KnowledgeGraphRepository
from ecos.knowledge.search import SemanticSearchProvider

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]


class KnowledgeGraphService:
    """Public Knowledge Graph service using injected repository and providers."""

    def __init__(
        self,
        repository: KnowledgeGraphRepository,
        *,
        semantic_search_provider: SemanticSearchProvider | None = None,
        event_service: EventService | None = None,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._semantic_search_provider = semantic_search_provider
        self._event_service = event_service
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_generator = id_generator or uuid4

    def append_entity(self, entity: KnowledgeEntity) -> KnowledgeEntity:
        created = self._repository.append_entity(entity)
        event_type = (
            EventType.KNOWLEDGE_ENTITY_CREATED
            if created.version == 1
            else EventType.KNOWLEDGE_ENTITY_VERSIONED
        )
        if created.status is KnowledgeStatus.ARCHIVED:
            event_type = EventType.KNOWLEDGE_ENTITY_ARCHIVED
        elif created.status is KnowledgeStatus.MERGED:
            event_type = EventType.KNOWLEDGE_ENTITY_MERGED
        self._publish(
            event_type,
            created.organization_id,
            {
                "entity_id": created.entity_id,
                "entity_type": created.entity_type.value,
                "status": created.status.value,
                "version": created.version,
            },
        )
        return created

    def append_relationship(
        self, relationship: KnowledgeRelationship
    ) -> KnowledgeRelationship:
        created = self._repository.append_relationship(relationship)
        event_type = (
            EventType.KNOWLEDGE_RELATIONSHIP_CREATED
            if created.version == 1
            else EventType.KNOWLEDGE_RELATIONSHIP_VERSIONED
        )
        if created.status is KnowledgeStatus.ARCHIVED:
            event_type = EventType.KNOWLEDGE_RELATIONSHIP_ARCHIVED
        self._publish(
            event_type,
            created.organization_id,
            {
                "relationship_id": created.relationship_id,
                "relationship_type": created.relationship_type.value,
                "source_entity_id": created.source_entity_id,
                "target_entity_id": created.target_entity_id,
                "status": created.status.value,
                "version": created.version,
            },
        )
        self._publish(
            EventType.KNOWLEDGE_LINKED,
            created.organization_id,
            {
                "relationship_id": created.relationship_id,
                "source_entity_id": created.source_entity_id,
                "target_entity_id": created.target_entity_id,
            },
        )
        return created

    def search(self, query: SemanticQuery):
        if self._semantic_search_provider is None:
            return []
        started = perf_counter()
        results = self._semantic_search_provider.search(query)
        self._publish(
            EventType.SEMANTIC_SEARCH_COMPLETED,
            query.organization_id,
            {
                "query_id": str(query.query_id),
                "result_count": len(results),
                "duration_seconds": round(perf_counter() - started, 6),
            },
        )
        return results

    def neighbors(self, organization_id: UUID, entity_id: str):
        return self._repository.neighbors(organization_id, entity_id)

    def dependency_chain(
        self, organization_id: UUID, entity_id: str, *, max_depth: int = 5
    ) -> list[GraphPath]:
        return self._repository.dependency_chain(
            organization_id, entity_id, max_depth=max_depth
        )

    def impact_chain(
        self, organization_id: UUID, entity_id: str, *, max_depth: int = 5
    ) -> list[GraphPath]:
        return self._repository.impact_chain(
            organization_id, entity_id, max_depth=max_depth
        )

    def query_related(
        self,
        organization_id: UUID,
        entity_id: str,
        relationship_types: list[KnowledgeRelationshipType],
        *,
        max_depth: int = 3,
    ) -> KnowledgeQueryResult:
        paths = self._repository.paths(
            organization_id,
            entity_id,
            "*",
            relationship_types=relationship_types,
            max_depth=max_depth,
            max_paths=50,
        )
        entity_ids = sorted({item for path in paths for item in path.entities})
        entities, relationships = self._repository.subgraph(organization_id, entity_ids)
        return KnowledgeQueryResult(
            entities=tuple(entities),
            relationships=tuple(relationships),
            paths=tuple(paths),
            references=tuple(
                sorted(
                    {
                        reference
                        for entity in entities
                        for reference in entity.evidence_references
                    }
                )
            ),
        )

    def health(self) -> RepositoryHealth:
        return self._repository.health()

    def _publish(
        self,
        event_type: EventType,
        organization_id: UUID,
        payload: dict[str, str | int | float | bool | None],
        *,
        session_id: UUID | None = None,
        correlation_id: UUID | None = None,
    ) -> None:
        if self._event_service is None:
            return
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="knowledge",
                organization_id=organization_id,
                session_id=session_id,
                payload={"organization_id": str(organization_id), **payload},
                metadata=EventMetadata(correlation_id=correlation_id),
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)


class KnowledgeContextExpander:
    """Produce bounded graph candidates for Context Engine consumption."""

    def __init__(
        self,
        service: KnowledgeGraphService,
        repository: KnowledgeGraphRepository,
    ) -> None:
        self._service = service
        self._repository = repository

    def expand(
        self, request: KnowledgeContextExpansionRequest
    ) -> KnowledgeContextExpansion:
        self._service._publish(
            EventType.CONTEXT_EXPANSION_STARTED,
            request.organization_id,
            {
                "session_id": str(request.session_id),
                "seed_count": len(request.seed_entity_ids),
                "max_depth": request.max_depth,
            },
            session_id=request.session_id,
            correlation_id=request.correlation_id,
        )
        semantic_results = (
            tuple(self._service.search(request.semantic_query))
            if request.semantic_query is not None
            else ()
        )
        ordered_ids: list[str] = []
        for entity_id in request.seed_entity_ids:
            if entity_id not in ordered_ids:
                ordered_ids.append(entity_id)
        for result in semantic_results:
            if result.entity.entity_id not in ordered_ids:
                ordered_ids.append(result.entity.entity_id)
        paths: list[GraphPath] = []
        for entity_id in list(ordered_ids):
            paths.extend(
                self._repository.paths(
                    request.organization_id,
                    entity_id,
                    "*",
                    relationship_types=list(request.allowed_relationship_types) or None,
                    max_depth=request.max_depth,
                    max_paths=request.context_budget,
                    min_confidence=request.min_confidence,
                    as_of=request.as_of,
                )
            )
        for path in paths:
            for entity_id in path.entities:
                if entity_id not in ordered_ids:
                    ordered_ids.append(entity_id)
        truncated = len(ordered_ids) > request.max_entities
        selected_ids = ordered_ids[: request.max_entities]
        excluded = tuple(ordered_ids[request.max_entities :])
        entities, relationships = self._repository.subgraph(
            request.organization_id, selected_ids
        )
        relationships = [
            relationship
            for relationship in relationships
            if relationship.confidence >= request.min_confidence
        ][: request.context_budget]
        confidence_values = [entity.confidence for entity in entities] + [
            relationship.confidence for relationship in relationships
        ]
        graph_confidence = (
            round(sum(confidence_values) / len(confidence_values), 4)
            if confidence_values
            else 0.0
        )
        warnings = []
        if not entities:
            warnings.append("knowledge_graph_empty")
        if any(value < 0.5 for value in confidence_values):
            warnings.append("low_confidence_graph_context")
        expansion = KnowledgeContextExpansion(
            selected_entities=tuple(entities),
            selected_relationships=tuple(relationships),
            graph_paths=tuple(paths[: request.context_budget]),
            semantic_results=semantic_results,
            expanded_entity_ids=tuple(selected_ids),
            excluded_entities=excluded,
            truncation_applied=truncated,
            completeness_signal="empty" if not entities else "partial",
            graph_confidence=graph_confidence,
            warnings=tuple(warnings),
            reason_codes=("bounded_context_expansion",),
            safe_metadata={
                "context_budget": request.context_budget,
                "max_entities": request.max_entities,
            },
        )
        self._service._publish(
            EventType.CONTEXT_EXPANDED,
            request.organization_id,
            {
                "session_id": str(request.session_id),
                "entity_count": len(expansion.selected_entities),
                "relationship_count": len(expansion.selected_relationships),
                "truncated": expansion.truncation_applied,
                "graph_confidence": expansion.graph_confidence,
            },
            session_id=request.session_id,
            correlation_id=request.correlation_id,
        )
        return expansion

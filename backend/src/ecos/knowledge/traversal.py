"""Typed graph traversal helpers."""

from uuid import UUID

from ecos.knowledge.models import (
    DEPENDENCY_RELATIONSHIP_TYPES,
    IMPACT_RELATIONSHIP_TYPES,
    GraphPath,
    KnowledgeEntity,
    KnowledgeRelationship,
    KnowledgeRelationshipType,
)
from ecos.knowledge.repository import KnowledgeGraphRepository


class KnowledgeTraversalService:
    """Deterministic bounded graph traversal façade."""

    def __init__(self, repository: KnowledgeGraphRepository) -> None:
        self._repository = repository

    def neighbors(
        self,
        organization_id: UUID,
        entity_id: str,
        *,
        direction: str = "both",
        relationship_types: list[KnowledgeRelationshipType] | None = None,
        max_nodes: int = 50,
        min_confidence: float = 0.0,
    ) -> tuple[list[KnowledgeEntity], list[KnowledgeRelationship]]:
        return self._repository.neighbors(
            organization_id,
            entity_id,
            direction=direction,
            relationship_types=relationship_types,
            max_nodes=max_nodes,
            min_confidence=min_confidence,
        )

    def shortest_path(
        self,
        organization_id: UUID,
        start_entity_id: str,
        end_entity_id: str,
        *,
        max_depth: int = 5,
    ) -> GraphPath | None:
        paths = self._repository.paths(
            organization_id,
            start_entity_id,
            end_entity_id,
            max_depth=max_depth,
            max_paths=1,
        )
        return paths[0] if paths else None

    def dependency_chain(
        self, organization_id: UUID, entity_id: str, *, max_depth: int = 5
    ) -> list[GraphPath]:
        return self._repository.paths(
            organization_id,
            entity_id,
            "*",
            relationship_types=list(DEPENDENCY_RELATIONSHIP_TYPES),
            max_depth=max_depth,
            max_paths=50,
        )

    def impact_chain(
        self, organization_id: UUID, entity_id: str, *, max_depth: int = 5
    ) -> list[GraphPath]:
        return self._repository.paths(
            organization_id,
            entity_id,
            "*",
            relationship_types=list(IMPACT_RELATIONSHIP_TYPES),
            max_depth=max_depth,
            max_paths=50,
        )

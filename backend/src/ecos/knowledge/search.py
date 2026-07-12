"""Deterministic structured and lexical semantic search."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from ecos.knowledge.exceptions import SemanticProviderUnavailableError
from ecos.knowledge.models import (
    KnowledgeEntity,
    KnowledgeRelationshipType,
    KnowledgeStatus,
    SemanticQuery,
    SemanticResult,
    tokenize,
)
from ecos.knowledge.repository import KnowledgeGraphRepository

Clock = Callable[[], datetime]

SEMANTIC_WEIGHTS = {
    "lexical": 0.35,
    "graph_proximity": 0.20,
    "relationship": 0.10,
    "importance": 0.10,
    "recency": 0.10,
    "confidence": 0.10,
    "organizational_relevance": 0.05,
}


class SemanticSearchProvider(ABC):
    """Provider-agnostic deterministic semantic search port."""

    @abstractmethod
    def search(self, query: SemanticQuery) -> list[SemanticResult]:
        """Return deterministic structured semantic search results."""
        raise NotImplementedError


class DeterministicSemanticSearchProvider(SemanticSearchProvider):
    """Structured lexical graph search without LLMs, embeddings or external calls."""

    def __init__(
        self,
        repository: KnowledgeGraphRepository,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        total = sum(SEMANTIC_WEIGHTS.values())
        if round(total, 6) != 1.0:
            raise SemanticProviderUnavailableError("semantic weights must sum to 1")

    def search(self, query: SemanticQuery) -> list[SemanticResult]:
        statuses = None if query.include_archived else [KnowledgeStatus.ACTIVE]
        candidates = self._repository.find_entities(
            query.organization_id,
            entity_types=list(query.entity_types) or None,
            statuses=statuses,
            tags=list(query.tags) or None,
            as_of=query.as_of,
            limit=max(query.max_results * 20, query.max_results),
        )
        results: list[SemanticResult] = []
        for entity in candidates:
            if entity.organization_id != query.organization_id:
                continue
            if entity.confidence < query.min_confidence:
                continue
            result = self._score_entity(query, entity)
            if result.semantic_score > 0.0:
                results.append(result)
        results.sort(
            key=lambda item: (
                -item.semantic_score,
                -item.entity.importance,
                item.entity.entity_id,
            )
        )
        return results[: query.max_results]

    def _score_entity(
        self, query: SemanticQuery, entity: KnowledgeEntity
    ) -> SemanticResult:
        terms = set(query.normalized_terms)
        entity_terms = tokenize(
            " ".join(
                [
                    entity.name,
                    entity.normalized_name or "",
                    entity.description or "",
                    " ".join(entity.aliases),
                    " ".join(entity.tags),
                    entity.entity_type.value,
                    _identity_safe_attributes(entity),
                ]
            )
        )
        matched_terms = tuple(sorted(terms.intersection(entity_terms)))
        matched_tags = tuple(sorted(set(query.tags).intersection(entity.tags)))
        lexical_score = _overlap(entity_terms, terms) if terms else 0.0
        if query.tags:
            lexical_score = max(lexical_score, len(matched_tags) / len(query.tags))
        if query.entity_types and entity.entity_type in query.entity_types:
            lexical_score = max(lexical_score, 0.6)
        proximity, path_reference = self._graph_proximity(query, entity.entity_id)
        relationship_score, matched_relationships = self._relationship_score(
            query.organization_id,
            entity.entity_id,
            query.relationship_types,
        )
        recency_score = self._recency(entity)
        organizational_relevance = (
            1.0 if entity.organization_id == query.organization_id else 0.0
        )
        score = (
            lexical_score * SEMANTIC_WEIGHTS["lexical"]
            + proximity * SEMANTIC_WEIGHTS["graph_proximity"]
            + relationship_score * SEMANTIC_WEIGHTS["relationship"]
            + entity.importance * SEMANTIC_WEIGHTS["importance"]
            + recency_score * SEMANTIC_WEIGHTS["recency"]
            + entity.confidence * SEMANTIC_WEIGHTS["confidence"]
            + organizational_relevance * SEMANTIC_WEIGHTS["organizational_relevance"]
        )
        if lexical_score == 0.0 and proximity == 0.0 and relationship_score == 0.0:
            score = 0.0
        return SemanticResult(
            entity=entity,
            semantic_score=round(max(0.0, min(score, 1.0)), 4),
            lexical_score=round(lexical_score, 4),
            graph_proximity_score=round(proximity, 4),
            relationship_score=round(relationship_score, 4),
            importance_score=entity.importance,
            recency_score=round(recency_score, 4),
            confidence_score=entity.confidence,
            organizational_relevance_score=organizational_relevance,
            matched_terms=matched_terms,
            matched_tags=matched_tags,
            matched_relationships=matched_relationships,
            path_reference=path_reference,
            evidence_references=entity.evidence_references,
            reason_codes=("structured_lexical_semantic_search",),
        )

    def _graph_proximity(
        self, query: SemanticQuery, entity_id: str
    ) -> tuple[float, str | None]:
        if not query.source_entity_ids:
            return 0.0, None
        best_score = 0.0
        best_path: str | None = None
        for source_id in query.source_entity_ids:
            if source_id == entity_id:
                return 1.0, None
            paths = self._repository.paths(
                query.organization_id,
                source_id,
                entity_id,
                relationship_types=list(query.relationship_types) or None,
                max_depth=query.max_depth,
                max_paths=1,
                min_confidence=query.min_confidence,
                as_of=query.as_of,
            )
            if not paths:
                continue
            score = 1.0 / (paths[0].depth + 1)
            if score > best_score:
                best_score = score
                best_path = paths[0].path_id
        return best_score, best_path

    def _relationship_score(
        self,
        organization_id: UUID,
        entity_id: str,
        relationship_types: tuple[KnowledgeRelationshipType, ...],
    ) -> tuple[float, tuple[str, ...]]:
        relationships = self._repository.find_relationships(
            organization_id,
            relationship_types=list(relationship_types) or None,
            source_entity_id=entity_id,
            statuses=[KnowledgeStatus.ACTIVE],
            limit=100,
        )
        incoming = self._repository.find_relationships(
            organization_id,
            relationship_types=list(relationship_types) or None,
            target_entity_id=entity_id,
            statuses=[KnowledgeStatus.ACTIVE],
            limit=100,
        )
        all_relationships = relationships + incoming
        if not all_relationships:
            return 0.0, ()
        score = min(len(all_relationships) / 5, 1.0)
        matched = tuple(
            sorted(
                {
                    relationship.relationship_type.value
                    for relationship in all_relationships
                }
            )
        )
        return score, matched

    def _recency(self, entity: KnowledgeEntity) -> float:
        age_days = max((self._clock() - entity.updated_at).days, 0)
        if age_days <= 30:
            return 1.0
        if age_days <= 365:
            return 0.7
        return 0.35


def _overlap(entity_terms: set[str], query_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    return len(entity_terms.intersection(query_terms)) / len(query_terms)


def _identity_safe_attributes(entity: KnowledgeEntity) -> str:
    return " ".join(
        str(value)
        for key, value in sorted(entity.attributes.items())
        if key.startswith("identity_") or key in {"domain", "namespace", "external_id"}
    )

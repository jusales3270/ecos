"""Knowledge Graph repository port and in-memory implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict, deque
from datetime import UTC, datetime
from uuid import UUID

from ecos.knowledge.exceptions import (
    ConflictingVersionError,
    DependencyCycleError,
    DuplicateRelationshipError,
    FingerprintConflictError,
    InvalidKnowledgeLimitError,
    OrganizationMismatchError,
    ReplacementCycleError,
    SourceEntityNotFoundError,
    TargetEntityNotFoundError,
)
from ecos.knowledge.models import (
    ACYCLIC_RELATIONSHIP_TYPES,
    DEPENDENCY_RELATIONSHIP_TYPES,
    IMPACT_RELATIONSHIP_TYPES,
    GraphPath,
    HealthStatus,
    KnowledgeEntity,
    KnowledgeEntityType,
    KnowledgeRelationship,
    KnowledgeRelationshipType,
    KnowledgeStatus,
    RepositoryHealth,
    stable_fingerprint,
)


class KnowledgeGraphRepository(ABC):
    """Abstract append-only persistence interface for Knowledge Graph versions."""

    @abstractmethod
    def append_entity(self, entity: KnowledgeEntity) -> KnowledgeEntity:
        """Append an immutable entity version."""
        raise NotImplementedError

    def append_entities(self, entities: list[KnowledgeEntity]) -> list[KnowledgeEntity]:
        """Append entity versions atomically where the backing store supports it."""
        return [self.append_entity(entity) for entity in entities]

    @abstractmethod
    def get_entity(
        self, organization_id: UUID, entity_id: str
    ) -> KnowledgeEntity | None:
        """Return the current entity version."""
        raise NotImplementedError

    @abstractmethod
    def get_entity_version(
        self, organization_id: UUID, entity_id: str, version: int
    ) -> KnowledgeEntity | None:
        """Return a specific entity version."""
        raise NotImplementedError

    @abstractmethod
    def get_current_entity(
        self,
        organization_id: UUID,
        entity_id: str,
        *,
        as_of: datetime | None = None,
    ) -> KnowledgeEntity | None:
        """Return the current/as_of entity version."""
        raise NotImplementedError

    @abstractmethod
    def list_entity_versions(
        self, organization_id: UUID, entity_id: str
    ) -> list[KnowledgeEntity]:
        """Return all versions for a logical entity."""
        raise NotImplementedError

    @abstractmethod
    def find_entities(
        self,
        organization_id: UUID,
        *,
        query: str | None = None,
        entity_types: list[KnowledgeEntityType] | None = None,
        statuses: list[KnowledgeStatus] | None = None,
        tags: list[str] | None = None,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeEntity]:
        """Find current/as_of entities using organization-scoped filters."""
        raise NotImplementedError

    def list_entities_by_type(
        self,
        organization_id: UUID,
        entity_type: KnowledgeEntityType,
        *,
        limit: int = 50,
    ) -> list[KnowledgeEntity]:
        return self.find_entities(
            organization_id, entity_types=[entity_type], limit=limit
        )

    def list_entities_by_tag(
        self, organization_id: UUID, tag: str, *, limit: int = 50
    ) -> list[KnowledgeEntity]:
        return self.find_entities(organization_id, tags=[tag], limit=limit)

    def list_entities_by_status(
        self, organization_id: UUID, status: KnowledgeStatus, *, limit: int = 50
    ) -> list[KnowledgeEntity]:
        return self.find_entities(organization_id, statuses=[status], limit=limit)

    def list_entities_by_source(
        self, organization_id: UUID, source_reference: str, *, limit: int = 50
    ) -> list[KnowledgeEntity]:
        entities = self.find_entities(organization_id, limit=max(limit, 1))
        return [
            entity
            for entity in entities
            if source_reference in entity.source_references
        ][:limit]

    def count_entities(self, organization_id: UUID) -> int:
        return len(self.find_entities(organization_id, limit=10000))

    @abstractmethod
    def append_relationship(
        self, relationship: KnowledgeRelationship
    ) -> KnowledgeRelationship:
        """Append an immutable relationship version."""
        raise NotImplementedError

    def append_relationships(
        self, relationships: list[KnowledgeRelationship]
    ) -> list[KnowledgeRelationship]:
        return [
            self.append_relationship(relationship) for relationship in relationships
        ]

    @abstractmethod
    def get_relationship(
        self, organization_id: UUID, relationship_id: str
    ) -> KnowledgeRelationship | None:
        """Return the current relationship version."""
        raise NotImplementedError

    @abstractmethod
    def get_relationship_version(
        self, organization_id: UUID, relationship_id: str, version: int
    ) -> KnowledgeRelationship | None:
        """Return a specific relationship version."""
        raise NotImplementedError

    @abstractmethod
    def get_current_relationship(
        self,
        organization_id: UUID,
        relationship_id: str,
        *,
        as_of: datetime | None = None,
    ) -> KnowledgeRelationship | None:
        """Return the current/as_of relationship version."""
        raise NotImplementedError

    @abstractmethod
    def list_relationship_versions(
        self, organization_id: UUID, relationship_id: str
    ) -> list[KnowledgeRelationship]:
        """Return all versions for a logical relationship."""
        raise NotImplementedError

    @abstractmethod
    def find_relationships(
        self,
        organization_id: UUID,
        *,
        relationship_types: list[KnowledgeRelationshipType] | None = None,
        statuses: list[KnowledgeStatus] | None = None,
        source_entity_id: str | None = None,
        target_entity_id: str | None = None,
        min_confidence: float = 0.0,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeRelationship]:
        """Find current/as_of relationships using organization-scoped filters."""
        raise NotImplementedError

    def list_outgoing(
        self, organization_id: UUID, entity_id: str, *, limit: int = 50
    ) -> list[KnowledgeRelationship]:
        return self.find_relationships(
            organization_id, source_entity_id=entity_id, limit=limit
        )

    def list_incoming(
        self, organization_id: UUID, entity_id: str, *, limit: int = 50
    ) -> list[KnowledgeRelationship]:
        return self.find_relationships(
            organization_id, target_entity_id=entity_id, limit=limit
        )

    def list_between(
        self, organization_id: UUID, source_entity_id: str, target_entity_id: str
    ) -> list[KnowledgeRelationship]:
        return self.find_relationships(
            organization_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            limit=100,
        )

    def list_by_type(
        self,
        organization_id: UUID,
        relationship_type: KnowledgeRelationshipType,
        *,
        limit: int = 50,
    ) -> list[KnowledgeRelationship]:
        return self.find_relationships(
            organization_id, relationship_types=[relationship_type], limit=limit
        )

    def count_relationships(self, organization_id: UUID) -> int:
        return len(self.find_relationships(organization_id, limit=10000))

    @abstractmethod
    def neighbors(
        self,
        organization_id: UUID,
        entity_id: str,
        *,
        direction: str = "both",
        relationship_types: list[KnowledgeRelationshipType] | None = None,
        max_nodes: int = 50,
        min_confidence: float = 0.0,
        as_of: datetime | None = None,
    ) -> tuple[list[KnowledgeEntity], list[KnowledgeRelationship]]:
        """Return direct graph neighbors."""
        raise NotImplementedError

    @abstractmethod
    def paths(
        self,
        organization_id: UUID,
        start_entity_id: str,
        end_entity_id: str,
        *,
        relationship_types: list[KnowledgeRelationshipType] | None = None,
        max_depth: int = 5,
        max_paths: int = 20,
        min_confidence: float = 0.0,
        as_of: datetime | None = None,
    ) -> list[GraphPath]:
        """Return bounded deterministic paths."""
        raise NotImplementedError

    def dependency_chain(
        self, organization_id: UUID, entity_id: str, *, max_depth: int = 5
    ) -> list[GraphPath]:
        return self.paths(
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
        return self.paths(
            organization_id,
            entity_id,
            "*",
            relationship_types=list(IMPACT_RELATIONSHIP_TYPES),
            max_depth=max_depth,
            max_paths=50,
        )

    def subgraph(
        self, organization_id: UUID, entity_ids: list[str]
    ) -> tuple[list[KnowledgeEntity], list[KnowledgeRelationship]]:
        entities = [
            entity
            for entity_id in sorted(set(entity_ids))
            if (entity := self.get_current_entity(organization_id, entity_id))
            is not None
        ]
        ids = {entity.entity_id for entity in entities}
        relationships = [
            relationship
            for relationship in self.find_relationships(organization_id, limit=10000)
            if relationship.source_entity_id in ids
            and relationship.target_entity_id in ids
        ]
        return entities, relationships

    @abstractmethod
    def health(self) -> RepositoryHealth:
        """Return repository health."""
        raise NotImplementedError


class InMemoryKnowledgeGraphRepository(KnowledgeGraphRepository):
    """Append-only deterministic in-memory Knowledge Graph repository."""

    def __init__(self) -> None:
        self._entities: dict[tuple[UUID, str], list[KnowledgeEntity]] = defaultdict(
            list
        )
        self._relationships: dict[tuple[UUID, str], list[KnowledgeRelationship]] = (
            defaultdict(list)
        )
        self._entity_fingerprints: dict[tuple[UUID, str], str] = {}
        self._relationship_fingerprints: dict[tuple[UUID, str], str] = {}

    def append_entity(self, entity: KnowledgeEntity) -> KnowledgeEntity:
        key = (entity.organization_id, entity.entity_id)
        versions = self._entities[key]
        existing = next(
            (item for item in versions if item.version == entity.version), None
        )
        fingerprint = _entity_content_fingerprint(entity)
        if existing is not None:
            if _entity_content_fingerprint(existing) == fingerprint:
                return existing
            raise ConflictingVersionError("entity version already exists")
        if versions and entity.version != max(item.version for item in versions) + 1:
            raise ConflictingVersionError("entity versions must be sequential")
        fp_key = (entity.organization_id, entity.identity_fingerprint)
        previous_entity_id = self._entity_fingerprints.get(fp_key)
        if previous_entity_id is not None and previous_entity_id != entity.entity_id:
            raise FingerprintConflictError(
                "identity fingerprint maps to another entity"
            )
        self._entity_fingerprints[fp_key] = entity.entity_id
        versions.append(entity)
        versions.sort(key=lambda item: item.version)
        return entity

    def get_entity(
        self, organization_id: UUID, entity_id: str
    ) -> KnowledgeEntity | None:
        return self.get_current_entity(organization_id, entity_id)

    def get_entity_version(
        self, organization_id: UUID, entity_id: str, version: int
    ) -> KnowledgeEntity | None:
        return next(
            (
                item
                for item in self._entities.get((organization_id, entity_id), [])
                if item.version == version
            ),
            None,
        )

    def get_current_entity(
        self,
        organization_id: UUID,
        entity_id: str,
        *,
        as_of: datetime | None = None,
    ) -> KnowledgeEntity | None:
        versions = self._entities.get((organization_id, entity_id), [])
        candidates = _valid_versions(versions, as_of)
        return candidates[-1] if candidates else None

    def list_entity_versions(
        self, organization_id: UUID, entity_id: str
    ) -> list[KnowledgeEntity]:
        return list(self._entities.get((organization_id, entity_id), []))

    def find_entities(
        self,
        organization_id: UUID,
        *,
        query: str | None = None,
        entity_types: list[KnowledgeEntityType] | None = None,
        statuses: list[KnowledgeStatus] | None = None,
        tags: list[str] | None = None,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeEntity]:
        _validate_page(limit, offset)
        entities = [
            entity
            for org_id, entity_id in sorted(self._entities)
            if org_id == organization_id
            if (entity := self.get_current_entity(org_id, entity_id, as_of=as_of))
            is not None
        ]
        if query:
            normalized = query.lower().strip()
            entities = [
                entity
                for entity in entities
                if normalized in entity.name.lower()
                or normalized in (entity.normalized_name or "")
                or any(normalized in alias.lower() for alias in entity.aliases)
            ]
        if entity_types is not None:
            allowed_types = set(entity_types)
            entities = [
                entity for entity in entities if entity.entity_type in allowed_types
            ]
        if statuses is not None:
            allowed_statuses = set(statuses)
            entities = [
                entity for entity in entities if entity.status in allowed_statuses
            ]
        if tags is not None:
            required = {tag.lower() for tag in tags}
            entities = [
                entity
                for entity in entities
                if required.issubset({tag.lower() for tag in entity.tags})
            ]
        entities.sort(
            key=lambda item: (
                item.entity_type.value,
                item.normalized_name or "",
                item.entity_id,
                item.version,
            )
        )
        return entities[offset : offset + limit]

    def append_relationship(
        self, relationship: KnowledgeRelationship
    ) -> KnowledgeRelationship:
        self._validate_relationship_endpoints(relationship)
        if relationship.relationship_type in ACYCLIC_RELATIONSHIP_TYPES:
            self._reject_cycle(relationship)
        key = (relationship.organization_id, relationship.relationship_id)
        versions = self._relationships[key]
        fingerprint = _relationship_content_fingerprint(relationship)
        existing = next(
            (item for item in versions if item.version == relationship.version), None
        )
        if existing is not None:
            if _relationship_content_fingerprint(existing) == fingerprint:
                return existing
            raise ConflictingVersionError("relationship version already exists")
        if (
            versions
            and relationship.version != max(item.version for item in versions) + 1
        ):
            raise ConflictingVersionError("relationship versions must be sequential")
        if relationship.status is KnowledgeStatus.ACTIVE:
            duplicate = self._active_duplicate(relationship)
            if (
                duplicate is not None
                and duplicate.relationship_id != relationship.relationship_id
            ):
                raise DuplicateRelationshipError("active relationship signature exists")
        fp_key = (relationship.organization_id, relationship.relationship_fingerprint)
        previous_id = self._relationship_fingerprints.get(fp_key)
        if previous_id is not None and previous_id != relationship.relationship_id:
            raise DuplicateRelationshipError("relationship fingerprint already exists")
        self._relationship_fingerprints[fp_key] = relationship.relationship_id
        versions.append(relationship)
        versions.sort(key=lambda item: item.version)
        return relationship

    def get_relationship(
        self, organization_id: UUID, relationship_id: str
    ) -> KnowledgeRelationship | None:
        return self.get_current_relationship(organization_id, relationship_id)

    def get_relationship_version(
        self, organization_id: UUID, relationship_id: str, version: int
    ) -> KnowledgeRelationship | None:
        return next(
            (
                item
                for item in self._relationships.get(
                    (organization_id, relationship_id), []
                )
                if item.version == version
            ),
            None,
        )

    def get_current_relationship(
        self,
        organization_id: UUID,
        relationship_id: str,
        *,
        as_of: datetime | None = None,
    ) -> KnowledgeRelationship | None:
        versions = self._relationships.get((organization_id, relationship_id), [])
        candidates = _valid_versions(versions, as_of)
        return candidates[-1] if candidates else None

    def list_relationship_versions(
        self, organization_id: UUID, relationship_id: str
    ) -> list[KnowledgeRelationship]:
        return list(self._relationships.get((organization_id, relationship_id), []))

    def find_relationships(
        self,
        organization_id: UUID,
        *,
        relationship_types: list[KnowledgeRelationshipType] | None = None,
        statuses: list[KnowledgeStatus] | None = None,
        source_entity_id: str | None = None,
        target_entity_id: str | None = None,
        min_confidence: float = 0.0,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeRelationship]:
        _validate_page(limit, offset)
        relationships = [
            relationship
            for org_id, relationship_id in sorted(self._relationships)
            if org_id == organization_id
            if (
                relationship := self.get_current_relationship(
                    org_id, relationship_id, as_of=as_of
                )
            )
            is not None
        ]
        if relationship_types is not None:
            allowed = set(relationship_types)
            relationships = [
                item for item in relationships if item.relationship_type in allowed
            ]
        if statuses is not None:
            allowed_statuses = set(statuses)
            relationships = [
                item for item in relationships if item.status in allowed_statuses
            ]
        if source_entity_id is not None:
            relationships = [
                item
                for item in relationships
                if item.source_entity_id == source_entity_id
            ]
        if target_entity_id is not None:
            relationships = [
                item
                for item in relationships
                if item.target_entity_id == target_entity_id
            ]
        relationships = [
            item for item in relationships if item.confidence >= min_confidence
        ]
        relationships.sort(
            key=lambda item: (
                item.source_entity_id,
                item.target_entity_id,
                item.relationship_type.value,
                item.relationship_id,
            )
        )
        return relationships[offset : offset + limit]

    def neighbors(
        self,
        organization_id: UUID,
        entity_id: str,
        *,
        direction: str = "both",
        relationship_types: list[KnowledgeRelationshipType] | None = None,
        max_nodes: int = 50,
        min_confidence: float = 0.0,
        as_of: datetime | None = None,
    ) -> tuple[list[KnowledgeEntity], list[KnowledgeRelationship]]:
        _validate_page(max_nodes, 0)
        if self.get_current_entity(organization_id, entity_id, as_of=as_of) is None:
            return [], []
        relationships: list[KnowledgeRelationship] = []
        if direction in {"both", "outgoing"}:
            relationships.extend(
                self.find_relationships(
                    organization_id,
                    relationship_types=relationship_types,
                    source_entity_id=entity_id,
                    min_confidence=min_confidence,
                    as_of=as_of,
                    limit=max_nodes,
                )
            )
        if direction in {"both", "incoming"}:
            relationships.extend(
                self.find_relationships(
                    organization_id,
                    relationship_types=relationship_types,
                    target_entity_id=entity_id,
                    min_confidence=min_confidence,
                    as_of=as_of,
                    limit=max_nodes,
                )
            )
        unique_relationships = {
            relationship.relationship_id: relationship for relationship in relationships
        }
        entity_ids = {
            relationship.target_entity_id
            if relationship.source_entity_id == entity_id
            else relationship.source_entity_id
            for relationship in unique_relationships.values()
        }
        entities = [
            entity
            for item_id in sorted(entity_ids)
            if (
                entity := self.get_current_entity(organization_id, item_id, as_of=as_of)
            )
            is not None
        ][:max_nodes]
        return entities, list(unique_relationships.values())[:max_nodes]

    def paths(
        self,
        organization_id: UUID,
        start_entity_id: str,
        end_entity_id: str,
        *,
        relationship_types: list[KnowledgeRelationshipType] | None = None,
        max_depth: int = 5,
        max_paths: int = 20,
        min_confidence: float = 0.0,
        as_of: datetime | None = None,
    ) -> list[GraphPath]:
        if max_depth <= 0 or max_paths <= 0:
            raise InvalidKnowledgeLimitError("max_depth and max_paths must be positive")
        queue: deque[tuple[str, tuple[str, ...], tuple[KnowledgeRelationship, ...]]] = (
            deque([(start_entity_id, (start_entity_id,), ())])
        )
        results: list[GraphPath] = []
        while queue and len(results) < max_paths:
            current, entity_path, relationship_path = queue.popleft()
            if len(relationship_path) >= max_depth:
                continue
            outgoing = self.find_relationships(
                organization_id,
                relationship_types=relationship_types,
                source_entity_id=current,
                statuses=[KnowledgeStatus.ACTIVE],
                min_confidence=min_confidence,
                as_of=as_of,
                limit=1000,
            )
            for relationship in outgoing:
                next_id = relationship.target_entity_id
                if next_id in entity_path:
                    continue
                next_entities = (*entity_path, next_id)
                next_relationships = (*relationship_path, relationship)
                if end_entity_id == "*" or next_id == end_entity_id:
                    results.append(
                        _make_path(organization_id, next_entities, next_relationships)
                    )
                    if len(results) >= max_paths:
                        break
                queue.append((next_id, next_entities, next_relationships))
        results.sort(key=lambda path: (path.depth, path.end_entity_id, path.path_id))
        return results

    def health(self) -> RepositoryHealth:
        return RepositoryHealth(
            status=HealthStatus.HEALTHY,
            details={
                "mode": "memory",
                "entity_versions": sum(len(items) for items in self._entities.values()),
                "relationship_versions": sum(
                    len(items) for items in self._relationships.values()
                ),
            },
        )

    def _validate_relationship_endpoints(
        self, relationship: KnowledgeRelationship
    ) -> None:
        source = self.get_current_entity(
            relationship.organization_id, relationship.source_entity_id
        )
        if source is None:
            raise SourceEntityNotFoundError("source entity does not exist")
        target = self.get_current_entity(
            relationship.organization_id, relationship.target_entity_id
        )
        if target is None:
            raise TargetEntityNotFoundError("target entity does not exist")
        if (
            source.organization_id != relationship.organization_id
            or target.organization_id != relationship.organization_id
        ):
            raise OrganizationMismatchError(
                "relationship crosses organization boundary"
            )

    def _active_duplicate(
        self, relationship: KnowledgeRelationship
    ) -> KnowledgeRelationship | None:
        for item in self.find_relationships(
            relationship.organization_id,
            source_entity_id=relationship.source_entity_id,
            target_entity_id=relationship.target_entity_id,
            relationship_types=[relationship.relationship_type],
            statuses=[KnowledgeStatus.ACTIVE],
            limit=10000,
        ):
            if item.relationship_fingerprint == relationship.relationship_fingerprint:
                return item
        return None

    def _reject_cycle(self, relationship: KnowledgeRelationship) -> None:
        paths = self.paths(
            relationship.organization_id,
            relationship.target_entity_id,
            relationship.source_entity_id,
            relationship_types=[relationship.relationship_type],
            max_depth=50,
            max_paths=1,
        )
        if not paths:
            return
        if relationship.relationship_type is KnowledgeRelationshipType.DEPENDS_ON:
            raise DependencyCycleError("depends_on cycle detected")
        raise ReplacementCycleError("replaces cycle detected")


def _validate_page(limit: int, offset: int) -> None:
    if limit <= 0 or offset < 0:
        raise InvalidKnowledgeLimitError(
            "limit must be positive and offset non-negative"
        )


def _valid_versions(
    versions: list[KnowledgeEntity] | list[KnowledgeRelationship],
    as_of: datetime | None,
):
    now = as_of or datetime.now(UTC)
    candidates = [
        item
        for item in versions
        if item.valid_from <= now
        and (item.valid_until is None or item.valid_until > now)
    ]
    if as_of is None:
        candidates = [
            item
            for item in candidates
            if item.status
            in {
                KnowledgeStatus.ACTIVE,
                KnowledgeStatus.ARCHIVED,
                KnowledgeStatus.DISPUTED,
                KnowledgeStatus.MERGED,
                KnowledgeStatus.INVALIDATED,
                KnowledgeStatus.SUPERSEDED,
            }
        ]
    candidates.sort(key=lambda item: (item.valid_from, item.version))
    return candidates


def _entity_content_fingerprint(entity: KnowledgeEntity) -> str:
    payload = entity.model_dump(mode="json")
    payload["identity_fingerprint"] = entity.identity_fingerprint
    return stable_fingerprint(payload)


def _relationship_content_fingerprint(relationship: KnowledgeRelationship) -> str:
    payload = relationship.model_dump(mode="json")
    payload["relationship_fingerprint"] = relationship.relationship_fingerprint
    return stable_fingerprint(payload)


def _make_path(
    organization_id: UUID,
    entity_ids: tuple[str, ...],
    relationships: tuple[KnowledgeRelationship, ...],
) -> GraphPath:
    total_weight = sum(relationship.weight for relationship in relationships)
    minimum_confidence = (
        min(relationship.confidence for relationship in relationships)
        if relationships
        else 1.0
    )
    average_weight = total_weight / len(relationships) if relationships else 1.0
    path_score = round(minimum_confidence * average_weight, 4)
    relationship_ids = tuple(
        relationship.relationship_id for relationship in relationships
    )
    return GraphPath(
        path_id=stable_fingerprint(
            {
                "organization_id": str(organization_id),
                "entities": entity_ids,
                "relationships": relationship_ids,
            }
        )[:32],
        organization_id=organization_id,
        start_entity_id=entity_ids[0],
        end_entity_id=entity_ids[-1],
        entities=entity_ids,
        relationships=relationship_ids,
        depth=len(entity_ids) - 1,
        total_weight=round(total_weight, 4),
        minimum_confidence=minimum_confidence,
        path_score=path_score,
        reason_codes=("graph_path",),
    )

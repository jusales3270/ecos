"""Knowledge Graph integrity validation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from ecos.events import EventType
from ecos.knowledge.models import (
    GraphIntegrityReport,
    GraphIntegrityStatus,
    IntegritySeverity,
    IntegrityViolation,
    KnowledgeRelationshipType,
    KnowledgeStatus,
)
from ecos.knowledge.repository import KnowledgeGraphRepository
from ecos.knowledge.service import KnowledgeGraphService

Clock = Callable[[], datetime]


class GraphIntegrityService:
    """Validate graph structure without modifying it."""

    def __init__(
        self,
        repository: KnowledgeGraphRepository,
        *,
        knowledge_service: KnowledgeGraphService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._knowledge_service = knowledge_service
        self._clock = clock or (lambda: datetime.now(UTC))

    def validate(self, organization_id: UUID) -> GraphIntegrityReport:
        started_at = self._clock()
        started = perf_counter()
        violations: list[IntegrityViolation] = []
        entities = self._repository.find_entities(
            organization_id,
            statuses=list(KnowledgeStatus),
            limit=10000,
        )
        relationships = self._repository.find_relationships(
            organization_id,
            statuses=list(KnowledgeStatus),
            limit=10000,
        )
        entity_ids = {entity.entity_id for entity in entities}
        fingerprint_to_ids: dict[str, set[str]] = defaultdict(set)
        for entity in entities:
            fingerprint_to_ids[entity.identity_fingerprint].add(entity.entity_id)
            if entity.status is KnowledgeStatus.MERGED and not entity.safe_metadata.get(
                "canonical_entity_id"
            ):
                violations.append(
                    _violation(
                        organization_id,
                        "merged_without_canonical",
                        IntegritySeverity.ERROR,
                        entity_ids=(entity.entity_id,),
                    )
                )
        duplicate_entities = tuple(
            sorted(
                entity_id
                for ids in fingerprint_to_ids.values()
                if len(ids) > 1
                for entity_id in ids
            )
        )
        for entity_id in duplicate_entities:
            violations.append(
                _violation(
                    organization_id,
                    "fingerprint_conflict",
                    IntegritySeverity.ERROR,
                    entity_ids=(entity_id,),
                )
            )
        broken_relationships: list[str] = []
        active_signatures: dict[tuple[str, str, str], str] = {}
        for relationship in relationships:
            if relationship.source_entity_id not in entity_ids:
                broken_relationships.append(relationship.relationship_id)
                violations.append(
                    _violation(
                        organization_id,
                        "missing_source",
                        IntegritySeverity.CRITICAL,
                        relationship_ids=(relationship.relationship_id,),
                    )
                )
            if relationship.target_entity_id not in entity_ids:
                broken_relationships.append(relationship.relationship_id)
                violations.append(
                    _violation(
                        organization_id,
                        "missing_target",
                        IntegritySeverity.CRITICAL,
                        relationship_ids=(relationship.relationship_id,),
                    )
                )
            if relationship.status is KnowledgeStatus.ACTIVE:
                signature = (
                    relationship.source_entity_id,
                    relationship.target_entity_id,
                    relationship.relationship_type.value,
                )
                existing = active_signatures.get(signature)
                if existing is not None:
                    violations.append(
                        _violation(
                            organization_id,
                            "duplicate_active_relationship",
                            IntegritySeverity.ERROR,
                            relationship_ids=(existing, relationship.relationship_id),
                        )
                    )
                active_signatures[signature] = relationship.relationship_id
        cyclic_paths = []
        for relationship_type in (
            KnowledgeRelationshipType.DEPENDS_ON,
            KnowledgeRelationshipType.REPLACES,
        ):
            cyclic_paths.extend(
                _cycles(self._repository, organization_id, relationship_type)
            )
        for path in cyclic_paths:
            violations.append(
                _violation(
                    organization_id,
                    f"{path.reason_codes[0]}_cycle",
                    IntegritySeverity.CRITICAL,
                    entity_ids=path.entities,
                    relationship_ids=path.relationships,
                )
            )
        status = GraphIntegrityStatus.VALID
        if violations:
            status = GraphIntegrityStatus.INVALID
        elif not entities:
            status = GraphIntegrityStatus.INCOMPLETE
        completed_at = self._clock()
        report = GraphIntegrityReport(
            organization_id=organization_id,
            status=status,
            checked_entities=len(entities),
            checked_relationships=len(relationships),
            violations=tuple(violations),
            warnings=("graph_empty",) if not entities else (),
            orphan_entities=(),
            duplicate_entities=duplicate_entities,
            broken_relationships=tuple(sorted(set(broken_relationships))),
            cyclic_dependencies=tuple(cyclic_paths),
            version_conflicts=(),
            started_at=started_at,
            completed_at=completed_at,
            duration=round(max(perf_counter() - started, 0.0), 6),
            reason_codes=("integrity_validated",),
        )
        if self._knowledge_service is not None:
            event_type = (
                EventType.GRAPH_INTEGRITY_FAILED
                if status is GraphIntegrityStatus.INVALID
                else EventType.GRAPH_INTEGRITY_VALIDATED
            )
            self._knowledge_service._publish(
                event_type,
                organization_id,
                {
                    "report_id": str(report.report_id),
                    "status": report.status.value,
                    "violation_count": len(report.violations),
                },
            )
        return report


def _violation(
    organization_id: UUID,
    violation_type: str,
    severity: IntegritySeverity,
    *,
    entity_ids: tuple[str, ...] = (),
    relationship_ids: tuple[str, ...] = (),
) -> IntegrityViolation:
    return IntegrityViolation(
        organization_id=organization_id,
        violation_type=violation_type,
        severity=severity,
        entity_ids=entity_ids,
        relationship_ids=relationship_ids,
        blocking=severity in {IntegritySeverity.ERROR, IntegritySeverity.CRITICAL},
        safe_message=f"Graph integrity violation: {violation_type}.",
        reason_codes=(violation_type,),
    )


def _cycles(
    repository: KnowledgeGraphRepository,
    organization_id: UUID,
    relationship_type: KnowledgeRelationshipType,
):
    paths = []
    relationships = repository.find_relationships(
        organization_id,
        relationship_types=[relationship_type],
        statuses=[KnowledgeStatus.ACTIVE],
        limit=10000,
    )
    for relationship in relationships:
        path = repository.paths(
            organization_id,
            relationship.target_entity_id,
            relationship.source_entity_id,
            relationship_types=[relationship_type],
            max_depth=50,
            max_paths=1,
        )
        if path:
            paths.append(
                path[0].model_copy(update={"reason_codes": (relationship_type.value,)})
            )
    return paths

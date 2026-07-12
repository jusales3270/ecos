"""Tests for the ECOS Knowledge Graph infrastructure."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.context import ContextBuildRequest, ContextEngine
from ecos.core.container import Container
from ecos.core.settings import Settings
from ecos.domain import Objective
from ecos.events import Event, EventService, EventType
from ecos.events.models import EventMetadata
from ecos.knowledge import (
    DeterministicSemanticSearchProvider,
    GraphIntegrityService,
    InMemoryKnowledgeGraphRepository,
    KnowledgeContextExpander,
    KnowledgeContextExpansionRequest,
    KnowledgeEntity,
    KnowledgeEntityType,
    KnowledgeGraphService,
    KnowledgeRelationship,
    KnowledgeRelationshipType,
    SemanticQuery,
)
from ecos.knowledge.exceptions import (
    DependencyCycleError,
    DuplicateRelationshipError,
    FingerprintConflictError,
    SelfRelationshipForbiddenError,
    SensitiveMetadataError,
)
from ecos.knowledge.models import HealthStatus
from ecos.knowledge.projector import KnowledgeProjector
from ecos.knowledge.search import SEMANTIC_WEIGHTS
from ecos.memory import MemoryObject, MemoryRepository, MemoryType
from ecos.observability import InMemoryEventStore, RedactionPolicy
from ecos.runtime import FakeEventBus

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
ORG = UUID("00000000-0000-4000-8000-0000000000a1")
SESSION = UUID("00000000-0000-4000-8000-000000000001")


def entity(entity_id: str, name: str, **kwargs: object) -> KnowledgeEntity:
    return KnowledgeEntity(
        entity_id=entity_id,
        organization_id=ORG,
        entity_type=kwargs.pop("entity_type", KnowledgeEntityType.PROJECT),
        name=name,
        confidence=kwargs.pop("confidence", 0.8),
        importance=kwargs.pop("importance", 0.7),
        valid_from=kwargs.pop("valid_from", NOW),
        created_at=kwargs.pop("created_at", NOW),
        updated_at=kwargs.pop("updated_at", NOW),
        tags=kwargs.pop("tags", ("retention",)),
        attributes=kwargs.pop("attributes", {}),
        **kwargs,
    )


def relationship(
    relationship_id: str,
    source: str,
    target: str,
    relationship_type: KnowledgeRelationshipType = KnowledgeRelationshipType.DEPENDS_ON,
) -> KnowledgeRelationship:
    return KnowledgeRelationship(
        relationship_id=relationship_id,
        organization_id=ORG,
        source_entity_id=source,
        target_entity_id=target,
        relationship_type=relationship_type,
        confidence=0.8,
        weight=0.9,
        valid_from=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def populated_repository() -> InMemoryKnowledgeGraphRepository:
    repository = InMemoryKnowledgeGraphRepository()
    repository.append_entity(entity("project:retention", "Retention Program"))
    repository.append_entity(
        entity(
            "policy:retention",
            "Retention Governance Policy",
            entity_type=KnowledgeEntityType.POLICY,
            tags=("policy", "retention"),
        )
    )
    repository.append_entity(
        entity(
            "risk:churn",
            "Customer Churn Risk",
            entity_type=KnowledgeEntityType.RISK,
            tags=("risk", "customer"),
        )
    )
    repository.append_relationship(
        relationship(
            "rel:project-policy",
            "project:retention",
            "policy:retention",
            KnowledgeRelationshipType.GOVERNED_BY,
        )
    )
    repository.append_relationship(
        relationship(
            "rel:project-risk",
            "project:retention",
            "risk:churn",
            KnowledgeRelationshipType.AFFECTS,
        )
    )
    return repository


def test_knowledge_entity_is_immutable_and_validates_safe_identity() -> None:
    aliases = ["Retention", "retention", "Retention"]
    tags = ["policy", "retention", "policy"]

    item = KnowledgeEntity(
        entity_id="policy:retention",
        organization_id=ORG,
        entity_type=KnowledgeEntityType.POLICY,
        name="Retenção Policy",
        aliases=aliases,
        tags=tags,
        confidence=0.9,
        importance=0.8,
        attributes={"identity_external_id": "POL-1"},
        valid_from=NOW,
        created_at=NOW,
        updated_at=NOW,
    )

    assert item.normalized_name == "retencao policy"
    assert item.aliases == ("Retention", "retention")
    assert item.tags == ("policy", "retention")
    assert len(item.identity_fingerprint) == 64
    aliases.append("mutated")
    assert "mutated" not in item.aliases
    with pytest.raises(ValidationError):
        item.name = "changed"  # type: ignore[misc]
    with pytest.raises(SensitiveMetadataError):
        KnowledgeEntity(
            entity_id="x",
            organization_id=ORG,
            entity_type=KnowledgeEntityType.PROJECT,
            name="Unsafe",
            safe_metadata={"token": "secret"},
            valid_from=NOW,
            created_at=NOW,
            updated_at=NOW,
        )


def test_knowledge_relationship_validation_and_fingerprint() -> None:
    item = relationship("rel:1", "a", "b")

    assert item.direction.value == "directed"
    assert len(item.relationship_fingerprint) == 64
    with pytest.raises(SelfRelationshipForbiddenError):
        relationship("rel:self", "a", "a")
    with pytest.raises(ValidationError):
        KnowledgeRelationship(
            relationship_id="rel:bad",
            organization_id=ORG,
            source_entity_id="a",
            target_entity_id="b",
            relationship_type=KnowledgeRelationshipType.RELATES_TO,
            weight=float("nan"),
            valid_from=NOW,
            created_at=NOW,
            updated_at=NOW,
        )


def test_in_memory_repository_versions_and_idempotency_are_append_only() -> None:
    repository = InMemoryKnowledgeGraphRepository()
    first = entity("project:x", "Project X")
    repository.append_entity(first)
    assert repository.append_entity(first) == first
    second = first.model_copy(
        update={
            "version": 2,
            "name": "Project X renamed",
            "supersedes_entity_version": 1,
            "updated_at": NOW + timedelta(days=1),
            "valid_from": NOW + timedelta(days=1),
        }
    )
    repository.append_entity(second)

    assert repository.get_current_entity(ORG, "project:x", as_of=NOW) == first
    assert (
        repository.get_current_entity(ORG, "project:x", as_of=NOW + timedelta(days=2))
        == second
    )
    assert repository.list_entity_versions(ORG, "project:x") == [first, second]
    assert repository.health().status is HealthStatus.HEALTHY


def test_repository_rejects_fingerprint_conflict_and_duplicate_relationship() -> None:
    repository = InMemoryKnowledgeGraphRepository()
    repository.append_entity(entity("project:a", "Project A"))
    repository.append_entity(entity("policy:a", "Policy A"))
    with pytest.raises(FingerprintConflictError):
        repository.append_entity(entity("project:duplicate", "Project A"))
    rel = relationship("rel:1", "project:a", "policy:a")
    repository.append_relationship(rel)
    with pytest.raises(DuplicateRelationshipError):
        repository.append_relationship(relationship("rel:2", "project:a", "policy:a"))


def test_traversal_dependency_impact_and_cycle_rules() -> None:
    repository = populated_repository()

    neighbors, edges = repository.neighbors(ORG, "project:retention")
    assert [item.entity_id for item in neighbors] == [
        "policy:retention",
        "risk:churn",
    ]
    assert {item.relationship_id for item in edges} == {
        "rel:project-policy",
        "rel:project-risk",
    }
    assert repository.dependency_chain(ORG, "project:retention")
    assert repository.impact_chain(ORG, "project:retention")
    repository.append_relationship(
        relationship(
            "rel:depends-forward",
            "project:retention",
            "policy:retention",
            KnowledgeRelationshipType.DEPENDS_ON,
        )
    )
    repository.append_relationship(
        relationship(
            "rel:relates-cycle",
            "risk:churn",
            "project:retention",
            KnowledgeRelationshipType.RELATES_TO,
        )
    )
    with pytest.raises(DependencyCycleError):
        repository.append_relationship(
            relationship(
                "rel:cycle",
                "policy:retention",
                "project:retention",
                KnowledgeRelationshipType.DEPENDS_ON,
            )
        )


def test_deterministic_semantic_search_uses_structured_lexical_graph_scores() -> None:
    repository = populated_repository()
    provider = DeterministicSemanticSearchProvider(repository, clock=lambda: NOW)
    query = SemanticQuery(
        organization_id=ORG,
        text="retention governance",
        source_entity_ids=("project:retention",),
        max_results=5,
        max_depth=2,
    )

    results = provider.search(query)

    assert round(sum(SEMANTIC_WEIGHTS.values()), 6) == 1.0
    assert {item.entity.entity_id for item in results[:2]} == {
        "project:retention",
        "policy:retention",
    }
    assert all(0.0 <= item.semantic_score <= 1.0 for item in results)
    assert all(
        "structured_lexical_semantic_search" in item.reason_codes for item in results
    )


def test_context_expansion_is_bounded_and_preserves_references() -> None:
    repository = populated_repository()
    provider = DeterministicSemanticSearchProvider(repository, clock=lambda: NOW)
    service = KnowledgeGraphService(repository, semantic_search_provider=provider)
    expander = KnowledgeContextExpander(service, repository)

    expansion = expander.expand(
        KnowledgeContextExpansionRequest(
            organization_id=ORG,
            session_id=SESSION,
            objective_reference="objective:retention",
            seed_entity_ids=("project:retention",),
            semantic_query=SemanticQuery(
                organization_id=ORG,
                text="retention",
                max_results=10,
            ),
            max_depth=2,
            max_entities=2,
            context_budget=2,
        )
    )

    assert len(expansion.selected_entities) == 2
    assert expansion.truncation_applied is True
    assert expansion.excluded_entities
    assert expansion.graph_confidence > 0


class StubMemoryRepository(MemoryRepository):
    def __init__(self, memories: list[MemoryObject]) -> None:
        self.memories = memories

    def store(self, memory: MemoryObject) -> MemoryObject:
        self.memories.append(memory)
        return memory

    def get(self, memory_id: UUID) -> MemoryObject | None:
        return next((item for item in self.memories if item.id == memory_id), None)

    def search(self, query: str, **kwargs: object) -> list[MemoryObject]:
        del query
        return self.memories

    def update(self, memory: MemoryObject) -> MemoryObject:
        return memory

    def delete(self, memory_id: UUID) -> None:
        del memory_id

    def list(self, **kwargs: object) -> list[MemoryObject]:
        return self.memories


def test_context_engine_consumes_knowledge_graph_without_selecting_final() -> None:
    repository = populated_repository()
    provider = DeterministicSemanticSearchProvider(repository, clock=lambda: NOW)
    service = KnowledgeGraphService(repository, semantic_search_provider=provider)
    expander = KnowledgeContextExpander(service, repository)
    engine = ContextEngine(
        StubMemoryRepository(
            [
                MemoryObject(
                    organization_id=ORG,
                    type=MemoryType.STRATEGIC,
                    title="Retention policy memory",
                    description="Retention policy prior decision.",
                    tags=["retention"],
                    confidence=0.9,
                    source="test",
                    created_at=NOW,
                    updated_at=NOW,
                )
            ]
        ),
        knowledge_graph_service=service,
        context_expander=expander,
        clock=lambda: NOW,
    )

    context = engine.build(
        ContextBuildRequest(
            session_id=SESSION,
            organization_id=ORG,
            objective=Objective(
                organization_id=ORG,
                title="Improve retention policy",
            ),
            relevant_entities=["project:retention"],
            policies=["Follow governance"],
            constraints=["Use verified data"],
            correlation_id=SESSION,
        )
    )

    assert context.context_graph is not None
    assert context.knowledge_references
    assert context.elements[0].title == "Objective"


def test_projector_projects_valid_events_once_and_integrity_reports_invalid() -> None:
    repository = InMemoryKnowledgeGraphRepository()
    service = KnowledgeGraphService(repository)
    projector = KnowledgeProjector(service, clock=lambda: NOW)
    event = Event(
        event_type=EventType.SESSION_CREATED,
        source="test",
        organization_id=ORG,
        session_id=SESSION,
        payload={"organization_id": str(ORG), "session_id": str(SESSION)},
    )

    projector.project(event)
    projector.project(event)

    assert repository.count_entities(ORG) == 1
    report = GraphIntegrityService(repository, clock=lambda: NOW).validate(ORG)
    assert report.status.value == "valid"


def test_event_service_projects_memory_updates_into_graph() -> None:
    repository = InMemoryKnowledgeGraphRepository()
    service = KnowledgeGraphService(repository)
    event_service = EventService(
        FakeEventBus(),
        InMemoryEventStore(RedactionPolicy()),
    )
    event_service.register_projector(KnowledgeProjector(service, clock=lambda: NOW))

    envelope = event_service.publish(
        Event(
            event_type=EventType.MEMORY_UPDATED,
            source="learning",
            organization_id=ORG,
            session_id=SESSION,
            payload={"organization_id": str(ORG), "memory_id": "memory-1"},
            metadata=EventMetadata(correlation_id=SESSION),
        )
    )
    event_service.dispatch(envelope)

    assert repository.get_current_entity(ORG, "memory:memory-1") is not None


def test_container_selects_memory_knowledge_repository_by_default() -> None:
    container = Container(settings=Settings())

    assert isinstance(container.knowledge_repository, InMemoryKnowledgeGraphRepository)
    assert container.knowledge_graph_service.health().status is HealthStatus.HEALTHY

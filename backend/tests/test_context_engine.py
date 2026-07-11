"""Tests for the deterministic real Context Engine."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config

from ecos.context import ContextBuildRequest, ContextEngine
from ecos.core.container import Container
from ecos.core.exceptions import CrossOrganizationMemoryError, MemoryRetrievalError
from ecos.core.settings import Settings
from ecos.domain import Objective
from ecos.events import EventService, EventType
from ecos.memory import (
    MemoryObject,
    MemoryRepository,
    MemoryType,
    PostgresMemoryRepository,
)
from ecos.runtime import FakeContextProvider, FakeEventBus, FakeMemoryRepository

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
ORG_A = UUID("00000000-0000-4000-8000-0000000000a1")
ORG_B = UUID("00000000-0000-4000-8000-0000000000b1")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")
DATABASE_URL = os.getenv("ECOS_TEST_DATABASE_URL")


class StubMemoryRepository(MemoryRepository):
    """Memory repository stub that records scoped retrieval calls."""

    def __init__(
        self,
        memories: list[MemoryObject],
        *,
        fail_search: bool = False,
    ) -> None:
        self.memories = list(memories)
        self.fail_search = fail_search
        self.calls: list[tuple[str, UUID | None, int | None]] = []

    def store(self, memory: MemoryObject) -> MemoryObject:
        self.memories.append(memory)
        return memory

    def get(self, memory_id: UUID) -> MemoryObject | None:
        return next((item for item in self.memories if item.id == memory_id), None)

    def search(
        self,
        query: str,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        if self.fail_search:
            raise RuntimeError("repository unavailable")
        self.calls.append((query, organization_id, limit))
        filtered = self.list(
            organization_id=organization_id,
            memory_type=memory_type,
            tags=tags,
            limit=None,
        )
        query_tokens = {query.lower()}
        matches = [
            memory
            for memory in filtered
            if query_tokens.intersection(
                {
                    *memory.title.lower().split(),
                    *memory.description.lower().split(),
                    *[tag.lower() for tag in memory.tags],
                }
            )
        ]
        return matches[:limit] if limit is not None else matches

    def update(self, memory: MemoryObject) -> MemoryObject:
        self.memories = [
            memory if item.id == memory.id else item for item in self.memories
        ]
        return memory

    def delete(self, memory_id: UUID) -> None:
        self.memories = [item for item in self.memories if item.id != memory_id]

    def list(
        self,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        memories = list(self.memories)
        if organization_id is not None:
            memories = [
                item for item in memories if item.organization_id == organization_id
            ]
        if memory_type is not None:
            memories = [item for item in memories if item.type is memory_type]
        if tags is not None:
            required = set(tags)
            memories = [item for item in memories if required.issubset(item.tags)]
        return memories[:limit] if limit is not None else memories


class LeakyMemoryRepository(StubMemoryRepository):
    """Repository stub that ignores organization filters to verify engine checks."""

    def list(
        self,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        del organization_id
        return super().list(memory_type=memory_type, tags=tags, limit=limit)


def memory(
    title: str,
    description: str,
    *,
    organization_id: UUID = ORG_A,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    confidence: float = 0.8,
    tags: list[str] | None = None,
    age_days: int = 3,
) -> MemoryObject:
    created_at = NOW - timedelta(days=age_days)
    return MemoryObject(
        organization_id=organization_id,
        type=memory_type,
        title=title,
        description=description,
        tags=tags or [],
        confidence=confidence,
        source="test",
        created_at=created_at,
        updated_at=created_at,
    )


def request(*, memory_limit: int = 8) -> ContextBuildRequest:
    objective = Objective(
        organization_id=ORG_A,
        title="Improve retention policy",
        description="Use governed retention constraints.",
        priority=5,
    )
    return ContextBuildRequest(
        session_id=SESSION_ID,
        organization_id=ORG_A,
        objective=objective,
        user_information=["Retention is below target."],
        constraints=["Use verified retention data"],
        policies=["Follow retention governance"],
        resources=["reasoning", "debate"],
        external_signals=["Market retention pressure increased"],
        relevant_entities=["retention", "policy"],
        previous_session_ids=[UUID("00000000-0000-4000-8000-000000000099")],
        required_context_fields=["objective", "memory", "evidence"],
        correlation_id=SESSION_ID,
        memory_limit=memory_limit,
    )


def test_context_engine_builds_unified_context_with_injected_dependencies() -> None:
    """ContextEngine builds a structured context using injected repository/clock/id."""
    repository = StubMemoryRepository(
        [
            memory(
                "Retention policy history",
                "Prior retention policy improved renewal quality.",
                memory_type=MemoryType.STRATEGIC,
                tags=["retention", "important"],
                confidence=0.9,
            )
        ]
    )
    context_id = UUID("00000000-0000-4000-8000-000000000abc")
    engine = ContextEngine(
        repository,
        clock=lambda: NOW,
        id_generator=lambda: context_id,
    )
    build_request = request()
    original = build_request.model_dump(mode="json")

    context = engine.build(build_request)

    assert context.id == context_id
    assert context.session_id == SESSION_ID
    assert context.organization_id == ORG_A
    assert context.objective.title == "Improve retention policy"
    assert context.summary == (
        "Context for 'Improve retention policy' includes 1 memory references, "
        "1 policies, 1 constraints, and 0 gaps."
    )
    assert context.policies == ["Follow retention governance"]
    assert context.constraints == ["Use verified retention data"]
    assert context.resources == ["reasoning", "debate"]
    assert context.external_context == ["Market retention pressure increased"]
    assert context.relevant_entities == ["retention", "policy"]
    assert context.memory_references[0].title == "Retention policy history"
    assert context.evidence == [f"memory:{context.memory_references[0].memory_id}"]
    assert context.previous_decisions == ["00000000-0000-4000-8000-000000000099"]
    assert context.generated_at == NOW
    assert 0.0 <= context.confidence <= 1.0
    assert 0.0 <= context.completeness <= 1.0
    assert build_request.model_dump(mode="json") == original
    assert repository.calls
    assert all(call[1] == ORG_A for call in repository.calls)


def test_context_engine_prioritizes_relevance_importance_confidence_and_recency() -> (
    None
):
    """Relevant memory ranking is deterministic and keeps old important memory."""
    old_important = memory(
        "Important retention policy decision",
        "Retention policy decision remains critical.",
        memory_type=MemoryType.STRATEGIC,
        confidence=0.95,
        tags=["retention", "important"],
        age_days=900,
    )
    recent_medium = memory(
        "Retention policy note",
        "Retention policy operational note.",
        memory_type=MemoryType.WORKING,
        confidence=0.6,
        tags=["retention"],
        age_days=1,
    )
    irrelevant = memory(
        "Procurement archive",
        "Vendor selection history.",
        memory_type=MemoryType.ORGANIZATIONAL,
        confidence=1.0,
        tags=["procurement"],
    )
    engine = ContextEngine(
        StubMemoryRepository([recent_medium, irrelevant, old_important]),
        clock=lambda: NOW,
    )

    context = engine.build(request(memory_limit=2))

    assert [item.memory_id for item in context.memory_references] == [
        old_important.id,
        recent_medium.id,
    ]
    assert all(item.memory_id != irrelevant.id for item in context.memory_references)
    assert len(context.memory_references) == 2
    assert context.memory_references[0].relevance_score >= (
        context.memory_references[1].relevance_score
    )
    assert any(item.field == "memory_recency" for item in context.missing_context)


def test_context_engine_deduplicates_memory_and_versions_new_generations() -> None:
    """Duplicate repository matches are collapsed and each build gets a new version."""
    selected = memory(
        "Retention policy evidence",
        "Retention policy evidence with verified impact.",
        tags=["retention"],
    )
    repository = StubMemoryRepository([selected, selected])
    engine = ContextEngine(repository, clock=lambda: NOW)

    first = engine.build(request())
    second = engine.build(request())

    assert len(first.memory_references) == 1
    assert second.version == first.version + 1
    assert first.version == 1


def test_context_engine_reports_missing_context_and_reduces_scores() -> None:
    """Missing required context stays explicit and lowers confidence/completeness."""
    engine = ContextEngine(StubMemoryRepository([]), clock=lambda: NOW)

    context = engine.build(request())

    fields = {item.field for item in context.missing_context}
    assert {"memory", "evidence"}.issubset(fields)
    assert context.confidence < 0.6
    assert context.completeness < 1.0


def test_context_engine_rejects_cross_organization_memory() -> None:
    """Engine validates repository results even when the repository leaks scope."""
    repository = LeakyMemoryRepository(
        [
            memory(
                "Retention policy from another org",
                "Retention policy should not leak.",
                organization_id=ORG_B,
                tags=["retention"],
            )
        ]
    )
    engine = ContextEngine(repository, clock=lambda: NOW)

    with pytest.raises(CrossOrganizationMemoryError):
        engine.build(request())


def test_context_engine_wraps_repository_failure_and_skips_final_event() -> None:
    """Repository errors remain explicit and no success event is emitted."""
    bus = FakeEventBus()
    engine = ContextEngine(
        StubMemoryRepository([], fail_search=True),
        event_service=EventService(bus),
        clock=lambda: NOW,
    )

    with pytest.raises(MemoryRetrievalError) as captured:
        engine.build(request())

    assert isinstance(captured.value.__cause__, RuntimeError)
    event_types = [envelope.event.event_type for envelope in bus.envelopes]
    assert event_types == [EventType.CONTEXT_REQUESTED]


def test_context_engine_emits_ordered_safe_events() -> None:
    """Context events preserve correlation data and safe metadata counts only."""
    bus = FakeEventBus()
    engine = ContextEngine(
        StubMemoryRepository(
            [
                memory(
                    "Retention policy evidence",
                    "Retention policy evidence.",
                    tags=["retention"],
                )
            ]
        ),
        event_service=EventService(bus),
        clock=lambda: NOW,
    )

    engine.build(request())

    event_types = [envelope.event.event_type for envelope in bus.envelopes]
    assert event_types == [EventType.CONTEXT_REQUESTED, EventType.CONTEXT_CREATED]
    final_event = bus.envelopes[-1].event
    assert final_event.metadata.correlation_id == SESSION_ID
    assert final_event.payload["organization_id"] == str(ORG_A)
    assert final_event.payload["memories_selected"] == 1
    assert "Retention policy evidence" not in str(final_event.payload)


def test_container_selects_fake_or_real_context_provider() -> None:
    """Container uses memory repository mode to select the context provider."""
    fake_container = Container(
        settings=Settings(memory_repository="fake", ai_provider="fake")
    )
    postgres_container = Container(
        settings=Settings(memory_repository="postgres", ai_provider="fake")
    )

    assert isinstance(fake_container.context_provider, FakeContextProvider)
    assert isinstance(postgres_container.context_provider, ContextEngine)
    assert postgres_container.context_provider._memory_repository is (
        postgres_container.memory_repository
    )


def test_context_engine_has_no_ai_or_external_dependencies() -> None:
    """The real Context Engine module does not import OpenAI or AIProvider."""
    import ecos.context.engine as context_engine

    source_names = set(context_engine.__dict__)
    assert "openai" not in source_names
    assert "AIProvider" not in source_names
    assert not hasattr(ContextEngine(FakeMemoryRepository()), "reason")


def test_context_engine_uses_uuid_generator_for_each_context() -> None:
    """Each generated context receives its own injected identifier."""
    ids = [
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
    ]

    def next_id() -> UUID:
        return ids.pop(0)

    engine = ContextEngine(
        StubMemoryRepository(
            [
                memory(
                    "Retention policy evidence",
                    "Retention policy evidence.",
                    tags=["retention"],
                )
            ]
        ),
        clock=lambda: NOW,
        id_generator=next_id,
    )

    first = engine.build(request())
    second = engine.build(request())

    assert first.id != second.id


@pytest.mark.skipif(
    DATABASE_URL is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)
def test_optional_postgres_context_engine_isolates_organizations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional PostgreSQL test for context isolation, priority and references."""
    assert DATABASE_URL is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", DATABASE_URL)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    repository = PostgresMemoryRepository(
        DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    org_a_memory = memory(
        "Retention policy strategic memory",
        "Retention policy strategic evidence.",
        organization_id=ORG_A,
        memory_type=MemoryType.STRATEGIC,
        tags=["retention", "important"],
        confidence=0.95,
    )
    org_b_memory = memory(
        "Retention policy other organization",
        "Retention policy must not cross organization boundaries.",
        organization_id=ORG_B,
        tags=["retention"],
        confidence=1.0,
    )
    try:
        repository.store(org_a_memory)
        repository.store(org_b_memory)
        context = ContextEngine(repository, clock=lambda: NOW).build(request())

        assert [item.memory_id for item in context.memory_references] == [
            org_a_memory.id
        ]
        assert context.memory_references[0].relevance_score > 0.0
        assert all(item.organization_id == ORG_A for item in context.memory_references)
    finally:
        repository.delete(org_a_memory.id)
        repository.delete(org_b_memory.id)
        command.downgrade(config, "base")

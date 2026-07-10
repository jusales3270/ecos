"""Unit tests for ECOS Memory Engine models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.memory import (
    MemoryContext,
    MemoryObject,
    MemoryReference,
    MemoryRepository,
    MemoryService,
    MemoryType,
)


def make_memory_object() -> MemoryObject:
    """Create a valid memory object for tests."""
    return MemoryObject(
        type=MemoryType.WORKING,
        title="Decision context",
        description="Relevant operating context for a decision.",
        tags=["context", "decision"],
        confidence=0.8,
        source="unit-test",
    )


def test_memory_type_values() -> None:
    """MemoryType exposes the supported memory categories."""
    assert {memory_type.value for memory_type in MemoryType} == {
        "WORKING",
        "EPISODIC",
        "SEMANTIC",
        "STRATEGIC",
        "ORGANIZATIONAL",
    }


def test_memory_object_creates_identity_and_utc_timestamps() -> None:
    """MemoryObject includes UUID identity and UTC audit timestamps."""
    memory = make_memory_object()

    assert isinstance(memory.id, UUID)
    assert memory.type == MemoryType.WORKING
    assert memory.created_at.tzinfo is not None
    assert memory.created_at.utcoffset() == UTC.utcoffset(memory.created_at)
    assert memory.updated_at.tzinfo is not None
    assert memory.updated_at.utcoffset() == UTC.utcoffset(memory.updated_at)
    assert memory.updated_at >= memory.created_at


def test_memory_object_validates_text_tags_and_confidence() -> None:
    """MemoryObject rejects blank text, blank tags, and invalid confidence."""
    with pytest.raises(ValidationError):
        MemoryObject(
            type=MemoryType.SEMANTIC,
            title="   ",
            description="Description",
            source="unit-test",
        )

    with pytest.raises(ValidationError):
        MemoryObject(
            type=MemoryType.SEMANTIC,
            title="Title",
            description="   ",
            source="unit-test",
        )

    with pytest.raises(ValidationError):
        MemoryObject(
            type=MemoryType.SEMANTIC,
            title="Title",
            description="Description",
            tags=["valid", "   "],
            source="unit-test",
        )

    with pytest.raises(ValidationError):
        MemoryObject(
            type=MemoryType.SEMANTIC,
            title="Title",
            description="Description",
            confidence=1.1,
            source="unit-test",
        )


def test_memory_reference_validates_required_fields() -> None:
    """MemoryReference links memory objects to non-blank targets."""
    memory = make_memory_object()
    reference = MemoryReference(
        memory_id=memory.id,
        target="objective:123",
        relationship="supports",
    )

    assert reference.memory_id == memory.id
    assert reference.target == "objective:123"
    assert reference.relationship == "supports"

    with pytest.raises(ValidationError):
        MemoryReference(memory_id=memory.id, target="   ", relationship="supports")

    with pytest.raises(ValidationError):
        MemoryReference(memory_id=memory.id, target="objective:123", relationship="   ")


def test_memory_context_groups_memories_and_references() -> None:
    """MemoryContext groups memory objects and references without persistence."""
    memory = make_memory_object()
    reference = MemoryReference(
        memory_id=memory.id,
        target="objective:123",
        relationship="supports",
    )
    context = MemoryContext(
        memories=[memory],
        references=[reference],
        summary="Decision support context.",
    )

    assert context.memories == [memory]
    assert context.references == [reference]
    assert context.summary == "Decision support context."

    with pytest.raises(ValidationError):
        MemoryContext(summary="   ")


def test_memory_models_reject_invalid_timestamps() -> None:
    """Memory models reject non-UTC, naive, and unordered timestamps."""
    created_at = datetime.now(UTC)

    with pytest.raises(ValidationError):
        MemoryObject(
            type=MemoryType.WORKING,
            title="Title",
            description="Description",
            source="unit-test",
            created_at=created_at,
            updated_at=created_at - timedelta(seconds=1),
        )

    with pytest.raises(ValidationError):
        MemoryObject(
            type=MemoryType.WORKING,
            title="Title",
            description="Description",
            source="unit-test",
            created_at=datetime.now(),
        )

    with pytest.raises(ValidationError):
        MemoryObject(
            type=MemoryType.WORKING,
            title="Title",
            description="Description",
            source="unit-test",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


class NotImplementedMemoryRepository(MemoryRepository):
    """Concrete test adapter that delegates to the interface methods."""

    def store(self, memory: MemoryObject) -> MemoryObject:
        """Delegate to the interface method."""
        return super().store(memory)

    def get(self, memory_id: UUID) -> MemoryObject | None:
        """Delegate to the interface method."""
        return super().get(memory_id)

    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """Delegate to the interface method."""
        return super().search(query, memory_type=memory_type, tags=tags)

    def update(self, memory: MemoryObject) -> MemoryObject:
        """Delegate to the interface method."""
        return super().update(memory)

    def delete(self, memory_id: UUID) -> None:
        """Delegate to the interface method."""
        super().delete(memory_id)

    def list(
        self,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """Delegate to the interface method."""
        return super().list(memory_type=memory_type, tags=tags)


def test_memory_repository_interface_methods_raise_not_implemented() -> None:
    """MemoryRepository interface methods are intentionally unimplemented."""
    repository = NotImplementedMemoryRepository()
    memory = make_memory_object()

    with pytest.raises(NotImplementedError):
        repository.store(memory)
    with pytest.raises(NotImplementedError):
        repository.get(memory.id)
    with pytest.raises(NotImplementedError):
        repository.search("decision")
    with pytest.raises(NotImplementedError):
        repository.update(memory)
    with pytest.raises(NotImplementedError):
        repository.delete(memory.id)
    with pytest.raises(NotImplementedError):
        repository.list()


class InMemoryTestRepository(MemoryRepository):
    """Minimal test double for verifying MemoryService delegation only."""

    def __init__(self) -> None:
        """Initialize an empty in-memory test double."""
        self.items: dict[UUID, MemoryObject] = {}

    def store(self, memory: MemoryObject) -> MemoryObject:
        """Store a memory object in the test double."""
        self.items[memory.id] = memory
        return memory

    def get(self, memory_id: UUID) -> MemoryObject | None:
        """Get a memory object from the test double."""
        return self.items.get(memory_id)

    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """Return memories matching basic test-double filters."""
        del query
        return self.list(memory_type=memory_type, tags=tags)

    def update(self, memory: MemoryObject) -> MemoryObject:
        """Update a memory object in the test double."""
        self.items[memory.id] = memory
        return memory

    def delete(self, memory_id: UUID) -> None:
        """Delete a memory object from the test double."""
        self.items.pop(memory_id, None)

    def list(
        self,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """List memory objects from the test double."""
        memories = list(self.items.values())
        if memory_type is not None:
            memories = [memory for memory in memories if memory.type == memory_type]
        if tags is not None:
            memories = [
                memory for memory in memories if set(tags).issubset(set(memory.tags))
            ]
        return memories


def test_memory_service_uses_repository_abstraction() -> None:
    """MemoryService delegates operations to the repository abstraction."""
    repository = InMemoryTestRepository()
    service = MemoryService(repository)
    memory = make_memory_object()

    assert service.store(memory) == memory
    assert service.get(memory.id) == memory
    assert service.search("decision", memory_type=MemoryType.WORKING) == [memory]
    assert service.list(tags=["context"]) == [memory]
    assert service.update(memory) == memory

    service.delete(memory.id)

    assert service.get(memory.id) is None

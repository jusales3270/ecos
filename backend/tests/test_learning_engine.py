"""Unit tests for the deterministic Learning Engine."""

from uuid import uuid4

from ecos.events import EventService, EventType
from ecos.learning import LearningObject, LearningService, LearningValidationStatus
from ecos.memory import MemoryService, MemoryType
from ecos.runtime import FakeEventBus, FakeMemoryRepository


def make_learning(*, confidence: float) -> LearningObject:
    """Build a learning candidate with preserved provenance and evidence."""
    return LearningObject(
        session_id=uuid4(),
        memory_type=MemoryType.STRATEGIC,
        title="Validated operating insight",
        description="Use an explicit learning boundary for durable knowledge.",
        evidence=["deterministic runtime result"],
        origin="unit-test-runtime",
        tags=["learning", "governance"],
        confidence=confidence,
    )


def make_service() -> tuple[LearningService, FakeMemoryRepository, FakeEventBus]:
    """Create a Learning Engine with observable fake boundaries."""
    repository = FakeMemoryRepository()
    event_bus = FakeEventBus()
    service = LearningService(MemoryService(repository), EventService(event_bus))
    return service, repository, event_bus


def test_approved_learning_becomes_memory_with_provenance() -> None:
    """Approved learning preserves origin, evidence-derived content and confidence."""
    service, repository, event_bus = make_service()
    learning = make_learning(confidence=0.8)

    memory = service.learn(learning)

    assert memory is not None
    assert learning.status is LearningValidationStatus.APPROVED
    assert memory.source == learning.origin
    assert memory.confidence == learning.confidence
    assert repository.get(memory.id) == memory
    assert [item.event.event_type for item in event_bus.envelopes] == [
        EventType.LEARNING_STARTED,
        EventType.LEARNING_VALIDATED,
        EventType.MEMORY_UPDATED,
        EventType.LEARNING_COMPLETED,
    ]


def test_rejected_learning_does_not_write_memory() -> None:
    """A candidate below the deterministic threshold is rejected without a write."""
    service, repository, event_bus = make_service()
    learning = make_learning(confidence=0.49)

    memory = service.learn(learning)

    assert memory is None
    assert learning.status is LearningValidationStatus.REJECTED
    assert repository.list() == []
    assert [item.event.event_type for item in event_bus.envelopes] == [
        EventType.LEARNING_STARTED,
        EventType.LEARNING_VALIDATED,
        EventType.LEARNING_COMPLETED,
    ]

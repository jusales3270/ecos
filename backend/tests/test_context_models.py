"""Unit tests for ECOS Context Engine models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.context import (
    ContextBuildRequest,
    ContextElement,
    ContextObject,
    ContextPriority,
    ContextProvider,
    ContextService,
    ContextSource,
    ContextSourceType,
)
from ecos.domain import Objective, Organization


def make_objective() -> Objective:
    """Create a valid objective for context tests."""
    organization = Organization(name="ACME")
    return Objective(
        organization_id=organization.id,
        title="Improve decision quality",
    )


def make_context_element() -> ContextElement:
    """Create a valid context element for tests."""
    return ContextElement(
        source_type=ContextSourceType.MEMORY,
        priority=ContextPriority.HIGH,
        title="Decision history",
        content="Relevant historical decision context.",
        confidence=0.9,
        metadata={"source": "unit-test"},
    )


def make_context_object() -> ContextObject:
    """Create a valid context object for tests."""
    return ContextObject(
        session_id=UUID("00000000-0000-4000-8000-000000000001"),
        objective=make_objective(),
        elements=[make_context_element()],
        confidence=0.8,
    )


def test_context_source_type_values() -> None:
    """ContextSourceType exposes all supported source categories."""
    assert {source_type.value for source_type in ContextSourceType} == {
        "MEMORY",
        "KNOWLEDGE_GRAPH",
        "USER",
        "DOCUMENT",
        "POLICY",
        "EXTERNAL",
        "SESSION",
    }


def test_context_priority_values() -> None:
    """ContextPriority exposes all supported priority levels."""
    assert {priority.value for priority in ContextPriority} == {
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }


def test_context_source_validates_required_fields() -> None:
    """ContextSource validates source type, name, and optional reference."""
    source = ContextSource(
        source_type=ContextSourceType.DOCUMENT,
        name="Policy document",
        reference="doc:policy",
    )

    assert isinstance(source.id, UUID)
    assert source.source_type == ContextSourceType.DOCUMENT
    assert source.name == "Policy document"
    assert source.reference == "doc:policy"

    with pytest.raises(ValidationError):
        ContextSource(source_type=ContextSourceType.DOCUMENT, name="   ")

    with pytest.raises(ValidationError):
        ContextSource(
            source_type=ContextSourceType.DOCUMENT,
            name="Policy document",
            reference="   ",
        )


def test_context_element_contains_required_fields_and_utc_timestamp() -> None:
    """ContextElement includes required fields and UTC created_at."""
    element = make_context_element()

    assert isinstance(element.id, UUID)
    assert element.source_type == ContextSourceType.MEMORY
    assert element.priority == ContextPriority.HIGH
    assert element.title == "Decision history"
    assert element.content == "Relevant historical decision context."
    assert element.confidence == 0.9
    assert element.metadata == {"source": "unit-test"}
    assert element.created_at.tzinfo is not None
    assert element.created_at.utcoffset() == UTC.utcoffset(element.created_at)


def test_context_element_validates_text_confidence_and_metadata() -> None:
    """ContextElement rejects invalid text, confidence, and metadata."""
    with pytest.raises(ValidationError):
        ContextElement(
            source_type=ContextSourceType.USER,
            priority=ContextPriority.MEDIUM,
            title="   ",
            content="Content",
        )

    with pytest.raises(ValidationError):
        ContextElement(
            source_type=ContextSourceType.USER,
            priority=ContextPriority.MEDIUM,
            title="Title",
            content="   ",
        )

    with pytest.raises(ValidationError):
        ContextElement(
            source_type=ContextSourceType.USER,
            priority=ContextPriority.MEDIUM,
            title="Title",
            content="Content",
            confidence=1.1,
        )

    with pytest.raises(ValidationError):
        ContextElement(
            source_type=ContextSourceType.USER,
            priority=ContextPriority.MEDIUM,
            title="Title",
            content="Content",
            metadata={"   ": "invalid"},
        )


def test_context_object_contains_session_objective_elements_and_confidence() -> None:
    """ContextObject groups a session, objective, elements, and confidence."""
    context = make_context_object()

    assert isinstance(context.id, UUID)
    assert isinstance(context.session_id, UUID)
    assert isinstance(context.objective, Objective)
    assert len(context.elements) == 1
    assert context.confidence == 0.8
    assert context.created_at.tzinfo is not None
    assert context.created_at.utcoffset() == UTC.utcoffset(context.created_at)


def test_context_object_validates_confidence() -> None:
    """ContextObject confidence must be between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        ContextObject(
            session_id=UUID("00000000-0000-4000-8000-000000000001"),
            objective=make_objective(),
            confidence=-0.1,
        )

    with pytest.raises(ValidationError):
        ContextObject(
            session_id=UUID("00000000-0000-4000-8000-000000000001"),
            objective=make_objective(),
            confidence=1.1,
        )


def test_context_models_reject_invalid_created_at() -> None:
    """Context models reject non-UTC and naive created_at values."""
    with pytest.raises(ValidationError):
        ContextElement(
            source_type=ContextSourceType.USER,
            priority=ContextPriority.MEDIUM,
            title="Title",
            content="Content",
            created_at=datetime.now(),
        )

    with pytest.raises(ValidationError):
        ContextElement(
            source_type=ContextSourceType.USER,
            priority=ContextPriority.MEDIUM,
            title="Title",
            content="Content",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


class NotImplementedContextProvider(ContextProvider):
    """Concrete test adapter that delegates to interface methods."""

    def build(self, request: ContextBuildRequest | None = None) -> ContextObject:
        """Delegate to the interface method."""
        del request
        return super().build()

    def expand(self, context: ContextObject) -> ContextObject:
        """Delegate to the interface method."""
        return super().expand(context)

    def compress(self, context: ContextObject) -> ContextObject:
        """Delegate to the interface method."""
        return super().compress(context)

    def validate(self, context: ContextObject) -> bool:
        """Delegate to the interface method."""
        return super().validate(context)


def test_context_provider_interface_methods_raise_not_implemented() -> None:
    """ContextProvider interface methods are intentionally unimplemented."""
    provider = NotImplementedContextProvider()
    context = make_context_object()

    with pytest.raises(NotImplementedError):
        provider.build()
    with pytest.raises(NotImplementedError):
        provider.expand(context)
    with pytest.raises(NotImplementedError):
        provider.compress(context)
    with pytest.raises(NotImplementedError):
        provider.validate(context)


class TestContextProvider(ContextProvider):
    """Test double for verifying ContextService delegation only."""

    def __init__(self, context: ContextObject) -> None:
        """Initialize the provider with a reusable context object."""
        self.context = context

    def build(self, request: ContextBuildRequest | None = None) -> ContextObject:
        """Return the configured context object."""
        del request
        return self.context

    def expand(self, context: ContextObject) -> ContextObject:
        """Return the provided context object."""
        return context

    def compress(self, context: ContextObject) -> ContextObject:
        """Return the provided context object."""
        return context

    def validate(self, context: ContextObject) -> bool:
        """Return whether the context has at least one element."""
        return len(context.elements) > 0


def test_context_service_uses_provider_abstraction() -> None:
    """ContextService delegates operations to the provider abstraction."""
    context = make_context_object()
    service = ContextService(TestContextProvider(context))

    assert service.build() == context
    assert service.expand(context) == context
    assert service.compress(context) == context
    assert service.validate(context) is True

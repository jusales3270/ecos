"""Unit tests for ECOS Specialist Framework models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.specialists import (
    Capability,
    Constraint,
    Contribution,
    ContributionType,
    Opinion,
    Specialist,
    SpecialistProvider,
    SpecialistRegistry,
    SpecialistService,
    SpecialistType,
)


def make_capability() -> Capability:
    """Create a valid specialist capability for tests."""
    return Capability(
        name="Financial analysis",
        description="Evaluate financial implications.",
    )


def make_constraint() -> Constraint:
    """Create a valid specialist constraint for tests."""
    return Constraint(
        name="No legal advice",
        description="Escalate legal conclusions to the legal specialist.",
    )


def make_specialist() -> Specialist:
    """Create a valid specialist for tests."""
    return Specialist(
        name="Finance Specialist",
        type=SpecialistType.FINANCE,
        description="Evaluates financial risks and opportunities.",
        capabilities=[make_capability()],
        constraints=[make_constraint()],
        enabled=True,
        version="0.1.0",
    )


def make_contribution(specialist_id: UUID) -> Contribution:
    """Create a valid contribution for tests."""
    return Contribution(
        specialist_id=specialist_id,
        contribution_type=ContributionType.OPINION,
        content="The option improves margin resilience.",
        confidence=0.8,
        metadata={"source": "unit-test"},
    )


def test_specialist_type_values() -> None:
    """SpecialistType exposes all supported cognitive specialist categories."""
    assert {specialist_type.value for specialist_type in SpecialistType} == {
        "EXECUTIVE",
        "FINANCE",
        "LEGAL",
        "OPERATIONS",
        "TECHNOLOGY",
        "MARKETING",
        "SALES",
        "HR",
        "RISK",
        "STRATEGY",
    }


def test_contribution_type_values() -> None:
    """ContributionType exposes all supported contribution categories."""
    assert {contribution_type.value for contribution_type in ContributionType} == {
        "OPINION",
        "RISK",
        "OPPORTUNITY",
        "ASSUMPTION",
        "QUESTION",
        "RECOMMENDATION",
    }


def test_capability_and_constraint_validate_required_fields() -> None:
    """Capability and Constraint reject blank names and descriptions."""
    capability = make_capability()
    constraint = make_constraint()

    assert isinstance(capability.id, UUID)
    assert capability.name == "Financial analysis"
    assert constraint.name == "No legal advice"

    with pytest.raises(ValidationError):
        Capability(name="   ", description="Description")

    with pytest.raises(ValidationError):
        Capability(name="Capability", description="   ")

    with pytest.raises(ValidationError):
        Constraint(name="   ", description="Description")

    with pytest.raises(ValidationError):
        Constraint(name="Constraint", description="   ")


def test_specialist_contains_required_fields_and_utc_created_at() -> None:
    """Specialist contains required architecture fields and UTC created_at."""
    specialist = make_specialist()

    assert isinstance(specialist.id, UUID)
    assert specialist.name == "Finance Specialist"
    assert specialist.type == SpecialistType.FINANCE
    assert specialist.description == "Evaluates financial risks and opportunities."
    assert len(specialist.capabilities) == 1
    assert specialist.capabilities[0].name == "Financial analysis"
    assert len(specialist.constraints) == 1
    assert specialist.constraints[0].name == "No legal advice"
    assert specialist.enabled is True
    assert specialist.version == "0.1.0"
    assert specialist.created_at.tzinfo is not None
    assert specialist.created_at.utcoffset() == UTC.utcoffset(specialist.created_at)


def test_specialist_validates_text_fields() -> None:
    """Specialist rejects blank name, description, and version."""
    with pytest.raises(ValidationError):
        Specialist(
            name="   ",
            type=SpecialistType.FINANCE,
            description="Description",
        )

    with pytest.raises(ValidationError):
        Specialist(
            name="Finance Specialist",
            type=SpecialistType.FINANCE,
            description="   ",
        )

    with pytest.raises(ValidationError):
        Specialist(
            name="Finance Specialist",
            type=SpecialistType.FINANCE,
            description="Description",
            version="   ",
        )


def test_opinion_validates_text_and_confidence() -> None:
    """Opinion rejects blank fields and invalid confidence."""
    specialist = make_specialist()
    opinion = Opinion(
        specialist_id=specialist.id,
        title="Financial view",
        content="The scenario improves cash efficiency.",
        confidence=0.7,
    )

    assert opinion.specialist_id == specialist.id
    assert opinion.confidence == 0.7

    with pytest.raises(ValidationError):
        Opinion(specialist_id=specialist.id, title="   ", content="Content")

    with pytest.raises(ValidationError):
        Opinion(specialist_id=specialist.id, title="Title", content="   ")

    with pytest.raises(ValidationError):
        Opinion(
            specialist_id=specialist.id,
            title="Title",
            content="Content",
            confidence=1.1,
        )


def test_contribution_validates_type_content_confidence_and_metadata() -> None:
    """Contribution validates type, content, confidence, and metadata."""
    specialist = make_specialist()
    contribution = make_contribution(specialist.id)

    assert contribution.specialist_id == specialist.id
    assert contribution.contribution_type == ContributionType.OPINION
    assert contribution.confidence == 0.8
    assert contribution.metadata == {"source": "unit-test"}

    with pytest.raises(ValidationError):
        Contribution(
            specialist_id=specialist.id,
            contribution_type=ContributionType.RISK,
            content="   ",
        )

    with pytest.raises(ValidationError):
        Contribution(
            specialist_id=specialist.id,
            contribution_type=ContributionType.RISK,
            content="Risk content",
            confidence=-0.1,
        )

    with pytest.raises(ValidationError):
        Contribution(
            specialist_id=specialist.id,
            contribution_type=ContributionType.RISK,
            content="Risk content",
            metadata={"   ": "invalid"},
        )


def test_specialist_models_reject_invalid_created_at() -> None:
    """Specialist models reject non-UTC and naive created_at values."""
    with pytest.raises(ValidationError):
        Capability(
            name="Capability",
            description="Description",
            created_at=datetime.now(),
        )

    with pytest.raises(ValidationError):
        Capability(
            name="Capability",
            description="Description",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


def test_specialist_registry_registers_and_finds_specialists() -> None:
    """SpecialistRegistry registers, retrieves, lists, filters, and unregisters."""
    registry = SpecialistRegistry()
    specialist = make_specialist()

    assert registry.register(specialist) == specialist
    assert registry.get(specialist.id) == specialist
    assert registry.list() == [specialist]
    assert registry.find_by_type(SpecialistType.FINANCE) == [specialist]
    assert registry.find_by_type(SpecialistType.LEGAL) == []

    registry.unregister(specialist.id)

    assert registry.get(specialist.id) is None
    assert registry.list() == []


class NotImplementedSpecialistProvider(SpecialistProvider):
    """Concrete test adapter that delegates to interface methods."""

    def load(self) -> list[Specialist]:
        """Delegate to the interface method."""
        return super().load()

    def analyze(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> list[Contribution]:
        """Delegate to the interface method."""
        return super().analyze(specialist, input_data)

    def contribute(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> Contribution:
        """Delegate to the interface method."""
        return super().contribute(specialist, input_data)


def test_specialist_provider_interface_methods_raise_not_implemented() -> None:
    """SpecialistProvider interface methods are intentionally unimplemented."""
    provider = NotImplementedSpecialistProvider()
    specialist = make_specialist()

    with pytest.raises(NotImplementedError):
        provider.load()
    with pytest.raises(NotImplementedError):
        provider.analyze(specialist, {"context": "test"})
    with pytest.raises(NotImplementedError):
        provider.contribute(specialist, {"context": "test"})


class TestSpecialistProvider(SpecialistProvider):
    """Test double for verifying SpecialistService delegation only."""

    def __init__(self, specialist: Specialist) -> None:
        """Initialize the provider with a reusable specialist."""
        self.specialist = specialist
        self.contribution = make_contribution(specialist.id)

    def load(self) -> list[Specialist]:
        """Return configured specialists."""
        return [self.specialist]

    def analyze(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> list[Contribution]:
        """Return configured analysis contributions."""
        del specialist, input_data
        return [self.contribution]

    def contribute(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> Contribution:
        """Return a configured contribution."""
        del specialist, input_data
        return self.contribution


def test_specialist_service_uses_provider_and_registry_abstractions() -> None:
    """SpecialistService delegates to provider and registry abstractions."""
    specialist = make_specialist()
    registry = SpecialistRegistry()
    service = SpecialistService(TestSpecialistProvider(specialist), registry)

    assert service.load() == [specialist]
    assert service.get(specialist.id) == specialist
    assert service.list() == [specialist]
    assert service.find_by_type(SpecialistType.FINANCE) == [specialist]
    analysis = service.analyze(specialist.id, {"context": "test"})
    contribution = service.contribute(specialist.id, {"context": "test"})

    assert len(analysis) == 1
    assert analysis[0].specialist_id == specialist.id
    assert contribution.specialist_id == specialist.id
    assert contribution.contribution_type == ContributionType.OPINION

    service.unregister(specialist.id)

    assert service.get(specialist.id) is None
    with pytest.raises(LookupError):
        service.analyze(specialist.id, {"context": "test"})

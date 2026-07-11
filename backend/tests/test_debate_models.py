"""Unit tests for ECOS Debate Engine models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.debate import (
    Argument,
    Consensus,
    ConsensusLevel,
    CounterArgument,
    Debate,
    DebateProvider,
    DebateResult,
    DebateService,
    DebateStatus,
)
from ecos.specialists import Specialist, SpecialistType

SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")


def make_specialist() -> Specialist:
    """Create a valid specialist for debate tests."""
    return Specialist(
        name="Strategy Specialist",
        type=SpecialistType.STRATEGY,
        description="Evaluates strategic implications.",
    )


def make_argument(specialist_id: UUID) -> Argument:
    """Create a valid debate argument for tests."""
    return Argument(
        specialist_id=specialist_id,
        position="Proceed with staged rollout",
        content="A staged rollout reduces execution risk.",
        confidence=0.8,
        metadata={"source": "unit-test"},
    )


def make_consensus() -> Consensus:
    """Create a valid consensus artifact for tests."""
    return Consensus(
        level=ConsensusLevel.HIGH,
        summary="Specialists broadly agree on staged rollout.",
        agreements=["Staged rollout reduces risk"],
        disagreements=["Timeline remains uncertain"],
    )


def make_debate() -> Debate:
    """Create a valid debate for tests."""
    specialist = make_specialist()
    return Debate(
        session_id=SESSION_ID,
        specialists=[specialist],
        arguments=[make_argument(specialist.id)],
        status=DebateStatus.CREATED,
    )


def make_debate_result(debate_id: UUID) -> DebateResult:
    """Create a valid debate result for tests."""
    return DebateResult(
        debate_id=debate_id,
        consensus=make_consensus(),
        recommendations=["Use staged rollout"],
        unresolved_questions=["Confirm rollout timeline"],
        confidence=0.75,
    )


def test_debate_status_values() -> None:
    """DebateStatus exposes all supported debate statuses."""
    assert {status.value for status in DebateStatus} == {
        "CREATED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
    }


def test_consensus_level_values() -> None:
    """ConsensusLevel exposes all supported consensus levels."""
    assert {level.value for level in ConsensusLevel} == {
        "NONE",
        "LOW",
        "MEDIUM",
        "HIGH",
        "UNANIMOUS",
    }


def test_argument_validates_fields_and_metadata() -> None:
    """Argument validates required fields, confidence, and metadata."""
    specialist = make_specialist()
    argument = make_argument(specialist.id)

    assert isinstance(argument.id, UUID)
    assert argument.specialist_id == specialist.id
    assert argument.position == "Proceed with staged rollout"
    assert argument.confidence == 0.8
    assert argument.created_at.tzinfo is not None
    assert argument.created_at.utcoffset() == UTC.utcoffset(argument.created_at)

    with pytest.raises(ValidationError):
        Argument(specialist_id=specialist.id, position="   ", content="Content")

    with pytest.raises(ValidationError):
        Argument(specialist_id=specialist.id, position="Position", content="   ")

    with pytest.raises(ValidationError):
        Argument(
            specialist_id=specialist.id,
            position="Position",
            content="Content",
            confidence=1.1,
        )

    with pytest.raises(ValidationError):
        Argument(
            specialist_id=specialist.id,
            position="Position",
            content="Content",
            metadata={"   ": "invalid"},
        )


def test_counter_argument_validates_fields_and_confidence() -> None:
    """CounterArgument validates references, content, and confidence."""
    specialist = make_specialist()
    argument = make_argument(specialist.id)
    counter_argument = CounterArgument(
        argument_id=argument.id,
        specialist_id=specialist.id,
        content="A staged rollout may delay value capture.",
        confidence=0.6,
    )

    assert counter_argument.argument_id == argument.id
    assert counter_argument.specialist_id == specialist.id
    assert counter_argument.confidence == 0.6

    with pytest.raises(ValidationError):
        CounterArgument(
            argument_id=argument.id,
            specialist_id=specialist.id,
            content="   ",
        )

    with pytest.raises(ValidationError):
        CounterArgument(
            argument_id=argument.id,
            specialist_id=specialist.id,
            content="Content",
            confidence=-0.1,
        )


def test_consensus_validates_summary_and_points() -> None:
    """Consensus validates summary, agreements, and disagreements."""
    consensus = make_consensus()

    assert consensus.level == ConsensusLevel.HIGH
    assert consensus.agreements == ["Staged rollout reduces risk"]
    assert consensus.disagreements == ["Timeline remains uncertain"]

    with pytest.raises(ValidationError):
        Consensus(level=ConsensusLevel.LOW, summary="   ")

    with pytest.raises(ValidationError):
        Consensus(
            level=ConsensusLevel.LOW,
            summary="Summary",
            agreements=["   "],
        )

    with pytest.raises(ValidationError):
        Consensus(
            level=ConsensusLevel.LOW,
            summary="Summary",
            disagreements=["   "],
        )


def test_debate_contains_required_architecture_fields() -> None:
    """Debate contains session, specialists, arguments, status, and created_at."""
    debate = make_debate()

    assert isinstance(debate.id, UUID)
    assert debate.session_id == SESSION_ID
    assert len(debate.specialists) == 1
    assert len(debate.arguments) == 1
    assert debate.status == DebateStatus.CREATED
    assert debate.created_at.tzinfo is not None
    assert debate.created_at.utcoffset() == UTC.utcoffset(debate.created_at)


def test_debate_result_contains_required_architecture_fields() -> None:
    """DebateResult contains consensus, recommendations, questions, and confidence."""
    debate = make_debate()
    result = make_debate_result(debate.id)

    assert isinstance(result.id, UUID)
    assert result.debate_id == debate.id
    assert result.consensus.level == ConsensusLevel.HIGH
    assert result.recommendations == ["Use staged rollout"]
    assert result.unresolved_questions == ["Confirm rollout timeline"]
    assert result.confidence == 0.75
    assert result.created_at.tzinfo is not None
    assert result.created_at.utcoffset() == UTC.utcoffset(result.created_at)


def test_debate_result_validates_text_lists_and_confidence() -> None:
    """DebateResult rejects blank list items and invalid confidence."""
    debate = make_debate()

    with pytest.raises(ValidationError):
        DebateResult(
            debate_id=debate.id,
            consensus=make_consensus(),
            recommendations=["   "],
        )

    with pytest.raises(ValidationError):
        DebateResult(
            debate_id=debate.id,
            consensus=make_consensus(),
            unresolved_questions=["   "],
        )

    with pytest.raises(ValidationError):
        DebateResult(
            debate_id=debate.id,
            consensus=make_consensus(),
            confidence=1.1,
        )


def test_debate_models_reject_invalid_created_at() -> None:
    """Debate models reject non-UTC and naive created_at values."""
    specialist = make_specialist()

    with pytest.raises(ValidationError):
        Argument(
            specialist_id=specialist.id,
            position="Position",
            content="Content",
            created_at=datetime.now(),
        )

    with pytest.raises(ValidationError):
        Argument(
            specialist_id=specialist.id,
            position="Position",
            content="Content",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


class NotImplementedDebateProvider(DebateProvider):
    """Concrete test adapter that delegates to interface methods."""

    def start(self, debate: Debate) -> Debate:
        """Delegate to the interface method."""
        return super().start(debate)

    def collect_arguments(self, debate: Debate) -> list[Argument]:
        """Delegate to the interface method."""
        return super().collect_arguments(debate)

    def evaluate_consensus(self, debate: Debate) -> Consensus:
        """Delegate to the interface method."""
        return super().evaluate_consensus(debate)

    def finalize(self, debate: Debate) -> DebateResult:
        """Delegate to the interface method."""
        return super().finalize(debate)


def test_debate_provider_interface_methods_raise_not_implemented() -> None:
    """DebateProvider interface methods are intentionally unimplemented."""
    provider = NotImplementedDebateProvider()
    debate = make_debate()

    with pytest.raises(NotImplementedError):
        provider.start(debate)
    with pytest.raises(NotImplementedError):
        provider.collect_arguments(debate)
    with pytest.raises(NotImplementedError):
        provider.evaluate_consensus(debate)
    with pytest.raises(NotImplementedError):
        provider.finalize(debate)


class TestDebateProvider(DebateProvider):
    """Test double for verifying DebateService delegation only."""

    def __init__(self, debate: Debate) -> None:
        """Initialize the provider with a reusable debate."""
        self.debate = debate
        self.result = make_debate_result(debate.id)

    def start(self, debate: Debate) -> Debate:
        """Return the provided debate."""
        return debate

    def collect_arguments(self, debate: Debate) -> list[Argument]:
        """Return debate arguments."""
        return debate.arguments

    def evaluate_consensus(self, debate: Debate) -> Consensus:
        """Return configured consensus without consensus logic."""
        del debate
        return self.result.consensus

    def finalize(self, debate: Debate) -> DebateResult:
        """Return configured debate result."""
        del debate
        return self.result


def test_debate_service_uses_provider_abstraction() -> None:
    """DebateService delegates operations to the provider abstraction."""
    debate = make_debate()
    service = DebateService(TestDebateProvider(debate))

    assert service.start(debate) == debate
    assert service.collect_arguments(debate) == debate.arguments
    assert service.evaluate_consensus(debate).level == ConsensusLevel.HIGH
    assert service.finalize(debate).debate_id == debate.id

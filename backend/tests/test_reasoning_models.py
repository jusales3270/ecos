"""Unit tests for ECOS Reasoning Engine models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.context import (
    ContextElement,
    ContextObject,
    ContextPriority,
    ContextSourceType,
)
from ecos.domain import Objective, Organization
from ecos.reasoning import (
    Alternative,
    Hypothesis,
    ReasoningContext,
    ReasoningEvidence,
    ReasoningProvider,
    ReasoningResult,
    ReasoningService,
    ReasoningType,
    Tradeoff,
)

SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")


def make_objective() -> Objective:
    """Create a valid objective for reasoning tests."""
    organization = Organization(name="ACME")
    return Objective(
        organization_id=organization.id,
        title="Improve decision quality",
    )


def make_context_object() -> ContextObject:
    """Create a valid context object for reasoning tests."""
    element = ContextElement(
        source_type=ContextSourceType.MEMORY,
        priority=ContextPriority.HIGH,
        title="Decision history",
        content="Relevant historical decision context.",
        confidence=0.9,
    )
    return ContextObject(
        session_id=SESSION_ID,
        objective=make_objective(),
        elements=[element],
        confidence=0.8,
    )


def make_reasoning_context() -> ReasoningContext:
    """Create a valid reasoning context for tests."""
    return ReasoningContext(
        session_id=SESSION_ID,
        context=make_context_object(),
        reasoning_type=ReasoningType.ANALYTICAL,
        constraints=["Use only verified inputs"],
    )


def make_hypothesis() -> Hypothesis:
    """Create a valid hypothesis for tests."""
    return Hypothesis(
        statement="Decision quality improves with explicit context.",
        rationale="Structured context reduces ambiguity.",
        confidence=0.7,
    )


def make_alternative() -> Alternative:
    """Create a valid alternative for tests."""
    return Alternative(
        title="Standardize context assembly",
        description="Use explicit context elements before reasoning.",
        score=0.8,
    )


def make_tradeoff() -> Tradeoff:
    """Create a valid tradeoff for tests."""
    return Tradeoff(
        dimension="Speed vs completeness",
        benefit="More reliable reasoning inputs.",
        cost="Additional preparation time.",
        severity=0.4,
    )


def make_evidence() -> ReasoningEvidence:
    """Create valid reasoning evidence for tests."""
    return ReasoningEvidence(
        source="context-engine",
        content="Context contains verified decision history.",
        confidence=0.9,
        metadata={"source": "unit-test"},
    )


def make_reasoning_result() -> ReasoningResult:
    """Create a valid reasoning result for tests."""
    return ReasoningResult(
        session_id=SESSION_ID,
        reasoning_type=ReasoningType.ANALYTICAL,
        hypotheses=[make_hypothesis()],
        alternatives=[make_alternative()],
        tradeoffs=[make_tradeoff()],
        evidence=[make_evidence()],
        confidence=0.75,
        summary="Structured context is likely to improve decision quality.",
    )


def test_reasoning_type_values() -> None:
    """ReasoningType exposes all supported reasoning modes."""
    assert {reasoning_type.value for reasoning_type in ReasoningType} == {
        "ANALYTICAL",
        "STRATEGIC",
        "CAUSAL",
        "COMPARATIVE",
        "CONSTRAINT",
        "RISK",
        "OPPORTUNITY",
    }


def test_reasoning_evidence_validates_fields_and_metadata() -> None:
    """ReasoningEvidence validates content, confidence, and metadata."""
    evidence = make_evidence()

    assert isinstance(evidence.id, UUID)
    assert evidence.source == "context-engine"
    assert evidence.confidence == 0.9
    assert evidence.created_at.tzinfo is not None
    assert evidence.created_at.utcoffset() == UTC.utcoffset(evidence.created_at)

    with pytest.raises(ValidationError):
        ReasoningEvidence(source="   ", content="Content")

    with pytest.raises(ValidationError):
        ReasoningEvidence(source="source", content="   ")

    with pytest.raises(ValidationError):
        ReasoningEvidence(source="source", content="Content", confidence=1.1)

    with pytest.raises(ValidationError):
        ReasoningEvidence(
            source="source",
            content="Content",
            metadata={"   ": "invalid"},
        )


def test_hypothesis_validates_text_and_confidence() -> None:
    """Hypothesis rejects blank fields and invalid confidence."""
    hypothesis = make_hypothesis()

    assert hypothesis.statement.startswith("Decision quality")
    assert hypothesis.confidence == 0.7

    with pytest.raises(ValidationError):
        Hypothesis(statement="   ", rationale="Rationale")

    with pytest.raises(ValidationError):
        Hypothesis(statement="Statement", rationale="   ")

    with pytest.raises(ValidationError):
        Hypothesis(statement="Statement", rationale="Rationale", confidence=-0.1)


def test_alternative_validates_text_and_score() -> None:
    """Alternative rejects blank fields and invalid score."""
    alternative = make_alternative()

    assert alternative.title == "Standardize context assembly"
    assert alternative.score == 0.8

    with pytest.raises(ValidationError):
        Alternative(title="   ", description="Description")

    with pytest.raises(ValidationError):
        Alternative(title="Title", description="   ")

    with pytest.raises(ValidationError):
        Alternative(title="Title", description="Description", score=1.1)


def test_tradeoff_validates_text_and_severity() -> None:
    """Tradeoff rejects blank fields and invalid severity."""
    tradeoff = make_tradeoff()

    assert tradeoff.dimension == "Speed vs completeness"
    assert tradeoff.severity == 0.4

    with pytest.raises(ValidationError):
        Tradeoff(dimension="   ", benefit="Benefit", cost="Cost")

    with pytest.raises(ValidationError):
        Tradeoff(dimension="Dimension", benefit="   ", cost="Cost")

    with pytest.raises(ValidationError):
        Tradeoff(dimension="Dimension", benefit="Benefit", cost="   ")

    with pytest.raises(ValidationError):
        Tradeoff(dimension="Dimension", benefit="Benefit", cost="Cost", severity=1.1)


def test_reasoning_context_contains_context_type_and_constraints() -> None:
    """ReasoningContext links session, context object, type, and constraints."""
    reasoning_context = make_reasoning_context()

    assert reasoning_context.session_id == SESSION_ID
    assert isinstance(reasoning_context.context, ContextObject)
    assert reasoning_context.reasoning_type == ReasoningType.ANALYTICAL
    assert reasoning_context.constraints == ["Use only verified inputs"]

    with pytest.raises(ValidationError):
        ReasoningContext(
            session_id=SESSION_ID,
            context=make_context_object(),
            reasoning_type=ReasoningType.ANALYTICAL,
            constraints=["   "],
        )


def test_reasoning_result_contains_required_architecture_fields() -> None:
    """ReasoningResult contains all required architecture fields."""
    result = make_reasoning_result()

    assert isinstance(result.id, UUID)
    assert result.session_id == SESSION_ID
    assert result.reasoning_type == ReasoningType.ANALYTICAL
    assert len(result.hypotheses) == 1
    assert len(result.alternatives) == 1
    assert len(result.tradeoffs) == 1
    assert len(result.evidence) == 1
    assert result.confidence == 0.75
    assert result.summary.startswith("Structured context")
    assert result.created_at.tzinfo is not None
    assert result.created_at.utcoffset() == UTC.utcoffset(result.created_at)


def test_reasoning_result_validates_confidence_and_summary() -> None:
    """ReasoningResult rejects invalid confidence and blank summary."""
    with pytest.raises(ValidationError):
        ReasoningResult(
            session_id=SESSION_ID,
            reasoning_type=ReasoningType.ANALYTICAL,
            confidence=1.1,
            summary="Summary",
        )

    with pytest.raises(ValidationError):
        ReasoningResult(
            session_id=SESSION_ID,
            reasoning_type=ReasoningType.ANALYTICAL,
            summary="   ",
        )


def test_reasoning_models_reject_invalid_created_at() -> None:
    """Reasoning models reject non-UTC and naive created_at values."""
    with pytest.raises(ValidationError):
        Hypothesis(
            statement="Statement",
            rationale="Rationale",
            created_at=datetime.now(),
        )

    with pytest.raises(ValidationError):
        Hypothesis(
            statement="Statement",
            rationale="Rationale",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


class NotImplementedReasoningProvider(ReasoningProvider):
    """Concrete test adapter that delegates to interface methods."""

    def analyze(self, context: ReasoningContext) -> ReasoningResult:
        """Delegate to the interface method."""
        return super().analyze(context)

    def generate_hypotheses(self, context: ReasoningContext) -> list[Hypothesis]:
        """Delegate to the interface method."""
        return super().generate_hypotheses(context)

    def evaluate_alternatives(
        self,
        context: ReasoningContext,
        hypotheses: list[Hypothesis],
    ) -> list[Alternative]:
        """Delegate to the interface method."""
        return super().evaluate_alternatives(context, hypotheses)

    def calculate_confidence(self, result: ReasoningResult) -> float:
        """Delegate to the interface method."""
        return super().calculate_confidence(result)


def test_reasoning_provider_interface_methods_raise_not_implemented() -> None:
    """ReasoningProvider interface methods are intentionally unimplemented."""
    provider = NotImplementedReasoningProvider()
    context = make_reasoning_context()
    result = make_reasoning_result()

    with pytest.raises(NotImplementedError):
        provider.analyze(context)
    with pytest.raises(NotImplementedError):
        provider.generate_hypotheses(context)
    with pytest.raises(NotImplementedError):
        provider.evaluate_alternatives(context, [make_hypothesis()])
    with pytest.raises(NotImplementedError):
        provider.calculate_confidence(result)


class TestReasoningProvider(ReasoningProvider):
    """Test double for verifying ReasoningService delegation only."""

    def __init__(self, result: ReasoningResult) -> None:
        """Initialize the provider with a reusable reasoning result."""
        self.result = result

    def analyze(self, context: ReasoningContext) -> ReasoningResult:
        """Return the configured reasoning result."""
        del context
        return self.result

    def generate_hypotheses(self, context: ReasoningContext) -> list[Hypothesis]:
        """Return the configured hypotheses."""
        del context
        return self.result.hypotheses

    def evaluate_alternatives(
        self,
        context: ReasoningContext,
        hypotheses: list[Hypothesis],
    ) -> list[Alternative]:
        """Return the configured alternatives."""
        del context, hypotheses
        return self.result.alternatives

    def calculate_confidence(self, result: ReasoningResult) -> float:
        """Return the configured confidence."""
        return result.confidence


def test_reasoning_service_uses_provider_abstraction() -> None:
    """ReasoningService delegates operations to the provider abstraction."""
    result = make_reasoning_result()
    context = make_reasoning_context()
    service = ReasoningService(TestReasoningProvider(result))

    assert service.analyze(context) == result
    assert service.generate_hypotheses(context) == result.hypotheses
    assert (
        service.evaluate_alternatives(context, result.hypotheses) == result.alternatives
    )
    assert service.calculate_confidence(result) == result.confidence

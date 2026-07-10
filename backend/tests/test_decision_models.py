"""Unit tests for ECOS Decision Support Engine models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.debate import Consensus, ConsensusLevel, DebateResult
from ecos.decision import (
    AlternativeAnalysis,
    DecisionImpact,
    DecisionPackage,
    DecisionProvider,
    DecisionService,
    ExecutiveBrief,
    Recommendation,
    RecommendationType,
    RiskSummary,
)
from ecos.reasoning import ReasoningResult, ReasoningType

SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")
DEBATE_ID = UUID("00000000-0000-4000-8000-000000000002")


def make_risk_summary() -> RiskSummary:
    """Create a valid risk summary for tests."""
    return RiskSummary(
        title="Execution risk",
        description="Rollout may exceed planned timeline.",
        impact=DecisionImpact.MEDIUM,
        probability=0.4,
        mitigation="Use phased delivery governance.",
    )


def make_alternative_analysis() -> AlternativeAnalysis:
    """Create a valid alternative analysis for tests."""
    return AlternativeAnalysis(
        title="Delay rollout",
        summary="Delay execution until dependencies are resolved.",
        pros=["Lower execution pressure"],
        cons=["Delayed value capture"],
        score=0.5,
    )


def make_recommendation() -> Recommendation:
    """Create a valid recommendation for tests."""
    return Recommendation(
        session_id=SESSION_ID,
        recommendation_type=RecommendationType.STRATEGIC,
        title="Proceed with staged rollout",
        summary="Adopt a staged rollout to balance value and execution risk.",
        confidence=0.8,
        risks=[make_risk_summary()],
        alternatives=[make_alternative_analysis()],
        expected_impact=DecisionImpact.HIGH,
    )


def make_executive_brief() -> ExecutiveBrief:
    """Create a valid executive brief for tests."""
    return ExecutiveBrief(
        title="Staged rollout recommendation",
        summary="A staged rollout is recommended for executive approval.",
        key_points=["Balances speed and control"],
        decision_required=True,
    )


def make_decision_package() -> DecisionPackage:
    """Create a valid decision package for tests."""
    return DecisionPackage(
        recommendation=make_recommendation(),
        executive_brief=make_executive_brief(),
        supporting_evidence=["reasoning:summary", "debate:consensus"],
        required_approvals=["Executive Committee"],
        metadata={"source": "unit-test"},
    )


def make_reasoning_result() -> ReasoningResult:
    """Create a minimal valid reasoning result for provider tests."""
    return ReasoningResult(
        session_id=SESSION_ID,
        reasoning_type=ReasoningType.STRATEGIC,
        confidence=0.75,
        summary="Reasoning supports staged rollout.",
    )


def make_debate_result() -> DebateResult:
    """Create a minimal valid debate result for provider tests."""
    return DebateResult(
        debate_id=DEBATE_ID,
        consensus=Consensus(
            level=ConsensusLevel.HIGH,
            summary="Debate supports staged rollout.",
        ),
        recommendations=["Use staged rollout"],
        confidence=0.7,
    )


def test_recommendation_type_values() -> None:
    """RecommendationType exposes all supported recommendation categories."""
    recommendation_types = {
        recommendation_type.value for recommendation_type in RecommendationType
    }
    assert recommendation_types == {
        "STRATEGIC",
        "OPERATIONAL",
        "FINANCIAL",
        "TECHNOLOGY",
        "LEGAL",
        "RISK",
        "PEOPLE",
        "INNOVATION",
    }


def test_decision_impact_values() -> None:
    """DecisionImpact exposes all supported impact levels."""
    assert {impact.value for impact in DecisionImpact} == {
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }


def test_risk_summary_validates_fields_probability_and_mitigation() -> None:
    """RiskSummary validates text, impact, probability, and mitigation."""
    risk = make_risk_summary()

    assert isinstance(risk.id, UUID)
    assert risk.impact == DecisionImpact.MEDIUM
    assert risk.probability == 0.4
    assert risk.created_at.tzinfo is not None
    assert risk.created_at.utcoffset() == UTC.utcoffset(risk.created_at)

    with pytest.raises(ValidationError):
        RiskSummary(title="   ", description="Description", impact=DecisionImpact.LOW)

    with pytest.raises(ValidationError):
        RiskSummary(title="Risk", description="   ", impact=DecisionImpact.LOW)

    with pytest.raises(ValidationError):
        RiskSummary(
            title="Risk",
            description="Description",
            impact=DecisionImpact.LOW,
            probability=1.1,
        )

    with pytest.raises(ValidationError):
        RiskSummary(
            title="Risk",
            description="Description",
            impact=DecisionImpact.LOW,
            mitigation="   ",
        )


def test_alternative_analysis_validates_text_lists_and_score() -> None:
    """AlternativeAnalysis validates text fields, lists, and score."""
    alternative = make_alternative_analysis()

    assert alternative.title == "Delay rollout"
    assert alternative.pros == ["Lower execution pressure"]
    assert alternative.cons == ["Delayed value capture"]
    assert alternative.score == 0.5

    with pytest.raises(ValidationError):
        AlternativeAnalysis(title="   ", summary="Summary")

    with pytest.raises(ValidationError):
        AlternativeAnalysis(title="Title", summary="   ")

    with pytest.raises(ValidationError):
        AlternativeAnalysis(title="Title", summary="Summary", pros=["   "])

    with pytest.raises(ValidationError):
        AlternativeAnalysis(title="Title", summary="Summary", cons=["   "])

    with pytest.raises(ValidationError):
        AlternativeAnalysis(title="Title", summary="Summary", score=-0.1)


def test_executive_brief_validates_text_and_key_points() -> None:
    """ExecutiveBrief validates text fields and key points."""
    brief = make_executive_brief()

    assert brief.title == "Staged rollout recommendation"
    assert brief.key_points == ["Balances speed and control"]
    assert brief.decision_required is True

    with pytest.raises(ValidationError):
        ExecutiveBrief(title="   ", summary="Summary")

    with pytest.raises(ValidationError):
        ExecutiveBrief(title="Title", summary="   ")

    with pytest.raises(ValidationError):
        ExecutiveBrief(title="Title", summary="Summary", key_points=["   "])


def test_recommendation_contains_required_architecture_fields() -> None:
    """Recommendation contains all required architecture fields."""
    recommendation = make_recommendation()

    assert isinstance(recommendation.id, UUID)
    assert recommendation.session_id == SESSION_ID
    assert recommendation.recommendation_type == RecommendationType.STRATEGIC
    assert recommendation.title == "Proceed with staged rollout"
    assert recommendation.confidence == 0.8
    assert len(recommendation.risks) == 1
    assert len(recommendation.alternatives) == 1
    assert recommendation.expected_impact == DecisionImpact.HIGH
    assert recommendation.created_at.tzinfo is not None
    assert recommendation.created_at.utcoffset() == UTC.utcoffset(
        recommendation.created_at
    )


def test_recommendation_validates_text_and_confidence() -> None:
    """Recommendation rejects blank text and invalid confidence."""
    with pytest.raises(ValidationError):
        Recommendation(
            session_id=SESSION_ID,
            recommendation_type=RecommendationType.STRATEGIC,
            title="   ",
            summary="Summary",
            expected_impact=DecisionImpact.HIGH,
        )

    with pytest.raises(ValidationError):
        Recommendation(
            session_id=SESSION_ID,
            recommendation_type=RecommendationType.STRATEGIC,
            title="Title",
            summary="   ",
            expected_impact=DecisionImpact.HIGH,
        )

    with pytest.raises(ValidationError):
        Recommendation(
            session_id=SESSION_ID,
            recommendation_type=RecommendationType.STRATEGIC,
            title="Title",
            summary="Summary",
            confidence=1.1,
            expected_impact=DecisionImpact.HIGH,
        )


def test_decision_package_contains_required_architecture_fields() -> None:
    """DecisionPackage contains recommendation, brief, evidence, and approvals."""
    package = make_decision_package()

    assert isinstance(package.id, UUID)
    assert isinstance(package.recommendation, Recommendation)
    assert isinstance(package.executive_brief, ExecutiveBrief)
    assert package.supporting_evidence == ["reasoning:summary", "debate:consensus"]
    assert package.required_approvals == ["Executive Committee"]
    assert package.metadata == {"source": "unit-test"}
    assert package.created_at.tzinfo is not None
    assert package.created_at.utcoffset() == UTC.utcoffset(package.created_at)


def test_decision_package_validates_lists_and_metadata() -> None:
    """DecisionPackage rejects blank list values and metadata keys."""
    recommendation = make_recommendation()
    brief = make_executive_brief()

    with pytest.raises(ValidationError):
        DecisionPackage(
            recommendation=recommendation,
            executive_brief=brief,
            supporting_evidence=["   "],
        )

    with pytest.raises(ValidationError):
        DecisionPackage(
            recommendation=recommendation,
            executive_brief=brief,
            required_approvals=["   "],
        )

    with pytest.raises(ValidationError):
        DecisionPackage(
            recommendation=recommendation,
            executive_brief=brief,
            metadata={"   ": "invalid"},
        )


def test_decision_models_reject_invalid_created_at() -> None:
    """Decision models reject non-UTC and naive created_at values."""
    with pytest.raises(ValidationError):
        ExecutiveBrief(
            title="Title",
            summary="Summary",
            created_at=datetime.now(),
        )

    with pytest.raises(ValidationError):
        ExecutiveBrief(
            title="Title",
            summary="Summary",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


class NotImplementedDecisionProvider(DecisionProvider):
    """Concrete test adapter that delegates to interface methods."""

    def build_recommendation(
        self,
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
    ) -> Recommendation:
        """Delegate to the interface method."""
        return super().build_recommendation(reasoning_result, debate_result)

    def build_executive_brief(
        self,
        recommendation: Recommendation,
    ) -> ExecutiveBrief:
        """Delegate to the interface method."""
        return super().build_executive_brief(recommendation)

    def build_decision_package(
        self,
        recommendation: Recommendation,
        executive_brief: ExecutiveBrief,
    ) -> DecisionPackage:
        """Delegate to the interface method."""
        return super().build_decision_package(recommendation, executive_brief)


def test_decision_provider_interface_methods_raise_not_implemented() -> None:
    """DecisionProvider interface methods are intentionally unimplemented."""
    provider = NotImplementedDecisionProvider()
    recommendation = make_recommendation()
    brief = make_executive_brief()

    with pytest.raises(NotImplementedError):
        provider.build_recommendation(make_reasoning_result(), make_debate_result())
    with pytest.raises(NotImplementedError):
        provider.build_executive_brief(recommendation)
    with pytest.raises(NotImplementedError):
        provider.build_decision_package(recommendation, brief)


class TestDecisionProvider(DecisionProvider):
    """Test double for verifying DecisionService delegation only."""

    def __init__(self) -> None:
        """Initialize reusable decision artifacts."""
        self.recommendation = make_recommendation()
        self.brief = make_executive_brief()
        self.package = make_decision_package()

    def build_recommendation(
        self,
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
    ) -> Recommendation:
        """Return configured recommendation."""
        del reasoning_result, debate_result
        return self.recommendation

    def build_executive_brief(
        self,
        recommendation: Recommendation,
    ) -> ExecutiveBrief:
        """Return configured executive brief."""
        del recommendation
        return self.brief

    def build_decision_package(
        self,
        recommendation: Recommendation,
        executive_brief: ExecutiveBrief,
    ) -> DecisionPackage:
        """Return configured decision package."""
        del recommendation, executive_brief
        return self.package


def test_decision_service_uses_provider_abstraction() -> None:
    """DecisionService delegates operations to the provider abstraction."""
    provider = TestDecisionProvider()
    service = DecisionService(provider)

    assert (
        service.build_recommendation(make_reasoning_result(), make_debate_result())
        == provider.recommendation
    )
    assert service.build_executive_brief(provider.recommendation) == provider.brief
    assert (
        service.build_decision_package(provider.recommendation, provider.brief)
        == provider.package
    )

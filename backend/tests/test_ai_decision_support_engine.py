"""Tests for the provider-backed Decision Support Engine."""

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ecos.context import (
    ContextElement,
    ContextObject,
    ContextPriority,
    ContextSourceType,
)
from ecos.core.container import Container
from ecos.core.exceptions import (
    DecisionProviderError,
    EmptyDecisionResponseError,
    IncompatibleDecisionSchemaError,
    InvalidDecisionAlternativeError,
    InvalidDecisionClassificationError,
    InvalidDecisionConfidenceError,
    InvalidDecisionResponseError,
    InvalidDecisionRiskError,
    InvalidStrategicAlignmentError,
    MissingDecisionEvidenceError,
    UnauthorizedDecisionApprovalError,
    UnauthorizedExecutionApprovalError,
)
from ecos.core.settings import Settings
from ecos.debate import Consensus, ConsensusLevel, DebateResult
from ecos.decision import (
    AIDecisionSupportEngine,
    DecisionContext,
    DecisionImpact,
    DecisionService,
    RecommendationType,
)
from ecos.domain import Objective, Organization
from ecos.events import EventType
from ecos.providers import (
    AIProvider,
    AIRequest,
    AIResponse,
    ProviderHealth,
    ProviderStatus,
    ProviderType,
    TokenUsage,
)
from ecos.reasoning import (
    Alternative,
    Hypothesis,
    ReasoningEvidence,
    ReasoningResult,
    ReasoningType,
    Tradeoff,
)
from ecos.runtime import CognitivePipeline, FakeDecisionProvider
from ecos.simulation import (
    Contingency,
    Scenario,
    ScenarioType,
    SimulationReport,
    SimulationRisk,
)

SESSION_ID = UUID("00000000-0000-4000-8000-0000000000e1")
DEBATE_ID = UUID("00000000-0000-4000-8000-0000000000e2")


class StubAIProvider(AIProvider):
    """Provider stub based only on the generic AIProvider contract."""

    def __init__(self, content: str, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.requests: list[AIRequest] = []
        self.before_generate: object | None = None

    def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        if callable(self.before_generate):
            self.before_generate()
        if self.error is not None:
            raise self.error
        return AIResponse.model_construct(
            request_id=request.id,
            provider=ProviderType.OPENAI,
            model=request.model,
            content=self.content,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=11, completion_tokens=22, total_tokens=33),
            latency_ms=44,
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=ProviderType.OPENAI, status=ProviderStatus.AVAILABLE
        )

    def stream(self, request: AIRequest) -> Iterator[str]:
        del request
        return iter(())

    def embeddings(self, input_text: str) -> list[float]:
        del input_text
        return []

    def list_models(self) -> list[str]:
        return ["decision-model"]


def valid_payload(**updates: object) -> dict[str, Any]:
    """Return a complete valid provider response payload."""
    payload: dict[str, Any] = {
        "objective": "Prepare governed expansion recommendation",
        "situation_summary": "Growth is possible, but capacity conflict remains.",
        "executive_summary": "Recommend a bounded pilot for human approval.",
        "recommended_action": "Run a governed pilot before scale-up.",
        "rationale": "The pilot preserves upside while exposing capacity constraints.",
        "supporting_evidence": [
            "Reasoning evidence: prior pilot reduced risk.",
            "Debate conflict: capacity remains disputed.",
            "Simulation scenario: worst case exposes service degradation.",
        ],
        "alternatives": [
            {
                "alternative_id": "pilot",
                "description": "Run a bounded pilot.",
                "benefits": ["Early learning", "Lower blast radius"],
                "risks": ["Pilot may not represent full scale"],
                "cost": "medium",
                "complexity": "medium",
                "strategic_alignment": 0.88,
                "estimated_impact": "High learning with controlled risk",
                "dependencies": ["Sponsor review"],
                "rejection_reason": None,
            },
            {
                "alternative_id": "full_scale",
                "description": "Scale immediately.",
                "benefits": ["Fast value capture"],
                "risks": ["Capacity shortfall", "Service degradation"],
                "cost": "high",
                "complexity": "high",
                "strategic_alignment": 0.62,
                "estimated_impact": "High upside with high risk",
                "dependencies": ["Capacity plan"],
                "rejection_reason": "Unresolved capacity conflict.",
            },
            {
                "alternative_id": "defer",
                "description": "Defer until evidence improves.",
                "benefits": ["More certainty"],
                "risks": ["Lost market window"],
                "cost": "low",
                "complexity": "low",
                "strategic_alignment": 0.4,
                "estimated_impact": "Lower immediate risk and lower upside",
                "dependencies": [],
                "rejection_reason": "Delays learning unnecessarily.",
            },
        ],
        "tradeoffs": [
            {
                "dimension_a": "speed",
                "dimension_b": "control",
                "explanation": "Pilot reduces speed but improves control.",
                "organizational_impact": "Requires staged governance.",
            }
        ],
        "risks": [
            {
                "description": "Capacity shortfall",
                "probability": 0.45,
                "impact": "Service quality may degrade.",
                "severity": "high",
                "mitigation": "Set capacity gates before scale-up.",
                "owner_role": "Operations",
                "related_scenario": "worst_case",
            }
        ],
        "expected_outcomes": {
            "short_term": ["Pilot readiness review"],
            "medium_term": ["Validated capacity threshold"],
            "long_term": ["Governed scalable rollout"],
            "measurable_indicators": ["Capacity utilization", "Support backlog"],
        },
        "dependencies": ["Capacity baseline", "Sponsor review"],
        "required_approvals": ["Executive sponsor"],
        "next_actions": ["Prepare pilot charter", "Review capacity gates"],
        "unresolved_questions": ["Can support capacity scale?"],
        "remaining_uncertainties": ["Demand durability"],
        "confidence": 0.78,
        "strategic_alignment": 0.84,
        "recommendation_classification": "strategic",
        "decision_package": {
            "executive_summary": "Human approval should evaluate the pilot.",
            "recommendation": "Run a governed pilot before scale-up.",
            "evidence": ["Prior pilots reduced risk."],
            "alternatives": ["pilot", "full_scale", "defer"],
            "tradeoffs": ["speed vs control"],
            "risk_summary": ["Capacity shortfall"],
            "scenario_summary": ["Worst case degrades service."],
            "implementation_considerations": ["Use stage gates."],
            "expected_outcomes": {
                "short_term": ["Pilot readiness review"],
                "medium_term": ["Validated capacity threshold"],
                "long_term": ["Governed scalable rollout"],
                "measurable_indicators": ["Capacity utilization"],
            },
            "required_approvals": ["Executive sponsor"],
            "dependencies": ["Capacity baseline"],
            "next_actions": ["Prepare pilot charter"],
            "confidence": 0.78,
            "unresolved_issues": ["Support capacity"],
        },
    }
    payload.update(updates)
    return payload


def decision_context() -> DecisionContext:
    organization = Organization(name="ACME")
    objective = Objective(
        organization_id=organization.id,
        title="Prepare governed expansion recommendation",
    )
    context = ContextObject(
        session_id=SESSION_ID,
        objective=objective,
        elements=[
            ContextElement(
                source_type=ContextSourceType.USER,
                priority=ContextPriority.HIGH,
                title="Objective",
                content=objective.title,
                confidence=0.9,
            ),
            ContextElement(
                source_type=ContextSourceType.POLICY,
                priority=ContextPriority.HIGH,
                title="Risk policy",
                content="Strategic changes require human approval.",
                confidence=0.95,
            ),
        ],
        confidence=0.9,
    )
    reasoning = ReasoningResult(
        session_id=SESSION_ID,
        reasoning_type=ReasoningType.STRATEGIC,
        hypotheses=[
            Hypothesis(
                statement="Pilot reduces risk.",
                rationale="Prior evidence supports staged rollout.",
                confidence=0.86,
            )
        ],
        alternatives=[
            Alternative(title="Pilot", description="Run a bounded pilot.", score=0.88),
            Alternative(title="Scale", description="Scale immediately.", score=0.62),
            Alternative(title="Defer", description="Wait for evidence.", score=0.4),
        ],
        tradeoffs=[
            Tradeoff(
                dimension="speed-control",
                benefit="Controlled learning",
                cost="Slower rollout",
                severity=0.3,
            )
        ],
        evidence=[
            ReasoningEvidence(
                source="memory",
                content="Prior pilot reduced risk.",
                confidence=0.9,
            )
        ],
        confidence=0.82,
        summary="Reasoning recommends a pilot.",
        report={
            "assumptions": ["Demand persists"],
            "risks": ["Capacity shortfall"],
            "opportunities": ["Learn early"],
            "recommendation": "Pilot",
        },
    )
    debate = DebateResult(
        debate_id=DEBATE_ID,
        consensus=Consensus(
            level=ConsensusLevel.MEDIUM,
            summary="Pilot has partial consensus.",
            agreements=["Governance is required"],
            disagreements=["Capacity readiness remains disputed"],
        ),
        recommendations=["Use pilot gates"],
        unresolved_questions=["Can support capacity scale?"],
        confidence=0.7,
        report={
            "supporting_arguments": ["Pilot controls risk"],
            "opposing_arguments": ["Pilot delays market entry"],
            "counterarguments": ["Delay is bounded"],
            "contradictions": ["Capacity conflict"],
            "weak_assumptions": ["Demand persists"],
            "evidence_gaps": ["No current capacity audit"],
            "blind_spots": ["Support teams"],
            "ignored_stakeholders": ["Customer support"],
            "outstanding_questions": ["Can support capacity scale?"],
        },
    )
    risk = SimulationRisk(
        description="Capacity shortfall",
        probability=0.45,
        impact="Service quality may degrade.",
        severity="high",
        mitigation="Set capacity gates.",
        early_warning_signal="Backlog growth",
        owner_role="Operations",
    )
    simulation = SimulationReport(
        session_id=SESSION_ID,
        objective=objective.title,
        critical_assumptions=["Demand persists"],
        scenarios=[
            Scenario(
                scenario_id=item.value,
                scenario_type=item,
                name=item.value,
                description=f"{item.value} scenario",
                assumptions=["Capacity can be measured"],
                trigger_conditions=["Demand shift"],
                probability=probability,
                early_warning_signals=["Backlog growth"],
                impacts={"operational": "material"},
                risks=[risk],
                opportunities=["Learn early"],
                second_order_effects=["Team load changes"],
                failure_modes=["Service degradation"],
                success_factors=["Capacity gates"],
                mitigation_actions=["Pilot"],
                recovery_options=["Rollback"],
            )
            for item, probability in (
                (ScenarioType.BEST_CASE, 0.35),
                (ScenarioType.EXPECTED_CASE, 0.55),
                (ScenarioType.WORST_CASE, 0.25),
                (ScenarioType.BLACK_SWAN, 0.01),
            )
        ],
        cross_scenario_risks=[risk],
        cross_scenario_opportunities=["Bounded pilot"],
        second_order_effects=["Operational load shifts"],
        failure_modes=["Capacity collapse"],
        success_factors=["Governance gates"],
        contingencies=[
            Contingency(
                primary_plan="Pilot",
                fallback_plan="Reduce scope",
                emergency_plan="Stop",
                recovery_plan="Rollback",
                exit_strategy="Governed exit",
                activation_conditions=["Threshold breach"],
            )
        ],
        resilience_score=0.68,
        confidence=0.66,
        executive_assessment="Unfavorable scenario remains manageable with gates.",
    )
    return DecisionContext(
        session_id=SESSION_ID,
        objective=objective.model_dump(mode="json"),
        unified_context=context,
        constraints=["Budget is fixed"],
        relevant_policies=["Strategic changes require human approval."],
        memory=[{"summary": "Prior pilot reduced risk."}],
        reasoning_report=reasoning,
        debate_report=debate,
        simulation_report=simulation,
    )


def engine(provider: StubAIProvider) -> AIDecisionSupportEngine:
    return AIDecisionSupportEngine(provider, ProviderType.OPENAI, "decision-model")


def run_valid(
    content: str | None = None,
    context: DecisionContext | None = None,
) -> tuple[StubAIProvider, Any, Any, Any]:
    provider = StubAIProvider(content or json.dumps(valid_payload()))
    decision_engine = engine(provider)
    context = context or decision_context()
    recommendation = decision_engine.build_recommendation(
        context.reasoning_report,
        context.debate_report,
        context,
    )
    brief = decision_engine.build_executive_brief(recommendation)
    package = decision_engine.build_decision_package(recommendation, brief)
    return provider, recommendation, brief, package


def test_injected_stub_provider_builds_complete_ai_request() -> None:
    context = decision_context()
    original = context.model_dump(mode="json")
    provider, recommendation, _, _ = run_valid(context=context)

    request = provider.requests[0]
    payload = json.loads(request.messages[1]["content"])
    assert request.provider is ProviderType.OPENAI
    assert request.model == "decision-model"
    assert request.metadata == {"session_id": str(SESSION_ID)}
    assert payload["objective"] == original["objective"]
    assert payload["unified_context"] == original["unified_context"]
    assert payload["constraints"] == ["Budget is fixed"]
    assert payload["relevant_policies"] == ["Strategic changes require human approval."]
    assert payload["memory"] == [{"summary": "Prior pilot reduced risk."}]
    assert payload["reasoning_report"] == original["reasoning_report"]
    assert payload["debate_report"] == original["debate_report"]
    assert payload["simulation_report"] == original["simulation_report"]
    prompt = " ".join(request.messages[0]["content"].split())
    assert "private chain-of-thought" in prompt
    assert "not a decision" in prompt
    assert "execution was authorized" in prompt
    assert context.model_dump(mode="json") == original
    assert recommendation.recommendation_type is RecommendationType.STRATEGIC


def test_valid_json_and_markdown_fence_convert_to_public_contract() -> None:
    for content in (
        json.dumps(valid_payload()),
        f"```json\n{json.dumps(valid_payload())}\n```",
    ):
        _, recommendation, brief, package = run_valid(content)
        assert recommendation.summary == "Recommend a bounded pilot for human approval."
        assert recommendation.confidence == 0.78
        assert recommendation.expected_impact is DecisionImpact.HIGH
        assert [item.title for item in recommendation.alternatives] == [
            "pilot",
            "full_scale",
            "defer",
        ]
        assert recommendation.risks[0].mitigation == (
            "Set capacity gates before scale-up."
        )
        assert brief.decision_required is True
        assert package.supporting_evidence[0].startswith("Reasoning evidence")
        assert package.required_approvals == ["Executive sponsor"]
        assert package.metadata["classification"] == "strategic"
        assert package.metadata["confidence"] == 0.78


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("   ", EmptyDecisionResponseError),
        ("not-json", InvalidDecisionResponseError),
        (json.dumps({"objective": "missing"}), IncompatibleDecisionSchemaError),
    ],
)
def test_rejects_empty_invalid_json_and_missing_schema(
    content: str, error: type[Exception]
) -> None:
    context = decision_context()
    with pytest.raises(error):
        engine(StubAIProvider(content)).build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )


@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("confidence",), -0.1, InvalidDecisionConfidenceError),
        (("confidence",), 1.1, InvalidDecisionConfidenceError),
        (("strategic_alignment",), 1.1, InvalidStrategicAlignmentError),
        (
            ("recommendation_classification",),
            "unknown",
            InvalidDecisionClassificationError,
        ),
        (("supporting_evidence",), [], MissingDecisionEvidenceError),
    ],
)
def test_rejects_invalid_top_level_values(
    path: tuple[str, ...], value: object, error: type[Exception]
) -> None:
    payload = valid_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    context = decision_context()
    with pytest.raises(error):
        engine(StubAIProvider(json.dumps(payload))).build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )


def test_rejects_incompatible_structures_and_extra_fields() -> None:
    payload = valid_payload()
    payload["unexpected"] = "extra"
    context = decision_context()
    with pytest.raises(IncompatibleDecisionSchemaError):
        engine(StubAIProvider(json.dumps(payload))).build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["alternatives"].__setitem__(
            1, {**payload["alternatives"][1], "alternative_id": "pilot"}
        ),
        lambda payload: payload["alternatives"][0].__setitem__("benefits", []),
        lambda payload: payload["alternatives"][0].__setitem__("risks", []),
        lambda payload: payload["alternatives"][0].__setitem__("estimated_impact", ""),
    ],
)
def test_rejects_invalid_alternatives(mutate: object) -> None:
    payload = valid_payload()
    mutate(payload)
    context = decision_context()
    with pytest.raises(InvalidDecisionAlternativeError):
        engine(StubAIProvider(json.dumps(payload))).build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["risks"][0].__setitem__("impact", ""),
        lambda payload: payload["risks"][0].__setitem__("mitigation", ""),
    ],
)
def test_rejects_invalid_risks(mutate: object) -> None:
    payload = valid_payload()
    mutate(payload)
    context = decision_context()
    with pytest.raises(InvalidDecisionRiskError):
        engine(StubAIProvider(json.dumps(payload))).build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )


@pytest.mark.parametrize(
    ("field", "text", "error"),
    [
        (
            "rationale",
            "The decision approved by leadership is ready.",
            UnauthorizedDecisionApprovalError,
        ),
        (
            "recommended_action",
            "Execution authorized for immediate rollout.",
            UnauthorizedExecutionApprovalError,
        ),
    ],
)
def test_rejects_approval_or_execution_authorization_claims(
    field: str, text: str, error: type[Exception]
) -> None:
    payload = valid_payload(**{field: text})
    context = decision_context()
    with pytest.raises(error):
        engine(StubAIProvider(json.dumps(payload))).build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )


def test_preserves_alternatives_risks_open_questions_and_uncertainties() -> None:
    _, recommendation, _, package = run_valid()
    assert len(recommendation.alternatives) == 3
    assert recommendation.risks[0].description == "Capacity shortfall"
    assert package.metadata["alternative_count"] == 3
    assert package.metadata["risk_count"] == 1
    assert "Support capacity" in package.executive_brief.key_points
    assert "Demand durability" in json.dumps(valid_payload()["remaining_uncertainties"])


def test_provider_error_is_propagated_safely() -> None:
    provider_error = RuntimeError("raw provider response with secret")
    context = decision_context()
    with pytest.raises(DecisionProviderError, match="AI provider failed") as captured:
        engine(StubAIProvider("{}", error=provider_error)).build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )
    assert captured.value.__cause__ is provider_error
    assert "secret" not in str(captured.value)


def test_runtime_event_order_and_no_completion_on_failure() -> None:
    pipeline = CognitivePipeline.with_fakes()
    provider = StubAIProvider(json.dumps(valid_payload()))
    provider.before_generate = lambda: (
        (
            EventType.ENGINE_INVOKED
            in [envelope.event.event_type for envelope in pipeline.event_bus.envelopes]
        )
        or pytest.fail("EngineInvoked must precede provider call")
    )
    pipeline.decision_service = DecisionService(engine(provider))

    pipeline.run("Prepare decision support")

    types = [envelope.event.event_type for envelope in pipeline.event_bus.envelopes]
    assert EventType.ENGINE_INVOKED in types
    assert EventType.ENGINE_COMPLETED in types
    assert types.index(EventType.ENGINE_INVOKED) < types.index(
        EventType.ENGINE_COMPLETED
    )

    failing = CognitivePipeline.with_fakes()
    failing.decision_service = DecisionService(
        engine(StubAIProvider("{}", error=RuntimeError("down")))
    )
    with pytest.raises(RuntimeError, match="AI provider failed"):
        failing.run("Fail decision support")
    failure_types = [item.event.event_type for item in failing.event_bus.envelopes]
    assert EventType.ENGINE_FAILED in failure_types
    assert EventType.PIPELINE_COMPLETED not in failure_types


def test_container_selects_fake_or_provider_backed_decision_engine() -> None:
    fake_container = Container(settings=Settings(ai_provider="fake"))
    assert isinstance(fake_container.decision_provider, FakeDecisionProvider)

    openai_container = Container(
        settings=Settings(ai_provider="openai", openai_api_key="test-key")
    )
    assert isinstance(openai_container.decision_provider, AIDecisionSupportEngine)


def test_decision_support_modules_do_not_import_openai() -> None:
    decision_dir = Path(__file__).parents[1] / "src" / "ecos" / "decision"
    engine_dirs = [
        Path(__file__).parents[1] / "src" / "ecos" / item
        for item in ("reasoning", "debate", "simulation", "decision")
    ]
    for directory in engine_dirs:
        for path in directory.glob("*.py"):
            assert "import openai" not in path.read_text()
    assert "openai" not in (decision_dir / "ai_engine.py").read_text().lower()


def test_prompt_does_not_request_private_chain_of_thought() -> None:
    provider, _, _, _ = run_valid()
    prompt = " ".join(provider.requests[0].messages[0]["content"].lower().split())
    assert "step-by-step internal reasoning" in prompt
    assert "private chain-of-thought" in prompt
    assert "provide private chain-of-thought" not in prompt


def test_no_partial_package_is_available_after_invalid_response() -> None:
    payload = valid_payload()
    payload["risks"][0]["mitigation"] = ""
    decision_engine = engine(StubAIProvider(json.dumps(payload)))
    context = decision_context()
    with pytest.raises(InvalidDecisionRiskError):
        decision_engine.build_recommendation(
            context.reasoning_report,
            context.debate_report,
            context,
        )


def test_valid_input_objects_are_not_mutated() -> None:
    context = decision_context()
    original = deepcopy(context.model_dump(mode="json"))
    decision_engine = engine(StubAIProvider(json.dumps(valid_payload())))
    recommendation = decision_engine.build_recommendation(
        context.reasoning_report,
        context.debate_report,
        context,
    )
    decision_engine.build_decision_package(
        recommendation,
        decision_engine.build_executive_brief(recommendation),
    )
    assert context.model_dump(mode="json") == original

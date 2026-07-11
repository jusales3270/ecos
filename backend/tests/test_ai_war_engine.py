"""Tests for provider-backed exploratory strategic simulation."""

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ecos.core.exceptions import (
    EmptyWarResponseError,
    IncompatibleWarSchemaError,
    InvalidResilienceScoreError,
    InvalidWarConfidenceError,
    InvalidWarProbabilityError,
    InvalidWarResponseError,
    InvalidWarRiskError,
    InvalidWarScenarioTypeError,
    MissingWarScenarioError,
    WarProviderError,
)
from ecos.debate import Consensus, ConsensusLevel, DebateResult
from ecos.providers import (
    AIProvider,
    AIRequest,
    AIResponse,
    ProviderHealth,
    ProviderStatus,
    ProviderType,
    TokenUsage,
)
from ecos.reasoning import ReasoningResult, ReasoningType
from ecos.simulation import AIWarEngine, ScenarioType, SimulationContext

SESSION_ID = UUID("00000000-0000-4000-8000-000000000016")


class StubAIProvider(AIProvider):
    def __init__(self, content: str, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.requests: list[AIRequest] = []

    def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        if self.error:
            raise self.error
        return AIResponse.model_construct(
            request_id=request.id,
            provider=ProviderType.OPENAI,
            model=request.model,
            content=self.content,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            latency_ms=4,
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
        return ["stub-model"]


def _risk() -> dict[str, object]:
    return {
        "description": "Cascade risk",
        "probability": 0.3,
        "impact": "high",
        "severity": "high",
        "mitigation": "Stage rollout",
        "early_warning_signal": "Capacity degradation",
        "owner_role": "Operations",
    }


def _scenario(kind: str, probability: float) -> dict[str, object]:
    return {
        "scenario_id": kind,
        "scenario_type": kind,
        "name": kind,
        "description": f"Explore {kind}",
        "assumptions": ["Demand remains observable"],
        "trigger_conditions": ["Demand changes"],
        "probability": probability,
        "early_warning_signals": ["Demand signal"],
        "impacts": {"financial": "material", "operational": "manageable"},
        "risks": [_risk()],
        "opportunities": ["Learn early"],
        "second_order_effects": ["Capacity shifts"],
        "failure_modes": ["Overextension"],
        "success_factors": ["Governance"],
        "mitigation_actions": ["Pilot"],
        "recovery_options": ["Rollback"],
    }


def _payload() -> dict[str, Any]:
    return {
        "objective": "Assess expansion",
        "critical_assumptions": ["Demand persists"],
        "scenarios": [
            _scenario("best_case", 0.4),
            _scenario("expected_case", 0.6),
            _scenario("worst_case", 0.25),
            _scenario("black_swan", 0.01),
        ],
        "cross_scenario_risks": [_risk()],
        "cross_scenario_opportunities": ["Bounded pilot"],
        "second_order_effects": ["Competitors respond"],
        "failure_modes": ["Capacity collapse"],
        "success_factors": ["Fast feedback"],
        "contingencies": [
            {
                "primary_plan": "Pilot",
                "fallback_plan": "Reduce scope",
                "emergency_plan": "Stop",
                "recovery_plan": "Rollback",
                "exit_strategy": "Orderly exit",
                "activation_conditions": ["Threshold exceeded"],
            }
        ],
        "resilience_score": 0.7,
        "confidence": 0.65,
        "executive_assessment": "Resilient if governance remains active.",
    }


def _context() -> SimulationContext:
    reasoning = ReasoningResult(
        session_id=SESSION_ID,
        reasoning_type=ReasoningType.STRATEGIC,
        summary="Initial recommendation",
        confidence=0.7,
        report={"assumptions": ["Demand persists"], "risks": [_risk()]},
    )
    debate = DebateResult(
        debate_id=UUID("00000000-0000-4000-8000-000000000017"),
        consensus=Consensus(
            level=ConsensusLevel.MEDIUM,
            summary="Conflict remains",
            disagreements=["Timing"],
        ),
        unresolved_questions=["Can capacity scale?"],
        confidence=0.6,
        report={
            "contradictions": ["Capacity conflict"],
            "outstanding_questions": ["Can capacity scale?"],
            "blind_spots": ["Supplier concentration"],
        },
    )
    return SimulationContext(
        session_id=SESSION_ID,
        objective={"title": "Assess expansion"},
        unified_context={"evidence": ["Market study"]},
        organizational_constraints=["Board approval"],
        relevant_policies=["Risk policy"],
        memory=[{"summary": "Prior pilot"}],
        reasoning_report=reasoning,
        debate_report=debate,
        external_signals=[{"signal": "Demand"}],
    )


def _engine(
    payload: dict[str, Any] | None = None,
) -> tuple[AIWarEngine, StubAIProvider]:
    provider = StubAIProvider(json.dumps(payload or _payload()))
    return AIWarEngine(provider, ProviderType.OPENAI, "stub-model"), provider


def test_builds_provider_neutral_request_with_complete_inputs() -> None:
    engine, provider = _engine()
    context = _context()
    original = context.model_dump(mode="json")

    report = engine.simulate(context)

    request = provider.requests[0]
    body = json.loads(request.messages[1]["content"])
    assert body["reasoning_report"] == original["reasoning_report"]
    assert body["debate_report"] == original["debate_report"]
    assert body["debate_report"]["report"]["contradictions"] == ["Capacity conflict"]
    assert body["debate_report"]["unresolved_questions"] == ["Can capacity scale?"]
    assert context.model_dump(mode="json") == original
    assert request.provider is ProviderType.OPENAI
    assert "private chain-of-thought" in request.messages[0]["content"]
    assert "authorize or execute" in request.messages[0]["content"]
    assert {item.scenario_type for item in report.scenarios} >= {
        ScenarioType.BEST_CASE,
        ScenarioType.EXPECTED_CASE,
        ScenarioType.WORST_CASE,
        ScenarioType.BLACK_SWAN,
    }


def test_parses_simple_json_markdown_fence_and_preserves_adverse_scenarios() -> None:
    provider = StubAIProvider(f"```json\n{json.dumps(_payload())}\n```")
    report = AIWarEngine(provider, ProviderType.OPENAI, "stub-model").simulate(
        _context()
    )
    assert any(
        item.scenario_type is ScenarioType.WORST_CASE for item in report.scenarios
    )
    assert any(
        item.scenario_type is ScenarioType.BLACK_SWAN for item in report.scenarios
    )
    assert report.cross_scenario_risks
    assert report.contingencies


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("", EmptyWarResponseError),
        ("not-json", InvalidWarResponseError),
        (json.dumps({"objective": "x"}), IncompatibleWarSchemaError),
    ],
)
def test_rejects_empty_invalid_and_incomplete_responses(
    content: str, error: type[Exception]
) -> None:
    provider = StubAIProvider(content)
    with pytest.raises(error):
        AIWarEngine(provider, ProviderType.OPENAI, "stub-model").simulate(_context())


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: value.update(confidence=-0.1), InvalidWarConfidenceError),
        (lambda value: value.update(confidence=1.1), InvalidWarConfidenceError),
        (lambda value: value.update(resilience_score=1.1), InvalidResilienceScoreError),
        (
            lambda value: value["scenarios"][0].update(probability=-0.1),
            InvalidWarProbabilityError,
        ),
        (
            lambda value: value["scenarios"][0].update(probability=1.1),
            InvalidWarProbabilityError,
        ),
        (
            lambda value: value["scenarios"][0].update(scenario_type="unknown"),
            InvalidWarScenarioTypeError,
        ),
        (lambda value: value["scenarios"].pop(), MissingWarScenarioError),
        (
            lambda value: value["scenarios"][1].update(scenario_id="best_case"),
            IncompatibleWarSchemaError,
        ),
        (
            lambda value: value["cross_scenario_risks"][0].pop("mitigation"),
            InvalidWarRiskError,
        ),
        (lambda value: value.update(extra_field=True), IncompatibleWarSchemaError),
    ],
)
def test_strict_validation(mutate: Any, error: type[Exception]) -> None:
    payload = deepcopy(_payload())
    mutate(payload)
    engine, _ = _engine(payload)
    with pytest.raises(error):
        engine.simulate(_context())


def test_rejects_certain_black_swan() -> None:
    payload = _payload()
    payload["scenarios"][-1]["probability"] = 1.0
    engine, _ = _engine(payload)
    with pytest.raises(InvalidWarProbabilityError):
        engine.simulate(_context())


def test_wraps_provider_failure_without_exposing_raw_content() -> None:
    provider = StubAIProvider("secret response", RuntimeError("sdk secret"))
    with pytest.raises(WarProviderError) as caught:
        AIWarEngine(provider, ProviderType.OPENAI, "stub-model").simulate(_context())
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "secret" not in str(caught.value)


def test_no_cognitive_engine_imports_openai_sdk() -> None:
    source_root = Path(__file__).parents[1] / "src" / "ecos"
    engine_sources = [
        source_root / "reasoning" / "ai_engine.py",
        source_root / "debate" / "ai_engine.py",
        source_root / "simulation" / "ai_engine.py",
    ]
    for source in engine_sources:
        content = source.read_text(encoding="utf-8")
        assert "import openai" not in content
        assert "from openai" not in content

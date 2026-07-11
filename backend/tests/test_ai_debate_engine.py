"""Tests for the provider-backed Debate Engine."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest

from ecos.context import ContextObject
from ecos.core.exceptions import (
    DebateProviderError,
    EmptyDebateResponseError,
    IncompatibleDebateSchemaError,
    InvalidDebateConfidenceError,
    InvalidDebateConsensusError,
    InvalidDebateResponseError,
    InvalidDebateSpecialistReferenceError,
)
from ecos.debate import AIDebateEngine, ConsensusLevel, Debate
from ecos.domain import Objective
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
from ecos.specialists import Contribution, ContributionType, Specialist, SpecialistType


class StubAIProvider(AIProvider):
    def __init__(self, content: str, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.requests: list[AIRequest] = []

    def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return AIResponse.model_construct(
            request_id=request.id,
            provider=ProviderType.OPENAI,
            model=request.model,
            content=self.content,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            latency_ms=12,
        )

    def stream(self, request: AIRequest) -> Iterator[str]:
        del request
        return iter(())

    def embeddings(self, input_text: str) -> list[float]:
        del input_text
        raise NotImplementedError

    def list_models(self) -> list[str]:
        return ["test-model"]

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=ProviderType.OPENAI, status=ProviderStatus.AVAILABLE
        )


def _payload(specialists: list[Specialist]) -> dict[str, Any]:
    return {
        "objective": "Assess expansion",
        "participants": [str(item.id) for item in specialists],
        "supporting_arguments": [
            {
                "specialist_id": str(specialists[0].id),
                "origin": None,
                "claim": "Expansion creates growth",
                "justification": "Demand evidence supports it",
                "evidence": ["market study"],
                "assumptions": ["demand persists"],
                "confidence": 0.7,
                "impact": "high",
            }
        ],
        "opposing_arguments": [
            {
                "specialist_id": str(specialists[1].id),
                "origin": None,
                "claim": "Expansion increases exposure",
                "justification": "Execution capacity is limited",
                "evidence": ["capacity review"],
                "assumptions": ["hiring remains slow"],
                "confidence": 0.8,
                "impact": "high",
            }
        ],
        "counterarguments": [],
        "agreements": ["Governance is required"],
        "disagreements": ["Timing remains disputed"],
        "contradictions": [
            {
                "participants": [str(item.id) for item in specialists],
                "divergence": "Whether capacity is sufficient",
                "evidence_by_side": {
                    "growth": ["market study"],
                    "risk": ["capacity review"],
                },
                "resolution_condition": "Complete a capacity audit",
                "resolved": False,
            }
        ],
        "weak_assumptions": ["Stable demand"],
        "evidence_gaps": ["No pilot data"],
        "blind_spots": ["Supplier concentration"],
        "ignored_stakeholders": ["Support teams"],
        "unconsidered_consequences": ["Service degradation"],
        "risks": [
            {
                "description": "Capacity shortfall",
                "probability": 0.4,
                "impact": "high",
                "mitigation": "Pilot first",
            }
        ],
        "opportunities": ["Run a bounded pilot"],
        "outstanding_questions": ["Can capacity scale?"],
        "consensus_level": 3,
        "confidence": 0.75,
        "final_cognitive_summary": (
            "Evidence supports a pilot while capacity remains disputed."
        ),
    }


def _debate() -> tuple[Debate, list[Specialist]]:
    specialists = [
        Specialist(
            name="Strategy", type=SpecialistType.STRATEGY, description="Strategy view"
        ),
        Specialist(name="Risk", type=SpecialistType.RISK, description="Risk view"),
    ]
    objective = Objective(
        organization_id=UUID("00000000-0000-4000-8000-000000000001"),
        title="Assess expansion",
    )
    context = ContextObject(
        session_id=UUID("00000000-0000-4000-8000-000000000002"),
        objective=objective,
        confidence=0.8,
    )
    reasoning = ReasoningResult(
        session_id=context.session_id,
        reasoning_type=ReasoningType.STRATEGIC,
        confidence=0.7,
        summary="Initial recommendation",
    )
    contributions = [
        Contribution(
            specialist_id=item.id,
            contribution_type=ContributionType.OPINION,
            content=f"Independent opinion from {item.name}",
            confidence=0.8,
        )
        for item in specialists
    ]
    return (
        Debate(
            session_id=context.session_id,
            specialists=specialists,
            objective=objective.title,
            unified_context=context.model_dump(mode="json"),
            reasoning_result=reasoning,
            contributions=contributions,
        ),
        specialists,
    )


def test_build_request_includes_reasoning_and_all_contributions_equally() -> None:
    debate, specialists = _debate()
    engine = AIDebateEngine(StubAIProvider("{}"), ProviderType.OPENAI, "test-model")

    request = engine.build_request(debate)
    content = json.loads(request.messages[1]["content"])

    assert content["reasoning_report"] == debate.reasoning_result.model_dump(
        mode="json"
    )
    assert content["specialist_contributions"] == [
        item.model_dump(mode="json") for item in debate.contributions
    ]
    assert [item["specialist_id"] for item in content["specialist_contributions"]] == [
        str(item.id) for item in specialists
    ]
    assert request.metadata == {"session_id": str(debate.session_id)}


def test_valid_json_and_markdown_are_parsed_and_preserve_disagreement() -> None:
    debate, specialists = _debate()
    payload = json.dumps(_payload(specialists))
    for content in (payload, f"```json\n{payload}\n```"):
        result = AIDebateEngine(
            StubAIProvider(content), ProviderType.OPENAI, "model"
        ).finalize(debate)
        assert result.consensus.level is ConsensusLevel.MEDIUM
        assert "Timing remains disputed" in result.consensus.disagreements
        assert any("unresolved" in item for item in result.consensus.disagreements)
        assert result.unresolved_questions == ["Can capacity scale?"]


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (" ", EmptyDebateResponseError),
        ("not-json", InvalidDebateResponseError),
        (json.dumps({}), IncompatibleDebateSchemaError),
    ],
)
def test_rejects_invalid_responses(content: str, error: type[Exception]) -> None:
    debate, _ = _debate()
    with pytest.raises(error):
        AIDebateEngine(StubAIProvider(content), ProviderType.OPENAI, "model").finalize(
            debate
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_rejects_invalid_confidence(confidence: float) -> None:
    debate, specialists = _debate()
    payload = _payload(specialists)
    payload["confidence"] = confidence
    with pytest.raises(InvalidDebateConfidenceError):
        AIDebateEngine(
            StubAIProvider(json.dumps(payload)), ProviderType.OPENAI, "model"
        ).finalize(debate)


@pytest.mark.parametrize("level", [0, 6])
def test_rejects_invalid_consensus(level: int) -> None:
    debate, specialists = _debate()
    payload = _payload(specialists)
    payload["consensus_level"] = level
    with pytest.raises(InvalidDebateConsensusError):
        AIDebateEngine(
            StubAIProvider(json.dumps(payload)), ProviderType.OPENAI, "model"
        ).finalize(debate)


def test_rejects_unknown_specialist_reference() -> None:
    debate, specialists = _debate()
    payload = _payload(specialists)
    payload["supporting_arguments"][0]["specialist_id"] = (
        "00000000-0000-4000-8000-000000000099"
    )
    with pytest.raises(InvalidDebateSpecialistReferenceError):
        AIDebateEngine(
            StubAIProvider(json.dumps(payload)), ProviderType.OPENAI, "model"
        ).finalize(debate)


def test_provider_failure_is_safely_chained() -> None:
    debate, _ = _debate()
    with pytest.raises(DebateProviderError) as captured:
        AIDebateEngine(
            StubAIProvider("", RuntimeError("secret response")),
            ProviderType.OPENAI,
            "model",
        ).finalize(debate)
    assert isinstance(captured.value.__cause__, RuntimeError)
    assert "secret response" not in str(captured.value)


def test_debate_module_does_not_import_openai() -> None:
    from pathlib import Path

    debate_dir = Path(__file__).parents[1] / "src" / "ecos" / "debate"
    assert "import openai" not in "\n".join(
        path.read_text() for path in debate_dir.glob("*.py")
    )

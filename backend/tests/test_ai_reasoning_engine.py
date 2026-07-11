"""Provider-neutral tests for the AI-backed Reasoning Engine."""

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest

from ecos.context import (
    ContextElement,
    ContextObject,
    ContextPriority,
    ContextSourceType,
)
from ecos.core.exceptions import (
    EmptyReasoningResponseError,
    IncompatibleReasoningSchemaError,
    InvalidReasoningResponseError,
    ReasoningProviderError,
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
    AIReasoningEngine,
    ReasoningContext,
    ReasoningService,
    ReasoningType,
)
from ecos.runtime import CognitivePipeline

SESSION_ID = UUID("00000000-0000-4000-8000-000000000016")


def valid_report(**updates: object) -> str:
    report: dict[str, object] = {
        "problem_statement": "Choose a governed path.",
        "summary": "Evidence supports a staged rollout.",
        "hypotheses": [
            {
                "statement": "Staging reduces risk.",
                "rationale": "Evidence favors validation.",
                "confidence": 0.8,
            }
        ],
        "alternatives": [
            {
                "title": "Stage rollout",
                "description": "Start with a pilot.",
                "benefits": ["Early learning"],
                "costs": ["More time"],
                "risks": ["Pilot bias"],
                "complexity": "medium",
                "expected_impact": "Reduced execution risk",
                "score": 0.85,
            }
        ],
        "assumptions": ["Pilot users are representative"],
        "risks": [
            {
                "description": "Delay",
                "impact": "medium",
                "mitigation": "Timebox the pilot",
            }
        ],
        "opportunities": ["Learn before scaling"],
        "recommendation": "Run a timeboxed pilot.",
        "confidence": 0.82,
        "evidence_used": [
            {
                "source": "context",
                "content": "Prior pilots reduced risk.",
                "confidence": 0.9,
            }
        ],
    }
    report.update(updates)
    return json.dumps(report)


class StubAIProvider(AIProvider):
    def __init__(self, content: str = "", error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.requests: list[AIRequest] = []
        self.before_generate: object | None = None

    def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        if callable(self.before_generate):
            self.before_generate()
        if self.error:
            raise self.error
        return AIResponse.model_construct(
            request_id=request.id,
            provider=ProviderType.OPENAI,
            model=request.model,
            content=self.content,
            finish_reason="stop",
            usage=TokenUsage(),
            latency_ms=5,
            metadata={},
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
        return ["reasoning-model"]


def reasoning_context() -> ReasoningContext:
    organization = Organization(name="ACME")
    objective = Objective(organization_id=organization.id, title="Reduce launch risk")
    context = ContextObject(
        session_id=SESSION_ID,
        objective=objective,
        elements=[
            ContextElement(
                source_type=ContextSourceType.MEMORY,
                priority=ContextPriority.HIGH,
                title="History",
                content="Prior pilots reduced risk.",
                confidence=0.9,
            )
        ],
        confidence=0.9,
    )
    return ReasoningContext(
        session_id=SESSION_ID,
        context=context,
        reasoning_type=ReasoningType.STRATEGIC,
        constraints=["Budget is fixed"],
        memory=["Prior launch record"],
        specialist_contributions=["Risk specialist recommends a pilot"],
    )


def engine(provider: StubAIProvider) -> AIReasoningEngine:
    return AIReasoningEngine(provider, ProviderType.OPENAI, "reasoning-model")


def test_injected_provider_receives_complete_provider_neutral_request() -> None:
    provider = StubAIProvider(valid_report())
    result = engine(provider).analyze(reasoning_context())

    request = provider.requests[0]
    payload = json.loads(request.messages[1]["content"])
    assert request.provider is ProviderType.OPENAI
    assert request.model == "reasoning-model"
    assert request.metadata == {"session_id": str(SESSION_ID)}
    assert payload["objective"]["title"] == "Reduce launch risk"
    assert payload["constraints"] == ["Budget is fixed"]
    assert payload["memory"] == ["Prior launch record"]
    assert payload["specialist_contributions"] == ["Risk specialist recommends a pilot"]
    assert payload["evidence"][0]["content"] == "Prior pilots reduced risk."
    assert "chain-of-thought" in request.messages[0]["content"]
    assert result.summary == "Evidence supports a staged rollout."
    assert result.confidence == 0.82


def test_parses_plain_json_and_simple_json_markdown_fence() -> None:
    assert (
        engine(StubAIProvider(valid_report())).analyze(reasoning_context()).confidence
        == 0.82
    )
    fenced = f"```json\n{valid_report()}\n```"
    assert (
        engine(StubAIProvider(fenced)).analyze(reasoning_context()).confidence == 0.82
    )


@pytest.mark.parametrize("content", ["not-json", "```\n{}\n```"])
def test_rejects_invalid_json(content: str) -> None:
    with pytest.raises(InvalidReasoningResponseError):
        engine(StubAIProvider(content)).analyze(reasoning_context())


def test_rejects_empty_response() -> None:
    with pytest.raises(EmptyReasoningResponseError):
        engine(StubAIProvider("   ")).analyze(reasoning_context())


def test_rejects_absent_required_field() -> None:
    payload = json.loads(valid_report())
    del payload["summary"]
    with pytest.raises(IncompatibleReasoningSchemaError):
        engine(StubAIProvider(json.dumps(payload))).analyze(reasoning_context())


@pytest.mark.parametrize(
    "updates", [{"summary": None}, {"confidence": -0.1}, {"confidence": 1.1}]
)
def test_rejects_missing_or_incompatible_required_fields(
    updates: dict[str, object],
) -> None:
    with pytest.raises(IncompatibleReasoningSchemaError):
        engine(StubAIProvider(valid_report(**updates))).analyze(reasoning_context())


def test_wraps_provider_error_without_exposing_sensitive_message() -> None:
    provider_error = RuntimeError("secret header and raw response")
    with pytest.raises(ReasoningProviderError, match="AI provider failed") as captured:
        engine(StubAIProvider(error=provider_error)).analyze(reasoning_context())
    assert captured.value.__cause__ is provider_error
    assert "secret" not in str(captured.value)


def test_runtime_emits_started_before_provider_and_completed_only_on_success() -> None:
    pipeline = CognitivePipeline.with_fakes()
    provider = StubAIProvider(valid_report())
    provider.before_generate = lambda: (
        (
            EventType.ENGINE_INVOKED
            in [envelope.event.event_type for envelope in pipeline.event_bus.envelopes]
        )
        or pytest.fail("EngineInvoked must precede provider call")
    )
    pipeline.reasoning_service = ReasoningService(engine(provider))
    pipeline.run("Test event ordering")
    types = [envelope.event.event_type for envelope in pipeline.event_bus.envelopes]
    assert types.index(EventType.ENGINE_INVOKED) < types.index(
        EventType.ENGINE_COMPLETED
    )

    failing_pipeline = CognitivePipeline.with_fakes()
    failing_pipeline.reasoning_service = ReasoningService(
        engine(StubAIProvider(error=RuntimeError("down")))
    )
    with pytest.raises(RuntimeError, match="AI provider failed"):
        failing_pipeline.run("Test failure events")
    failure_types = [
        envelope.event.event_type for envelope in failing_pipeline.event_bus.envelopes
    ]
    assert EventType.ENGINE_FAILED in failure_types
    assert EventType.PIPELINE_COMPLETED not in failure_types


def test_reasoning_module_does_not_import_openai() -> None:
    reasoning_dir = Path(__file__).parents[1] / "src" / "ecos" / "reasoning"
    assert all(
        "import openai" not in path.read_text()
        and "from openai" not in path.read_text()
        for path in reasoning_dir.glob("*.py")
    )

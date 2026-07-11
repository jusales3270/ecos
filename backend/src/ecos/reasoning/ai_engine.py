"""Provider-backed implementation of the provider-neutral Reasoning contract."""

from __future__ import annotations

import json
from json import JSONDecodeError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ecos.core.exceptions import (
    EmptyReasoningResponseError,
    IncompatibleReasoningSchemaError,
    InvalidReasoningResponseError,
    ReasoningProviderError,
)
from ecos.providers.models import AIRequest, ProviderType
from ecos.providers.provider import AIProvider
from ecos.reasoning.models import (
    Alternative,
    Hypothesis,
    ReasoningContext,
    ReasoningEvidence,
    ReasoningResult,
    Tradeoff,
)
from ecos.reasoning.provider import ReasoningProvider


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Hypothesis(_StrictModel):
    statement: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class _Alternative(_StrictModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    benefits: list[str] = Field(min_length=1)
    costs: list[str] = Field(min_length=1)
    risks: list[str]
    complexity: str = Field(min_length=1)
    expected_impact: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)


class _Risk(_StrictModel):
    description: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)


class _Evidence(_StrictModel):
    source: str = Field(min_length=1)
    content: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class _CognitiveReport(_StrictModel):
    problem_statement: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    hypotheses: list[_Hypothesis]
    alternatives: list[_Alternative]
    assumptions: list[str]
    risks: list[_Risk]
    opportunities: list[str]
    recommendation: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_used: list[_Evidence]


class AIReasoningEngine(ReasoningProvider):
    """Produce validated reasoning reports through an injected AIProvider."""

    def __init__(
        self, provider: AIProvider, provider_type: ProviderType, model: str
    ) -> None:
        self._provider = provider
        self._provider_type = provider_type
        self._model = model

    def analyze(self, context: ReasoningContext) -> ReasoningResult:
        request = self.build_request(context)
        try:
            response = self._provider.generate(request)
        except Exception as error:
            raise ReasoningProviderError() from error
        report = self._parse(response.content)
        return self._to_result(
            context,
            report,
            {
                "provider": response.provider.value,
                "model": response.model,
                "latency_ms": response.latency_ms,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
                "status": response.finish_reason,
            },
        )

    def build_request(self, context: ReasoningContext) -> AIRequest:
        """Build a provider-neutral request containing only cognitive inputs."""
        cognitive_input = {
            "objective": context.context.objective.model_dump(mode="json"),
            "unified_context": context.context.model_dump(
                mode="json", exclude={"objective"}
            ),
            "evidence": [
                element.model_dump(mode="json") for element in context.context.elements
            ],
            "constraints": context.constraints,
            "memory": context.memory,
            "specialist_contributions": context.specialist_contributions,
        }
        system_message = (
            "Produce an objective, evidence-based reasoning report as JSON only. "
            "Do not provide private chain-of-thought or step-by-step internal "
            "reasoning. Explain only conclusions, evidence, assumptions, trade-offs, "
            "risks, and a concise justification. Use hypotheses and explicit "
            "assumptions; include opportunities and risks with impact and mitigation. "
            "When context permits, include at least three alternatives, each with "
            "benefits, costs, risks, complexity, expected impact, and a 0-to-1 score. "
            "Justify the recommendation and return confidence from 0 to 1. Required "
            "schema keys: problem_statement, summary, hypotheses, alternatives, "
            "assumptions, "
            "risks, opportunities, recommendation, confidence, evidence_used."
        )
        return AIRequest(
            provider=self._provider_type,
            model=self._model,
            messages=[
                {"role": "system", "content": system_message},
                {
                    "role": "user",
                    "content": json.dumps(cognitive_input, ensure_ascii=False),
                },
            ],
            temperature=0.0,
            metadata={"session_id": str(context.session_id)},
        )

    @staticmethod
    def _parse(content: str) -> _CognitiveReport:
        normalized = content.strip()
        if not normalized:
            raise EmptyReasoningResponseError
        if normalized.startswith("```json") and normalized.endswith("```"):
            normalized = normalized[7:-3].strip()
        try:
            payload = json.loads(normalized)
        except (JSONDecodeError, TypeError) as error:
            raise InvalidReasoningResponseError() from error
        try:
            return _CognitiveReport.model_validate(payload)
        except ValidationError as error:
            raise IncompatibleReasoningSchemaError() from error

    @staticmethod
    def _to_result(
        context: ReasoningContext,
        report: _CognitiveReport,
        metadata: dict[str, str | int],
    ) -> ReasoningResult:
        hypotheses = [Hypothesis(**item.model_dump()) for item in report.hypotheses]
        alternatives = [
            Alternative(
                title=item.title, description=item.description, score=item.score
            )
            for item in report.alternatives
        ]
        tradeoffs = [
            Tradeoff(
                dimension=item.title,
                benefit="; ".join(item.benefits),
                cost="; ".join(
                    [*item.costs, *item.risks, f"Complexity: {item.complexity}"]
                ),
                severity=1.0 - item.score,
            )
            for item in report.alternatives
        ]
        evidence = [
            ReasoningEvidence(**item.model_dump()) for item in report.evidence_used
        ]
        return ReasoningResult(
            session_id=context.session_id,
            reasoning_type=context.reasoning_type,
            hypotheses=hypotheses,
            alternatives=alternatives,
            tradeoffs=tradeoffs,
            evidence=evidence,
            confidence=report.confidence,
            summary=report.summary,
            metadata=metadata,
            report=report.model_dump(mode="json"),
        )

    def generate_hypotheses(self, context: ReasoningContext) -> list[Hypothesis]:
        return self.analyze(context).hypotheses

    def evaluate_alternatives(
        self, context: ReasoningContext, hypotheses: list[Hypothesis]
    ) -> list[Alternative]:
        del hypotheses
        return self.analyze(context).alternatives

    def calculate_confidence(self, result: ReasoningResult) -> float:
        return result.confidence

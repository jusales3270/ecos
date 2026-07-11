"""Provider-backed strategic simulation using only the generic AIProvider."""

from __future__ import annotations

import json
from json import JSONDecodeError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from ecos.providers.models import AIRequest, ProviderType
from ecos.providers.provider import AIProvider
from ecos.simulation.models import ScenarioType, SimulationContext, SimulationReport
from ecos.simulation.provider import SimulationProvider


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Risk(_StrictModel):
    description: str = Field(min_length=1)
    probability: float = Field(ge=0.0, le=1.0)
    impact: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)
    early_warning_signal: str = Field(min_length=1)
    owner_role: str | None = None


class _Scenario(_StrictModel):
    scenario_id: str = Field(min_length=1)
    scenario_type: ScenarioType
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    assumptions: list[str]
    trigger_conditions: list[str]
    probability: float = Field(ge=0.0, le=1.0)
    early_warning_signals: list[str]
    impacts: dict[str, str]
    risks: list[_Risk]
    opportunities: list[str]
    second_order_effects: list[str]
    failure_modes: list[str]
    success_factors: list[str]
    mitigation_actions: list[str]
    recovery_options: list[str]


class _Contingency(_StrictModel):
    primary_plan: str = Field(min_length=1)
    fallback_plan: str = Field(min_length=1)
    emergency_plan: str = Field(min_length=1)
    recovery_plan: str = Field(min_length=1)
    exit_strategy: str = Field(min_length=1)
    activation_conditions: list[str] = Field(min_length=1)


class _WarReport(_StrictModel):
    objective: str = Field(min_length=1)
    critical_assumptions: list[str]
    scenarios: list[_Scenario] = Field(min_length=4)
    cross_scenario_risks: list[_Risk]
    cross_scenario_opportunities: list[str]
    second_order_effects: list[str]
    failure_modes: list[str]
    success_factors: list[str]
    contingencies: list[_Contingency]
    resilience_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    executive_assessment: str = Field(min_length=1)


class AIWarEngine(SimulationProvider):
    """Explore possible futures through an injected provider-neutral boundary."""

    def __init__(
        self, provider: AIProvider, provider_type: ProviderType, model: str
    ) -> None:
        self._provider = provider
        self._provider_type = provider_type
        self._model = model

    def simulate(self, context: SimulationContext) -> SimulationReport:
        request = self.build_request(context)
        try:
            response = self._provider.generate(request)
        except Exception as error:
            raise WarProviderError() from error
        report = self._parse(response.content)
        self._validate(report)
        metadata: dict[str, str | int | float] = {
            "provider": response.provider.value,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "status": response.finish_reason,
            "scenario_count": len(report.scenarios),
            "risk_count": len(report.cross_scenario_risks)
            + sum(len(item.risks) for item in report.scenarios),
            "contingency_count": len(report.contingencies),
            "resilience_score": report.resilience_score,
            "confidence": report.confidence,
        }
        return SimulationReport(
            session_id=context.session_id,
            **report.model_dump(),
            metadata=metadata,
        )

    def build_request(self, context: SimulationContext) -> AIRequest:
        cognitive_input = context.model_dump(
            mode="json", exclude={"session_id", "correlation_id"}
        )
        system_message = """Explore possible strategic futures; this is simulation,
not prediction.
Return JSON only with objective, critical_assumptions, scenarios, cross_scenario_risks,
cross_scenario_opportunities, second_order_effects, failure_modes, success_factors,
contingencies, resilience_score, confidence, executive_assessment. Include best_case,
expected_case, worst_case, and black_swan; include competitive and internal when
supported.
Every scenario requires scenario_id, scenario_type, name, description, assumptions,
trigger_conditions, probability (0 to 1), early_warning_signals, impacts, risks,
opportunities, second_order_effects, failure_modes, success_factors, mitigation_actions,
recovery_options. Applicable impacts cover financial, operational, strategic, legal,
technological, reputational, human, execution_complexity, and recovery_cost. Every risk
requires description, probability, impact, severity, mitigation, early_warning_signal,
and owner_role when known. Every contingency requires primary_plan, fallback_plan,
emergency_plan, recovery_plan, exit_strategy, activation_conditions. Preserve favorable
and unfavorable scenarios, Debate conflicts, uncertainty, and open questions. Challenge
assumptions; identify known, hidden, emerging, cascading and systemic risks,
opportunities,
supported second/third-order effects, early warnings, adaptation and recovery capacity.
Do not minimize risks, make or approve a decision, authorize or execute action, claim
certainty, or replace decision support. Do not provide private chain-of-thought or
step-by-step internal reasoning. Explain only scenarios, assumptions, evidence, risks,
opportunities, consequences, signals, contingencies, and objective resilience
rationale."""
        metadata = {"session_id": str(context.session_id)}
        if context.correlation_id is not None:
            metadata["correlation_id"] = str(context.correlation_id)
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
            metadata=metadata,
        )

    @staticmethod
    def _parse(content: str) -> _WarReport:
        normalized = content.strip()
        if not normalized:
            raise EmptyWarResponseError
        if normalized.startswith("```json") and normalized.endswith("```"):
            normalized = normalized[7:-3].strip()
        try:
            payload = json.loads(normalized)
        except (JSONDecodeError, TypeError) as error:
            raise InvalidWarResponseError() from error
        try:
            return _WarReport.model_validate(payload)
        except ValidationError as error:
            failures = error.errors()
            if any(
                item["loc"] == ("scenarios",) and item["type"] == "too_short"
                for item in failures
            ):
                raise MissingWarScenarioError() from error
            if any(
                item["loc"]
                and item["loc"][-1] == "scenario_type"
                and item["type"] != "missing"
                for item in failures
            ):
                raise InvalidWarScenarioTypeError() from error
            if any(
                item["loc"]
                and item["loc"][-1] == "probability"
                and item["type"] != "missing"
                for item in failures
            ):
                raise InvalidWarProbabilityError() from error
            if any(
                item["loc"]
                and item["loc"][-1] == "confidence"
                and item["type"] != "missing"
                for item in failures
            ):
                raise InvalidWarConfidenceError() from error
            if any(
                item["loc"]
                and item["loc"][-1] == "resilience_score"
                and item["type"] != "missing"
                for item in failures
            ):
                raise InvalidResilienceScoreError() from error
            if any(
                item["loc"]
                and any(str(part).endswith("risks") for part in item["loc"])
                and item["loc"][-1] in {"impact", "mitigation"}
                for item in failures
            ):
                raise InvalidWarRiskError() from error
            raise IncompatibleWarSchemaError() from error

    @staticmethod
    def _validate(report: _WarReport) -> None:
        required = {
            ScenarioType.BEST_CASE,
            ScenarioType.EXPECTED_CASE,
            ScenarioType.WORST_CASE,
            ScenarioType.BLACK_SWAN,
        }
        present = {item.scenario_type for item in report.scenarios}
        if not required.issubset(present):
            raise MissingWarScenarioError
        ids = [item.scenario_id for item in report.scenarios]
        if len(ids) != len(set(ids)):
            raise IncompatibleWarSchemaError
        black_swans = [
            item
            for item in report.scenarios
            if item.scenario_type is ScenarioType.BLACK_SWAN
        ]
        if any(item.probability == 1.0 for item in black_swans):
            raise InvalidWarProbabilityError
        all_risks = [
            *report.cross_scenario_risks,
            *(risk for item in report.scenarios for risk in item.risks),
        ]
        if any(not risk.impact or not risk.mitigation for risk in all_risks):
            raise InvalidWarRiskError
        if report.resilience_score > 0.8 and all_risks and not report.contingencies:
            raise InvalidResilienceScoreError

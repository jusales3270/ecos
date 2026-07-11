"""Provider-backed implementation of the Decision Support Engine contract."""

from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
from ecos.debate import DebateResult
from ecos.decision.models import (
    AlternativeAnalysis,
    DecisionContext,
    DecisionImpact,
    DecisionPackage,
    ExecutiveBrief,
    Recommendation,
    RecommendationType,
    RiskSummary,
)
from ecos.decision.provider import DecisionProvider
from ecos.providers.models import AIRequest, ProviderType
from ecos.providers.provider import AIProvider
from ecos.reasoning import ReasoningResult


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Alternative(_StrictModel):
    alternative_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    benefits: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    cost: str = Field(min_length=1)
    complexity: str = Field(min_length=1)
    strategic_alignment: float = Field(ge=0.0, le=1.0)
    estimated_impact: str = Field(min_length=1)
    dependencies: list[str]
    rejection_reason: str | None = None


class _Risk(_StrictModel):
    description: str = Field(min_length=1)
    probability: float = Field(ge=0.0, le=1.0)
    impact: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    mitigation: str = Field(min_length=1)
    owner_role: str | None = None
    related_scenario: str | None = None


class _Tradeoff(_StrictModel):
    dimension_a: str = Field(min_length=1)
    dimension_b: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    organizational_impact: str = Field(min_length=1)


class _ExpectedOutcomes(_StrictModel):
    short_term: list[str] = Field(min_length=1)
    medium_term: list[str] = Field(min_length=1)
    long_term: list[str] = Field(min_length=1)
    measurable_indicators: list[str] = Field(min_length=1)


class _DecisionPackagePayload(_StrictModel):
    executive_summary: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    alternatives: list[str] = Field(min_length=1)
    tradeoffs: list[str] = Field(min_length=1)
    risk_summary: list[str] = Field(min_length=1)
    scenario_summary: list[str]
    implementation_considerations: list[str] = Field(min_length=1)
    expected_outcomes: _ExpectedOutcomes
    required_approvals: list[str]
    dependencies: list[str]
    next_actions: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    unresolved_issues: list[str]


class _DecisionReport(_StrictModel):
    objective: str = Field(min_length=1)
    situation_summary: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    supporting_evidence: list[str] = Field(min_length=1)
    alternatives: list[_Alternative] = Field(min_length=1)
    tradeoffs: list[_Tradeoff] = Field(min_length=1)
    risks: list[_Risk] = Field(min_length=1)
    expected_outcomes: _ExpectedOutcomes
    dependencies: list[str]
    required_approvals: list[str]
    next_actions: list[str] = Field(min_length=1)
    unresolved_questions: list[str]
    remaining_uncertainties: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    strategic_alignment: float = Field(ge=0.0, le=1.0)
    recommendation_classification: Literal[
        "low_impact",
        "medium_impact",
        "high_impact",
        "strategic",
        "critical",
    ]
    decision_package: _DecisionPackagePayload

    @model_validator(mode="after")
    def validate_report(self) -> _DecisionReport:
        ids = [item.alternative_id for item in self.alternatives]
        if len(ids) != len(set(ids)):
            raise ValueError("alternative ids must be unique")
        if any(
            not item.benefits or not item.risks or not item.estimated_impact
            for item in self.alternatives
        ):
            raise ValueError("alternatives must include benefits, risks and impact")
        if any(not risk.impact or not risk.mitigation for risk in self.risks):
            raise ValueError("risks must include impact and mitigation")
        if self.recommendation_classification in {"strategic", "critical"} and not (
            self.required_approvals or self.decision_package.required_approvals
        ):
            raise ValueError("strategic or critical recommendations require approvals")
        return self


class AIDecisionSupportEngine(DecisionProvider):
    """Prepare validated executive recommendations through an injected AIProvider."""

    def __init__(
        self, provider: AIProvider, provider_type: ProviderType, model: str
    ) -> None:
        self._provider = provider
        self._provider_type = provider_type
        self._model = model
        self._last_report: _DecisionReport | None = None
        self._last_metadata: dict[str, str | int | float] = {}
        self._last_recommendation_id: str | None = None

    def build_recommendation(
        self,
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
        decision_context: DecisionContext | None = None,
    ) -> Recommendation:
        context = decision_context or self._minimal_context(
            reasoning_result,
            debate_result,
        )
        report, metadata = self._generate(context)
        recommendation = self._to_recommendation(context, report)
        self._last_report = report
        self._last_metadata = metadata
        self._last_recommendation_id = str(recommendation.id)
        return recommendation

    def build_executive_brief(
        self,
        recommendation: Recommendation,
    ) -> ExecutiveBrief:
        report = self._require_report(recommendation)
        return ExecutiveBrief(
            title="Decision support recommendation",
            summary=report.executive_summary,
            key_points=[
                report.situation_summary,
                report.rationale,
                *report.decision_package.unresolved_issues,
            ],
            decision_required=True,
        )

    def build_decision_package(
        self,
        recommendation: Recommendation,
        executive_brief: ExecutiveBrief,
    ) -> DecisionPackage:
        report = self._require_report(recommendation)
        metadata = {
            **self._last_metadata,
            "strategic_alignment": report.strategic_alignment,
            "classification": report.recommendation_classification,
            "alternative_count": len(report.alternatives),
            "risk_count": len(report.risks),
        }
        return DecisionPackage(
            recommendation=recommendation,
            executive_brief=executive_brief,
            supporting_evidence=report.supporting_evidence,
            required_approvals=report.required_approvals,
            metadata=metadata,
        )

    def build_request(self, context: DecisionContext) -> AIRequest:
        """Build a provider-neutral request with complete decision inputs."""
        cognitive_input = {
            "objective": context.objective,
            "unified_context": context.unified_context.model_dump(mode="json"),
            "constraints": context.constraints,
            "relevant_policies": context.relevant_policies,
            "memory": context.memory,
            "reasoning_report": context.reasoning_report.model_dump(mode="json"),
            "debate_report": context.debate_report.model_dump(mode="json"),
            "simulation_report": context.simulation_report.model_dump(mode="json")
            if context.simulation_report is not None
            else None,
        }
        system_message = """Prepare an executive decision support recommendation as
JSON only. Consolidate the supplied Context, Reasoning Report, Debate Report, and
Simulation Report; do not invent facts. This is a recommendation package for human
evaluation, not a decision, approval, authorization, execution result, governance
substitute, memory update, learning update, or policy change. Preserve disagreement,
unfavorable scenarios, open questions, weak assumptions, evidence gaps, risks,
limitations, conflicts, uncertainties, alternatives, and required human approvals as
requirements only. Do not state that a decision was approved or execution was
authorized. Do not request, expose, or store private chain-of-thought or step-by-step
internal reasoning. Explain only conclusion, evidence, alternatives, assumptions,
trade-offs, risks, scenarios, uncertainties, and objective rationale.
Return required keys: objective, situation_summary, executive_summary,
recommended_action, rationale, supporting_evidence, alternatives, tradeoffs, risks,
expected_outcomes, dependencies, required_approvals, next_actions,
unresolved_questions, remaining_uncertainties, confidence, strategic_alignment,
recommendation_classification, decision_package. recommendation_classification must be
one of low_impact, medium_impact, high_impact, strategic, critical. confidence and
numeric strategic_alignment must be 0 to 1. Evaluate at least three alternatives when
the context permits. Alternatives require alternative_id, description, benefits, risks,
cost, complexity, strategic_alignment, estimated_impact, dependencies, and
rejection_reason when not recommended. Risks require description, probability, impact,
severity, mitigation, owner_role when known, and related_scenario when applicable.
Tradeoffs require dimension_a, dimension_b, explanation, organizational_impact.
expected_outcomes requires short_term, medium_term, long_term, measurable_indicators.
decision_package requires executive_summary, recommendation, evidence, alternatives,
tradeoffs, risk_summary, scenario_summary, implementation_considerations,
expected_outcomes, required_approvals, dependencies, next_actions, confidence,
unresolved_issues."""
        metadata: dict[str, str] = {"session_id": str(context.session_id)}
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

    def _generate(
        self, context: DecisionContext
    ) -> tuple[_DecisionReport, dict[str, str | int | float]]:
        request = self.build_request(context)
        try:
            response = self._provider.generate(request)
        except Exception as error:
            raise DecisionProviderError() from error
        report = self._parse(response.content)
        self._validate_safe_content(report)
        metadata: dict[str, str | int | float] = {
            "provider": response.provider.value,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "status": response.finish_reason,
            "alternative_count": len(report.alternatives),
            "risk_count": len(report.risks),
            "classification": report.recommendation_classification,
            "confidence": report.confidence,
            "strategic_alignment": report.strategic_alignment,
        }
        return report, metadata

    @staticmethod
    def _parse(content: str) -> _DecisionReport:
        normalized = content.strip()
        if not normalized:
            raise EmptyDecisionResponseError
        if normalized.startswith("```json") and normalized.endswith("```"):
            normalized = normalized[7:-3].strip()
        try:
            payload = json.loads(normalized)
        except (JSONDecodeError, TypeError) as error:
            raise InvalidDecisionResponseError() from error
        try:
            return _DecisionReport.model_validate(payload)
        except ValidationError as error:
            failures = error.errors()
            if any(item["type"] == "missing" for item in failures):
                raise IncompatibleDecisionSchemaError() from error
            if AIDecisionSupportEngine._has_field_failure(failures, "confidence"):
                raise InvalidDecisionConfidenceError() from error
            if AIDecisionSupportEngine._has_field_failure(
                failures, "strategic_alignment"
            ):
                raise InvalidStrategicAlignmentError() from error
            if AIDecisionSupportEngine._has_field_failure(
                failures, "recommendation_classification"
            ):
                raise InvalidDecisionClassificationError() from error
            if any("alternatives" in item["loc"] for item in failures):
                raise InvalidDecisionAlternativeError() from error
            if any("risks" in item["loc"] for item in failures):
                raise InvalidDecisionRiskError() from error
            if AIDecisionSupportEngine._has_field_failure(
                failures, "supporting_evidence"
            ):
                raise MissingDecisionEvidenceError() from error
            if any("alternative" in str(item.get("msg", "")) for item in failures):
                raise InvalidDecisionAlternativeError() from error
            if any("risk" in str(item.get("msg", "")) for item in failures):
                raise InvalidDecisionRiskError() from error
            raise IncompatibleDecisionSchemaError() from error
        except ValueError as error:
            message = str(error)
            if "alternative" in message:
                raise InvalidDecisionAlternativeError() from error
            if "risk" in message:
                raise InvalidDecisionRiskError() from error
            raise IncompatibleDecisionSchemaError() from error

    @staticmethod
    def _has_field_failure(failures: list[dict[str, object]], field: str) -> bool:
        return any(item["loc"] and item["loc"][-1] == field for item in failures)

    @staticmethod
    def _validate_safe_content(report: _DecisionReport) -> None:
        payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False).lower()
        approval_phrases = (
            "decision approved",
            "approved decision",
            "decisão aprovada",
            "approved by leadership",
        )
        execution_phrases = (
            "execution authorized",
            "authorized execution",
            "execução autorizada",
            "autorizada a execução",
        )
        if any(phrase in payload for phrase in approval_phrases):
            raise UnauthorizedDecisionApprovalError
        if any(phrase in payload for phrase in execution_phrases):
            raise UnauthorizedExecutionApprovalError

    @staticmethod
    def _to_recommendation(
        context: DecisionContext,
        report: _DecisionReport,
    ) -> Recommendation:
        return Recommendation(
            session_id=context.session_id,
            recommendation_type=RecommendationType.STRATEGIC,
            title=report.recommended_action[:200],
            summary=report.executive_summary,
            confidence=report.confidence,
            risks=[
                RiskSummary(
                    title=item.description[:200],
                    description=item.description,
                    impact=AIDecisionSupportEngine._to_public_impact(item.severity),
                    probability=item.probability,
                    mitigation=item.mitigation,
                )
                for item in report.risks
            ],
            alternatives=[
                AlternativeAnalysis(
                    title=item.alternative_id[:200],
                    summary=item.description,
                    pros=item.benefits,
                    cons=[*item.risks, f"Cost: {item.cost}"],
                    score=item.strategic_alignment,
                )
                for item in report.alternatives
            ],
            expected_impact=AIDecisionSupportEngine._classification_to_impact(
                report.recommendation_classification
            ),
        )

    @staticmethod
    def _to_public_impact(severity: str) -> DecisionImpact:
        return {
            "low": DecisionImpact.LOW,
            "medium": DecisionImpact.MEDIUM,
            "high": DecisionImpact.HIGH,
            "critical": DecisionImpact.CRITICAL,
        }[severity]

    @staticmethod
    def _classification_to_impact(classification: str) -> DecisionImpact:
        return {
            "low_impact": DecisionImpact.LOW,
            "medium_impact": DecisionImpact.MEDIUM,
            "high_impact": DecisionImpact.HIGH,
            "strategic": DecisionImpact.HIGH,
            "critical": DecisionImpact.CRITICAL,
        }[classification]

    def _require_report(self, recommendation: Recommendation) -> _DecisionReport:
        if self._last_report is None or self._last_recommendation_id != str(
            recommendation.id
        ):
            raise IncompatibleDecisionSchemaError
        return self._last_report

    @staticmethod
    def _minimal_context(
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
    ) -> DecisionContext:
        from ecos.context import ContextObject
        from ecos.domain import Objective

        objective = Objective(
            organization_id=reasoning_result.session_id,
            title=reasoning_result.summary,
        )
        context = ContextObject(
            session_id=reasoning_result.session_id,
            objective=objective,
            elements=[],
            confidence=reasoning_result.confidence,
        )
        return DecisionContext(
            session_id=reasoning_result.session_id,
            objective=objective.model_dump(mode="json"),
            unified_context=context,
            reasoning_report=reasoning_result,
            debate_report=debate_result,
        )

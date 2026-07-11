"""Provider-backed implementation of the provider-neutral Debate contract."""

from __future__ import annotations

import json
from json import JSONDecodeError
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ecos.core.exceptions import (
    DebateProviderError,
    EmptyDebateResponseError,
    IncompatibleDebateSchemaError,
    InvalidDebateConfidenceError,
    InvalidDebateConsensusError,
    InvalidDebateResponseError,
    InvalidDebateSpecialistReferenceError,
)
from ecos.debate.models import (
    Argument,
    Consensus,
    ConsensusLevel,
    Debate,
    DebateResult,
    DebateStatus,
)
from ecos.debate.provider import DebateProvider
from ecos.providers.models import AIRequest, ProviderType
from ecos.providers.provider import AIProvider


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Argument(_StrictModel):
    specialist_id: UUID | None = None
    origin: str | None = None
    claim: str = Field(min_length=1)
    justification: str = Field(min_length=1)
    evidence: list[str]
    assumptions: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    impact: str = Field(min_length=1)


class _Risk(_StrictModel):
    description: str = Field(min_length=1)
    probability: float = Field(ge=0.0, le=1.0)
    impact: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)


class _Conflict(_StrictModel):
    participants: list[str] = Field(min_length=1)
    divergence: str = Field(min_length=1)
    evidence_by_side: dict[str, list[str]]
    resolution_condition: str = Field(min_length=1)
    resolved: bool


class _DebateReport(_StrictModel):
    objective: str = Field(min_length=1)
    participants: list[UUID] = Field(min_length=1)
    supporting_arguments: list[_Argument]
    opposing_arguments: list[_Argument]
    counterarguments: list[_Argument]
    agreements: list[str]
    disagreements: list[str]
    contradictions: list[_Conflict]
    weak_assumptions: list[str]
    evidence_gaps: list[str]
    blind_spots: list[str]
    ignored_stakeholders: list[str]
    unconsidered_consequences: list[str]
    risks: list[_Risk]
    opportunities: list[str]
    outstanding_questions: list[str]
    consensus_level: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    final_cognitive_summary: str = Field(min_length=1)


class AIDebateEngine(DebateProvider):
    """Evaluate independent contributions through an injected AIProvider only."""

    def __init__(
        self, provider: AIProvider, provider_type: ProviderType, model: str
    ) -> None:
        self._provider = provider
        self._provider_type = provider_type
        self._model = model

    def start(self, debate: Debate) -> Debate:
        return debate.model_copy(update={"status": DebateStatus.RUNNING}, deep=True)

    def collect_arguments(self, debate: Debate) -> list[Argument]:
        return [
            Argument(
                specialist_id=item.specialist_id,
                position=item.contribution_type.value,
                content=item.content,
                confidence=item.confidence,
            )
            for item in debate.contributions
        ]

    def evaluate_consensus(self, debate: Debate) -> Consensus:
        report, _ = self._generate(debate)
        return self._to_consensus(report)

    def finalize(self, debate: Debate) -> DebateResult:
        report, metadata = self._generate(debate)
        consensus = self._to_consensus(report)
        recommendations = [report.final_cognitive_summary, *report.opportunities]
        return DebateResult(
            debate_id=debate.id,
            consensus=consensus,
            recommendations=recommendations,
            unresolved_questions=report.outstanding_questions,
            confidence=report.confidence,
            metadata=metadata,
            report=report.model_dump(mode="json"),
        )

    def build_request(self, debate: Debate) -> AIRequest:
        if debate.reasoning_result is None or debate.objective is None:
            raise IncompatibleDebateSchemaError
        cognitive_input = {
            "objective": debate.objective,
            "unified_context": debate.unified_context,
            "organizational_constraints": debate.organizational_constraints,
            "relevant_policies": debate.relevant_policies,
            "reasoning_report": debate.reasoning_result.model_dump(mode="json"),
            "specialist_contributions": [
                contribution.model_dump(mode="json")
                for contribution in debate.contributions
            ],
        }
        system_message = """Evaluate the supplied reasoning and independent specialist
contributions. Return JSON only. Preserve useful disagreement; distinguish agreement,
partial agreement, and disagreement. Identify contradictions, weak assumptions, evidence
gaps, blind spots, ignored stakeholders, unconsidered consequences, risks,
opportunities, and open questions. Do not make a final decision, authorize execution,
or invent unanimity.
Do not provide private chain-of-thought or step-by-step internal reasoning; expose only
arguments, counterarguments, evidence, assumptions, conflicts, trade-offs, risks, open
questions, and an objective synthesis. Treat every specialist equally. consensus_level
must be 1 Strong Disagreement, 2 Moderate Disagreement, 3 Partial Consensus,
4 Strong Consensus,
or 5 Unanimous Consensus; confidence is independently 0 to 1. Required keys: objective,
participants, supporting_arguments, opposing_arguments, counterarguments, agreements,
disagreements, contradictions, weak_assumptions, evidence_gaps, blind_spots,
ignored_stakeholders, unconsidered_consequences, risks, opportunities,
outstanding_questions,
consensus_level, confidence, final_cognitive_summary. Arguments require specialist_id or
origin, claim, justification, evidence, assumptions, confidence, impact. Risks require
description, probability, impact, mitigation. Contradictions require participants,
divergence, evidence_by_side, resolution_condition, resolved."""
        metadata: dict[str, str] = {"session_id": str(debate.session_id)}
        if debate.correlation_id is not None:
            metadata["correlation_id"] = str(debate.correlation_id)
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
        self, debate: Debate
    ) -> tuple[_DebateReport, dict[str, str | int | float]]:
        request = self.build_request(debate)
        try:
            response = self._provider.generate(request)
        except Exception as error:
            raise DebateProviderError() from error
        report = self._parse(response.content)
        self._validate_report(report, debate)
        metadata: dict[str, str | int | float] = {
            "provider": response.provider.value,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "status": response.finish_reason,
            "participants": len(report.participants),
            "conflicts": len(report.contradictions),
            "consensus_level": report.consensus_level,
            "confidence": report.confidence,
        }
        return report, metadata

    @staticmethod
    def _parse(content: str) -> _DebateReport:
        normalized = content.strip()
        if not normalized:
            raise EmptyDebateResponseError
        if normalized.startswith("```json") and normalized.endswith("```"):
            normalized = normalized[7:-3].strip()
        try:
            payload = json.loads(normalized)
        except (JSONDecodeError, TypeError) as error:
            raise InvalidDebateResponseError() from error
        try:
            return _DebateReport.model_validate(payload)
        except ValidationError as error:
            errors = error.errors()
            if any(
                item["loc"]
                and item["loc"][-1] == "consensus_level"
                and item["type"] != "missing"
                for item in errors
            ):
                raise InvalidDebateConsensusError() from error
            if any(
                item["loc"]
                and item["loc"][-1] == "confidence"
                and item["type"] != "missing"
                for item in errors
            ):
                raise InvalidDebateConfidenceError() from error
            raise IncompatibleDebateSchemaError() from error

    @staticmethod
    def _validate_report(report: _DebateReport, debate: Debate) -> None:
        known = {specialist.id for specialist in debate.specialists}
        if set(report.participants) != known:
            raise InvalidDebateSpecialistReferenceError
        arguments = [
            *report.supporting_arguments,
            *report.opposing_arguments,
            *report.counterarguments,
        ]
        if any(
            item.specialist_id is not None and item.specialist_id not in known
            for item in arguments
        ):
            raise InvalidDebateSpecialistReferenceError
        if report.consensus_level == 5 and (
            report.disagreements
            or any(not conflict.resolved for conflict in report.contradictions)
        ):
            raise InvalidDebateConsensusError

    @staticmethod
    def _to_consensus(report: _DebateReport) -> Consensus:
        levels = {
            1: ConsensusLevel.NONE,
            2: ConsensusLevel.LOW,
            3: ConsensusLevel.MEDIUM,
            4: ConsensusLevel.HIGH,
            5: ConsensusLevel.UNANIMOUS,
        }
        conflicts = [
            f"{' / '.join(item.participants)}: {item.divergence} "
            f"[{'resolved' if item.resolved else 'unresolved'}]"
            for item in report.contradictions
        ]
        return Consensus(
            level=levels[report.consensus_level],
            summary=report.final_cognitive_summary,
            agreements=report.agreements,
            disagreements=[*report.disagreements, *conflicts],
        )

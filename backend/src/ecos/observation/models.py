"""Typed immutable models for organizational outcome observation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ObservationMetadataValue = str | int | float | bool | None


class ObservationModel(BaseModel):
    """Base immutable observation model."""

    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )


class ObservationSourceType(StrEnum):
    """Supported sources for organizational outcome observation."""

    EXECUTION_RESULT = "execution_result"
    DECISION_OUTCOME = "decision_outcome"
    SIMULATION_RESULT = "simulation_result"
    USER_FEEDBACK = "user_feedback"
    ORGANIZATIONAL_METRIC = "organizational_metric"
    BUSINESS_KPI = "business_kpi"
    EXTERNAL_EVENT = "external_event"
    MANUAL_MEASUREMENT = "manual_measurement"
    MONITORING_SNAPSHOT = "monitoring_snapshot"


class MeasurementValueType(StrEnum):
    """Supported measurement value types."""

    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    STATUS = "status"
    DURATION = "duration"
    COUNT = "count"
    PERCENTAGE = "percentage"
    SCORE = "score"
    TEXT_REFERENCE = "text_reference"


class ComparisonOperator(StrEnum):
    """Allowlisted deterministic comparison operators."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    WITHIN_TOLERANCE = "within_tolerance"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class ComparisonStatus(StrEnum):
    """Result status for a single expected/observed comparison."""

    MATCHED = "matched"
    EXCEEDED = "exceeded"
    PARTIALLY_MET = "partially_met"
    MISSED = "missed"
    INCONCLUSIVE = "inconclusive"
    NOT_OBSERVED = "not_observed"


class ObservedOutcomeStatus(StrEnum):
    """Organizational outcome status."""

    SUCCESSFUL = "successful"
    PARTIALLY_SUCCESSFUL = "partially_successful"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    NOT_OBSERVED = "not_observed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


class DeviationDirection(StrEnum):
    """Direction of an observed deviation."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class MeasurementSource(ObservationModel):
    """Provider-agnostic reference to a measurement source."""

    source_type: ObservationSourceType
    source_id: str = Field(min_length=1)
    reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    verified: bool = False
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ObservationEvidence(ObservationModel):
    """Evidence reference used by observation without embedding sensitive payload."""

    evidence_id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    description: str = Field(default="", max_length=500)
    recorded_at: datetime
    verified: bool = False
    sensitive: bool = False
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ExpectedMetric(ObservationModel):
    """Typed expected metric declaration."""

    metric_key: str = Field(min_length=1)
    value_type: MeasurementValueType
    unit: str | None = None
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ExpectedOutcome(ObservationModel):
    """Declared expected outcome to compare against observed measurements."""

    expected_outcome_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    metric_key: str = Field(min_length=1)
    expected_value: Any = None
    expected_status: str | None = None
    baseline_value: Any = None
    comparison_operator: ComparisonOperator = ComparisonOperator.EQUALS
    tolerance: float = Field(default=0.0, ge=0.0)
    weight: float = Field(default=1.0, ge=0.0)
    deadline: datetime | None = None
    required: bool = True
    source_reference: str = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class Measurement(ObservationModel):
    """Observed metric value with provenance and verification state."""

    measurement_id: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    value: Any = None
    value_type: MeasurementValueType
    unit: str | None = None
    source: MeasurementSource
    observed_at: datetime
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool = False
    sensitive: bool = False
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)

    @field_validator("evidence_references", "reason_codes", mode="before")
    @classmethod
    def tuple_strings(cls, value: object) -> tuple[str, ...]:
        """Normalize list-like strings."""
        return tuple(str(item).strip() for item in (value or ()) if str(item).strip())

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        """Validate value compatibility with declared type."""
        if self.value_type in {
            MeasurementValueType.NUMERIC,
            MeasurementValueType.DURATION,
            MeasurementValueType.COUNT,
            MeasurementValueType.PERCENTAGE,
            MeasurementValueType.SCORE,
        }:
            if not isinstance(self.value, int | float) or isinstance(self.value, bool):
                msg = "numeric measurement values must be numbers"
                raise ValueError(msg)
            if not isfinite(float(self.value)):
                msg = "numeric measurement values must be finite"
                raise ValueError(msg)
        if self.value_type is MeasurementValueType.PERCENTAGE and not (
            0.0 <= float(self.value) <= 100.0
        ):
            msg = "percentage measurements must be between 0 and 100"
            raise ValueError(msg)
        if self.value_type is MeasurementValueType.BOOLEAN and not isinstance(
            self.value, bool
        ):
            msg = "boolean measurement values must be boolean"
            raise ValueError(msg)
        return self


class FeedbackRecord(ObservationModel):
    """Feedback preserved as evidence, not as truth."""

    feedback_id: str = Field(min_length=1)
    organization_id: UUID
    session_id: UUID
    actor_id: str | None = None
    actor_role: str | None = None
    rating: float | None = Field(default=None, ge=0.0, le=1.0)
    outcome: str | None = None
    accepted: bool | None = None
    comments_reference: str | None = None
    submitted_at: datetime
    verified_identity: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sensitive: bool = False
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ObservationContext(ObservationModel):
    """Context available to the Observation Engine."""

    affected_domains: tuple[str, ...] = Field(default_factory=tuple)
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ObservationWindow(ObservationModel):
    """Bounded observation window."""

    started_at: datetime
    ended_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        """Ensure coherent timestamps."""
        if self.ended_at < self.started_at:
            msg = "observation_window end cannot be before start"
            raise ValueError(msg)
        return self


class OutcomeComparison(ObservationModel):
    """Comparison between one expected outcome and one observed measurement."""

    expected_outcome_id: str
    metric_key: str
    operator: ComparisonOperator
    status: ComparisonStatus
    expected_value: Any = None
    observed_value: Any = None
    normalized_score: float = Field(ge=0.0, le=1.0)
    absolute_deviation: float | None = None
    relative_deviation: float | None = None
    direction: DeviationDirection = DeviationDirection.UNKNOWN
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class Deviation(ObservationModel):
    """Deviation signal derived from an outcome comparison."""

    deviation_id: str
    metric_key: str
    direction: DeviationDirection
    magnitude: float | None = None
    relative_magnitude: float | None = None
    comparison_id: str
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class AnomalySignal(ObservationModel):
    """Deterministic anomaly signal, not a causal conclusion."""

    anomaly_id: str
    metric_key: str
    signal: str
    severity: float = Field(ge=0.0, le=1.0)
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class ObservationQuality(ObservationModel):
    """Quality profile for an observation result."""

    completeness_score: float = Field(ge=0.0, le=1.0)
    evidence_quality_score: float = Field(ge=0.0, le=1.0)
    source_reliability_score: float = Field(ge=0.0, le=1.0)
    timeliness_score: float = Field(ge=0.0, le=1.0)
    consistency_score: float = Field(ge=0.0, le=1.0)
    verified_measurement_ratio: float = Field(ge=0.0, le=1.0)
    missing_metrics: tuple[str, ...] = Field(default_factory=tuple)
    conflicting_evidence: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class ObservedOutcome(ObservationModel):
    """Observed organizational outcome summary."""

    outcome_id: str
    status: ObservedOutcomeStatus
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class ObservationTimelineEntry(ObservationModel):
    """Append-only observation timeline entry."""

    sequence: int = Field(ge=1)
    timestamp: datetime
    component: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: str = Field(min_length=1)
    source_reference: str | None = None
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ObservationFailure(ObservationModel):
    """Safe failure report for observation."""

    failure_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    component: str
    source_id: str
    classification: str
    recoverable: bool
    occurred_at: datetime
    safe_message: str
    cause_type: str
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    human_escalation_required: bool = False
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ObservationRequest(ObservationModel):
    """Input contract for Observation Engine."""

    observation_request_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    source_type: ObservationSourceType
    source_id: str = Field(min_length=1)
    execution_result: Any = None
    decision_package: Any = None
    recommendation: Any = None
    expected_outcomes: tuple[ExpectedOutcome, ...] = Field(default_factory=tuple)
    observed_measurements: tuple[Measurement, ...] = Field(default_factory=tuple)
    feedback: tuple[FeedbackRecord, ...] = Field(default_factory=tuple)
    organizational_metrics: tuple[Measurement, ...] = Field(default_factory=tuple)
    simulation_results: tuple[Any, ...] = Field(default_factory=tuple)
    observation_window: ObservationWindow | None = None
    affected_domains: tuple[str, ...] = Field(default_factory=tuple)
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)


class ObservationResult(ObservationModel):
    """Immutable result produced by the Observation Engine."""

    observation_id: UUID
    observation_request_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    source_type: ObservationSourceType
    source_id: str
    status: ObservedOutcomeStatus
    observed_outcomes: tuple[ObservedOutcome, ...]
    comparisons: tuple[OutcomeComparison, ...]
    deviations: tuple[Deviation, ...]
    anomalies: tuple[AnomalySignal, ...]
    measurements: tuple[Measurement, ...]
    evidence: tuple[ObservationEvidence, ...]
    feedback: tuple[FeedbackRecord, ...]
    quality: ObservationQuality
    outcome_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    started_at: datetime
    completed_at: datetime
    duration: float = Field(ge=0.0)
    timeline: tuple[ObservationTimelineEntry, ...]
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, ObservationMetadataValue] = Field(default_factory=dict)

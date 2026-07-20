"""Models for deterministic organizational learning validation."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.memory import MemoryType
from ecos.observation import ObservationResult


class LearningValidationStatus(StrEnum):
    """Possible outcomes of learning validation."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LearningObject(BaseModel):
    """Candidate knowledge that must be validated before persistence."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    organization_id: UUID | None = None
    memory_type: MemoryType
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(min_length=1)
    origin: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: LearningValidationStatus = LearningValidationStatus.PENDING
    validation_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


LearningMetadataValue = str | int | float | bool | None


class LearningCategory(StrEnum):
    """Official learning categories."""

    OUTCOME = "outcome"
    DECISION = "decision"
    STRATEGY = "strategy"
    OPERATIONAL = "operational"
    ORGANIZATIONAL = "organizational"
    BEHAVIORAL = "behavioral"


class LearningStatus(StrEnum):
    """Lifecycle status for learning candidates and results."""

    CANDIDATE = "candidate"
    PENDING_VALIDATION = "pending_validation"
    VALIDATED = "validated"
    REJECTED = "rejected"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    STORED = "stored"
    FAILED = "failed"
    COMPLETED = "completed"


class LearningValidationOutcome(StrEnum):
    """Deterministic validation outcome."""

    VALIDATED = "validated"
    REJECTED = "rejected"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    POLICY_BLOCKED = "policy_blocked"


class RelationshipType(StrEnum):
    """Non-causal relationship vocabulary."""

    ASSOCIATED_WITH = "associated_with"
    OCCURRED_AFTER = "occurred_after"
    CORRELATED_WITH = "correlated_with"
    OBSERVED_TOGETHER = "observed_together"
    CONTRIBUTING_FACTOR_REPORTED = "contributing_factor_reported"
    DECLARED_CAUSAL_CLAIM = "declared_causal_claim"


class CalibrationDirection(StrEnum):
    """Direction of confidence calibration."""

    CALIBRATED = "calibrated"
    OVERCONFIDENT = "overconfident"
    UNDERCONFIDENT = "underconfident"
    INCONCLUSIVE = "inconclusive"


class LearningModel(BaseModel):
    """Base immutable learning model."""

    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )


class LearningSource(LearningModel):
    """Typed learning source reference."""

    source_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class LearningEvidence(LearningModel):
    """Evidence reference used to validate a learning candidate."""

    evidence_id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    verified: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    sensitive: bool = False
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class LearningCandidate(LearningModel):
    """Structured candidate extracted from an ObservationResult."""

    learning_candidate_id: UUID
    category: LearningCategory
    source_references: tuple[str, ...]
    evidence_references: tuple[str, ...]
    statement: dict[str, Any]
    affected_components: tuple[str, ...] = Field(default_factory=tuple)
    affected_domains: tuple[str, ...] = Field(default_factory=tuple)
    confidence: float = Field(ge=0.0, le=1.0)
    recurrence_count: int = Field(default=1, ge=1)
    novelty_score: float = Field(default=1.0, ge=0.0, le=1.0)
    organizational_impact: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: LearningStatus = LearningStatus.CANDIDATE
    human_review_required: bool = False
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    relationship: RelationshipType = RelationshipType.ASSOCIATED_WITH
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, LearningMetadataValue] = Field(default_factory=dict)


class PatternSignal(LearningModel):
    """Recurring pattern signal produced only after sufficient history."""

    pattern_id: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    recurrence_count: int = Field(ge=2)
    distinct_sources: int = Field(ge=1)
    window: str = Field(min_length=1)
    evidence_references: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class ConfidenceCalibration(LearningModel):
    """Proposed confidence calibration, never an in-place overwrite."""

    predicted_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_score: float = Field(ge=0.0, le=1.0)
    calibration_error: float | None = Field(default=None, ge=0.0, le=1.0)
    direction: CalibrationDirection
    prior_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    proposed_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)
    quality_adjustment: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class LearningValidation(LearningModel):
    """Validation decision for a LearningCandidate."""

    learning_candidate_id: UUID
    outcome: LearningValidationOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)
    human_review_required: bool = False
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class MemoryUpdateProposal(LearningModel):
    """Immutable proposal to store validated knowledge through Memory."""

    proposal_id: UUID
    organization_id: UUID
    session_id: UUID
    learning_candidate_id: UUID
    memory_type: MemoryType
    content: dict[str, Any]
    evidence_references: tuple[str, ...]
    source_references: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    validation_status: LearningValidationOutcome
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    supersedes_reference: str | None = None
    version: int = Field(default=1, ge=1)
    retention_hint: str | None = None
    sensitive: bool = False
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, LearningMetadataValue] = Field(default_factory=dict)


class LearningRequest(LearningModel):
    """Input contract for the real learning loop."""

    learning_request_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    execution_id: UUID | None = None
    observation_id: UUID | None = None
    observation_result: ObservationResult
    decision_package: Any = None
    recommendation: Any = None
    execution_result: Any = None
    simulation_result: Any = None
    debate_report: Any = None
    user_feedback: tuple[Any, ...] = Field(default_factory=tuple)
    prior_learning_references: tuple[str, ...] = Field(default_factory=tuple)
    applicable_policies: tuple[str, ...] = Field(default_factory=tuple)
    human_review_state: str | None = None
    safe_metadata: dict[str, LearningMetadataValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        """Ensure request and observation identities match."""
        if self.organization_id != self.observation_result.organization_id:
            msg = "organization_id mismatch"
            raise ValueError(msg)
        if self.session_id != self.observation_result.session_id:
            msg = "session_id mismatch"
            raise ValueError(msg)
        if self.plan_id != self.observation_result.plan_id:
            msg = "plan_id mismatch"
            raise ValueError(msg)
        if self.observation_id not in {None, self.observation_result.observation_id}:
            raise ValueError("observation_id mismatch")
        if self.execution_id not in {None, self.observation_result.execution_id}:
            raise ValueError("execution_id mismatch")
        if self.correlation_id != self.observation_result.correlation_id:
            raise ValueError("correlation_id mismatch")
        return self

    @field_validator("safe_metadata")
    @classmethod
    def validate_safe_metadata(
        cls,
        value: dict[str, LearningMetadataValue],
    ) -> dict[str, LearningMetadataValue]:
        """Reject sensitive metadata keys."""
        sensitive = {"password", "secret", "token", "api_key", "private_key"}
        if any(key.lower() in sensitive for key in value):
            msg = "safe_metadata contains sensitive keys"
            raise ValueError(msg)
        return dict(value)


class LearningFailure(LearningModel):
    """Safe failure report for learning."""

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
    safe_metadata: dict[str, LearningMetadataValue] = Field(default_factory=dict)


class LearningResult(LearningModel):
    """Immutable result of the learning loop."""

    learning_id: UUID
    learning_request_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    execution_id: UUID | None = None
    observation_id: UUID
    policy_version: str = Field(min_length=1, max_length=100)
    fingerprint: str = Field(min_length=64, max_length=64)
    status: LearningStatus
    candidates: tuple[LearningCandidate, ...]
    validations: tuple[LearningValidation, ...]
    validated_candidates: tuple[LearningCandidate, ...]
    rejected_candidates: tuple[LearningCandidate, ...]
    human_review_candidates: tuple[LearningCandidate, ...]
    pattern_signals: tuple[PatternSignal, ...]
    confidence_calibrations: tuple[ConfidenceCalibration, ...]
    memory_update_proposals: tuple[MemoryUpdateProposal, ...]
    stored_memory_references: tuple[str, ...]
    evidence_references: tuple[str, ...]
    validation_summary: dict[str, int]
    started_at: datetime
    completed_at: datetime
    duration: float = Field(ge=0.0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, LearningMetadataValue] = Field(default_factory=dict)

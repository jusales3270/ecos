"""Typed immutable Governance Engine models."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.decision import DecisionPackage
from ecos.planner import CognitivePlan, RiskLevel

GovernanceMetadataValue = str | int | float | bool | None


class GovernanceModel(BaseModel):
    """Base immutable governance model."""

    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )


class ImpactLevel(StrEnum):
    """Canonical impact levels for governance."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class GovernanceActionType(StrEnum):
    """Known action classes governance can validate."""

    RECOMMENDATION = "recommendation"
    DECISION_SUPPORT = "decision_support"
    EXECUTION = "execution"
    CONTINUATION = "continuation"


class PolicyStatus(StrEnum):
    """Supported policy lifecycle states."""

    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class PolicyDomain(StrEnum):
    """Supported organizational policy domains."""

    FINANCIAL = "financial"
    LEGAL = "legal"
    COMPLIANCE = "compliance"
    SECURITY = "security"
    PRIVACY = "privacy"
    DATA = "data"
    TECHNOLOGY = "technology"
    PROCUREMENT = "procurement"
    OPERATIONS = "operations"
    HUMAN_RESOURCES = "human_resources"
    EXECUTIVE = "executive"
    AI_USAGE = "ai_usage"
    GENERAL = "general"


class EnforcementLevel(StrEnum):
    """Policy enforcement levels."""

    ADVISORY = "advisory"
    REQUIRED = "required"
    BLOCKING = "blocking"
    CRITICAL = "critical"


class RuleOperator(StrEnum):
    """Allowlisted structured policy rule operators."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    ALL = "all"
    ANY = "any"
    NOT = "not"


class RuleEvaluationStatus(StrEnum):
    """Possible policy rule evaluation outcomes."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"


class ComplianceStatus(StrEnum):
    """Compliance report statuses."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    REVIEW_REQUIRED = "review_required"
    INDETERMINATE = "indeterminate"


class AuthorizationDecisionValue(StrEnum):
    """Authorization decision values."""

    AUTHORIZED = "authorized"
    DENIED = "denied"
    REVIEW_REQUIRED = "review_required"
    AWAITING_APPROVAL = "awaiting_approval"
    NOT_APPLICABLE = "not_applicable"


class GovernanceResultStatus(StrEnum):
    """Final or paused governance statuses."""

    AUTHORIZED = "authorized"
    DENIED = "denied"
    AWAITING_APPROVAL = "awaiting_approval"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class ApprovalLevel(IntEnum):
    """Official ECOS approval levels."""

    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4
    LEVEL_5 = 5


class ApprovalRequestStatus(StrEnum):
    """Lifecycle of a human approval request."""

    PENDING = "pending"
    PARTIALLY_APPROVED = "partially_approved"
    GRANTED = "granted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CANCELLED = "cancelled"


class HumanDecision(StrEnum):
    """Human approval decision values."""

    APPROVE = "approve"
    REJECT = "reject"
    REVOKE = "revoke"


class PolicyRule(GovernanceModel):
    """Structured non-executable policy rule."""

    rule_id: str = Field(min_length=1)
    operator: RuleOperator
    field: str | None = None
    value: Any = None
    rules: tuple[PolicyRule, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("rules", "reason_codes", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[object, ...]:
        """Normalize immutable tuple fields."""
        return tuple(value or ())


class OrganizationalPolicy(GovernanceModel):
    """Versioned immutable organizational policy."""

    policy_id: str = Field(min_length=1)
    organization_id: UUID
    name: str = Field(min_length=1)
    domain: PolicyDomain = PolicyDomain.GENERAL
    version: str = Field(min_length=1)
    status: PolicyStatus = PolicyStatus.ACTIVE
    effective_from: datetime
    effective_until: datetime | None = None
    enforcement_level: EnforcementLevel = EnforcementLevel.REQUIRED
    priority: int = Field(default=100, ge=0)
    scope: tuple[str, ...] = Field(default_factory=tuple)
    applicable_actions: tuple[GovernanceActionType, ...] = Field(default_factory=tuple)
    rules: tuple[PolicyRule, ...] = Field(default_factory=tuple)
    required_approval_level: ApprovalLevel | None = None
    required_roles: tuple[str, ...] = Field(default_factory=tuple)
    minimum_approvals: int = Field(default=0, ge=0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)

    @field_validator(
        "scope",
        "applicable_actions",
        "rules",
        "required_roles",
        "reason_codes",
        mode="before",
    )
    @classmethod
    def tuple_fields(cls, value: object) -> tuple[object, ...]:
        """Normalize tuple fields."""
        return tuple(value or ())

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        """Validate policy version and time bounds."""
        if self.effective_from.tzinfo is None:
            msg = "effective_from must be timezone-aware"
            raise ValueError(msg)
        if self.effective_until is not None:
            if self.effective_until.tzinfo is None:
                msg = "effective_until must be timezone-aware"
                raise ValueError(msg)
            if self.effective_until <= self.effective_from:
                msg = "effective_until must be after effective_from"
                raise ValueError(msg)
        return self


class PolicySet(GovernanceModel):
    """A deterministic collection of policies."""

    policies: tuple[OrganizationalPolicy, ...] = Field(default_factory=tuple)

    @field_validator("policies", mode="before")
    @classmethod
    def tuple_policies(cls, value: object) -> tuple[OrganizationalPolicy, ...]:
        """Normalize policies."""
        return tuple(value or ())


class GovernanceContext(GovernanceModel):
    """Safe fields available for policy evaluation."""

    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    user_id: UUID | None = None
    actor_id: UUID | None = None
    current_stage: str
    requested_action: str
    action_type: GovernanceActionType
    risk_level: RiskLevel
    impact_level: ImpactLevel
    execution_requested: bool = False
    affected_domains: tuple[PolicyDomain, ...] = Field(default_factory=tuple)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reversibility: bool = True
    rollback_available: bool = True
    resources: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)

    @field_validator("affected_domains", "resources", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[object, ...]:
        """Normalize tuple fields."""
        return tuple(value or ())


class GovernanceRequest(GovernanceModel):
    """Input consumed by GovernanceEngine."""

    governance_id: UUID
    request_id: UUID | None = None
    session_id: UUID
    organization_id: UUID
    plan_id: UUID
    correlation_id: UUID
    user_id: UUID | None = None
    actor_id: UUID | None = None
    cognitive_plan: CognitivePlan
    current_stage: str
    requested_action: str
    action_type: GovernanceActionType
    recommendation: Any | None = None
    decision_package: DecisionPackage | None = None
    execution_requested: bool = False
    risk_level: RiskLevel
    impact_level: ImpactLevel = ImpactLevel.LOW
    affected_domains: tuple[PolicyDomain, ...] = Field(default_factory=tuple)
    applicable_policy_ids: tuple[str, ...] = Field(default_factory=tuple)
    policy_context: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)
    approval_state: Any | None = None
    governance_state: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)
    resources: tuple[str, ...] = Field(default_factory=tuple)
    reversibility: bool = True
    rollback_available: bool = True
    execution_window: tuple[datetime, datetime] | None = None
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)

    @field_validator(
        "affected_domains",
        "applicable_policy_ids",
        "resources",
        mode="before",
    )
    @classmethod
    def tuple_fields(cls, value: object) -> tuple[object, ...]:
        """Normalize tuple fields."""
        return tuple(value or ())

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Reject partial or mismatched requests."""
        if self.cognitive_plan.plan_id != self.plan_id:
            msg = "request plan_id does not match cognitive plan"
            raise ValueError(msg)
        if self.cognitive_plan.session_id != self.session_id:
            msg = "request session_id does not match cognitive plan"
            raise ValueError(msg)
        if self.cognitive_plan.organization_id != self.organization_id:
            msg = "request organization_id does not match cognitive plan"
            raise ValueError(msg)
        if (
            self.action_type
            in {GovernanceActionType.RECOMMENDATION, GovernanceActionType.EXECUTION}
            and self.recommendation is None
            and self.decision_package is None
        ):
            msg = "recommendation or decision_package is required"
            raise ValueError(msg)
        if self.execution_window is not None:
            starts_at, ends_at = self.execution_window
            if ends_at <= starts_at:
                msg = "execution_window end must be after start"
                raise ValueError(msg)
        return self

    def to_context(self) -> GovernanceContext:
        """Build allowlisted policy context from the request."""
        confidence = _extract_confidence(self)
        return GovernanceContext(
            organization_id=self.organization_id,
            session_id=self.session_id,
            plan_id=self.plan_id,
            correlation_id=self.correlation_id,
            user_id=self.user_id,
            actor_id=self.actor_id,
            current_stage=self.current_stage,
            requested_action=self.requested_action,
            action_type=self.action_type,
            risk_level=self.risk_level,
            impact_level=self.impact_level,
            execution_requested=self.execution_requested,
            affected_domains=self.affected_domains,
            confidence=confidence,
            reversibility=self.reversibility,
            rollback_available=self.rollback_available,
            resources=self.resources,
            metadata=self.policy_context,
        )


class PolicyEvaluation(GovernanceModel):
    """Result of evaluating one rule in one policy."""

    policy_id: str
    policy_version: str
    rule_id: str
    enforcement_level: EnforcementLevel
    status: RuleEvaluationStatus
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class PolicyViolation(GovernanceModel):
    """Safe policy violation record."""

    violation_id: UUID
    policy_id: str
    policy_version: str
    rule_id: str
    enforcement_level: EnforcementLevel
    severity: str
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    safe_message: str
    blocking: bool
    remediation_required: bool
    human_escalation_required: bool
    detected_at: datetime
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)


class ExplainabilityReport(GovernanceModel):
    """Validation of recommendation explainability structure."""

    valid: bool
    completeness_score: float = Field(ge=0.0, le=1.0)
    missing_fields: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class ComplianceReport(GovernanceModel):
    """Immutable governance compliance report."""

    report_id: UUID
    governance_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    status: ComplianceStatus
    evaluated_policies: tuple[str, ...] = Field(default_factory=tuple)
    passed_rules: tuple[PolicyEvaluation, ...] = Field(default_factory=tuple)
    failed_rules: tuple[PolicyEvaluation, ...] = Field(default_factory=tuple)
    indeterminate_rules: tuple[PolicyEvaluation, ...] = Field(default_factory=tuple)
    violations: tuple[PolicyViolation, ...] = Field(default_factory=tuple)
    explainability_report: ExplainabilityReport
    risk_level: RiskLevel
    approval_level: ApprovalLevel
    human_review_required: bool
    generated_at: datetime
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)


class ApprovalRequirement(GovernanceModel):
    """Computed human approval requirement."""

    approval_level: ApprovalLevel
    required_roles: tuple[str, ...]
    minimum_approvals: int = Field(ge=0)
    distinct_approvers_required: bool = True
    approval_required: bool
    auto_approval_allowed: bool = False
    score: int = Field(ge=0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class AuthorizationDecision(GovernanceModel):
    """Typed authorization decision scoped to one request."""

    authorization_id: UUID
    governance_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    action_scope: str
    decision: AuthorizationDecisionValue
    risk_level: RiskLevel
    compliance_status: ComplianceStatus
    approval_level: ApprovalLevel
    approval_required: bool
    execution_authorized: bool
    valid_from: datetime
    valid_until: datetime
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    human_escalation_required: bool = False
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)


class ApprovalDecision(GovernanceModel):
    """Explicit human decision consumed by GovernanceEngine."""

    approval_decision_id: UUID
    approval_request_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    actor_id: UUID
    actor_role: str = Field(min_length=1)
    decision: HumanDecision
    reason: str | None = None
    decided_at: datetime
    identity_reference: str = Field(min_length=1)
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        """Require reason for reject and revoke decisions."""
        if self.decision in {HumanDecision.REJECT, HumanDecision.REVOKE} and not (
            self.reason and self.reason.strip()
        ):
            msg = "reason is required for reject and revoke"
            raise ValueError(msg)
        return self


class ApprovalRequest(GovernanceModel):
    """Immutable human approval request."""

    approval_request_id: UUID
    governance_id: UUID
    authorization_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    action_scope: str
    approval_level: ApprovalLevel
    required_roles: tuple[str, ...]
    minimum_approvals: int = Field(ge=1)
    distinct_approvers_required: bool = True
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING
    requested_at: datetime
    expires_at: datetime
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    current_approvals: tuple[ApprovalDecision, ...] = Field(default_factory=tuple)
    current_rejections: tuple[ApprovalDecision, ...] = Field(default_factory=tuple)
    metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)


class ApprovalState(GovernanceModel):
    """Governance-owned approval state."""

    approval_request: ApprovalRequest | None = None
    decisions: tuple[ApprovalDecision, ...] = Field(default_factory=tuple)
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING


class AuditRecord(GovernanceModel):
    """Append-only safe audit record returned by GovernanceEngine."""

    audit_id: UUID
    sequence: int = Field(ge=1)
    governance_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    timestamp: datetime
    actor_id: UUID | None = None
    actor_role: str | None = None
    action: str
    policy_references: tuple[str, ...] = Field(default_factory=tuple)
    decision: str | None = None
    approval_level: ApprovalLevel | None = None
    risk_level: RiskLevel | None = None
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    outcome: str
    previous_state: str | None = None
    new_state: str | None = None
    safe_metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)


class GovernanceFailure(GovernanceModel):
    """Safe governance failure report."""

    failure_id: UUID
    governance_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    occurred_at: datetime
    safe_message: str
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    human_escalation_required: bool = False


class GovernanceResult(GovernanceModel):
    """Complete Governance Engine result."""

    governance_id: UUID
    organization_id: UUID
    session_id: UUID
    plan_id: UUID
    correlation_id: UUID
    status: GovernanceResultStatus
    authorization_decision: AuthorizationDecision | None
    compliance_report: ComplianceReport | None
    explainability_report: ExplainabilityReport | None
    approval_requirement: ApprovalRequirement | None
    approval_request: ApprovalRequest | None
    approval_state: ApprovalState | None
    policy_violations: tuple[PolicyViolation, ...] = Field(default_factory=tuple)
    audit_records: tuple[AuditRecord, ...] = Field(default_factory=tuple)
    execution_authorized: bool
    continuation_allowed: bool
    human_review_required: bool
    completed_at: datetime | None
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, GovernanceMetadataValue] = Field(default_factory=dict)
    failure: GovernanceFailure | None = None


class GovernanceConfig(GovernanceModel):
    """Immutable Governance Engine configuration."""

    authorization_ttl: timedelta = timedelta(minutes=15)
    approval_request_ttl: timedelta = timedelta(hours=24)
    board_quorum: int = Field(default=3, ge=1)


class ValidatedIdentity(GovernanceModel):
    """Identity data validated by an injected identity port."""

    actor_id: UUID
    organization_id: UUID
    roles: tuple[str, ...]
    active: bool
    verified: bool
    identity_reference: str


def _extract_confidence(request: GovernanceRequest) -> float | None:
    package = request.decision_package
    if package is not None:
        return package.recommendation.confidence
    recommendation = request.recommendation
    value = getattr(recommendation, "confidence", None)
    if isinstance(recommendation, dict):
        value = recommendation.get("confidence")
    if isinstance(value, int | float):
        normalized = float(value)
        if 0.0 <= normalized <= 1.0:
            return normalized
    return None

"""Tests for the real ECOS Governance Engine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ecos.decision import (
    AlternativeAnalysis,
    DecisionImpact,
    DecisionPackage,
    ExecutiveBrief,
    Recommendation,
    RecommendationType,
    RiskSummary,
)
from ecos.domain import Objective
from ecos.events import EventService, EventType
from ecos.governance import (
    ApprovalDecision,
    ApprovalLevel,
    ApprovalRequestStatus,
    AuthorizationDecisionValue,
    ComplianceStatus,
    DefaultApprovalPolicyProvider,
    EnforcementLevel,
    GovernanceActionType,
    GovernanceConfig,
    GovernanceEngine,
    GovernanceRequest,
    GovernanceResultStatus,
    HumanDecision,
    ImpactLevel,
    InMemoryPolicyProvider,
    InvalidGovernanceRequestError,
    InvalidIdentityError,
    OrganizationalPolicy,
    PolicyDomain,
    PolicyRule,
    PolicyStatus,
    RuleOperator,
    StaticIdentityPort,
    UnauthorizedRoleError,
    ValidatedIdentity,
)
from ecos.planner import (
    CognitivePlan,
    EngineSelection,
    ExecutionStrategy,
    Pipeline,
    PipelineStep,
    PlanningStrategy,
    RiskLevel,
)
from ecos.runtime import FakeEventBus

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
ORG_ID = UUID("00000000-0000-4000-8000-000000000201")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000202")
PLAN_ID = UUID("00000000-0000-4000-8000-000000000203")
GOVERNANCE_ID = UUID("00000000-0000-4000-8000-000000000204")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000205")


def make_plan(*, risk: RiskLevel = RiskLevel.LOW) -> CognitivePlan:
    """Build a minimal immutable cognitive plan."""
    objective = Objective(organization_id=ORG_ID, title="Governed decision")
    strategy = ExecutionStrategy(
        strategy=PlanningStrategy.BALANCED,
        rationale="Test strategy.",
    )
    decision = PipelineStep(order=1, engine="decision")
    governance = PipelineStep(
        order=2,
        engine="governance",
        dependencies=(decision.stage_id,),
    )
    return CognitivePlan(
        plan_id=PLAN_ID,
        session_id=SESSION_ID,
        organization_id=ORG_ID,
        objective=objective,
        strategy=strategy,
        selected_engines=(
            EngineSelection(engine="decision", reason="test"),
            EngineSelection(engine="governance", reason="test"),
        ),
        pipeline=Pipeline(steps=(decision, governance)),
        risk_level=risk,
    )


def make_decision_package(*, confidence: float = 0.8) -> DecisionPackage:
    """Build a decision package with complete explainability fields."""
    recommendation = Recommendation(
        session_id=SESSION_ID,
        recommendation_type=RecommendationType.STRATEGIC,
        title="Proceed",
        summary="Proceed with governed continuation.",
        confidence=confidence,
        risks=[
            RiskSummary(
                title="Risk",
                description="Approval may be required.",
                impact=DecisionImpact.MEDIUM,
                probability=0.2,
            )
        ],
        alternatives=[
            AlternativeAnalysis(
                title="Wait",
                summary="Wait for more evidence.",
                pros=["More context."],
                cons=["Slower action."],
                score=0.4,
            )
        ],
        expected_impact=DecisionImpact.LOW,
    )
    return DecisionPackage(
        recommendation=recommendation,
        executive_brief=ExecutiveBrief(
            title="Brief",
            summary="Reasoning summary.",
            key_points=["Evidence reviewed"],
        ),
        supporting_evidence=["evidence-1"],
        metadata={"test": True},
    )


def make_policy(
    *,
    policy_id: str = "policy",
    rule: PolicyRule | None = None,
    enforcement: EnforcementLevel = EnforcementLevel.REQUIRED,
    level: ApprovalLevel | None = None,
    roles: tuple[str, ...] = (),
    minimum: int = 0,
    status: PolicyStatus = PolicyStatus.ACTIVE,
    effective_from: datetime = NOW - timedelta(days=1),
    effective_until: datetime | None = NOW + timedelta(days=1),
    priority: int = 10,
) -> OrganizationalPolicy:
    """Build a versioned organizational policy."""
    return OrganizationalPolicy(
        policy_id=policy_id,
        organization_id=ORG_ID,
        name=policy_id,
        domain=PolicyDomain.GENERAL,
        version="1.0.0",
        status=status,
        effective_from=effective_from,
        effective_until=effective_until,
        enforcement_level=enforcement,
        priority=priority,
        applicable_actions=(GovernanceActionType.CONTINUATION,),
        rules=(
            rule
            or PolicyRule(
                rule_id="risk_low",
                operator=RuleOperator.EQUALS,
                field="risk_level",
                value=RiskLevel.LOW.value,
            ),
        ),
        required_approval_level=level,
        required_roles=roles,
        minimum_approvals=minimum,
        reason_codes=(policy_id,),
    )


def make_engine(
    policies: tuple[OrganizationalPolicy, ...],
    *,
    identities: tuple[ValidatedIdentity, ...] = (),
) -> tuple[GovernanceEngine, FakeEventBus]:
    """Build GovernanceEngine with injected test doubles."""
    bus = FakeEventBus()
    engine = GovernanceEngine(
        policy_provider=InMemoryPolicyProvider(policies),
        approval_policy_provider=DefaultApprovalPolicyProvider(GovernanceConfig()),
        event_service=EventService(bus),
        identity_port=StaticIdentityPort(identities),
        clock=lambda: NOW,
        id_generator=uuid4,
        config=GovernanceConfig(),
    )
    return engine, bus


def make_request(
    *,
    policies: tuple[str, ...] = ("policy",),
    risk: RiskLevel = RiskLevel.LOW,
    impact: ImpactLevel = ImpactLevel.LOW,
    execution_requested: bool = False,
    recommendation: object | None = None,
) -> GovernanceRequest:
    """Build a valid governance request."""
    return GovernanceRequest(
        governance_id=GOVERNANCE_ID,
        organization_id=ORG_ID,
        session_id=SESSION_ID,
        plan_id=PLAN_ID,
        correlation_id=SESSION_ID,
        cognitive_plan=make_plan(risk=risk),
        current_stage="governance",
        requested_action="continue",
        action_type=GovernanceActionType.CONTINUATION,
        decision_package=make_decision_package() if recommendation is None else None,
        recommendation=recommendation,
        execution_requested=execution_requested,
        risk_level=risk,
        impact_level=impact,
        applicable_policy_ids=policies,
        policy_context={"flag": "on", "amount": 10},
    )


def test_governance_injects_dependencies_and_authorizes_level_1() -> None:
    """Level 1 non-execution can be auto-authorized by explicit policy."""
    engine, bus = make_engine((make_policy(level=ApprovalLevel.LEVEL_1),))

    result = engine.evaluate(make_request())

    assert result.status is GovernanceResultStatus.AUTHORIZED
    assert result.execution_authorized is False
    assert result.authorization_decision is not None
    assert result.authorization_decision.decision is (
        AuthorizationDecisionValue.AUTHORIZED
    )
    assert result.approval_requirement.approval_level is ApprovalLevel.LEVEL_1
    assert [record.sequence for record in result.audit_records] == list(
        range(1, len(result.audit_records) + 1)
    )
    assert EventType.GOVERNANCE_STARTED in [
        envelope.event.event_type for envelope in bus.envelopes
    ]


def test_governance_models_are_immutable_and_plan_is_not_mutated() -> None:
    """Governance result objects are frozen and input plan is not changed."""
    request = make_request()
    plan_dump = request.cognitive_plan.model_dump(mode="json")
    engine, _ = make_engine((make_policy(),))

    result = engine.evaluate(request)

    assert request.cognitive_plan.model_dump(mode="json") == plan_dump
    with pytest.raises(ValidationError):
        result.audit_records[0].sequence = 99


def test_policy_selection_rejects_expired_and_ambiguous_versions() -> None:
    """Policy selection is active, versioned and deterministic."""
    expired = make_policy(effective_until=NOW - timedelta(seconds=1))
    engine, _ = make_engine((expired,))

    with pytest.raises(InvalidGovernanceRequestError, match="expired"):
        engine.evaluate(make_request())

    first = make_policy(policy_id="ambiguous")
    second = make_policy(policy_id="ambiguous", priority=11)
    engine, _ = make_engine((first, second))

    with pytest.raises(InvalidGovernanceRequestError, match="ambiguous"):
        engine.evaluate(make_request(policies=("ambiguous",)))


@pytest.mark.parametrize(
    ("operator", "field", "value"),
    [
        (RuleOperator.EQUALS, "risk_level", RiskLevel.LOW.value),
        (RuleOperator.NOT_EQUALS, "risk_level", RiskLevel.HIGH.value),
        (RuleOperator.GREATER_THAN, "metadata.amount", 5),
        (RuleOperator.GREATER_THAN_OR_EQUAL, "metadata.amount", 10),
        (RuleOperator.LESS_THAN, "metadata.amount", 20),
        (RuleOperator.LESS_THAN_OR_EQUAL, "metadata.amount", 10),
        (RuleOperator.IN, "risk_level", ("low", "medium")),
        (RuleOperator.NOT_IN, "risk_level", ("high", "critical")),
        (RuleOperator.CONTAINS, "affected_domains", "general"),
        (RuleOperator.NOT_CONTAINS, "resources", "external_api"),
        (RuleOperator.EXISTS, "metadata.flag", None),
        (RuleOperator.NOT_EXISTS, "metadata.missing", None),
    ],
)
def test_policy_rule_operators_pass(
    operator: RuleOperator,
    field: str,
    value: object,
) -> None:
    """Allowlisted operators evaluate structured fields without dynamic code."""
    rule = PolicyRule(
        rule_id=operator.value,
        operator=operator,
        field=field,
        value=value,
    )
    engine, _ = make_engine((make_policy(rule=rule),))
    request = make_request()
    request = request.model_copy(update={"affected_domains": (PolicyDomain.GENERAL,)})

    result = engine.evaluate(request)

    assert result.compliance_report.status is ComplianceStatus.COMPLIANT


def test_nested_rule_operators_and_rejected_operator() -> None:
    """all, any, not work and unknown operators are rejected clearly."""
    nested = PolicyRule(
        rule_id="all",
        operator=RuleOperator.ALL,
        rules=(
            PolicyRule(
                rule_id="risk",
                operator=RuleOperator.EQUALS,
                field="risk_level",
                value="low",
            ),
            PolicyRule(
                rule_id="not_exec",
                operator=RuleOperator.NOT,
                rules=(
                    PolicyRule(
                        rule_id="exec",
                        operator=RuleOperator.EQUALS,
                        field="execution_requested",
                        value=True,
                    ),
                ),
            ),
        ),
    )
    engine, _ = make_engine((make_policy(rule=nested),))

    assert engine.evaluate(make_request()).status is GovernanceResultStatus.AUTHORIZED

    bad = PolicyRule.model_construct(
        rule_id="bad",
        operator="unknown",
        field="risk_level",
        value="low",
        rules=(),
        reason_codes=(),
    )
    engine, _ = make_engine((make_policy(rule=bad),))

    with pytest.raises(InvalidGovernanceRequestError, match="operator"):
        engine.evaluate(make_request())


def test_enforcement_semantics_and_explainability() -> None:
    """Advisory warns, required reviews, blocking denies and explainability blocks."""
    failing = PolicyRule(
        rule_id="fail",
        operator=RuleOperator.EQUALS,
        field="risk_level",
        value="critical",
    )
    advisory_engine, _ = make_engine(
        (make_policy(rule=failing, enforcement=EnforcementLevel.ADVISORY),)
    )
    advisory = advisory_engine.evaluate(make_request())
    assert advisory.status is GovernanceResultStatus.AUTHORIZED
    assert advisory.warnings

    required_engine, _ = make_engine(
        (make_policy(rule=failing, enforcement=EnforcementLevel.REQUIRED),)
    )
    required = required_engine.evaluate(make_request())
    assert required.status is GovernanceResultStatus.REVIEW_REQUIRED

    blocking_engine, _ = make_engine(
        (make_policy(rule=failing, enforcement=EnforcementLevel.BLOCKING),)
    )
    blocking = blocking_engine.evaluate(make_request())
    assert blocking.status is GovernanceResultStatus.DENIED
    assert blocking.policy_violations[0].blocking is True

    bad_recommendation = {
        "objective": "x",
        "evidence": ["x"],
        "confidence": 1.2,
        "recommendation": "x",
    }
    invalid = blocking_engine.evaluate(make_request(recommendation=bad_recommendation))
    assert invalid.explainability_report.valid is False
    assert invalid.status is GovernanceResultStatus.DENIED


@pytest.mark.parametrize(
    ("risk", "impact", "expected"),
    [
        (RiskLevel.LOW, ImpactLevel.LOW, ApprovalLevel.LEVEL_1),
        (RiskLevel.MEDIUM, ImpactLevel.LOW, ApprovalLevel.LEVEL_2),
        (RiskLevel.HIGH, ImpactLevel.LOW, ApprovalLevel.LEVEL_3),
        (RiskLevel.CRITICAL, ImpactLevel.LOW, ApprovalLevel.LEVEL_4),
    ],
)
def test_approval_level_calculation(
    risk: RiskLevel,
    impact: ImpactLevel,
    expected: ApprovalLevel,
) -> None:
    """Risk and impact deterministically elevate approval level."""
    engine, _ = make_engine((make_policy(policy_id="policy"),))

    result = engine.evaluate(make_request(risk=risk, impact=impact))

    assert result.approval_requirement.approval_level is expected


def test_policy_can_elevate_approval_and_execution_requires_human_approval() -> None:
    """Policies elevate requirements and execution is never auto-authorized."""
    policy = make_policy(
        level=ApprovalLevel.LEVEL_5,
        roles=("executive_board",),
        minimum=3,
    )
    engine, _ = make_engine((policy,))

    result = engine.evaluate(make_request(execution_requested=True))

    assert result.status is GovernanceResultStatus.AWAITING_APPROVAL
    assert result.execution_authorized is False
    assert result.approval_request is not None
    assert result.approval_request.required_roles == ("executive_board",)
    assert result.approval_request.minimum_approvals == 3


def test_approval_decision_roles_quorum_rejection_and_idempotency() -> None:
    """Human approval decisions require explicit valid identity and quorum."""
    manager = ValidatedIdentity(
        actor_id=ACTOR_ID,
        organization_id=ORG_ID,
        roles=("manager",),
        active=True,
        verified=True,
        identity_reference="manager-ref",
    )
    executive_id = UUID("00000000-0000-4000-8000-000000000206")
    executive = ValidatedIdentity(
        actor_id=executive_id,
        organization_id=ORG_ID,
        roles=("executive",),
        active=True,
        verified=True,
        identity_reference="executive-ref",
    )
    policy = make_policy(
        level=ApprovalLevel.LEVEL_4,
        roles=("manager", "executive"),
        minimum=2,
    )
    engine, _ = make_engine((policy,), identities=(manager, executive))
    result = engine.evaluate(make_request(execution_requested=True))
    approval_request = result.approval_request
    assert approval_request is not None

    manager_decision = ApprovalDecision(
        approval_decision_id=uuid4(),
        approval_request_id=approval_request.approval_request_id,
        organization_id=ORG_ID,
        session_id=SESSION_ID,
        plan_id=PLAN_ID,
        actor_id=ACTOR_ID,
        actor_role="manager",
        decision=HumanDecision.APPROVE,
        decided_at=NOW,
        identity_reference="manager-ref",
    )
    partial, audit = engine.record_decision(
        approval_request=approval_request,
        decision=manager_decision,
        audit_records=result.audit_records,
    )
    replay, replay_audit = engine.record_decision(
        approval_request=partial,
        decision=manager_decision,
        audit_records=audit,
    )
    assert replay == partial
    assert replay_audit == audit
    assert partial.status is ApprovalRequestStatus.PARTIALLY_APPROVED

    executive_decision = manager_decision.model_copy(
        update={
            "approval_decision_id": uuid4(),
            "actor_id": executive_id,
            "actor_role": "executive",
            "identity_reference": "executive-ref",
        }
    )
    granted, audit = engine.record_decision(
        approval_request=partial,
        decision=executive_decision,
        audit_records=audit,
    )
    assert granted.status is ApprovalRequestStatus.GRANTED
    assert len(granted.current_approvals) == 2
    assert [record.sequence for record in audit] == list(range(1, len(audit) + 1))

    unknown_decision = manager_decision.model_copy(
        update={"approval_decision_id": uuid4(), "actor_id": uuid4()}
    )
    with pytest.raises(InvalidIdentityError):
        engine.record_decision(
            approval_request=approval_request,
            decision=unknown_decision,
        )

    bad_role = manager_decision.model_copy(
        update={"approval_decision_id": uuid4(), "actor_role": "executive"}
    )
    with pytest.raises(UnauthorizedRoleError):
        engine.record_decision(approval_request=approval_request, decision=bad_role)


def test_governance_architecture_has_no_forbidden_dependencies() -> None:
    """Governance does not import forbidden infrastructure or dynamic execution."""
    source = "\n".join(
        path.read_text() for path in Path("src/ecos/governance").glob("*.py")
    )

    assert "openai" not in source.lower()
    assert "AIProvider" not in source
    assert "Container" not in source
    assert "sqlalchemy" not in source.lower()
    assert "postgres" not in source.lower()
    assert "os.environ" not in source
    assert ("ev" + "al(") not in source

"""Deterministic Governance Engine implementation."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.governance.exceptions import (
    AmbiguousPolicyError,
    ApprovalAfterRejectionError,
    ApprovalRequestExpiredError,
    ConflictingDecisionReplayError,
    ExpiredPolicyError,
    FieldNotAllowedError,
    IncompatibleApprovalError,
    InvalidGovernanceRequestError,
    InvalidIdentityError,
    OperatorNotAllowedError,
    PolicyNotFoundError,
    UnauthorizedRoleError,
)
from ecos.governance.models import (
    ApprovalDecision,
    ApprovalLevel,
    ApprovalRequest,
    ApprovalRequestStatus,
    ApprovalRequirement,
    ApprovalState,
    AuditRecord,
    AuthorizationDecision,
    AuthorizationDecisionValue,
    ComplianceReport,
    ComplianceStatus,
    EnforcementLevel,
    ExplainabilityReport,
    GovernanceActionType,
    GovernanceConfig,
    GovernanceContext,
    GovernanceRequest,
    GovernanceResult,
    GovernanceResultStatus,
    HumanDecision,
    ImpactLevel,
    OrganizationalPolicy,
    PolicyEvaluation,
    PolicyRule,
    PolicyStatus,
    PolicyViolation,
    RuleEvaluationStatus,
    RuleOperator,
)
from ecos.governance.provider import (
    ApprovalPolicyProvider,
    IdentityPort,
    PolicyProvider,
)
from ecos.planner import ObjectiveClassification, RiskLevel

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]


class GovernanceEngine:
    """Validate whether cognition may proceed without performing cognition."""

    def __init__(
        self,
        *,
        policy_provider: PolicyProvider,
        approval_policy_provider: ApprovalPolicyProvider,
        event_service: EventService,
        identity_port: IdentityPort,
        clock: Clock,
        id_generator: IdGenerator,
        config: GovernanceConfig,
    ) -> None:
        self._policy_provider = policy_provider
        self._approval_policy_provider = approval_policy_provider
        self._event_service = event_service
        self._identity_port = identity_port
        self._clock = clock
        self._id_generator = id_generator
        self._config = config

    def evaluate(self, request: GovernanceRequest) -> GovernanceResult:
        """Evaluate governance for a request."""
        audits: list[AuditRecord] = []
        try:
            self._validate_request(request)
            self._audit(audits, request, "governance_started", "started")
            self._publish(request, EventType.GOVERNANCE_STARTED)
            policies = self._select_policies(request)
            self._publish(request, EventType.POLICY_EVALUATION_STARTED)
            explainability = self._validate_explainability(request)
            self._audit(
                audits,
                request,
                "explainability_validated",
                "valid" if explainability.valid else "invalid",
                reason_codes=explainability.reason_codes,
            )
            self._publish(
                request,
                EventType.EXPLAINABILITY_VALIDATED
                if explainability.valid
                else EventType.EXPLAINABILITY_FAILED,
            )
            policy_results = self._evaluate_policies(request, policies)
            for violation in policy_results["violations"]:
                self._audit(
                    audits,
                    request,
                    "violation_detected",
                    "blocked" if violation.blocking else "warning",
                    policy_references=(violation.policy_id,),
                    reason_codes=violation.reason_codes,
                )
                self._publish(
                    request,
                    EventType.POLICY_VIOLATION_DETECTED,
                    policy_references=(violation.policy_id,),
                    reason_codes=violation.reason_codes,
                )
            level = self._approval_level(request, policies)
            policy_requirements = self._policy_requirements(request, policies)
            approval_requirement = self._approval_policy_provider.requirement_for(
                level=level,
                request=request,
                policy_requirements=policy_requirements,
            )
            compliance = self._compliance_report(
                request,
                policies,
                explainability,
                approval_requirement.approval_level,
                policy_results,
            )
            self._audit(
                audits,
                request,
                "policy_evaluated",
                compliance.status.value,
                policy_references=compliance.evaluated_policies,
                reason_codes=compliance.reason_codes,
            )
            self._publish(
                request,
                EventType.COMPLIANCE_PASSED
                if compliance.status is ComplianceStatus.COMPLIANT
                else EventType.COMPLIANCE_FAILED,
            )
            authorization = self._authorization_decision(
                request,
                compliance,
                approval_requirement,
            )
            approval_request = self._approval_request(
                request,
                authorization,
                approval_requirement,
            )
            status = self._result_status(authorization)
            if approval_request is not None:
                self._audit(
                    audits,
                    request,
                    "approval_requested",
                    approval_request.status.value,
                    policy_references=approval_request.policy_references,
                    approval_level=approval_requirement.approval_level,
                    reason_codes=approval_request.reason_codes,
                )
                self._publish(
                    request,
                    EventType.APPROVAL_REQUESTED,
                    policy_references=approval_request.policy_references,
                    reason_codes=approval_request.reason_codes,
                )
            self._audit(
                audits,
                request,
                "authorization_decided",
                authorization.decision.value,
                policy_references=authorization.policy_references,
                approval_level=authorization.approval_level,
                risk_level=request.risk_level,
                reason_codes=authorization.reason_codes,
            )
            if authorization.decision is AuthorizationDecisionValue.AUTHORIZED:
                self._publish(request, EventType.AUTHORIZATION_GRANTED)
            elif authorization.decision is AuthorizationDecisionValue.DENIED:
                self._publish(request, EventType.AUTHORIZATION_DENIED)
            self._audit(audits, request, "governance_completed", status.value)
            if status is not GovernanceResultStatus.FAILED:
                self._publish(request, EventType.GOVERNANCE_COMPLETED)
            return GovernanceResult(
                governance_id=request.governance_id,
                organization_id=request.organization_id,
                session_id=request.session_id,
                plan_id=request.plan_id,
                correlation_id=request.correlation_id,
                status=status,
                authorization_decision=authorization,
                compliance_report=compliance,
                explainability_report=explainability,
                approval_requirement=approval_requirement,
                approval_request=approval_request,
                approval_state=ApprovalState(
                    approval_request=approval_request,
                    status=approval_request.status
                    if approval_request
                    else ApprovalRequestStatus.GRANTED,
                ),
                policy_violations=tuple(policy_results["violations"]),
                audit_records=tuple(audits),
                execution_authorized=authorization.execution_authorized,
                continuation_allowed=status is GovernanceResultStatus.AUTHORIZED,
                human_review_required=authorization.human_escalation_required,
                completed_at=self._now(),
                reason_codes=authorization.reason_codes,
                warnings=compliance.warnings,
                safe_metadata={"engine": "governance"},
            )
        except Exception as error:
            self._publish(request, EventType.GOVERNANCE_FAILED)
            raise InvalidGovernanceRequestError(str(error)) from error

    def record_decision(
        self,
        *,
        approval_request: ApprovalRequest,
        decision: ApprovalDecision,
        audit_records: tuple[AuditRecord, ...] = (),
    ) -> tuple[ApprovalRequest, tuple[AuditRecord, ...]]:
        """Record one explicit human approval decision idempotently."""
        self._validate_decision_scope(approval_request, decision)
        identity = self._identity_port.validate_identity(
            actor_id=decision.actor_id,
            organization_id=decision.organization_id,
        )
        if identity is None or not identity.active or not identity.verified:
            raise InvalidIdentityError("identity is unknown, inactive, or unverified")
        if decision.actor_role not in identity.roles:
            raise UnauthorizedRoleError("decision role was not validated for actor")
        if decision.actor_role not in approval_request.required_roles:
            raise UnauthorizedRoleError("actor role is not allowed for request")
        if approval_request.expires_at <= self._now():
            raise ApprovalRequestExpiredError("approval request is expired")
        if approval_request.status is ApprovalRequestStatus.REJECTED:
            raise ApprovalAfterRejectionError("approval request was already rejected")
        existing = [
            item
            for item in (
                *approval_request.current_approvals,
                *approval_request.current_rejections,
            )
            if item.approval_decision_id == decision.approval_decision_id
        ]
        if existing:
            if existing[0] == decision:
                return approval_request, audit_records
            raise ConflictingDecisionReplayError("approval decision replay conflicts")
        approvals = list(approval_request.current_approvals)
        rejections = list(approval_request.current_rejections)
        prior_decisions = (*approvals, *rejections)
        if any(item.actor_id == decision.actor_id for item in prior_decisions):
            raise ConflictingDecisionReplayError("actor already decided")
        status = approval_request.status
        action = "approval_recorded"
        if decision.decision is HumanDecision.APPROVE:
            approvals.append(decision)
            if self._quorum_met(approval_request, tuple(approvals)):
                status = ApprovalRequestStatus.GRANTED
                action = "approval_recorded"
                event_type = EventType.APPROVAL_GRANTED
            else:
                status = ApprovalRequestStatus.PARTIALLY_APPROVED
                event_type = EventType.APPROVAL_PARTIALLY_GRANTED
        elif decision.decision is HumanDecision.REJECT:
            rejections.append(decision)
            status = ApprovalRequestStatus.REJECTED
            action = "approval_rejected"
            event_type = EventType.APPROVAL_REJECTED
        else:
            status = ApprovalRequestStatus.REVOKED
            action = "approval_revoked"
            event_type = EventType.APPROVAL_REVOKED
        updated = approval_request.model_copy(
            update={
                "status": status,
                "current_approvals": tuple(approvals),
                "current_rejections": tuple(rejections),
            }
        )
        audit_list = list(audit_records)
        self._audit_for_scope(
            audit_list,
            governance_id=approval_request.governance_id,
            organization_id=approval_request.organization_id,
            session_id=approval_request.session_id,
            plan_id=approval_request.plan_id,
            correlation_id=approval_request.correlation_id,
            action=action,
            outcome=status.value,
            actor_id=decision.actor_id,
            actor_role=decision.actor_role,
            approval_level=approval_request.approval_level,
            reason_codes=(decision.decision.value,),
            previous_state=approval_request.status.value,
            new_state=status.value,
        )
        self._publish_scope(
            event_type,
            governance_id=approval_request.governance_id,
            organization_id=approval_request.organization_id,
            session_id=approval_request.session_id,
            plan_id=approval_request.plan_id,
            correlation_id=approval_request.correlation_id,
            reason_codes=(decision.decision.value,),
        )
        return updated, tuple(audit_list)

    def _validate_request(self, request: GovernanceRequest) -> None:
        if request.organization_id is None:
            raise InvalidGovernanceRequestError("organization_id is required")
        if request.session_id is None:
            raise InvalidGovernanceRequestError("session_id is required")
        if request.plan_id is None:
            raise InvalidGovernanceRequestError("plan_id is required")
        if request.correlation_id is None:
            raise InvalidGovernanceRequestError("correlation_id is required")
        if request.approval_state is not None:
            approval_request = request.approval_state.approval_request
            if approval_request is not None and (
                approval_request.organization_id != request.organization_id
                or approval_request.session_id != request.session_id
                or approval_request.plan_id != request.plan_id
            ):
                raise IncompatibleApprovalError("approval state scope mismatch")

    def _select_policies(
        self,
        request: GovernanceRequest,
    ) -> tuple[OrganizationalPolicy, ...]:
        now = self._now()
        policies = self._policy_provider.list_policies(
            organization_id=request.organization_id,
            policy_ids=request.applicable_policy_ids,
        )
        seen_policy_ids = {policy.policy_id for policy in policies}
        selected: dict[str, OrganizationalPolicy] = {}
        for policy in policies:
            if policy.organization_id != request.organization_id:
                continue
            if policy.status is not PolicyStatus.ACTIVE:
                continue
            if policy.effective_from > now:
                continue
            if policy.effective_until is not None and policy.effective_until <= now:
                if policy.policy_id in request.applicable_policy_ids:
                    raise ExpiredPolicyError(f"policy is expired: {policy.policy_id}")
                continue
            if policy.applicable_actions and request.action_type not in (
                policy.applicable_actions
            ):
                continue
            if policy.policy_id in selected:
                raise AmbiguousPolicyError(
                    f"ambiguous active policy {policy.policy_id}"
                )
            selected[policy.policy_id] = policy
        missing = set(request.applicable_policy_ids) - seen_policy_ids
        if missing:
            missing_policy = sorted(missing)[0]
            raise PolicyNotFoundError(f"policy not found: {missing_policy}")
        inactive = set(request.applicable_policy_ids) - set(selected)
        if inactive:
            inactive_policy = sorted(inactive)[0]
            raise PolicyNotFoundError(f"policy not active: {inactive_policy}")
        return tuple(
            sorted(
                selected.values(),
                key=lambda item: (item.priority, item.policy_id, item.version),
            )
        )

    def _validate_explainability(
        self,
        request: GovernanceRequest,
    ) -> ExplainabilityReport:
        fields = self._explainability_fields(request)
        required = (
            "objective",
            "evidence",
            "reasoning_summary",
            "assumptions",
            "risks",
            "alternatives",
            "confidence",
            "missing_information",
            "recommendation",
        )
        missing = tuple(
            name
            for name in required
            if _blank(fields.get(name), allow_empty=name == "missing_information")
        )
        warnings: list[str] = []
        confidence = fields.get("confidence")
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            missing = (
                (*missing, "confidence") if "confidence" not in missing else missing
            )
        if confidence == 1:
            warnings.append("absolute_confidence_claim")
        score = (len(required) - len(set(missing))) / len(required)
        return ExplainabilityReport(
            valid=not missing,
            completeness_score=max(0.0, min(score, 1.0)),
            missing_fields=tuple(sorted(set(missing))),
            warnings=tuple(warnings),
            reason_codes=()
            if not missing
            else tuple(f"missing_{field}" for field in sorted(set(missing))),
        )

    def _explainability_fields(
        self,
        request: GovernanceRequest,
    ) -> dict[str, object]:
        if request.decision_package is not None:
            package = request.decision_package
            recommendation = package.recommendation
            return {
                "objective": recommendation.title,
                "evidence": tuple(package.supporting_evidence),
                "reasoning_summary": package.executive_brief.summary,
                "assumptions": package.metadata.get("assumptions", ("tracked",)),
                "risks": tuple(risk.description for risk in recommendation.risks),
                "alternatives": tuple(
                    item.summary for item in recommendation.alternatives
                ),
                "confidence": recommendation.confidence,
                "missing_information": package.metadata.get(
                    "missing_information",
                    (),
                ),
                "recommendation": recommendation.summary,
            }
        recommendation = request.recommendation
        if isinstance(recommendation, dict):
            return dict(recommendation)
        return {
            "objective": getattr(recommendation, "title", None),
            "evidence": getattr(recommendation, "evidence", None),
            "reasoning_summary": getattr(recommendation, "reasoning_summary", None),
            "assumptions": getattr(recommendation, "assumptions", None),
            "risks": getattr(recommendation, "risks", None),
            "alternatives": getattr(recommendation, "alternatives", None),
            "confidence": getattr(recommendation, "confidence", None),
            "missing_information": getattr(
                recommendation,
                "missing_information",
                None,
            ),
            "recommendation": getattr(recommendation, "recommendation", None),
        }

    def _evaluate_policies(
        self,
        request: GovernanceRequest,
        policies: tuple[OrganizationalPolicy, ...],
    ) -> dict[str, tuple[object, ...]]:
        context = request.to_context()
        passed: list[PolicyEvaluation] = []
        failed: list[PolicyEvaluation] = []
        indeterminate: list[PolicyEvaluation] = []
        violations: list[PolicyViolation] = []
        for policy in policies:
            for rule in policy.rules:
                status = self._evaluate_rule(rule, context)
                evaluation = PolicyEvaluation(
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    rule_id=rule.rule_id,
                    enforcement_level=policy.enforcement_level,
                    status=status,
                    reason_codes=rule.reason_codes or policy.reason_codes,
                )
                if status is RuleEvaluationStatus.PASSED:
                    passed.append(evaluation)
                    self._publish(
                        request,
                        EventType.POLICY_VALIDATED,
                        policy_references=(policy.policy_id,),
                    )
                elif status is RuleEvaluationStatus.FAILED:
                    failed.append(evaluation)
                    violations.append(self._violation(request, policy, rule))
                elif status is RuleEvaluationStatus.INDETERMINATE:
                    indeterminate.append(evaluation)
                    if policy.enforcement_level in {
                        EnforcementLevel.REQUIRED,
                        EnforcementLevel.BLOCKING,
                        EnforcementLevel.CRITICAL,
                    }:
                        violations.append(self._violation(request, policy, rule))
        return {
            "passed": tuple(passed),
            "failed": tuple(failed),
            "indeterminate": tuple(indeterminate),
            "violations": tuple(violations),
        }

    def _evaluate_rule(
        self,
        rule: PolicyRule,
        context: GovernanceContext,
    ) -> RuleEvaluationStatus:
        operator = rule.operator
        if operator in {RuleOperator.ALL, RuleOperator.ANY}:
            results = tuple(self._evaluate_rule(item, context) for item in rule.rules)
            if not results:
                return RuleEvaluationStatus.INDETERMINATE
            if RuleEvaluationStatus.INDETERMINATE in results:
                return RuleEvaluationStatus.INDETERMINATE
            passed = all(item is RuleEvaluationStatus.PASSED for item in results)
            if operator is RuleOperator.ANY:
                passed = any(item is RuleEvaluationStatus.PASSED for item in results)
            return (
                RuleEvaluationStatus.PASSED if passed else RuleEvaluationStatus.FAILED
            )
        if operator is RuleOperator.NOT:
            if len(rule.rules) != 1:
                return RuleEvaluationStatus.INDETERMINATE
            result = self._evaluate_rule(rule.rules[0], context)
            if result is RuleEvaluationStatus.PASSED:
                return RuleEvaluationStatus.FAILED
            if result is RuleEvaluationStatus.FAILED:
                return RuleEvaluationStatus.PASSED
            return result
        if operator not in set(RuleOperator):
            raise OperatorNotAllowedError(f"operator is not allowed: {operator}")
        exists, left = self._resolve_field(rule.field, context)
        if operator is RuleOperator.EXISTS:
            return _status(exists)
        if operator is RuleOperator.NOT_EXISTS:
            return _status(not exists)
        if not exists:
            return RuleEvaluationStatus.INDETERMINATE
        right = rule.value
        if isinstance(left, StrEnumValue):
            left = left.value
        if isinstance(right, StrEnumValue):
            right = right.value
        try:
            if operator is RuleOperator.EQUALS:
                return _status(left == right)
            if operator is RuleOperator.NOT_EQUALS:
                return _status(left != right)
            if operator is RuleOperator.GREATER_THAN:
                return _status(left > right)
            if operator is RuleOperator.GREATER_THAN_OR_EQUAL:
                return _status(left >= right)
            if operator is RuleOperator.LESS_THAN:
                return _status(left < right)
            if operator is RuleOperator.LESS_THAN_OR_EQUAL:
                return _status(left <= right)
            if operator is RuleOperator.IN:
                return _status(left in right)
            if operator is RuleOperator.NOT_IN:
                return _status(left not in right)
            if operator is RuleOperator.CONTAINS:
                return _status(right in left)
            if operator is RuleOperator.NOT_CONTAINS:
                return _status(right not in left)
        except TypeError:
            return RuleEvaluationStatus.INDETERMINATE
        raise OperatorNotAllowedError(f"operator is not allowed: {operator}")

    def _resolve_field(
        self,
        field: str | None,
        context: GovernanceContext,
    ) -> tuple[bool, object]:
        if field is None:
            raise FieldNotAllowedError("field is required")
        allowed = {
            "risk_level": context.risk_level.value,
            "impact_level": context.impact_level.value,
            "requested_action": context.requested_action,
            "action_type": context.action_type.value,
            "execution_requested": context.execution_requested,
            "affected_domains": tuple(item.value for item in context.affected_domains),
            "confidence": context.confidence,
            "current_stage": context.current_stage,
            "reversibility": context.reversibility,
            "rollback_available": context.rollback_available,
            "resources": context.resources,
            "organization_id": str(context.organization_id),
            "session_id": str(context.session_id),
            "plan_id": str(context.plan_id),
        }
        if field.startswith("metadata."):
            key = field.removeprefix("metadata.")
            return key in context.metadata, context.metadata.get(key)
        if field not in allowed:
            raise FieldNotAllowedError(f"field is not allowed: {field}")
        return allowed[field] is not None, allowed[field]

    def _violation(
        self,
        request: GovernanceRequest,
        policy: OrganizationalPolicy,
        rule: PolicyRule,
    ) -> PolicyViolation:
        blocking = policy.enforcement_level in {
            EnforcementLevel.BLOCKING,
            EnforcementLevel.CRITICAL,
        }
        return PolicyViolation(
            violation_id=self._id_generator(),
            policy_id=policy.policy_id,
            policy_version=policy.version,
            rule_id=rule.rule_id,
            enforcement_level=policy.enforcement_level,
            severity=policy.enforcement_level.value,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            safe_message=f"Policy {policy.policy_id} rule {rule.rule_id} failed",
            blocking=blocking,
            remediation_required=policy.enforcement_level
            is not EnforcementLevel.ADVISORY,
            human_escalation_required=policy.enforcement_level
            in {EnforcementLevel.REQUIRED, EnforcementLevel.CRITICAL},
            detected_at=self._now(),
            reason_codes=rule.reason_codes or policy.reason_codes,
        )

    def _approval_level(
        self,
        request: GovernanceRequest,
        policies: tuple[OrganizationalPolicy, ...],
    ) -> ApprovalLevel:
        level = ApprovalLevel.LEVEL_1
        if request.risk_level is RiskLevel.MEDIUM or request.impact_level is (
            ImpactLevel.MODERATE
        ):
            level = max(level, ApprovalLevel.LEVEL_2)
        if (
            request.risk_level is RiskLevel.HIGH
            or request.impact_level is ImpactLevel.HIGH
        ):
            level = max(level, ApprovalLevel.LEVEL_3)
        if request.risk_level is RiskLevel.CRITICAL or request.impact_level is (
            ImpactLevel.CRITICAL
        ):
            level = max(level, ApprovalLevel.LEVEL_4)
        if request.cognitive_plan.objective_classification in {
            ObjectiveClassification.EXECUTION,
        } or request.cognitive_plan.strategy.strategy.value.lower().startswith(
            "executive"
        ):
            level = max(level, ApprovalLevel.LEVEL_5)
        if request.execution_requested and not request.rollback_available:
            level = max(level, ApprovalLevel.LEVEL_3)
        if len(request.affected_domains) >= 3:
            level = max(level, ApprovalLevel.LEVEL_3)
        for policy in policies:
            if policy.required_approval_level is not None:
                level = max(level, policy.required_approval_level)
        return level

    def _policy_requirements(
        self,
        request: GovernanceRequest,
        policies: tuple[OrganizationalPolicy, ...],
    ) -> tuple[ApprovalRequirement, ...]:
        requirements = []
        for policy in policies:
            if policy.required_approval_level is None:
                continue
            requirements.append(
                ApprovalRequirement(
                    approval_level=policy.required_approval_level,
                    required_roles=policy.required_roles,
                    minimum_approvals=policy.minimum_approvals,
                    distinct_approvers_required=True,
                    approval_required=True,
                    auto_approval_allowed=False,
                    score=int(policy.required_approval_level) * 10,
                    reason_codes=policy.reason_codes,
                )
            )
        return tuple(requirements)

    def _compliance_report(
        self,
        request: GovernanceRequest,
        policies: tuple[OrganizationalPolicy, ...],
        explainability: ExplainabilityReport,
        approval_level: ApprovalLevel,
        policy_results: dict[str, tuple[object, ...]],
    ) -> ComplianceReport:
        violations = policy_results["violations"]
        failed = policy_results["failed"]
        indeterminate = policy_results["indeterminate"]
        blocking = any(item.blocking for item in violations)
        review = any(item.human_escalation_required for item in violations)
        non_advisory_failed = any(
            item.enforcement_level is not EnforcementLevel.ADVISORY for item in failed
        )
        warnings = [
            item.safe_message
            for item in violations
            if item.enforcement_level is EnforcementLevel.ADVISORY
        ]
        if blocking or not explainability.valid:
            status = ComplianceStatus.NON_COMPLIANT
        elif indeterminate:
            status = ComplianceStatus.INDETERMINATE
        elif non_advisory_failed or review:
            status = ComplianceStatus.REVIEW_REQUIRED
        else:
            status = ComplianceStatus.COMPLIANT
        return ComplianceReport(
            report_id=self._id_generator(),
            governance_id=request.governance_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            status=status,
            evaluated_policies=tuple(
                f"{policy.policy_id}:{policy.version}" for policy in policies
            ),
            passed_rules=policy_results["passed"],
            failed_rules=failed,
            indeterminate_rules=indeterminate,
            violations=violations,
            explainability_report=explainability,
            risk_level=request.risk_level,
            approval_level=approval_level,
            human_review_required=status
            in {ComplianceStatus.REVIEW_REQUIRED, ComplianceStatus.INDETERMINATE},
            generated_at=self._now(),
            reason_codes=(status.value,),
            warnings=tuple(warnings),
        )

    def _authorization_decision(
        self,
        request: GovernanceRequest,
        compliance: ComplianceReport,
        approval_requirement: ApprovalRequirement,
    ) -> AuthorizationDecision:
        if compliance.status is ComplianceStatus.NON_COMPLIANT:
            decision = AuthorizationDecisionValue.DENIED
        elif compliance.status in {
            ComplianceStatus.REVIEW_REQUIRED,
            ComplianceStatus.INDETERMINATE,
        }:
            decision = AuthorizationDecisionValue.REVIEW_REQUIRED
        elif approval_requirement.approval_required:
            decision = AuthorizationDecisionValue.AWAITING_APPROVAL
        else:
            decision = AuthorizationDecisionValue.AUTHORIZED
        execution_authorized = (
            decision is AuthorizationDecisionValue.AUTHORIZED
            and request.execution_requested
            and not approval_requirement.approval_required
        )
        if not request.execution_requested:
            execution_authorized = False
        now = self._now()
        return AuthorizationDecision(
            authorization_id=self._id_generator(),
            governance_id=request.governance_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            action_scope=request.requested_action,
            decision=decision,
            risk_level=request.risk_level,
            compliance_status=compliance.status,
            approval_level=approval_requirement.approval_level,
            approval_required=approval_requirement.approval_required,
            execution_authorized=execution_authorized,
            valid_from=now,
            valid_until=now + self._config.authorization_ttl,
            policy_references=compliance.evaluated_policies,
            reason_codes=(
                *compliance.reason_codes,
                *approval_requirement.reason_codes,
            ),
            human_escalation_required=decision
            in {
                AuthorizationDecisionValue.AWAITING_APPROVAL,
                AuthorizationDecisionValue.REVIEW_REQUIRED,
                AuthorizationDecisionValue.DENIED,
            },
        )

    def _approval_request(
        self,
        request: GovernanceRequest,
        authorization: AuthorizationDecision,
        requirement: ApprovalRequirement,
    ) -> ApprovalRequest | None:
        if authorization.decision is not AuthorizationDecisionValue.AWAITING_APPROVAL:
            return None
        now = self._now()
        return ApprovalRequest(
            approval_request_id=self._id_generator(),
            governance_id=request.governance_id,
            authorization_id=authorization.authorization_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            correlation_id=request.correlation_id,
            action_scope=request.requested_action,
            approval_level=requirement.approval_level,
            required_roles=requirement.required_roles,
            minimum_approvals=max(requirement.minimum_approvals, 1),
            distinct_approvers_required=requirement.distinct_approvers_required,
            reason_codes=requirement.reason_codes,
            status=ApprovalRequestStatus.PENDING,
            requested_at=now,
            expires_at=now + self._config.approval_request_ttl,
            policy_references=authorization.policy_references,
        )

    def _result_status(
        self,
        authorization: AuthorizationDecision,
    ) -> GovernanceResultStatus:
        return {
            AuthorizationDecisionValue.AUTHORIZED: GovernanceResultStatus.AUTHORIZED,
            AuthorizationDecisionValue.DENIED: GovernanceResultStatus.DENIED,
            AuthorizationDecisionValue.REVIEW_REQUIRED: (
                GovernanceResultStatus.REVIEW_REQUIRED
            ),
            AuthorizationDecisionValue.AWAITING_APPROVAL: (
                GovernanceResultStatus.AWAITING_APPROVAL
            ),
            AuthorizationDecisionValue.NOT_APPLICABLE: (
                GovernanceResultStatus.AUTHORIZED
            ),
        }[authorization.decision]

    def _validate_decision_scope(
        self,
        approval_request: ApprovalRequest,
        decision: ApprovalDecision,
    ) -> None:
        if approval_request.approval_request_id != decision.approval_request_id:
            raise IncompatibleApprovalError("approval_request_id mismatch")
        if approval_request.organization_id != decision.organization_id:
            raise IncompatibleApprovalError("organization_id mismatch")
        if approval_request.session_id != decision.session_id:
            raise IncompatibleApprovalError("session_id mismatch")
        if approval_request.plan_id != decision.plan_id:
            raise IncompatibleApprovalError("plan_id mismatch")

    def _quorum_met(
        self,
        request: ApprovalRequest,
        approvals: tuple[ApprovalDecision, ...],
    ) -> bool:
        if request.distinct_approvers_required:
            if len({item.actor_id for item in approvals}) != len(approvals):
                return False
        roles = {item.actor_role for item in approvals}
        if request.approval_level is ApprovalLevel.LEVEL_4:
            if not {"manager", "executive"}.issubset(roles):
                return False
        return len(approvals) >= request.minimum_approvals

    def _audit(
        self,
        records: list[AuditRecord],
        request: GovernanceRequest,
        action: str,
        outcome: str,
        *,
        policy_references: tuple[str, ...] = (),
        approval_level: ApprovalLevel | None = None,
        risk_level: RiskLevel | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        self._audit_for_scope(
            records,
            governance_id=request.governance_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            correlation_id=request.correlation_id,
            action=action,
            outcome=outcome,
            policy_references=policy_references,
            approval_level=approval_level,
            risk_level=risk_level,
            reason_codes=reason_codes,
        )

    def _audit_for_scope(
        self,
        records: list[AuditRecord],
        *,
        governance_id: UUID,
        organization_id: UUID,
        session_id: UUID,
        plan_id: UUID,
        correlation_id: UUID,
        action: str,
        outcome: str,
        policy_references: tuple[str, ...] = (),
        decision: str | None = None,
        approval_level: ApprovalLevel | None = None,
        risk_level: RiskLevel | None = None,
        reason_codes: tuple[str, ...] = (),
        actor_id: UUID | None = None,
        actor_role: str | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
    ) -> None:
        records.append(
            AuditRecord(
                audit_id=self._id_generator(),
                sequence=len(records) + 1,
                governance_id=governance_id,
                organization_id=organization_id,
                session_id=session_id,
                plan_id=plan_id,
                correlation_id=correlation_id,
                timestamp=self._now(),
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                policy_references=policy_references,
                decision=decision,
                approval_level=approval_level,
                risk_level=risk_level,
                reason_codes=reason_codes,
                outcome=outcome,
                previous_state=previous_state,
                new_state=new_state,
            )
        )

    def _publish(
        self,
        request: GovernanceRequest,
        event_type: EventType,
        *,
        policy_references: tuple[str, ...] = (),
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        self._publish_scope(
            event_type,
            governance_id=request.governance_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            correlation_id=request.correlation_id,
            policy_references=policy_references,
            reason_codes=reason_codes,
        )

    def _publish_scope(
        self,
        event_type: EventType,
        *,
        governance_id: UUID,
        organization_id: UUID,
        session_id: UUID,
        plan_id: UUID,
        correlation_id: UUID,
        policy_references: tuple[str, ...] = (),
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="governance",
                session_id=session_id,
                payload={
                    "governance_id": str(governance_id),
                    "organization_id": str(organization_id),
                    "plan_id": str(plan_id),
                    "policy_references": ",".join(policy_references),
                    "reason_codes": ",".join(reason_codes),
                },
                metadata=EventMetadata(correlation_id=correlation_id),
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


StrEnumValue = (
    RiskLevel
    | ImpactLevel
    | GovernanceActionType
    | EnforcementLevel
    | ComplianceStatus
    | ApprovalRequestStatus
)


def _status(value: bool) -> RuleEvaluationStatus:
    return RuleEvaluationStatus.PASSED if value else RuleEvaluationStatus.FAILED


def _blank(value: object, *, allow_empty: bool = False) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, tuple | list | dict | set):
        return False if allow_empty else len(value) == 0
    return False

"""Governance provider ports and deterministic in-memory implementations."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from uuid import UUID

from ecos.governance.models import (
    ApprovalLevel,
    ApprovalRequirement,
    GovernanceActionType,
    GovernanceConfig,
    GovernanceRequest,
    OrganizationalPolicy,
    PolicyDomain,
    PolicyRule,
    PolicyStatus,
    RuleOperator,
    ValidatedIdentity,
)
from ecos.planner import RiskLevel


class PolicyProvider(ABC):
    """Port used by GovernanceEngine to load organizational policies."""

    @abstractmethod
    def list_policies(
        self,
        *,
        organization_id: UUID,
        policy_ids: tuple[str, ...] = (),
    ) -> tuple[OrganizationalPolicy, ...]:
        """Return policies for one organization."""
        raise NotImplementedError


class ApprovalPolicyProvider(ABC):
    """Port used to resolve default approval policy by level."""

    @abstractmethod
    def requirement_for(
        self,
        *,
        level: ApprovalLevel,
        request: GovernanceRequest,
        policy_requirements: tuple[ApprovalRequirement, ...] = (),
    ) -> ApprovalRequirement:
        """Return the applicable approval requirement."""
        raise NotImplementedError


class IdentityPort(ABC):
    """Port that validates identity supplied by an external caller."""

    @abstractmethod
    def validate_identity(
        self,
        *,
        actor_id: UUID,
        organization_id: UUID,
    ) -> ValidatedIdentity | None:
        """Return validated identity data or None."""
        raise NotImplementedError


class InMemoryPolicyProvider(PolicyProvider):
    """Deterministic in-memory policy provider for tests and demos."""

    def __init__(self, policies: tuple[OrganizationalPolicy, ...] = ()) -> None:
        self._policies = tuple(policies)

    def list_policies(
        self,
        *,
        organization_id: UUID,
        policy_ids: tuple[str, ...] = (),
    ) -> tuple[OrganizationalPolicy, ...]:
        allowed = set(policy_ids)
        return tuple(
            policy
            for policy in self._policies
            if policy.organization_id == organization_id
            and (not allowed or policy.policy_id in allowed)
        )


class DefaultApprovalPolicyProvider(ApprovalPolicyProvider):
    """Default ECOS approval policy mapping."""

    def __init__(self, config: GovernanceConfig | None = None) -> None:
        self._config = config or GovernanceConfig()

    def requirement_for(
        self,
        *,
        level: ApprovalLevel,
        request: GovernanceRequest,
        policy_requirements: tuple[ApprovalRequirement, ...] = (),
    ) -> ApprovalRequirement:
        highest = max(
            (requirement.approval_level for requirement in policy_requirements),
            default=level,
        )
        level = max(level, highest)
        defaults = {
            ApprovalLevel.LEVEL_1: ((), 0, False, True),
            ApprovalLevel.LEVEL_2: (("manager",), 1, True, False),
            ApprovalLevel.LEVEL_3: (("executive",), 1, True, False),
            ApprovalLevel.LEVEL_4: (("manager", "executive"), 2, True, False),
            ApprovalLevel.LEVEL_5: (
                ("executive_board",),
                self._config.board_quorum,
                True,
                False,
            ),
        }
        roles, minimum, distinct, auto_allowed = defaults[level]
        for requirement in policy_requirements:
            if requirement.approval_level != level:
                continue
            roles = tuple(dict.fromkeys((*roles, *requirement.required_roles)))
            minimum = max(minimum, requirement.minimum_approvals)
            distinct = distinct or requirement.distinct_approvers_required
            auto_allowed = auto_allowed and requirement.auto_approval_allowed
        execution_requires_human = request.execution_requested
        approval_required = (
            execution_requires_human or level is not ApprovalLevel.LEVEL_1
        )
        if execution_requires_human and minimum == 0:
            minimum = 1
            roles = roles or ("manager",)
            distinct = True
            auto_allowed = False
        reason_codes = [f"approval_level_{int(level)}"]
        if execution_requires_human:
            reason_codes.append("execution_requires_human_approval")
        return ApprovalRequirement(
            approval_level=level,
            required_roles=roles,
            minimum_approvals=minimum,
            distinct_approvers_required=distinct,
            approval_required=approval_required,
            auto_approval_allowed=auto_allowed and not execution_requires_human,
            score=int(level) * 10,
            reason_codes=tuple(reason_codes),
        )


class StaticIdentityPort(IdentityPort):
    """Simple deterministic identity port for demos and tests."""

    def __init__(self, identities: tuple[ValidatedIdentity, ...] = ()) -> None:
        self._identities = {
            (identity.organization_id, identity.actor_id): identity
            for identity in identities
        }

    def validate_identity(
        self,
        *,
        actor_id: UUID,
        organization_id: UUID,
    ) -> ValidatedIdentity | None:
        return self._identities.get((organization_id, actor_id))


def demo_policy(organization_id: UUID) -> OrganizationalPolicy:
    """Create the deterministic safe runtime demo policy."""
    return OrganizationalPolicy(
        policy_id="runtime_governance_level_1",
        organization_id=organization_id,
        name="Runtime demo governance policy",
        domain=PolicyDomain.GENERAL,
        version="1.0.0",
        status=PolicyStatus.ACTIVE,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_until=datetime(2027, 1, 1, tzinfo=UTC),
        applicable_actions=(GovernanceActionType.CONTINUATION,),
        rules=(
            PolicyRule(
                rule_id="no_execution_requested",
                operator=RuleOperator.EQUALS,
                field="execution_requested",
                value=False,
                reason_codes=("continuation_only",),
            ),
            PolicyRule(
                rule_id="risk_not_critical",
                operator=RuleOperator.NOT_EQUALS,
                field="risk_level",
                value=RiskLevel.CRITICAL.value,
                reason_codes=("risk_acceptable_for_demo",),
            ),
        ),
        required_approval_level=ApprovalLevel.LEVEL_1,
        reason_codes=("runtime_demo_policy",),
        metadata={"runtime": True},
    )

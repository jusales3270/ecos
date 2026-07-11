"""Governance Engine exceptions."""


class GovernanceError(Exception):
    """Base class for explicit governance failures."""


class InvalidGovernanceRequestError(GovernanceError):
    """Raised when a governance request is incomplete or inconsistent."""


class OrganizationMissingError(InvalidGovernanceRequestError):
    """Raised when organization scope is missing."""


class PolicyNotFoundError(GovernanceError):
    """Raised when an applicable policy cannot be found."""


class AmbiguousPolicyError(GovernanceError):
    """Raised when multiple active versions are applicable."""


class ExpiredPolicyError(GovernanceError):
    """Raised when a policy version is expired."""


class InvalidPolicyVersionError(GovernanceError):
    """Raised when a policy version is invalid."""


class InvalidPolicyRuleError(GovernanceError):
    """Raised when a policy rule is malformed."""


class OperatorNotAllowedError(GovernanceError):
    """Raised when a rule uses an operator outside the allowlist."""


class FieldNotAllowedError(GovernanceError):
    """Raised when a rule reads a field outside the allowlist."""


class IndeterminateComplianceError(GovernanceError):
    """Raised when required compliance is indeterminate."""


class InvalidExplainabilityError(GovernanceError):
    """Raised when explainability fields are missing or invalid."""


class IncompatibleAuthorizationError(GovernanceError):
    """Raised when an authorization does not match the requested scope."""


class AuthorizationExpiredError(GovernanceError):
    """Raised when an authorization has expired."""


class ApprovalMissingError(GovernanceError):
    """Raised when explicit human approval is required but missing."""


class IncompatibleApprovalError(GovernanceError):
    """Raised when an approval decision does not match its request."""


class InvalidIdentityError(GovernanceError):
    """Raised when a provided identity is unknown, inactive, or unverified."""


class UnauthorizedRoleError(GovernanceError):
    """Raised when an actor role is not allowed to approve."""


class QuorumInsufficientError(GovernanceError):
    """Raised when approval quorum has not been reached."""


class ConflictingDecisionReplayError(GovernanceError):
    """Raised when a replayed decision conflicts with the original decision."""


class ApprovalRequestExpiredError(GovernanceError):
    """Raised when an approval request is expired."""


class ApprovalAfterRejectionError(GovernanceError):
    """Raised when an approval is attempted after final rejection."""


class InvalidRevocationError(GovernanceError):
    """Raised when a revocation cannot be applied."""


class BlockingViolationError(GovernanceError):
    """Raised when a blocking policy violation is detected."""


class ExecutionNotAuthorizedError(GovernanceError):
    """Raised when execution is requested without valid authorization."""


class InvalidGovernanceStateError(GovernanceError):
    """Raised when governance state is inconsistent."""


class InconsistentGovernanceResultError(GovernanceError):
    """Raised when a governance result violates invariants."""


class GovernanceDependencyUnavailableError(GovernanceError):
    """Raised when an injected governance dependency is unavailable."""

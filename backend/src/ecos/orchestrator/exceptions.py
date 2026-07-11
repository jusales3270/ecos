"""Typed exceptions for the real ECOS Orchestrator."""


class OrchestratorError(RuntimeError):
    """Base exception for orchestration failures."""


class PlanMissingError(OrchestratorError):
    """Raised when an orchestration input does not include a plan."""


class IncompatiblePlanError(OrchestratorError):
    """Raised when plan identity does not match the session."""


class IncompatibleSessionError(OrchestratorError):
    """Raised when session identity does not match the plan."""


class EngineNotRegisteredError(OrchestratorError):
    """Raised when a plan references an engine without an executor."""


class ExecutorIncompatibleError(OrchestratorError):
    """Raised when an executor returns a result for another engine or stage."""


class DuplicateExecutorError(OrchestratorError):
    """Raised when the executor registry contains duplicate engine names."""


class InvalidDependencyError(OrchestratorError):
    """Raised when a stage dependency is invalid."""


class CycleDetectedError(OrchestratorError):
    """Raised when the plan dependency graph is cyclic."""


class InvalidTransitionError(OrchestratorError):
    """Raised when an invalid pipeline or stage transition is requested."""


class InvalidConditionError(OrchestratorError):
    """Raised when a structured condition is malformed."""


class OperatorNotAllowedError(InvalidConditionError):
    """Raised when a condition uses an unknown operator."""


class InvalidTimeoutError(OrchestratorError):
    """Raised when a stage timeout is invalid."""


class InvalidRetryError(OrchestratorError):
    """Raised when retry policy values are invalid."""


class RequiredStageFailedError(OrchestratorError):
    """Raised when a required stage fails definitively."""


class InvalidResultError(OrchestratorError):
    """Raised when an executor returns an invalid result."""


class RequiredOutputMissingError(OrchestratorError):
    """Raised when a required stage completed without output."""


class GovernanceMissingError(OrchestratorError):
    """Raised when execution is requested without satisfied governance."""


class ApprovalMissingError(OrchestratorError):
    """Raised when execution is requested without explicit human approval."""


class IncompatibleApprovalError(OrchestratorError):
    """Raised when approval belongs to another plan, session or organization."""


class AuthorizationExpiredError(OrchestratorError):
    """Raised when supplied approval is expired."""


class ExecutionBlockedError(OrchestratorError):
    """Raised when execution must remain blocked."""


class InvalidResumeStateError(OrchestratorError):
    """Raised when a resumable state cannot be safely resumed."""


class PipelineInconsistentError(OrchestratorError):
    """Raised when final pipeline validation fails."""


class OrchestrationCancelledError(OrchestratorError):
    """Raised when orchestration is cancelled."""

"""Execution Layer exception types."""


class ExecutionError(Exception):
    """Base class for Execution Layer errors."""


class InvalidExecutionRequestError(ExecutionError):
    """Raised when an execution request is incomplete or incompatible."""


class InvalidExecutionPlanError(ExecutionError):
    """Raised when an execution plan is invalid."""


class AuthorizationRejectedError(ExecutionError):
    """Raised when execution authorization is absent or rejected."""


class ApprovalEvidenceMissingError(ExecutionError):
    """Raised when required human approval evidence is absent."""


class ConnectorRegistryError(ExecutionError):
    """Raised for connector registry errors."""


class ConnectorDuplicateError(ConnectorRegistryError):
    """Raised when a connector is registered twice."""


class ConnectorNotRegisteredError(ConnectorRegistryError):
    """Raised when a connector cannot be found."""


class ConnectorUnavailableError(ExecutionError):
    """Raised when a connector is unavailable."""


class ConnectorIncompatibleError(ExecutionError):
    """Raised when a connector cannot execute the requested step."""


class IdempotencyConflictError(ExecutionError):
    """Raised when an idempotency key is reused for a different payload."""


class DuplicateExecutionError(ExecutionError):
    """Raised when an in-flight idempotent execution is duplicated."""


class InvalidConditionError(ExecutionError):
    """Raised when a structured condition is invalid."""


class OperatorNotAllowedError(InvalidConditionError):
    """Raised when a condition operator is not allowlisted."""


class ExecutionTimeoutError(ExecutionError):
    """Raised when a step times out."""


class ValidationRuleFailedError(ExecutionError):
    """Raised when a post-execution validation rule is false."""


class HumanTaskError(ExecutionError):
    """Raised when a human task request or resume state is invalid."""


class RollbackUnavailableError(ExecutionError):
    """Raised when rollback is required but not explicitly available."""


class RollbackUnauthorizedError(ExecutionError):
    """Raised when rollback is requested without authorization."""

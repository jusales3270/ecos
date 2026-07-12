"""Operational workflow errors."""

from ecos.core.exceptions import EcosError


class OperationalConflictError(EcosError):
    """Raised when an operational command conflicts with persisted state."""

    def __init__(self, message: str, code: str = "OPERATIONAL_CONFLICT") -> None:
        super().__init__(message=message, code=code, details={})


class IdempotencyConflictError(OperationalConflictError):
    """Raised when an idempotency key is reused with a different payload."""

    def __init__(self) -> None:
        super().__init__(
            "idempotency key was already used with a different payload",
            "IDEMPOTENCY_CONFLICT",
        )

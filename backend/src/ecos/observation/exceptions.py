"""Safe exceptions for the ECOS Observation Engine."""


class ObservationError(Exception):
    """Base exception for observation failures."""


class ObservationValidationError(ObservationError):
    """Raised when an observation request violates the contract."""


class ObservationIdempotencyConflictError(ObservationError):
    """Raised when the same idempotency key receives different inputs."""

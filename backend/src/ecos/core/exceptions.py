"""Standardized ECOS exception types."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EcosError(Exception):
    """Base standardized ECOS exception."""

    message: str
    code: str = "ECOS_ERROR"
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Return the human-readable error message."""
        return self.message


class ConfigurationError(EcosError):
    """Raised when application configuration is invalid."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize a configuration error."""
        super().__init__(
            message=message,
            code="CONFIGURATION_ERROR",
            details=details or {},
        )


class DependencyNotFoundError(EcosError):
    """Raised when a dependency is not registered in the container."""

    def __init__(self, dependency: str) -> None:
        """Initialize a dependency lookup error."""
        super().__init__(
            message=f"dependency not registered: {dependency}",
            code="DEPENDENCY_NOT_FOUND",
            details={"dependency": dependency},
        )


class RuntimeExecutionError(EcosError):
    """Raised when runtime execution fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize a runtime execution error."""
        super().__init__(
            message=message,
            code="RUNTIME_EXECUTION_ERROR",
            details=details or {},
        )


class AIProviderError(EcosError):
    """Base error raised by an external AI provider adapter."""

    def __init__(self, message: str, code: str = "AI_PROVIDER_ERROR") -> None:
        """Initialize without provider SDK objects or sensitive details."""
        super().__init__(message=message, code=code)


class AIProviderAuthenticationError(AIProviderError):
    """Raised when an AI provider rejects configured credentials."""

    def __init__(self) -> None:
        """Initialize a provider-neutral authentication error."""
        super().__init__(
            "AI provider authentication failed.", "AI_PROVIDER_AUTHENTICATION"
        )


class AIProviderRateLimitError(AIProviderError):
    """Raised when an AI provider rate limit is reached."""

    def __init__(self) -> None:
        """Initialize a provider-neutral rate-limit error."""
        super().__init__("AI provider rate limit exceeded.", "AI_PROVIDER_RATE_LIMIT")


class AIProviderTimeoutError(AIProviderError):
    """Raised when an AI provider request times out."""

    def __init__(self) -> None:
        """Initialize a provider-neutral timeout error."""
        super().__init__("AI provider request timed out.", "AI_PROVIDER_TIMEOUT")


class AIProviderUnsupportedOperationError(AIProviderError):
    """Raised when a provider operation is intentionally unsupported."""

    def __init__(self, operation: str) -> None:
        """Initialize an unsupported-operation error."""
        super().__init__(
            f"AI provider operation is not supported: {operation}.",
            "AI_PROVIDER_UNSUPPORTED_OPERATION",
        )

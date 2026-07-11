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


class ReasoningResponseError(EcosError):
    """Base error for provider-backed cognitive response failures."""

    def __init__(self, message: str, code: str) -> None:
        """Initialize without including raw provider content."""
        super().__init__(message=message, code=code)


class EmptyReasoningResponseError(ReasoningResponseError):
    """Raised when the provider returns no cognitive response."""

    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an empty reasoning response.",
            "EMPTY_REASONING_RESPONSE",
        )


class InvalidReasoningResponseError(ReasoningResponseError):
    """Raised when cognitive response JSON cannot be parsed."""

    def __init__(self) -> None:
        super().__init__(
            "AI provider returned invalid reasoning JSON.", "INVALID_REASONING_RESPONSE"
        )


class IncompatibleReasoningSchemaError(ReasoningResponseError):
    """Raised when cognitive response data violates the internal schema."""

    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an incompatible reasoning schema.",
            "INCOMPATIBLE_REASONING_SCHEMA",
        )


class ReasoningProviderError(ReasoningResponseError):
    """Raised when the injected AI provider fails during reasoning."""

    def __init__(self) -> None:
        super().__init__(
            "AI provider failed during reasoning.", "REASONING_PROVIDER_ERROR"
        )


class DebateResponseError(EcosError):
    """Base error for provider-backed debate response failures."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message=message, code=code)


class EmptyDebateResponseError(DebateResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an empty debate response.", "EMPTY_DEBATE_RESPONSE"
        )


class InvalidDebateResponseError(DebateResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned invalid debate JSON.", "INVALID_DEBATE_RESPONSE"
        )


class IncompatibleDebateSchemaError(DebateResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an incompatible debate schema.",
            "INCOMPATIBLE_DEBATE_SCHEMA",
        )


class InvalidDebateConsensusError(DebateResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid debate consensus.",
            "INVALID_DEBATE_CONSENSUS",
        )


class InvalidDebateConfidenceError(DebateResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid debate confidence.",
            "INVALID_DEBATE_CONFIDENCE",
        )


class InvalidDebateSpecialistReferenceError(DebateResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider referenced an unknown debate specialist.",
            "INVALID_DEBATE_SPECIALIST_REFERENCE",
        )


class DebateProviderError(DebateResponseError):
    def __init__(self) -> None:
        super().__init__("AI provider failed during debate.", "DEBATE_PROVIDER_ERROR")

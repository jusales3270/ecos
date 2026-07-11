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


class ContextEngineError(EcosError):
    """Base error raised by the deterministic Context Engine."""

    def __init__(
        self,
        message: str,
        code: str = "CONTEXT_ENGINE_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details or {})


class MissingOrganizationError(ContextEngineError):
    """Raised when a context request has no usable organization scope."""

    def __init__(self) -> None:
        super().__init__(
            "organization_id is required to build context.",
            "CONTEXT_MISSING_ORGANIZATION",
        )


class InvalidObjectiveError(ContextEngineError):
    """Raised when a context request objective is unusable."""

    def __init__(self) -> None:
        super().__init__(
            "objective is required to build context.",
            "CONTEXT_INVALID_OBJECTIVE",
        )


class MemoryRetrievalError(ContextEngineError):
    """Raised when memory retrieval fails."""

    def __init__(self) -> None:
        super().__init__(
            "context memory retrieval failed.",
            "CONTEXT_MEMORY_RETRIEVAL_FAILED",
        )


class CrossOrganizationMemoryError(ContextEngineError):
    """Raised when a repository returns memory from another organization."""

    def __init__(self) -> None:
        super().__init__(
            "repository returned memory outside the requested organization.",
            "CONTEXT_CROSS_ORGANIZATION_MEMORY",
        )


class ImpossibleContextError(ContextEngineError):
    """Raised when context cannot be constructed at all."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            "context cannot be constructed.",
            "CONTEXT_IMPOSSIBLE",
            {"reason": reason},
        )


class InvalidContextVersionError(ContextEngineError):
    """Raised when context versioning input is invalid."""

    def __init__(self) -> None:
        super().__init__("context version is invalid.", "CONTEXT_INVALID_VERSION")


class IncompatibleContextResultError(ContextEngineError):
    """Raised when a provider returns an incompatible context object."""

    def __init__(self) -> None:
        super().__init__(
            "context provider returned an incompatible result.",
            "CONTEXT_INCOMPATIBLE_RESULT",
        )


class ContextDependencyUnavailableError(ContextEngineError):
    """Raised when an injected context dependency is unavailable."""

    def __init__(self, dependency: str) -> None:
        super().__init__(
            "context dependency is unavailable.",
            "CONTEXT_DEPENDENCY_UNAVAILABLE",
            {"dependency": dependency},
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


class WarResponseError(EcosError):
    """Base error for provider-backed simulation response failures."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message=message, code=code)


class EmptyWarResponseError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an empty simulation response.", "EMPTY_WAR_RESPONSE"
        )


class InvalidWarResponseError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned invalid simulation JSON.", "INVALID_WAR_RESPONSE"
        )


class IncompatibleWarSchemaError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an incompatible simulation schema.",
            "INCOMPATIBLE_WAR_SCHEMA",
        )


class MissingWarScenarioError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider omitted a required simulation scenario.",
            "MISSING_WAR_SCENARIO",
        )


class InvalidWarScenarioTypeError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid simulation scenario type.",
            "INVALID_WAR_SCENARIO_TYPE",
        )


class InvalidWarProbabilityError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid scenario probability.",
            "INVALID_WAR_PROBABILITY",
        )


class InvalidWarConfidenceError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned invalid simulation confidence.",
            "INVALID_WAR_CONFIDENCE",
        )


class InvalidResilienceScoreError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid resilience score.",
            "INVALID_RESILIENCE_SCORE",
        )


class InvalidWarRiskError(WarResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid simulation risk.", "INVALID_WAR_RISK"
        )


class WarProviderError(WarResponseError):
    def __init__(self) -> None:
        super().__init__("AI provider failed during simulation.", "WAR_PROVIDER_ERROR")


class DecisionResponseError(EcosError):
    """Base error for provider-backed decision support response failures."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message=message, code=code)


class EmptyDecisionResponseError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an empty decision support response.",
            "EMPTY_DECISION_RESPONSE",
        )


class InvalidDecisionResponseError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned invalid decision support JSON.",
            "INVALID_DECISION_RESPONSE",
        )


class IncompatibleDecisionSchemaError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an incompatible decision support schema.",
            "INCOMPATIBLE_DECISION_SCHEMA",
        )


class InvalidDecisionConfidenceError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid decision confidence.",
            "INVALID_DECISION_CONFIDENCE",
        )


class InvalidStrategicAlignmentError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid strategic alignment.",
            "INVALID_STRATEGIC_ALIGNMENT",
        )


class InvalidDecisionClassificationError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid recommendation classification.",
            "INVALID_DECISION_CLASSIFICATION",
        )


class InvalidDecisionAlternativeError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid decision alternative.",
            "INVALID_DECISION_ALTERNATIVE",
        )


class InvalidDecisionRiskError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned an invalid decision risk.",
            "INVALID_DECISION_RISK",
        )


class MissingDecisionEvidenceError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider returned a recommendation without supporting evidence.",
            "MISSING_DECISION_EVIDENCE",
        )


class UnauthorizedDecisionApprovalError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider indicated a decision was approved.",
            "UNAUTHORIZED_DECISION_APPROVAL",
        )


class UnauthorizedExecutionApprovalError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider indicated execution was authorized.",
            "UNAUTHORIZED_EXECUTION_APPROVAL",
        )


class DecisionProviderError(DecisionResponseError):
    def __init__(self) -> None:
        super().__init__(
            "AI provider failed during decision support.",
            "DECISION_PROVIDER_ERROR",
        )

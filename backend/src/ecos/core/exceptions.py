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

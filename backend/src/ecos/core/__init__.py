"""Core infrastructure primitives for ECOS."""

from ecos.core.exceptions import (
    ConfigurationError,
    DependencyNotFoundError,
    EcosError,
    RuntimeExecutionError,
)
from ecos.core.logging import configure_logging, get_correlation_id, set_correlation_id
from ecos.core.settings import Settings, settings


def __getattr__(name: str) -> object:
    """Load Container lazily to avoid package initialization cycles."""
    if name == "Container":
        from ecos.core.container import Container

        return Container
    raise AttributeError(name)


__all__ = [
    "ConfigurationError",
    "Container",
    "DependencyNotFoundError",
    "EcosError",
    "RuntimeExecutionError",
    "Settings",
    "configure_logging",
    "get_correlation_id",
    "set_correlation_id",
    "settings",
]

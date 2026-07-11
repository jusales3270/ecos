"""Provider interface for the ECOS Context Engine."""

from abc import ABC, abstractmethod

from ecos.context.models import ContextBuildRequest, ContextObject


class ContextProvider(ABC):
    """Abstract provider interface for context assembly operations."""

    @abstractmethod
    def build(self, request: ContextBuildRequest | None = None) -> ContextObject:
        """Build an initial context object."""
        raise NotImplementedError

    @abstractmethod
    def expand(self, context: ContextObject) -> ContextObject:
        """Expand an existing context object."""
        raise NotImplementedError

    @abstractmethod
    def compress(self, context: ContextObject) -> ContextObject:
        """Compress an existing context object."""
        raise NotImplementedError

    @abstractmethod
    def validate(self, context: ContextObject) -> bool:
        """Validate an existing context object."""
        raise NotImplementedError

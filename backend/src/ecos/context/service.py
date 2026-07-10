"""Service layer for the ECOS Context Engine architecture."""

from ecos.context.models import ContextObject
from ecos.context.provider import ContextProvider


class ContextService:
    """Coordinates context operations through a provider abstraction only."""

    def __init__(self, provider: ContextProvider) -> None:
        """Initialize the service with a context provider abstraction."""
        self._provider = provider

    def build(self) -> ContextObject:
        """Build context through the provider abstraction."""
        return self._provider.build()

    def expand(self, context: ContextObject) -> ContextObject:
        """Expand context through the provider abstraction."""
        return self._provider.expand(context)

    def compress(self, context: ContextObject) -> ContextObject:
        """Compress context through the provider abstraction."""
        return self._provider.compress(context)

    def validate(self, context: ContextObject) -> bool:
        """Validate context through the provider abstraction."""
        return self._provider.validate(context)

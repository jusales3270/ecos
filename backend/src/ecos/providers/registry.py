"""Registry for ECOS AI providers."""

from ecos.providers.models import ProviderType
from ecos.providers.provider import AIProvider


class ProviderRegistry:
    """In-memory registry for AI provider abstractions."""

    def __init__(self) -> None:
        """Initialize an empty provider registry."""
        self._providers: dict[ProviderType, AIProvider] = {}
        self._default_provider: ProviderType | None = None

    def register(
        self,
        provider_type: ProviderType,
        provider: AIProvider,
        *,
        default: bool = False,
    ) -> AIProvider:
        """Register an AI provider abstraction."""
        self._providers[provider_type] = provider
        if default or self._default_provider is None:
            self._default_provider = provider_type
        return provider

    def unregister(self, provider_type: ProviderType) -> None:
        """Remove an AI provider abstraction from the registry."""
        self._providers.pop(provider_type, None)
        if self._default_provider == provider_type:
            self._default_provider = next(iter(self._providers), None)

    def get(self, provider_type: ProviderType) -> AIProvider | None:
        """Get an AI provider abstraction by provider type."""
        return self._providers.get(provider_type)

    def list(self) -> list[ProviderType]:
        """List registered provider types."""
        return list(self._providers.keys())

    def default_provider(self) -> AIProvider | None:
        """Return the default AI provider abstraction when one is registered."""
        if self._default_provider is None:
            return None
        return self._providers.get(self._default_provider)

"""Service layer for the ECOS AI Provider abstraction."""

from collections.abc import Iterator

from ecos.providers.models import AIRequest, AIResponse, ProviderHealth, ProviderType
from ecos.providers.provider import AIProvider
from ecos.providers.registry import ProviderRegistry


class AIService:
    """Coordinates AI operations through provider abstractions only."""

    def __init__(self, registry: ProviderRegistry) -> None:
        """Initialize the service with a provider registry abstraction."""
        self._registry = registry

    def register(
        self,
        provider_type: ProviderType,
        provider: AIProvider,
        *,
        default: bool = False,
    ) -> AIProvider:
        """Register a provider through the registry abstraction."""
        return self._registry.register(provider_type, provider, default=default)

    def unregister(self, provider_type: ProviderType) -> None:
        """Unregister a provider through the registry abstraction."""
        self._registry.unregister(provider_type)

    def get(self, provider_type: ProviderType) -> AIProvider | None:
        """Get a provider through the registry abstraction."""
        return self._registry.get(provider_type)

    def list(self) -> list[ProviderType]:
        """List providers through the registry abstraction."""
        return self._registry.list()

    def default_provider(self) -> AIProvider | None:
        """Return the default provider through the registry abstraction."""
        return self._registry.default_provider()

    def health(self, provider_type: ProviderType) -> ProviderHealth:
        """Return provider health through the selected provider abstraction."""
        return self._require_provider(provider_type).health()

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate through the selected provider abstraction."""
        return self._require_provider(request.provider).generate(request)

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Stream through the selected provider abstraction."""
        return self._require_provider(request.provider).stream(request)

    def embeddings(self, provider_type: ProviderType, input_text: str) -> list[float]:
        """Generate embeddings through the selected provider abstraction."""
        return self._require_provider(provider_type).embeddings(input_text)

    def list_models(self, provider_type: ProviderType) -> list[str]:
        """List models through the selected provider abstraction."""
        return self._require_provider(provider_type).list_models()

    def _require_provider(self, provider_type: ProviderType) -> AIProvider:
        """Return a registered provider or raise a lookup error."""
        provider = self._registry.get(provider_type)
        if provider is None:
            msg = f"provider not registered: {provider_type}"
            raise LookupError(msg)
        return provider

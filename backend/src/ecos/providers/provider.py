"""AI provider interface for ECOS."""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ecos.providers.models import AIRequest, AIResponse, ProviderHealth


class AIProvider(ABC):
    """Abstract AI provider interface for complete provider decoupling."""

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Return the provider health report."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a response for a provider-neutral request."""
        raise NotImplementedError

    @abstractmethod
    def stream(self, request: AIRequest) -> Iterator[str]:
        """Stream provider-neutral content chunks."""
        raise NotImplementedError

    @abstractmethod
    def embeddings(self, input_text: str) -> list[float]:
        """Generate embeddings for provider-neutral input text."""
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[str]:
        """List provider-neutral model identifiers."""
        raise NotImplementedError

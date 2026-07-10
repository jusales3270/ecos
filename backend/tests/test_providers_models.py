"""Unit tests for ECOS AI Provider abstraction models and services."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.providers import (
    AIProvider,
    AIRequest,
    AIResponse,
    AIService,
    ProviderCapabilities,
    ProviderHealth,
    ProviderRegistry,
    ProviderStatus,
    ProviderType,
    TokenUsage,
)


def make_request() -> AIRequest:
    """Create a valid AI request for tests."""
    return AIRequest(
        provider=ProviderType.CUSTOM,
        model="ecos-test-model",
        messages=[{"role": "user", "content": "Summarize the decision."}],
        temperature=0.5,
        max_tokens=256,
        metadata={"session": "unit-test"},
    )


def make_response(request: AIRequest) -> AIResponse:
    """Create a valid AI response for tests."""
    return AIResponse(
        request_id=request.id,
        provider=request.provider,
        model=request.model,
        content="Generated response.",
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        latency_ms=42,
    )


def test_provider_type_values() -> None:
    """ProviderType exposes all supported provider categories."""
    assert {provider.value for provider in ProviderType} == {
        "OPENAI",
        "ANTHROPIC",
        "GOOGLE",
        "XAI",
        "DEEPSEEK",
        "OLLAMA",
        "CUSTOM",
    }


def test_provider_status_values() -> None:
    """ProviderStatus exposes all supported health statuses."""
    assert {status.value for status in ProviderStatus} == {
        "AVAILABLE",
        "UNAVAILABLE",
        "DEGRADED",
    }


def test_token_usage_validates_totals() -> None:
    """TokenUsage requires non-negative counts and a coherent total."""
    usage = TokenUsage(prompt_tokens=3, completion_tokens=7, total_tokens=10)

    assert usage.prompt_tokens == 3
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 10

    with pytest.raises(ValidationError):
        TokenUsage(prompt_tokens=-1, completion_tokens=0, total_tokens=0)

    with pytest.raises(ValidationError, match="total_tokens must equal"):
        TokenUsage(prompt_tokens=3, completion_tokens=7, total_tokens=11)


def test_provider_capabilities_validate_supported_models() -> None:
    """ProviderCapabilities validates blank and duplicate model identifiers."""
    capabilities = ProviderCapabilities(
        provider=ProviderType.CUSTOM,
        supports_generation=True,
        supports_streaming=True,
        supports_embeddings=True,
        supported_models=["model-a", "model-b"],
    )

    assert capabilities.provider is ProviderType.CUSTOM
    assert capabilities.supports_generation is True
    assert capabilities.supports_streaming is True
    assert capabilities.supports_embeddings is True
    assert capabilities.supported_models == ["model-a", "model-b"]

    with pytest.raises(ValidationError, match="model identifiers cannot be blank"):
        ProviderCapabilities(provider=ProviderType.CUSTOM, supported_models=[" "])

    with pytest.raises(ValidationError, match="model identifiers must be unique"):
        ProviderCapabilities(
            provider=ProviderType.CUSTOM,
            supported_models=["model-a", "model-a"],
        )


def test_provider_health_validates_status_message_latency_and_created_at() -> None:
    """ProviderHealth validates health metadata and UTC timestamps."""
    health = ProviderHealth(
        provider=ProviderType.CUSTOM,
        status=ProviderStatus.AVAILABLE,
        message="Provider is available.",
        latency_ms=12,
    )

    assert isinstance(health.id, UUID)
    assert health.provider is ProviderType.CUSTOM
    assert health.status is ProviderStatus.AVAILABLE
    assert health.message == "Provider is available."
    assert health.latency_ms == 12
    assert health.created_at.tzinfo is UTC

    with pytest.raises(ValidationError, match="health message cannot be blank"):
        ProviderHealth(
            provider=ProviderType.CUSTOM,
            status=ProviderStatus.DEGRADED,
            message=" ",
        )

    with pytest.raises(ValidationError):
        ProviderHealth(
            provider=ProviderType.CUSTOM,
            status=ProviderStatus.AVAILABLE,
            latency_ms=-1,
        )

    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        ProviderHealth(
            provider=ProviderType.CUSTOM,
            status=ProviderStatus.AVAILABLE,
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )

    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        ProviderHealth(
            provider=ProviderType.CUSTOM,
            status=ProviderStatus.AVAILABLE,
            created_at=datetime(
                2026,
                1,
                1,
                12,
                0,
                0,
                tzinfo=timezone(timedelta(hours=-3)),
            ),
        )


def test_ai_request_contains_required_fields_and_validations() -> None:
    """AIRequest contains required provider-neutral request fields."""
    request = make_request()

    assert isinstance(request.id, UUID)
    assert request.provider is ProviderType.CUSTOM
    assert request.model == "ecos-test-model"
    assert request.messages[0]["role"] == "user"
    assert request.temperature == 0.5
    assert request.max_tokens == 256
    assert request.metadata == {"session": "unit-test"}
    assert request.created_at.tzinfo is UTC

    with pytest.raises(ValidationError):
        AIRequest(
            provider=ProviderType.CUSTOM,
            model=" ",
            messages=[{"role": "user", "content": "x"}],
        )

    with pytest.raises(ValidationError, match="messages cannot be empty"):
        AIRequest(provider=ProviderType.CUSTOM, model="model", messages=[])

    with pytest.raises(ValidationError, match="messages cannot contain empty items"):
        AIRequest(provider=ProviderType.CUSTOM, model="model", messages=[{}])

    with pytest.raises(ValidationError, match="message keys cannot be blank"):
        AIRequest(
            provider=ProviderType.CUSTOM,
            model="model",
            messages=[{" ": "content"}],
        )

    with pytest.raises(ValidationError, match="message values cannot be blank"):
        AIRequest(
            provider=ProviderType.CUSTOM,
            model="model",
            messages=[{"role": " "}],
        )

    with pytest.raises(ValidationError):
        AIRequest(
            provider=ProviderType.CUSTOM,
            model="model",
            messages=[{"role": "user", "content": "x"}],
            temperature=2.1,
        )

    with pytest.raises(ValidationError):
        AIRequest(
            provider=ProviderType.CUSTOM,
            model="model",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=0,
        )

    with pytest.raises(ValidationError, match="metadata keys cannot be blank"):
        AIRequest(
            provider=ProviderType.CUSTOM,
            model="model",
            messages=[{"role": "user", "content": "x"}],
            metadata={" ": "invalid"},
        )


def test_ai_response_contains_required_fields_and_validations() -> None:
    """AIResponse contains required provider-neutral response fields."""
    request = make_request()
    response = make_response(request)

    assert isinstance(response.id, UUID)
    assert response.request_id == request.id
    assert response.provider is ProviderType.CUSTOM
    assert response.model == "ecos-test-model"
    assert response.content == "Generated response."
    assert response.finish_reason == "stop"
    assert response.usage.total_tokens == 15
    assert response.latency_ms == 42
    assert response.created_at.tzinfo is UTC

    with pytest.raises(ValidationError):
        AIResponse(
            request_id=request.id,
            provider=ProviderType.CUSTOM,
            model=" ",
            content="Generated response.",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=1,
        )

    with pytest.raises(ValidationError):
        AIResponse(
            request_id=request.id,
            provider=ProviderType.CUSTOM,
            model="model",
            content=" ",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=1,
        )

    with pytest.raises(ValidationError):
        AIResponse(
            request_id=request.id,
            provider=ProviderType.CUSTOM,
            model="model",
            content="Generated response.",
            finish_reason=" ",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=1,
        )

    with pytest.raises(ValidationError):
        AIResponse(
            request_id=request.id,
            provider=ProviderType.CUSTOM,
            model="model",
            content="Generated response.",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=-1,
        )


class NotImplementedAIProvider(AIProvider):
    """Concrete test provider that exercises abstract NotImplementedError paths."""

    def health(self) -> ProviderHealth:
        """Return health through the abstract interface."""
        return super().health()

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate through the abstract interface."""
        return super().generate(request)

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Stream through the abstract interface."""
        return super().stream(request)

    def embeddings(self, input_text: str) -> list[float]:
        """Generate embeddings through the abstract interface."""
        return super().embeddings(input_text)

    def list_models(self) -> list[str]:
        """List models through the abstract interface."""
        return super().list_models()


def test_ai_provider_interface_methods_raise_not_implemented() -> None:
    """AIProvider abstract operations intentionally have no implementation."""
    provider = NotImplementedAIProvider()
    request = make_request()

    with pytest.raises(NotImplementedError):
        provider.health()

    with pytest.raises(NotImplementedError):
        provider.generate(request)

    with pytest.raises(NotImplementedError):
        next(provider.stream(request))

    with pytest.raises(NotImplementedError):
        provider.embeddings("input")

    with pytest.raises(NotImplementedError):
        provider.list_models()


class FakeAIProvider(AIProvider):
    """Test double used to verify registry and service delegation only."""

    def __init__(self) -> None:
        """Initialize the provider call history."""
        self.health_calls = 0
        self.generated: list[AIRequest] = []
        self.streamed: list[AIRequest] = []
        self.embedding_inputs: list[str] = []
        self.model_calls = 0

    def health(self) -> ProviderHealth:
        """Record health calls."""
        self.health_calls += 1
        return ProviderHealth(
            provider=ProviderType.CUSTOM,
            status=ProviderStatus.AVAILABLE,
        )

    def generate(self, request: AIRequest) -> AIResponse:
        """Record generation calls."""
        self.generated.append(request)
        return make_response(request)

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Record streaming calls."""
        self.streamed.append(request)
        yield "chunk-a"
        yield "chunk-b"

    def embeddings(self, input_text: str) -> list[float]:
        """Record embeddings calls."""
        self.embedding_inputs.append(input_text)
        return [0.1, 0.2, 0.3]

    def list_models(self) -> list[str]:
        """Record model listing calls."""
        self.model_calls += 1
        return ["ecos-test-model"]


def test_provider_registry_registers_gets_lists_and_unregisters_providers() -> None:
    """ProviderRegistry manages provider abstractions without concrete SDKs."""
    registry = ProviderRegistry()
    custom_provider = FakeAIProvider()
    ollama_provider = FakeAIProvider()

    assert registry.default_provider() is None

    registered = registry.register(ProviderType.CUSTOM, custom_provider)
    registry.register(ProviderType.OLLAMA, ollama_provider, default=True)

    assert registered is custom_provider
    assert registry.get(ProviderType.CUSTOM) is custom_provider
    assert registry.get(ProviderType.OPENAI) is None
    assert registry.list() == [ProviderType.CUSTOM, ProviderType.OLLAMA]
    assert registry.default_provider() is ollama_provider

    registry.unregister(ProviderType.OLLAMA)

    assert registry.get(ProviderType.OLLAMA) is None
    assert registry.default_provider() is custom_provider

    registry.unregister(ProviderType.CUSTOM)

    assert registry.list() == []
    assert registry.default_provider() is None


def test_ai_service_delegates_exclusively_to_registered_provider() -> None:
    """AIService delegates operations through registry and provider abstractions."""
    registry = ProviderRegistry()
    provider = FakeAIProvider()
    service = AIService(registry)
    request = make_request()

    assert service.register(ProviderType.CUSTOM, provider, default=True) is provider
    assert service.get(ProviderType.CUSTOM) is provider
    assert service.list() == [ProviderType.CUSTOM]
    assert service.default_provider() is provider

    health = service.health(ProviderType.CUSTOM)
    response = service.generate(request)
    stream_chunks = list(service.stream(request))
    embeddings = service.embeddings(ProviderType.CUSTOM, "enterprise context")
    models = service.list_models(ProviderType.CUSTOM)

    assert health.status is ProviderStatus.AVAILABLE
    assert response.request_id == request.id
    assert stream_chunks == ["chunk-a", "chunk-b"]
    assert embeddings == [0.1, 0.2, 0.3]
    assert models == ["ecos-test-model"]
    assert provider.health_calls == 1
    assert provider.generated == [request]
    assert provider.streamed == [request]
    assert provider.embedding_inputs == ["enterprise context"]
    assert provider.model_calls == 1

    service.unregister(ProviderType.CUSTOM)

    assert service.get(ProviderType.CUSTOM) is None


def test_ai_service_raises_for_unregistered_provider() -> None:
    """AIService requires a registered provider for provider operations."""
    service = AIService(ProviderRegistry())
    request = make_request()

    with pytest.raises(LookupError, match="provider not registered"):
        service.health(ProviderType.CUSTOM)

    with pytest.raises(LookupError, match="provider not registered"):
        service.generate(request)

    with pytest.raises(LookupError, match="provider not registered"):
        list(service.stream(request))

    with pytest.raises(LookupError, match="provider not registered"):
        service.embeddings(ProviderType.CUSTOM, "input")

    with pytest.raises(LookupError, match="provider not registered"):
        service.list_models(ProviderType.CUSTOM)

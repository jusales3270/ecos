"""Tests for the OpenAI adapter without external network calls."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import openai
import pytest

from ecos.core import Container, Settings
from ecos.core.exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    ConfigurationError,
)
from ecos.providers import AIRequest, OpenAIProvider, ProviderStatus, ProviderType
from ecos.runtime import FakeAIProvider


def make_provider(
    client: Mock, *, api_key: str | None = "test-placeholder"
) -> OpenAIProvider:
    """Build an adapter with an injected client and non-secret placeholder key."""
    return OpenAIProvider(
        api_key=api_key,
        model="test-generation-model",
        embedding_model="test-embedding-model",
        timeout_seconds=3.0,
        max_retries=0,
        client=client,
    )


def make_request() -> AIRequest:
    """Build a provider-neutral request."""
    return AIRequest(
        provider=ProviderType.OPENAI,
        model="engine-neutral-model",
        messages=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello."},
        ],
        temperature=0.2,
        max_tokens=42,
        metadata={"trace": "local-test"},
    )


def test_official_client_receives_timeout_and_retry_configuration() -> None:
    """Timeout and retry settings are applied when constructing the SDK client."""
    with patch("ecos.providers.openai_provider.OpenAI") as client_class:
        OpenAIProvider(
            api_key="test-placeholder",
            model="test-generation-model",
            embedding_model="test-embedding-model",
            timeout_seconds=7.5,
            max_retries=4,
        )

    client_class.assert_called_once_with(
        api_key="test-placeholder",
        timeout=7.5,
        max_retries=4,
    )


def test_request_conversion_uses_supported_responses_api_fields() -> None:
    """AIRequest becomes a non-streaming Responses API call."""
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        id="resp_test",
        model="test-generation-model",
        output_text="Normalized text.",
        status="completed",
        usage=SimpleNamespace(input_tokens=7, output_tokens=3),
    )

    make_provider(client).generate(make_request())

    client.responses.create.assert_called_once_with(
        model="test-generation-model",
        input=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello."},
        ],
        temperature=0.2,
        max_output_tokens=42,
    )


def test_response_content_model_usage_latency_and_metadata_are_normalized() -> None:
    """SDK response data is copied into provider-neutral response fields."""
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        id="resp_test",
        model="resolved-model",
        output_text="  Normalized text.  ",
        status="completed",
        usage=SimpleNamespace(input_tokens=11, output_tokens=5, total_tokens=16),
    )
    request = make_request()

    response = make_provider(client).generate(request)

    assert response.request_id == request.id
    assert response.provider is ProviderType.OPENAI
    assert response.model == "resolved-model"
    assert response.content == "Normalized text."
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 5
    assert response.usage.total_tokens == 16
    assert response.latency_ms >= 0
    assert response.metadata == {
        "provider_response_id": "resp_test",
        "status": "completed",
    }


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (
            openai.APITimeoutError(httpx.Request("POST", "https://example.invalid")),
            AIProviderTimeoutError,
        ),
        (
            openai.RateLimitError(
                "limited",
                response=httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://example.invalid"),
                ),
                body=None,
            ),
            AIProviderRateLimitError,
        ),
        (
            openai.AuthenticationError(
                "unauthorized",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://example.invalid"),
                ),
                body=None,
            ),
            AIProviderAuthenticationError,
        ),
        (RuntimeError("SDK internals must not leak"), AIProviderError),
    ],
)
def test_sdk_errors_are_mapped_to_internal_exceptions(
    sdk_error: Exception,
    expected_error: type[AIProviderError],
) -> None:
    """Timeout, rate-limit, auth and generic failures have stable ECOS types."""
    client = Mock()
    client.responses.create.side_effect = sdk_error

    with pytest.raises(expected_error):
        make_provider(client).generate(make_request())


def test_missing_api_key_is_unavailable_without_client_call() -> None:
    """Health and generation fail locally when credentials are absent."""
    client = Mock()
    provider = make_provider(client, api_key=None)

    health = provider.health()

    assert health.status is ProviderStatus.UNAVAILABLE
    assert health.message == "OpenAI API key is not configured."
    client.assert_not_called()
    with pytest.raises(AIProviderAuthenticationError):
        provider.generate(make_request())


def test_health_uses_controlled_model_check_and_sanitizes_failure() -> None:
    """Configured health checks only retrieve the configured model."""
    client = Mock()
    client.models.retrieve.side_effect = RuntimeError("sensitive upstream detail")

    health = make_provider(client).health()

    client.models.retrieve.assert_called_once_with("test-generation-model")
    assert health.status is ProviderStatus.UNAVAILABLE
    assert health.message == "AI provider request failed."


def test_embeddings_use_configured_model() -> None:
    """The required embeddings contract remains isolated in the adapter."""
    client = Mock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.25, -0.5])]
    )

    result = make_provider(client).embeddings("provider-neutral input")

    assert result == [0.25, -0.5]
    client.embeddings.create.assert_called_once_with(
        model="test-embedding-model",
        input="provider-neutral input",
    )


def test_container_selects_fake_by_default_and_openai_when_configured() -> None:
    """Container selection registers either implementation through the registry."""
    fake_container = Container(settings=Settings())
    openai_container = Container(
        settings=Settings(
            ai_provider="openai",
            openai_api_key="test-placeholder",
            openai_model="test-generation-model",
        )
    )

    assert isinstance(fake_container.ai_provider, FakeAIProvider)
    assert fake_container.ai_service.default_provider() is fake_container.ai_provider
    assert isinstance(openai_container.ai_provider, OpenAIProvider)
    assert (
        openai_container.ai_service.get(ProviderType.OPENAI)
        is openai_container.ai_provider
    )


def test_container_rejects_openai_without_api_key() -> None:
    """Explicit OpenAI selection requires credentials with a clear message."""
    with pytest.raises(ConfigurationError, match="ECOS_OPENAI_API_KEY is required"):
        Container(settings=Settings(ai_provider="openai", openai_api_key=None))


def test_engines_do_not_import_openai_sdk() -> None:
    """OpenAI SDK imports remain confined to the concrete provider module."""
    source_root = Path(__file__).parents[1] / "src" / "ecos"
    engine_areas = [
        "context",
        "reasoning",
        "debate",
        "decision",
        "learning",
        "memory",
        "session",
        "runtime",
    ]
    violations: list[str] = []
    for area in engine_areas:
        for path in (source_root / area).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                imported = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                if any(
                    name == "openai" or name.startswith("openai.") for name in imported
                ):
                    violations.append(str(path.relative_to(source_root)))
    assert violations == []


@pytest.mark.skipif(
    os.getenv("ECOS_RUN_OPENAI_TESTS") != "1" or not os.getenv("ECOS_OPENAI_API_KEY"),
    reason="requires ECOS_RUN_OPENAI_TESTS=1 and ECOS_OPENAI_API_KEY",
)
def test_optional_real_openai_generation() -> None:
    """Run one explicit opt-in real Responses API smoke test."""
    settings = Settings(ai_provider="openai")
    provider = OpenAIProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        embedding_model=settings.openai_embedding_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )
    response = provider.generate(
        AIRequest(
            provider=ProviderType.OPENAI,
            model=settings.openai_model,
            messages=[{"role": "user", "content": "Reply only with OK."}],
            max_tokens=5,
        )
    )
    assert response.content

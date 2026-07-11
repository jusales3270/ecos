"""OpenAI implementation of the provider-neutral ECOS AI contract."""

from __future__ import annotations

from collections.abc import Iterator
from time import perf_counter
from typing import Any

import openai
from openai import OpenAI

from ecos.core.exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnsupportedOperationError,
)
from ecos.providers.models import (
    AIRequest,
    AIResponse,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatus,
    ProviderType,
    TokenUsage,
)
from ecos.providers.provider import AIProvider


class OpenAIProvider(AIProvider):
    """Adapt the official OpenAI client to ECOS provider-neutral models."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        embedding_model: str,
        timeout_seconds: float,
        max_retries: int,
        *,
        client: Any | None = None,
    ) -> None:
        """Configure the adapter, optionally with an injected test client."""
        self._api_key = api_key
        self._model = model
        self._embedding_model = embedding_model
        self._client = client
        if client is None and api_key:
            self._client = OpenAI(
                api_key=api_key,
                timeout=timeout_seconds,
                max_retries=max_retries,
            )

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Declare the capabilities enabled by this sprint."""
        supported_models = list(dict.fromkeys([self._model, self._embedding_model]))
        return ProviderCapabilities(
            provider=ProviderType.OPENAI,
            supports_generation=True,
            supports_streaming=False,
            supports_embeddings=True,
            supported_models=supported_models,
        )

    def health(self) -> ProviderHealth:
        """Check configured model availability without exposing credentials."""
        if not self._api_key or self._client is None:
            return ProviderHealth(
                provider=ProviderType.OPENAI,
                status=ProviderStatus.UNAVAILABLE,
                message="OpenAI API key is not configured.",
            )
        started = perf_counter()
        try:
            self._client.models.retrieve(self._model)
        except Exception as error:
            mapped = self._map_error(error)
            return ProviderHealth(
                provider=ProviderType.OPENAI,
                status=ProviderStatus.UNAVAILABLE,
                message=str(mapped),
                latency_ms=self._elapsed_ms(started),
            )
        return ProviderHealth(
            provider=ProviderType.OPENAI,
            status=ProviderStatus.AVAILABLE,
            latency_ms=self._elapsed_ms(started),
        )

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate text with the Responses API and normalize the result."""
        client = self._require_client()
        started = perf_counter()
        try:
            response = client.responses.create(**self._request_parameters(request))
        except Exception as error:
            raise self._map_error(error) from error

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        content = str(getattr(response, "output_text", "") or "").strip()
        if not content:
            raise AIProviderError("AI provider returned no text content.")
        status = str(getattr(response, "status", "completed") or "completed")
        return AIResponse(
            request_id=request.id,
            provider=ProviderType.OPENAI,
            model=str(getattr(response, "model", None) or self._model),
            content=content,
            finish_reason="stop" if status == "completed" else status,
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            latency_ms=self._elapsed_ms(started),
            metadata={
                "provider_response_id": str(getattr(response, "id", "")),
                "status": status,
            },
        )

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Reject streaming because it is outside this sprint."""
        del request
        raise AIProviderUnsupportedOperationError("streaming")
        yield  # pragma: no cover

    def embeddings(self, input_text: str) -> list[float]:
        """Generate an embedding through the official embeddings API."""
        client = self._require_client()
        try:
            response = client.embeddings.create(
                model=self._embedding_model,
                input=input_text,
            )
            return [float(value) for value in response.data[0].embedding]
        except Exception as error:
            raise self._map_error(error) from error

    def list_models(self) -> list[str]:
        """List only models explicitly configured for this adapter."""
        return list(self.capabilities.supported_models)

    def _request_parameters(self, request: AIRequest) -> dict[str, Any]:
        """Convert an ECOS request to supported Responses API parameters."""
        parameters: dict[str, Any] = {
            "model": self._model,
            "input": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            parameters["max_output_tokens"] = request.max_tokens
        return parameters

    def _require_client(self) -> Any:
        """Return the configured client or fail without an external call."""
        if not self._api_key or self._client is None:
            raise AIProviderAuthenticationError
        return self._client

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))

    @staticmethod
    def _map_error(error: Exception) -> AIProviderError:
        """Map official SDK errors to stable ECOS exceptions."""
        if isinstance(error, openai.AuthenticationError):
            return AIProviderAuthenticationError()
        if isinstance(error, openai.RateLimitError):
            return AIProviderRateLimitError()
        if isinstance(error, openai.APITimeoutError):
            return AIProviderTimeoutError()
        return AIProviderError("AI provider request failed.")

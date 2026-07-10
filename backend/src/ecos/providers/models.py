"""Pydantic models for the ECOS AI Provider abstraction."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProviderMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ProviderType(StrEnum):
    """Supported AI provider categories."""

    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    GOOGLE = "GOOGLE"
    XAI = "XAI"
    DEEPSEEK = "DEEPSEEK"
    OLLAMA = "OLLAMA"
    CUSTOM = "CUSTOM"


class ProviderStatus(StrEnum):
    """Supported provider health statuses."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"


class ProviderModel(BaseModel):
    """Base provider model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique provider model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for provider model creation.",
    )

    @model_validator(mode="after")
    def validate_created_at(self) -> Self:
        """Ensure created_at is timezone-aware UTC."""
        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() != UTC.utcoffset(self.created_at)
        ):
            msg = "created_at must be timezone-aware and in UTC"
            raise ValueError(msg)
        return self


class TokenUsage(BaseModel):
    """Token accounting returned by a provider."""

    model_config = ConfigDict(validate_assignment=True)

    prompt_tokens: int = Field(
        default=0,
        ge=0,
        description="Number of prompt/input tokens.",
    )
    completion_tokens: int = Field(
        default=0,
        ge=0,
        description="Number of completion/output tokens.",
    )
    total_tokens: int = Field(
        default=0,
        ge=0,
        description="Total number of tokens.",
    )

    @model_validator(mode="after")
    def validate_total_tokens(self) -> Self:
        """Ensure total_tokens matches prompt plus completion tokens."""
        expected_total = self.prompt_tokens + self.completion_tokens
        if self.total_tokens != expected_total:
            msg = "total_tokens must equal prompt_tokens plus completion_tokens"
            raise ValueError(msg)
        return self


class ProviderCapabilities(BaseModel):
    """Declared provider capabilities without concrete SDK coupling."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    provider: ProviderType = Field(description="Provider type for the capabilities.")
    supports_generation: bool = Field(
        default=True,
        description="Whether the provider supports text generation.",
    )
    supports_streaming: bool = Field(
        default=False,
        description="Whether the provider supports streaming responses.",
    )
    supports_embeddings: bool = Field(
        default=False,
        description="Whether the provider supports embeddings.",
    )
    supported_models: list[str] = Field(
        default_factory=list,
        description="Provider-neutral supported model identifiers.",
    )

    @field_validator("supported_models")
    @classmethod
    def validate_supported_models(cls, value: list[str]) -> list[str]:
        """Reject blank and duplicate supported model identifiers."""
        normalized = [model.strip() for model in value]
        if any(model == "" for model in normalized):
            msg = "supported model identifiers cannot be blank"
            raise ValueError(msg)
        if len(normalized) != len(set(normalized)):
            msg = "supported model identifiers must be unique"
            raise ValueError(msg)
        return normalized


class ProviderHealth(ProviderModel):
    """Provider health report exposed through the abstraction layer."""

    provider: ProviderType = Field(description="Provider type for the health report.")
    status: ProviderStatus = Field(description="Current provider health status.")
    message: str | None = Field(
        default=None,
        max_length=500,
        description="Optional health status message.",
    )
    latency_ms: int | None = Field(
        default=None,
        ge=0,
        description="Optional provider health latency in milliseconds.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str | None) -> str | None:
        """Reject blank health messages when provided."""
        if value is not None and value.strip() == "":
            msg = "health message cannot be blank"
            raise ValueError(msg)
        return value


class AIRequest(ProviderModel):
    """Provider-neutral request for AI generation."""

    provider: ProviderType = Field(description="Target provider type.")
    model: str = Field(
        min_length=1,
        max_length=200,
        description="Provider-neutral model identifier.",
    )
    messages: list[dict[str, str]] = Field(
        description="Ordered provider-neutral messages.",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Generation temperature.",
    )
    max_tokens: int | None = Field(
        default=None,
        gt=0,
        description="Optional maximum number of generated tokens.",
    )
    metadata: dict[str, ProviderMetadataValue] = Field(
        default_factory=dict,
        description="Provider-neutral request metadata.",
    )

    @field_validator("messages")
    @classmethod
    def validate_messages(
        cls,
        value: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Ensure messages are non-empty and contain non-blank values."""
        if not value:
            msg = "messages cannot be empty"
            raise ValueError(msg)
        for message in value:
            if not message:
                msg = "messages cannot contain empty items"
                raise ValueError(msg)
            if any(key.strip() == "" for key in message):
                msg = "message keys cannot be blank"
                raise ValueError(msg)
            if any(content.strip() == "" for content in message.values()):
                msg = "message values cannot be blank"
                raise ValueError(msg)
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, ProviderMetadataValue],
    ) -> dict[str, ProviderMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value


class AIResponse(ProviderModel):
    """Provider-neutral response returned by AI generation."""

    request_id: UUID = Field(description="Identifier of the originating request.")
    provider: ProviderType = Field(
        description="Provider type that generated the response.",
    )
    model: str = Field(
        min_length=1,
        max_length=200,
        description="Provider-neutral model identifier.",
    )
    content: str = Field(
        min_length=1,
        description="Generated provider-neutral content.",
    )
    finish_reason: str = Field(
        min_length=1,
        max_length=200,
        description="Provider-neutral completion finish reason.",
    )
    usage: TokenUsage = Field(description="Token usage reported by the provider.")
    latency_ms: int = Field(
        ge=0,
        description="Generation latency in milliseconds.",
    )

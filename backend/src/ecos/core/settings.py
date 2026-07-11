"""Centralized settings for the ECOS backend."""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("backend/.env", ".env"),
        env_prefix="ECOS_",
        extra="ignore",
    )

    name: str = Field(default="ECOS", description="Application display name.")
    service_name: str = Field(
        default="ecos-backend",
        description="Backend service identifier.",
    )
    version: str = Field(default="0.1.0", description="Application version.")
    environment: str = Field(default="development", description="Runtime environment.")
    log_level: str = Field(default="INFO", description="Structured logging level.")
    database_url: str = Field(
        default="postgresql://ecos:ecos@postgres:5432/ecos",
        description="Development PostgreSQL connection URL with placeholder values.",
    )
    session_repository: Literal["fake", "postgres"] = Field(
        default="fake",
        description="Session repository implementation used by the application.",
    )
    memory_repository: Literal["fake", "postgres"] = Field(
        default="fake",
        description="Memory repository implementation used by the application.",
    )
    observability_repository: Literal["memory", "postgres"] = Field(
        default="memory",
        description="Event, audit and observability repository implementation.",
    )
    ai_provider: Literal["fake", "openai"] = Field(
        default="fake",
        description="AI provider implementation used by the application.",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key. It must only be supplied through the environment.",
    )
    openai_model: str = Field(
        default="gpt-4.1-mini",
        description="OpenAI model used for text generation.",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI model used for embeddings.",
    )
    openai_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="OpenAI request timeout in seconds.",
    )
    openai_max_retries: int = Field(
        default=2,
        ge=0,
        description="Maximum retries performed by the OpenAI client.",
    )

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Use SQLAlchemy's asyncpg driver for PostgreSQL URLs."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    redis_url: str = Field(
        default="redis://redis:6379/0",
        description="Development Redis connection URL.",
    )
    pgadmin_email: str = Field(
        default="admin@example.local",
        description="Development pgAdmin login email placeholder.",
    )
    pgadmin_password: str = Field(
        default="change-me-development-only",
        description="Development pgAdmin password placeholder.",
    )
    correlation_id_header: str = Field(
        default="X-Correlation-ID",
        description="HTTP header used to propagate correlation IDs.",
    )


settings = Settings()

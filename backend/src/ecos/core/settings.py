"""Centralized settings for the ECOS backend."""

from datetime import timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ecos.version import application_version


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
    version: str = Field(
        default_factory=application_version, description="Application version."
    )
    environment: str = Field(default="development", description="Runtime environment.")
    log_level: str = Field(default="INFO", description="Structured logging level.")
    database_url: str = Field(
        default="postgresql://ecos:ecos@postgres:5432/ecos",
        description="Development PostgreSQL connection URL with placeholder values.",
    )
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_recycle_seconds: int = Field(default=1800, ge=30)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    database_lock_timeout_ms: int = Field(default=2000, ge=100, le=60000)
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
    knowledge_repository: Literal["memory", "postgres"] = Field(
        default="memory",
        description="Knowledge Graph repository implementation.",
    )
    security_repository: Literal["memory", "postgres"] = Field(
        default="memory",
        description="Identity and authentication repository implementation.",
    )
    operational_repository: Literal["memory", "postgres"] = Field(
        default="memory",
        description="Operational workflow repository implementation.",
    )
    auth_token_secret: str = Field(
        default="development-only-auth-secret-change-me-000000",
        description="Local token signing secret supplied through secure config.",
    )
    auth_token_key_ring: str | None = Field(
        default=None,
        description="Comma-separated JWT key ring entries in kid:secret format.",
    )
    auth_active_key_id: str = Field(default="local-dev", min_length=1)
    auth_previous_key_grace_minutes: int = Field(default=120, ge=0, le=10080)
    auth_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    auth_token_ttl_minutes: int = Field(
        default=60,
        ge=1,
        description="Authentication token lifetime in minutes.",
    )
    auth_issuer: str = Field(
        default="ecos.local",
        min_length=1,
        description="Issuer used for local ECOS auth tokens.",
    )
    auth_audience: str = Field(
        default="ecos.api",
        min_length=1,
        description="Audience used for local ECOS auth tokens.",
    )
    auth_demo_enabled: bool = Field(
        default=True,
        description="Allow explicit demo identity for /runtime/demo.",
    )
    demo_seed_enabled: bool = Field(
        default=True,
        description="Create explicit local/E2E demo identities and data.",
    )
    web_cookie_name: str = Field(
        default="ecos_session",
        min_length=1,
        description="HttpOnly browser session cookie name.",
    )
    csrf_cookie_name: str = Field(
        default="ecos_csrf",
        min_length=1,
        description="Readable CSRF cookie name for browser clients.",
    )
    csrf_header_name: str = Field(
        default="X-CSRF-Token",
        min_length=1,
        description="Header required for mutable cookie-authenticated requests.",
    )
    frontend_static_dir: str = Field(
        default="frontend/dist",
        description="Compiled frontend directory served by the backend.",
    )
    metrics_enabled: bool = Field(
        default=True,
        description="Expose operational metrics when enabled.",
    )
    outbox_enabled: bool = Field(default=True)
    outbox_process_on_startup: bool = Field(default=False)
    outbox_batch_size: int = Field(default=25, ge=1, le=250)
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    login_throttle_window_seconds: int = Field(default=300, ge=10)
    login_throttle_limit: int = Field(default=5, ge=1)
    login_throttle_block_seconds: int = Field(default=900, ge=10)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_default: int = Field(default=120, ge=1)
    rate_limit_login: int = Field(default=10, ge=1)
    rate_limit_admin: int = Field(default=60, ge=1)
    trusted_proxy_cidrs: str = Field(default="")
    allowed_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")
    allowed_hosts: str = Field(default="localhost,127.0.0.1,testserver")
    openapi_enabled: bool = Field(default=True)
    docs_enabled: bool = Field(default=True)
    build_commit_sha: str | None = Field(default=None)
    build_date: str | None = Field(default=None)
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

    @model_validator(mode="after")
    def validate_security_defaults(self) -> "Settings":
        """Reject insecure defaults in production-like environments."""
        if self.environment.lower() in {"production", "prod"} and (
            self.auth_token_secret == "development-only-auth-secret-change-me-000000"
            or len(self.auth_token_secret) < 32
        ):
            msg = "ECOS_AUTH_TOKEN_SECRET must be securely configured in production"
            raise ValueError(msg)
        if self.environment.lower() in {"production", "prod"} and (
            not self.auth_token_key_ring
            or "development-only-auth-secret" in self.auth_token_key_ring
        ):
            msg = "ECOS_AUTH_TOKEN_KEY_RING must be securely configured in production"
            raise ValueError(msg)
        if self.environment.lower() in {"production", "prod"} and (
            self.auth_demo_enabled or self.demo_seed_enabled
        ):
            msg = "demo authentication and seed data must be disabled in production"
            raise ValueError(msg)
        if self.environment.lower() in {"production", "prod"} and (
            self.session_repository != "postgres"
            or self.security_repository != "postgres"
            or self.observability_repository != "postgres"
            or self.operational_repository != "postgres"
        ):
            msg = "PostgreSQL repositories must be explicit in production"
            raise ValueError(msg)
        return self

    @property
    def auth_token_ttl(self) -> timedelta:
        """Return token lifetime as timedelta."""
        return timedelta(minutes=self.auth_token_ttl_minutes)

    @property
    def production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

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

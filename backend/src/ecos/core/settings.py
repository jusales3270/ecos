"""Centralized settings for the ECOS backend."""

from pydantic import Field
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

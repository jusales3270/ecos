"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the ECOS backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ECOS_",
        extra="ignore",
    )

    service_name: str = "ecos-backend"
    version: str = "0.1.0"

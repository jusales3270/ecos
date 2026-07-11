"""Tests for ECOS core infrastructure primitives."""

import json
import logging

from ecos.core import Container, DependencyNotFoundError, Settings
from ecos.core.logging import (
    StructuredJsonFormatter,
    get_correlation_id,
    set_correlation_id,
)
from ecos.runtime import RuntimeEngine


def test_settings_exposes_development_defaults_without_real_secrets() -> None:
    """Settings centralizes local development configuration defaults."""
    settings = Settings()

    assert settings.name == "ECOS"
    assert settings.service_name == "ecos-backend"
    assert settings.version == "0.1.0"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url.startswith("postgresql://ecos:ecos@")
    assert settings.redis_url.startswith("redis://")
    assert settings.pgadmin_email == "admin@example.local"
    assert settings.pgadmin_password == "change-me-development-only"


def test_container_registers_services_fake_providers_and_runtime() -> None:
    """Container registers services, fake providers and runtime engine."""
    container = Container(settings=Settings())
    health = container.health()

    assert isinstance(container.runtime_engine, RuntimeEngine)
    assert container.runtime_engine.pipeline is container.runtime_pipeline
    assert container.memory_service is not None
    assert container.context_service is not None
    assert container.event_service is not None
    assert container.session_service is not None
    assert container.planner_service is not None
    assert container.reasoning_service is not None
    assert container.specialist_service is not None
    assert container.debate_service is not None
    assert container.decision_service is not None
    assert container.orchestrator_service is not None
    assert container.ai_service is not None
    assert health == {
        "container": "ok",
        "providers": {"CUSTOM": True},
        "runtime": True,
    }


def test_structured_logging_includes_correlation_id() -> None:
    """StructuredJsonFormatter includes the active correlation identifier."""
    set_correlation_id("test-correlation-id")
    record = logging.LogRecord(
        name="ecos.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.correlation_id = get_correlation_id()

    payload = json.loads(StructuredJsonFormatter().format(record))

    assert payload == {
        "correlation_id": "test-correlation-id",
        "level": "INFO",
        "logger": "ecos.test",
        "message": "hello",
    }


def test_standardized_exception_contains_code_and_details() -> None:
    """Standardized exceptions expose code and details."""
    error = DependencyNotFoundError("runtime_engine")

    assert str(error) == "dependency not registered: runtime_engine"
    assert error.code == "DEPENDENCY_NOT_FOUND"
    assert error.details == {"dependency": "runtime_engine"}

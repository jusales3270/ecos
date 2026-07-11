"""Tests for ECOS core infrastructure primitives."""

import json
import logging

from ecos.core import Container, DependencyNotFoundError, Settings
from ecos.core.logging import (
    StructuredJsonFormatter,
    get_correlation_id,
    set_correlation_id,
)
from ecos.debate import AIDebateEngine
from ecos.memory import PostgresMemoryRepository
from ecos.reasoning import AIReasoningEngine
from ecos.runtime import RuntimeEngine
from ecos.runtime.fakes import (
    FakeDebateProvider,
    FakeMemoryRepository,
    FakeReasoningProvider,
    FakeSessionRepository,
    FakeWarEngine,
)
from ecos.session import PostgresSessionRepository
from ecos.simulation import AIWarEngine


def test_settings_exposes_development_defaults_without_real_secrets() -> None:
    """Settings centralizes local development configuration defaults."""
    settings = Settings()

    assert settings.name == "ECOS"
    assert settings.service_name == "ecos-backend"
    assert settings.version == "0.1.0"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url.startswith("postgresql+asyncpg://ecos:ecos@")
    assert settings.session_repository == "fake"
    assert settings.memory_repository == "fake"
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
    assert container.learning_service is not None
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
    assert isinstance(container.reasoning_provider, FakeReasoningProvider)
    assert isinstance(container.debate_provider, FakeDebateProvider)
    assert isinstance(container.simulation_provider, FakeWarEngine)


def test_container_selects_ai_reasoning_engine_for_openai() -> None:
    """Container injects its registry-selected provider into AI reasoning."""
    container = Container(
        settings=Settings(ai_provider="openai", openai_api_key="test-placeholder")
    )

    assert isinstance(container.reasoning_provider, AIReasoningEngine)
    assert container.reasoning_provider._provider is container.provider_registry.get(
        container.ai_provider_type
    )
    assert isinstance(container.debate_provider, AIDebateEngine)
    assert container.debate_provider._provider is container.provider_registry.get(
        container.ai_provider_type
    )
    assert isinstance(container.simulation_provider, AIWarEngine)
    assert container.simulation_provider._provider is container.provider_registry.get(
        container.ai_provider_type
    )


def test_container_selects_configured_session_repository() -> None:
    """Container keeps fake by default and supports PostgreSQL explicitly."""
    fake_container = Container(settings=Settings(session_repository="fake"))
    postgres_container = Container(
        settings=Settings(
            session_repository="postgres",
            database_url="postgresql://ecos:ecos@localhost/ecos",
        )
    )

    assert isinstance(fake_container.session_repository, FakeSessionRepository)
    assert isinstance(postgres_container.session_repository, PostgresSessionRepository)


def test_container_selects_configured_memory_repository() -> None:
    """Container keeps fake memory by default and supports PostgreSQL explicitly."""
    fake_container = Container(settings=Settings(memory_repository="fake"))
    postgres_container = Container(
        settings=Settings(
            memory_repository="postgres",
            database_url="postgresql://ecos:ecos@localhost/ecos",
        )
    )

    assert isinstance(fake_container.memory_repository, FakeMemoryRepository)
    assert isinstance(postgres_container.memory_repository, PostgresMemoryRepository)


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

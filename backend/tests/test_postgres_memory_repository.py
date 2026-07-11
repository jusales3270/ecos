"""Conditional PostgreSQL integration tests for memory persistence."""

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config

from ecos.memory import MemoryObject, MemoryType, PostgresMemoryRepository

database_url = os.getenv("ECOS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    database_url is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)


def async_database_url(value: str) -> str:
    """Normalize a PostgreSQL URL to SQLAlchemy's asyncpg dialect."""
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


def test_postgres_memory_repository_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist, query, update and delete memory through the public contract."""
    assert database_url is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    repository = PostgresMemoryRepository(async_database_url(database_url))
    memory = MemoryObject(
        type=MemoryType.SEMANTIC,
        title="PostgreSQL memory",
        description="Durable organizational learning.",
        tags=["postgres", "integration"],
        confidence=0.8,
        source="integration-test",
    )

    try:
        assert repository.store(memory) == memory
        assert repository.get(memory.id) == memory
        assert repository.search("organizational", tags=["postgres"]) == [memory]
        assert repository.list(memory_type=MemoryType.SEMANTIC) == [memory]

        updated = memory.model_copy(
            update={"confidence": 0.9, "updated_at": datetime.now(UTC)}
        )
        assert repository.update(updated) == updated
        assert repository.get(memory.id) == updated
        repository.delete(memory.id)
        assert repository.get(memory.id) is None
    finally:
        command.downgrade(config, "base")

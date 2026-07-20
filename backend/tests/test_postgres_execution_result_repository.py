"""PostgreSQL integration tests for canonical execution results."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from ecos.execution import (
    ExecutionMetric,
    ExecutionMode,
    ExecutionResult,
    ExecutionResultConflictError,
    ExecutionStatus,
    deterministic_fingerprint,
)
from ecos.execution.postgres_repository import PostgresExecutionResultRepository

database_url = os.getenv("ECOS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    database_url is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)


def _async_database_url(value: str) -> str:
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


def _result() -> ExecutionResult:
    execution_id = uuid4()
    provisional = ExecutionResult(
        execution_id=execution_id,
        execution_request_id=uuid4(),
        execution_plan_id=uuid4(),
        organization_id=uuid4(),
        session_id=uuid4(),
        plan_id=uuid4(),
        correlation_id=uuid4(),
        status=ExecutionStatus.COMPLETED,
        fingerprint="0" * 64,
        mode=ExecutionMode.DRY_RUN,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        duration=0.25,
        outputs_by_step={uuid4(): {"typed": True, "count": 2}},
        metrics=(ExecutionMetric(name="quality", value=0.9, unit="score"),),
        idempotency_key=f"postgres:{execution_id}",
        authorization_id=uuid4(),
        policy_references=("policy:canonical",),
        reason_codes=("postgres_round_trip",),
    )
    return provisional.model_copy(
        update={
            "fingerprint": deterministic_fingerprint(
                provisional.model_dump(mode="json", exclude={"fingerprint"})
            )
        }
    )


def test_postgres_execution_result_round_trip_and_immutable_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert database_url is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    repository = PostgresExecutionResultRepository(_async_database_url(database_url))
    result = _result()

    try:
        assert repository.save(result) == result
        assert repository.save(result) == result
        assert repository.get(result.organization_id, result.execution_id) == result
        assert repository.get(uuid4(), result.execution_id) is None
        with pytest.raises(ExecutionResultConflictError):
            repository.save(result.model_copy(update={"fingerprint": "b" * 64}))
        with pytest.raises(ExecutionResultConflictError):
            repository.save(result.model_copy(update={"organization_id": uuid4()}))
    finally:
        asyncio.run(repository.engine.dispose())

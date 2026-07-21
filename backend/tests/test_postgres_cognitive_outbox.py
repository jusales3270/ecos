"""PostgreSQL transaction and fencing tests for cognitive terminal events."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from ecos.events import Event, EventMetadata, EventService, EventType
from ecos.execution import (
    ExecutionMode,
    ExecutionResult,
    ExecutionStatus,
    deterministic_fingerprint,
)
from ecos.execution.postgres_repository import PostgresExecutionResultRepository
from ecos.outbox import OutboxService, PostgresOutboxRepository, terminal_event_id
from ecos.runtime import FakeEventBus

DATABASE_URL = os.getenv("ECOS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="ECOS_TEST_DATABASE_URL is not configured"
)


def _async_url(value: str) -> str:
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


def _result_and_event() -> tuple[ExecutionResult, Event]:
    organization_id = uuid4()
    execution_id = uuid4()
    event_id = terminal_event_id(
        organization_id=organization_id,
        aggregate_type="execution",
        aggregate_id=execution_id,
        event_type=EventType.EXECUTION_COMPLETED.value,
    )
    provisional = ExecutionResult(
        execution_id=execution_id,
        execution_request_id=uuid4(),
        execution_plan_id=uuid4(),
        organization_id=organization_id,
        session_id=uuid4(),
        plan_id=uuid4(),
        correlation_id=uuid4(),
        status=ExecutionStatus.COMPLETED,
        fingerprint="0" * 64,
        terminal_event_id=event_id,
        mode=ExecutionMode.DRY_RUN,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        duration=0.1,
        idempotency_key=f"outbox:{execution_id}",
        authorization_id=uuid4(),
    )
    result = provisional.model_copy(
        update={
            "fingerprint": deterministic_fingerprint(
                provisional.model_dump(mode="json", exclude={"fingerprint"})
            )
        }
    )
    event = Event(
        id=event_id,
        event_type=EventType.EXECUTION_COMPLETED,
        source="execution",
        organization_id=organization_id,
        session_id=result.session_id,
        payload={
            "execution_id": str(execution_id),
            "status": result.status.value,
            "fingerprint": result.fingerprint,
        },
        metadata=EventMetadata(correlation_id=result.correlation_id),
    )
    return result, event


async def _counts(url: str, execution_id) -> tuple[int, int]:
    repository = PostgresExecutionResultRepository(url)
    try:
        async with repository.engine.connect() as connection:
            aggregate = await connection.scalar(
                text(
                    "SELECT count(*) FROM execution_results "
                    "WHERE execution_id = :execution_id"
                ),
                {"execution_id": execution_id},
            )
            outbox = await connection.scalar(
                text(
                    "SELECT count(*) FROM transactional_outbox "
                    "WHERE execution_id = :execution_id"
                ),
                {"execution_id": execution_id},
            )
            return int(aggregate or 0), int(outbox or 0)
    finally:
        await repository.engine.dispose()


def test_aggregate_and_outbox_commit_replay_and_rollback_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", DATABASE_URL)
    command.upgrade(Config("alembic.ini"), "head")
    url = _async_url(DATABASE_URL)
    repository = PostgresExecutionResultRepository(url)
    result, event = _result_and_event()

    try:
        assert repository.save_terminal(result, event) == result
        assert asyncio.run(_counts(url, result.execution_id)) == (1, 1)
        assert repository.save_terminal(result, event) == result
        assert asyncio.run(_counts(url, result.execution_id)) == (1, 1)

        rollback_result, rollback_event = _result_and_event()

        async def fail_before_commit(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("simulated pre-commit failure")

        monkeypatch.setattr(
            "ecos.execution.postgres_repository.append_outbox_event",
            fail_before_commit,
        )
        with pytest.raises(RuntimeError, match="pre-commit"):
            repository.save_terminal(rollback_result, rollback_event)
        assert asyncio.run(_counts(url, rollback_result.execution_id)) == (0, 0)
    finally:
        asyncio.run(repository.engine.dispose())


def test_postgres_claim_is_exclusive_versioned_and_expired_lease_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", DATABASE_URL)
    command.upgrade(Config("alembic.ini"), "head")
    url = _async_url(DATABASE_URL)
    aggregate = PostgresExecutionResultRepository(url)
    first_worker = PostgresOutboxRepository(url)
    second_worker = PostgresOutboxRepository(url)
    result, event = _result_and_event()
    aggregate.save_terminal(result, event)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(
                pool.map(
                    lambda item: item[0].claim(
                        limit=100, stale_after=timedelta(minutes=5), owner=item[1]
                    ),
                    ((first_worker, "worker-a"), (second_worker, "worker-b")),
                )
            )
        claimed = [
            item
            for batch in claims
            for item in batch
            if item.event_id == event.event_id
        ]
        assert len(claimed) == 1
        active = claimed[0]
        assert not second_worker.mark_delivered(
            active.message_id, owner="wrong-owner", version=active.version
        )

        async def expire() -> None:
            async with aggregate.engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE transactional_outbox SET claim_expires_at = :expired "
                        "WHERE message_id = :message_id"
                    ),
                    {
                        "expired": datetime.now(UTC) - timedelta(seconds=1),
                        "message_id": active.message_id,
                    },
                )

        asyncio.run(expire())
        recovered = second_worker.claim(
            limit=1, stale_after=timedelta(minutes=5), owner="worker-b"
        )
        assert len(recovered) == 1
        assert recovered[0].event_id == event.event_id
        assert recovered[0].attempts == active.attempts + 1
        assert second_worker.mark_delivered(
            recovered[0].message_id,
            owner="worker-b",
            version=recovered[0].version,
        )
        assert not first_worker.mark_delivered(
            active.message_id, owner="worker-a", version=active.version
        )
    finally:
        asyncio.run(second_worker.engine.dispose())
        asyncio.run(first_worker.engine.dispose())
        asyncio.run(aggregate.engine.dispose())


def test_restart_dispatches_committed_pending_event() -> None:
    assert DATABASE_URL is not None
    url = _async_url(DATABASE_URL)
    aggregate = PostgresExecutionResultRepository(url)
    result, event = _result_and_event()
    aggregate.save_terminal(result, event)
    asyncio.run(aggregate.engine.dispose())

    bus = FakeEventBus()
    restarted_repository = PostgresOutboxRepository(url)
    dispatcher = OutboxService(
        restarted_repository,
        EventService(bus),
        max_attempts=3,
        batch_size=100,
    )
    try:
        outcome = dispatcher.process_once()
        assert outcome["delivered"] >= 1
        assert sum(item.event.event_id == event.event_id for item in bus.envelopes) == 1
    finally:
        asyncio.run(restarted_repository.engine.dispose())

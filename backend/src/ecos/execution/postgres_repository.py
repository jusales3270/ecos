"""PostgreSQL storage for immutable canonical execution results."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.events import Event
from ecos.execution.models import ExecutionResult
from ecos.execution.repository import (
    ExecutionResultConflictError,
    ExecutionResultRepository,
    validate_execution_result_fingerprint,
    validate_execution_terminal_event,
)
from ecos.outbox import append_outbox_event


class Base(DeclarativeBase):
    """Declarative base for canonical execution result persistence."""


class ExecutionResultRecord(Base):
    """Immutable row containing a typed execution result JSON payload."""

    __tablename__ = "execution_results"

    execution_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    plan_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    correlation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    """Run async persistence while preserving the synchronous repository port."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class PostgresExecutionResultRepository(ExecutionResultRepository):
    """Persist the first complete result and reject every divergent reuse."""

    supports_transactional_outbox = True

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_database_engine(database_url or "")
        self._session_factory = session_factory or create_session_factory(self.engine)

    def get(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> ExecutionResult | None:
        return _run(self._get(organization_id, execution_id))

    async def _get(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> ExecutionResult | None:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(ExecutionResultRecord).where(
                    ExecutionResultRecord.execution_id == execution_id,
                    ExecutionResultRecord.organization_id == organization_id,
                )
            )
            return None if record is None else self._model(record)

    def save(self, result: ExecutionResult) -> ExecutionResult:
        return _run(self._save(result, event=None))

    def save_terminal(self, result: ExecutionResult, event: Event) -> ExecutionResult:
        validate_execution_terminal_event(result, event)
        return _run(self._save(result, event=event))

    async def _save(
        self, result: ExecutionResult, *, event: Event | None
    ) -> ExecutionResult:
        validate_execution_result_fingerprint(result)
        async with self._session_factory() as database:
            inserted = await database.scalar(
                insert(ExecutionResultRecord)
                .values(
                    execution_id=result.execution_id,
                    organization_id=result.organization_id,
                    session_id=result.session_id,
                    plan_id=result.plan_id,
                    correlation_id=result.correlation_id,
                    status=result.status.value,
                    fingerprint=result.fingerprint,
                    payload=result.model_dump(mode="json"),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["execution_id"])
                .returning(ExecutionResultRecord.execution_id)
            )
            if inserted is not None:
                canonical = result.model_copy(deep=True)
            else:
                record = await database.scalar(
                    select(ExecutionResultRecord).where(
                        ExecutionResultRecord.execution_id == result.execution_id
                    )
                )
                if record is None:
                    raise ExecutionResultConflictError(
                        "execution result conflict could not be resolved safely"
                    )
                canonical = self._model(record)
                if (
                    record.organization_id != result.organization_id
                    or record.session_id != result.session_id
                    or record.plan_id != result.plan_id
                    or record.correlation_id != result.correlation_id
                    or record.fingerprint != result.fingerprint
                ):
                    raise ExecutionResultConflictError(
                        "execution result identity or fingerprint conflict"
                    )
            if event is not None:
                await append_outbox_event(
                    database,
                    event,
                    aggregate_type="execution",
                    aggregate_id=result.execution_id,
                    execution_id=result.execution_id,
                )
            await database.commit()
            return canonical

    @staticmethod
    def _model(record: ExecutionResultRecord) -> ExecutionResult:
        result = ExecutionResult.model_validate(record.payload)
        validate_execution_result_fingerprint(result)
        if (
            result.execution_id != record.execution_id
            or result.organization_id != record.organization_id
            or result.session_id != record.session_id
            or result.plan_id != record.plan_id
            or result.correlation_id != record.correlation_id
            or result.status.value != record.status
            or result.fingerprint != record.fingerprint
        ):
            raise ExecutionResultConflictError(
                "stored execution result columns do not match typed payload"
            )
        return result

"""PostgreSQL persistence for authenticated runtime checkpoints."""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.runtime.repository import (
    RuntimeCheckpoint,
    RuntimeCheckpointConflictError,
    RuntimeCheckpointRepository,
    RuntimeCheckpointScopeError,
)


class Base(DeclarativeBase):
    """Declarative base for runtime checkpoint persistence."""


class RuntimeCheckpointRecord(Base):
    """Versioned durable runtime checkpoint row."""

    __tablename__ = "runtime_checkpoints"

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    correlation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    cognitive_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resumable_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    stage_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    governance_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    """Run async persistence while preserving the synchronous service contract."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class PostgresRuntimeCheckpointRepository(RuntimeCheckpointRepository):
    """Store runtime checkpoints in PostgreSQL with optimistic concurrency."""

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

    def get(self, organization_id: UUID, session_id: UUID) -> RuntimeCheckpoint | None:
        return _run(self._get(organization_id, session_id))

    async def _get(
        self, organization_id: UUID, session_id: UUID
    ) -> RuntimeCheckpoint | None:
        async with self._session_factory() as database:
            record = await database.get(RuntimeCheckpointRecord, session_id)
            if record is None:
                return None
            if record.organization_id != organization_id:
                raise RuntimeCheckpointScopeError("runtime checkpoint is not available")
            return _checkpoint(record)

    def save(
        self,
        checkpoint: RuntimeCheckpoint,
        *,
        expected_version: int | None,
    ) -> RuntimeCheckpoint:
        return _run(self._save(checkpoint, expected_version=expected_version))

    async def _save(
        self,
        checkpoint: RuntimeCheckpoint,
        *,
        expected_version: int | None,
    ) -> RuntimeCheckpoint:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(RuntimeCheckpointRecord)
                .where(RuntimeCheckpointRecord.session_id == checkpoint.session_id)
                .with_for_update()
            )
            if (
                record is not None
                and record.organization_id != checkpoint.organization_id
            ):
                raise RuntimeCheckpointScopeError("runtime checkpoint scope mismatch")
            current_version = None if record is None else record.version
            if current_version != expected_version:
                raise RuntimeCheckpointConflictError(
                    "runtime checkpoint version conflict"
                )
            if record is None:
                if checkpoint.version != 1:
                    raise RuntimeCheckpointConflictError(
                        "new checkpoint version must be 1"
                    )
                record = RuntimeCheckpointRecord(
                    session_id=checkpoint.session_id,
                    organization_id=checkpoint.organization_id,
                    user_id=checkpoint.user_id,
                    correlation_id=checkpoint.correlation_id,
                    cognitive_plan={},
                    stage_results=[],
                    version=checkpoint.version,
                    status=checkpoint.status.value,
                    created_at=checkpoint.created_at,
                    updated_at=checkpoint.updated_at,
                )
                database.add(record)
            elif checkpoint.version != record.version + 1:
                raise RuntimeCheckpointConflictError(
                    "updated checkpoint version must increment by one"
                )
            _update_record(record, checkpoint)
            await database.commit()
            return checkpoint.model_copy(deep=True)


def _update_record(
    record: RuntimeCheckpointRecord, checkpoint: RuntimeCheckpoint
) -> None:
    record.organization_id = checkpoint.organization_id
    record.user_id = checkpoint.user_id
    record.correlation_id = checkpoint.correlation_id
    record.cognitive_plan = checkpoint.cognitive_plan.model_dump(mode="json")
    record.resumable_state = (
        checkpoint.resumable_state.model_dump(mode="json")
        if checkpoint.resumable_state is not None
        else None
    )
    record.stage_results = [
        item.model_dump(mode="json") for item in checkpoint.stage_results
    ]
    record.governance_result = (
        checkpoint.governance_result.model_dump(mode="json")
        if checkpoint.governance_result is not None
        else None
    )
    record.version = checkpoint.version
    record.status = checkpoint.status.value
    record.created_at = checkpoint.created_at
    record.updated_at = checkpoint.updated_at


def _checkpoint(record: RuntimeCheckpointRecord) -> RuntimeCheckpoint:
    return RuntimeCheckpoint.model_validate(
        {
            "session_id": record.session_id,
            "organization_id": record.organization_id,
            "user_id": record.user_id,
            "correlation_id": record.correlation_id,
            "cognitive_plan": record.cognitive_plan,
            "resumable_state": record.resumable_state,
            "stage_results": record.stage_results,
            "governance_result": record.governance_result,
            "version": record.version,
            "status": record.status,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
    )

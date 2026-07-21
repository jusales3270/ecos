"""PostgreSQL storage for immutable canonical observations."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.events import Event
from ecos.outbox import OutboxConflictError, OutboxRecord, append_outbox_event

from .models import ObservationResult
from .repository import (
    ObservationConflictError,
    ObservationRepository,
    _validate_compatible,
    validate_observation_terminal_event,
)


class Base(DeclarativeBase):
    pass


class ObservationResultRecord(Base):
    __tablename__ = "observation_results"

    observation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    execution_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    source_event_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_result_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class PostgresObservationRepository(ObservationRepository):
    """Persist the first observation and safely resolve concurrent inserts."""

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
        self._sync_lock = RLock()

    def get(
        self, organization_id: UUID, execution_id: UUID
    ) -> ObservationResult | None:
        with self._sync_lock:
            return _run(self._get(organization_id, execution_id))

    async def _get(
        self, organization_id: UUID, execution_id: UUID
    ) -> ObservationResult | None:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(ObservationResultRecord).where(
                    ObservationResultRecord.organization_id == organization_id,
                    ObservationResultRecord.execution_id == execution_id,
                )
            )
            return None if record is None else self._model(record)

    def save(self, result: ObservationResult) -> ObservationResult:
        with self._sync_lock:
            return _run(self._save(result, event=None))

    def save_terminal(
        self, result: ObservationResult, event: Event
    ) -> ObservationResult:
        validate_observation_terminal_event(result, event)
        with self._sync_lock:
            return _run(self._save(result, event=event))

    async def _save(
        self, result: ObservationResult, *, event: Event | None
    ) -> ObservationResult:
        if result.execution_id is None:
            raise ObservationConflictError(
                "canonical observation requires execution_id"
            )
        async with self._session_factory() as database:
            inserted = await database.scalar(
                insert(ObservationResultRecord)
                .values(
                    observation_id=result.observation_id,
                    organization_id=result.organization_id,
                    session_id=result.session_id,
                    execution_id=result.execution_id,
                    correlation_id=result.correlation_id,
                    source_event_id=result.source_event_id,
                    status=result.status.value,
                    fingerprint=result.fingerprint,
                    execution_result_fingerprint=result.execution_result_fingerprint,
                    payload=result.model_dump(mode="json"),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing()
                .returning(ObservationResultRecord.observation_id)
            )
            if inserted is not None:
                canonical = result.model_copy(deep=True)
            else:
                record = await database.scalar(
                    select(ObservationResultRecord).where(
                        ObservationResultRecord.execution_id == result.execution_id,
                    )
                )
                if record is None:
                    raise ObservationConflictError(
                        "observation conflict could not be resolved"
                    )
                canonical = self._model(record)
                _validate_compatible(canonical, result)
            if event is not None and inserted is not None:
                await append_outbox_event(
                    database,
                    event,
                    aggregate_type="observation",
                    aggregate_id=result.observation_id,
                    execution_id=result.execution_id,
                    observation_id=result.observation_id,
                )
            elif event is not None:
                existing_event = await database.scalar(
                    select(OutboxRecord).where(
                        OutboxRecord.aggregate_type == "observation",
                        OutboxRecord.aggregate_id == str(canonical.observation_id),
                        OutboxRecord.organization_id == canonical.organization_id,
                    )
                )
                if existing_event is None:
                    raise OutboxConflictError(
                        "canonical observation is missing its terminal outbox event"
                    )
            await database.commit()
            return canonical

    @staticmethod
    def _model(record: ObservationResultRecord) -> ObservationResult:
        result = ObservationResult.model_validate(record.payload)
        if (
            result.observation_id != record.observation_id
            or result.organization_id != record.organization_id
            or result.session_id != record.session_id
            or result.execution_id != record.execution_id
            or result.correlation_id != record.correlation_id
            or result.source_event_id != record.source_event_id
            or result.status.value != record.status
            or result.fingerprint != record.fingerprint
            or result.execution_result_fingerprint
            != record.execution_result_fingerprint
        ):
            raise ObservationConflictError(
                "stored observation columns do not match payload"
            )
        return result

"""PostgreSQL adapter for operational workflow persistence."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, delete, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.operational.exceptions import (
    IdempotencyConflictError,
    OperationalConflictError,
)
from ecos.operational.models import OperationalSessionView
from ecos.operational.repository import (
    IdempotencyRecord,
    OperationalRepository,
    utc_now,
)
from ecos.session.orm import Base


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class OperationalSessionRecord(Base):
    """Persisted operational session aggregate."""

    __tablename__ = "operational_sessions"

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    approval_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    correlation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    session_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class OperationalIdempotencyRecord(Base):
    """Persisted idempotency result for operational commands."""

    __tablename__ = "operational_idempotency_keys"

    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    operation: Mapped[str] = mapped_column(String(80), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resource_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class PostgresOperationalRepository(OperationalRepository):
    """OperationalRepository backed by PostgreSQL and SQLAlchemy."""

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

    def save_session(
        self, session: OperationalSessionView, *, expected_version: int | None = None
    ) -> tuple[OperationalSessionView, int]:
        return _run(self._save_session(session, expected_version=expected_version))

    async def _save_session(
        self, session: OperationalSessionView, *, expected_version: int | None
    ) -> tuple[OperationalSessionView, int]:
        async with self._session_factory() as database:
            existing = await database.get(OperationalSessionRecord, session.session_id)
            if existing is None:
                if expected_version not in {None, 0}:
                    raise OperationalConflictError("session was modified concurrently")
                row = _session_row(session, version=1)
                database.add(OperationalSessionRecord(**row))
                await database.commit()
                return session, 1
            if expected_version is not None and existing.version != expected_version:
                raise OperationalConflictError("session was modified concurrently")
            next_version = existing.version + 1
            statement = (
                update(OperationalSessionRecord)
                .where(
                    OperationalSessionRecord.session_id == session.session_id,
                    OperationalSessionRecord.organization_id == session.organization_id,
                    OperationalSessionRecord.version == existing.version,
                )
                .values(**_session_row(session, version=next_version))
            )
            result = await database.execute(statement)
            if result.rowcount != 1:
                await database.rollback()
                raise OperationalConflictError("session was modified concurrently")
            await database.commit()
            return session, next_version

    def get_session(
        self, organization_id: UUID, session_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        return _run(self._get_session(organization_id, session_id))

    async def _get_session(
        self, organization_id: UUID, session_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(OperationalSessionRecord).where(
                    OperationalSessionRecord.organization_id == organization_id,
                    OperationalSessionRecord.session_id == session_id,
                )
            )
            return None if row is None else (_session_model(row), row.version)

    def list_sessions(
        self, organization_id: UUID, *, status: str | None = None
    ) -> list[OperationalSessionView]:
        return _run(self._list_sessions(organization_id, status=status))

    async def _list_sessions(
        self, organization_id: UUID, *, status: str | None
    ) -> list[OperationalSessionView]:
        statement = select(OperationalSessionRecord).where(
            OperationalSessionRecord.organization_id == organization_id
        )
        if status is not None:
            statement = statement.where(OperationalSessionRecord.status == status)
        statement = statement.order_by(OperationalSessionRecord.created_at.desc())
        async with self._session_factory() as database:
            rows = (await database.scalars(statement)).all()
        return [_session_model(row) for row in rows]

    def find_by_approval(
        self, organization_id: UUID, approval_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        return _run(self._find_by_approval(organization_id, approval_id))

    async def _find_by_approval(
        self, organization_id: UUID, approval_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(OperationalSessionRecord).where(
                    OperationalSessionRecord.organization_id == organization_id,
                    OperationalSessionRecord.approval_id == approval_id,
                )
            )
            return None if row is None else (_session_model(row), row.version)

    def find_by_execution(
        self, organization_id: UUID, execution_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        return _run(self._find_by_execution(organization_id, execution_id))

    async def _find_by_execution(
        self, organization_id: UUID, execution_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(OperationalSessionRecord).where(
                    OperationalSessionRecord.organization_id == organization_id,
                    OperationalSessionRecord.execution_id == execution_id,
                )
            )
            return None if row is None else (_session_model(row), row.version)

    def get_idempotency(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        operation: str,
        key: str,
    ) -> IdempotencyRecord | None:
        return _run(
            self._get_idempotency(
                organization_id=organization_id,
                user_id=user_id,
                operation=operation,
                key=key,
            )
        )

    async def _get_idempotency(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        operation: str,
        key: str,
    ) -> IdempotencyRecord | None:
        async with self._session_factory() as database:
            row = await database.get(
                OperationalIdempotencyRecord,
                {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "operation": operation,
                    "key": key,
                },
            )
            if row is None or row.expires_at <= utc_now():
                return None
            return _idempotency_model(row)

    def store_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        return _run(self._store_idempotency(record))

    async def _store_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        async with self._session_factory() as database:
            existing = await database.get(
                OperationalIdempotencyRecord,
                {
                    "organization_id": record.organization_id,
                    "user_id": record.user_id,
                    "operation": record.operation,
                    "key": record.key,
                },
            )
            if existing is not None:
                if existing.request_hash != record.request_hash:
                    raise IdempotencyConflictError()
                return _idempotency_model(existing)
            try:
                database.add(OperationalIdempotencyRecord(**asdict(record)))
                await database.commit()
            except IntegrityError as error:
                await database.rollback()
                raise OperationalConflictError(
                    "idempotent command is already running"
                ) from error
            return record

    def cleanup_expired_idempotency(self, *, now: datetime | None = None) -> int:
        return _run(self._cleanup_expired_idempotency(now=now or utc_now()))

    async def _cleanup_expired_idempotency(self, *, now: datetime) -> int:
        async with self._session_factory() as database:
            result = await database.execute(
                delete(OperationalIdempotencyRecord).where(
                    OperationalIdempotencyRecord.expires_at <= now
                )
            )
            await database.commit()
            return int(result.rowcount or 0)

    def interrupted_sessions(
        self, organization_id: UUID | None = None
    ) -> list[OperationalSessionView]:
        return _run(self._interrupted_sessions(organization_id))

    async def _interrupted_sessions(
        self, organization_id: UUID | None
    ) -> list[OperationalSessionView]:
        states = ("processing", "waiting_approval", "approved", "executing")
        statement = select(OperationalSessionRecord).where(
            OperationalSessionRecord.status.in_(states)
        )
        if organization_id is not None:
            statement = statement.where(
                OperationalSessionRecord.organization_id == organization_id
            )
        async with self._session_factory() as database:
            rows = (await database.scalars(statement)).all()
        return [_session_model(row) for row in rows]


def _session_row(session: OperationalSessionView, *, version: int) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "organization_id": session.organization_id,
        "created_by": session.created_by,
        "status": session.status.value,
        "objective": session.objective,
        "description": session.description,
        "approval_id": None
        if session.approval is None
        else session.approval.approval_id,
        "execution_id": None
        if session.execution is None
        else session.execution.execution_id,
        "correlation_id": session.correlation_id,
        "version": version,
        "session_json": session.model_dump(mode="json"),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _session_model(row: OperationalSessionRecord) -> OperationalSessionView:
    return OperationalSessionView.model_validate(row.session_json)


def _idempotency_model(row: OperationalIdempotencyRecord) -> IdempotencyRecord:
    return IdempotencyRecord(
        organization_id=row.organization_id,
        user_id=row.user_id,
        operation=row.operation,
        key=row.key,
        request_hash=row.request_hash,
        response_payload=row.response_payload,
        resource_id=row.resource_id,
        status_code=row.status_code,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )

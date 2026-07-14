"""PostgreSQL persistence for authenticated runtime checkpoints."""

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.runtime.repository import (
    DEFAULT_START_CLAIM_LEASE,
    RuntimeCheckpoint,
    RuntimeCheckpointConflictError,
    RuntimeCheckpointRepository,
    RuntimeCheckpointScopeError,
    RuntimeStartAcquisition,
    RuntimeStartClaim,
    RuntimeStartClaimStatus,
    RuntimeStartLeaseLostError,
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


class RuntimeStartClaimRecord(Base):
    """Atomic persistent ownership record for runtime startup."""

    __tablename__ = "runtime_start_claims"

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    objective: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
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
        lease_duration: timedelta = DEFAULT_START_CLAIM_LEASE,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_database_engine(database_url or "")
        self._session_factory = session_factory or create_session_factory(self.engine)
        if lease_duration <= timedelta(0):
            raise ValueError("runtime start claim lease duration must be positive")
        self._lease_duration = lease_duration
        self._clock = clock

    @property
    def start_claim_lease_duration(self) -> timedelta:
        return self._lease_duration

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

    def acquire_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        user_id: UUID,
        correlation_id: UUID,
        objective: str,
    ) -> RuntimeStartAcquisition:
        return _run(
            self._acquire_start_claim(
                organization_id=organization_id,
                session_id=session_id,
                user_id=user_id,
                correlation_id=correlation_id,
                objective=objective,
            )
        )

    async def _acquire_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        user_id: UUID,
        correlation_id: UUID,
        objective: str,
    ) -> RuntimeStartAcquisition:
        now = self._now()
        lease_expires_at = now + self._lease_duration
        async with self._session_factory() as database:
            inserted = await database.scalar(
                insert(RuntimeStartClaimRecord)
                .values(
                    session_id=session_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    objective=objective,
                    status=RuntimeStartClaimStatus.INITIALIZING.value,
                    attempt=1,
                    lease_expires_at=lease_expires_at,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["session_id"])
                .returning(RuntimeStartClaimRecord.session_id)
            )
            if inserted is not None:
                await database.commit()
                claim = RuntimeStartClaim(
                    session_id=session_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    objective=objective,
                    status=RuntimeStartClaimStatus.INITIALIZING,
                    attempt=1,
                    lease_expires_at=lease_expires_at,
                    created_at=now,
                    updated_at=now,
                )
                return RuntimeStartAcquisition(claim=claim, acquired=True)
            record = await database.scalar(
                select(RuntimeStartClaimRecord)
                .where(RuntimeStartClaimRecord.session_id == session_id)
                .with_for_update()
            )
            if record is None:
                raise RuntimeCheckpointConflictError(
                    "runtime start claim disappeared during acquisition"
                )
            if record.organization_id != organization_id:
                raise RuntimeCheckpointScopeError(
                    "runtime start claim is not available"
                )
            if record.objective != objective:
                raise RuntimeCheckpointConflictError(
                    "runtime start claim objective mismatch"
                )
            recoverable = record.status == RuntimeStartClaimStatus.FAILED.value or (
                record.status == RuntimeStartClaimStatus.INITIALIZING.value
                and record.lease_expires_at <= now
            )
            if not recoverable:
                return RuntimeStartAcquisition(
                    claim=_start_claim(record),
                    acquired=False,
                )
            record.user_id = user_id
            record.correlation_id = correlation_id
            record.status = RuntimeStartClaimStatus.INITIALIZING.value
            record.attempt += 1
            record.lease_expires_at = lease_expires_at
            record.updated_at = now
            await database.commit()
            return RuntimeStartAcquisition(
                claim=_start_claim(record),
                acquired=True,
            )

    def mark_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
        status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        return _run(
            self._mark_start_claim(
                organization_id=organization_id,
                session_id=session_id,
                expected_attempt=expected_attempt,
                expected_status=expected_status,
                status=status,
            )
        )

    async def _mark_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
        status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        now = self._now()
        async with self._session_factory() as database:
            record = await database.scalar(
                select(RuntimeStartClaimRecord)
                .where(RuntimeStartClaimRecord.session_id == session_id)
                .with_for_update()
            )
            if record is None:
                raise RuntimeStartLeaseLostError("runtime start claim is missing")
            if record.organization_id != organization_id:
                raise RuntimeCheckpointScopeError(
                    "runtime start claim is not available"
                )
            if record.attempt != expected_attempt:
                raise RuntimeStartLeaseLostError("runtime start claim attempt conflict")
            if record.status != expected_status.value:
                raise RuntimeStartLeaseLostError("runtime start claim status conflict")
            if (
                expected_status is not RuntimeStartClaimStatus.INITIALIZING
                or status
                not in {
                    RuntimeStartClaimStatus.STARTED,
                    RuntimeStartClaimStatus.FAILED,
                }
            ):
                raise RuntimeCheckpointConflictError(
                    "invalid runtime start claim transition"
                )
            if record.lease_expires_at <= now:
                raise RuntimeStartLeaseLostError("runtime start claim lease expired")
            record.status = status.value
            record.updated_at = now
            await database.commit()
            return _start_claim(record)

    def renew_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        return _run(
            self._renew_start_claim(
                organization_id=organization_id,
                session_id=session_id,
                expected_attempt=expected_attempt,
                expected_status=expected_status,
            )
        )

    async def _renew_start_claim(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
        expected_attempt: int,
        expected_status: RuntimeStartClaimStatus,
    ) -> RuntimeStartClaim:
        if expected_status is not RuntimeStartClaimStatus.INITIALIZING:
            raise RuntimeCheckpointConflictError(
                "only initializing runtime start claims can be renewed"
            )
        now = self._now()
        async with self._session_factory() as database:
            record = await database.scalar(
                select(RuntimeStartClaimRecord)
                .where(RuntimeStartClaimRecord.session_id == session_id)
                .with_for_update()
            )
            if record is None:
                raise RuntimeStartLeaseLostError("runtime start claim is missing")
            if record.organization_id != organization_id:
                raise RuntimeCheckpointScopeError(
                    "runtime start claim is not available"
                )
            if record.attempt != expected_attempt:
                raise RuntimeStartLeaseLostError("runtime start claim attempt conflict")
            if record.status != expected_status.value:
                raise RuntimeStartLeaseLostError("runtime start claim status conflict")
            if record.lease_expires_at <= now:
                raise RuntimeStartLeaseLostError("runtime start claim lease expired")
            record.lease_expires_at = now + self._lease_duration
            record.updated_at = now
            await database.commit()
            return _start_claim(record)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("runtime start claim clock must be timezone-aware")
        return now


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


def _start_claim(record: RuntimeStartClaimRecord) -> RuntimeStartClaim:
    return RuntimeStartClaim(
        session_id=record.session_id,
        organization_id=record.organization_id,
        user_id=record.user_id,
        correlation_id=record.correlation_id,
        objective=record.objective,
        status=record.status,
        attempt=record.attempt,
        lease_expires_at=record.lease_expires_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )

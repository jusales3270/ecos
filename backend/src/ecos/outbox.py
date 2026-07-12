"""Transactional outbox infrastructure for local/PostgreSQL deployments."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.events import Event, EventService
from ecos.observability.redaction import RedactionPolicy, default_redaction_policy
from ecos.session.orm import Base


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def utc_now() -> datetime:
    return datetime.now(UTC)


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    message_id: UUID
    organization_id: UUID
    actor_id: UUID | None
    correlation_id: UUID | None
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    status: OutboxStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None
    idempotency_key: str
    event_json: dict[str, Any]


class OutboxRecord(Base):
    """Append-only durable event publication queue."""

    __tablename__ = "transactional_outbox"

    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    correlation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class InMemoryOutboxRepository:
    """Thread-safe outbox for explicit local/test use."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._messages: dict[UUID, OutboxMessage] = {}
        self._keys: set[str] = set()

    def enqueue(self, message: OutboxMessage) -> OutboxMessage:
        with self._lock:
            if message.idempotency_key in self._keys:
                return message
            self._messages[message.message_id] = message
            self._keys.add(message.idempotency_key)
            return message

    def claim(self, *, limit: int, stale_after: timedelta) -> list[OutboxMessage]:
        del stale_after
        now = utc_now()
        claimed: list[OutboxMessage] = []
        with self._lock:
            for message in sorted(
                self._messages.values(), key=lambda item: item.created_at
            ):
                if len(claimed) >= limit:
                    break
                if message.status not in {OutboxStatus.PENDING, OutboxStatus.FAILED}:
                    continue
                if message.next_attempt_at > now:
                    continue
                updated = _replace_message(
                    message,
                    status=OutboxStatus.PROCESSING,
                    attempts=message.attempts + 1,
                )
                self._messages[message.message_id] = updated
                claimed.append(updated)
        return claimed

    def mark_delivered(self, message_id: UUID) -> None:
        with self._lock:
            message = self._messages[message_id]
            self._messages[message_id] = _replace_message(
                message, status=OutboxStatus.DELIVERED, delivered_at=utc_now()
            )

    def mark_failed(
        self, message_id: UUID, *, error: str, max_attempts: int, backoff: timedelta
    ) -> None:
        with self._lock:
            message = self._messages[message_id]
            terminal = message.attempts >= max_attempts
            self._messages[message_id] = _replace_message(
                message,
                status=OutboxStatus.FAILED if terminal else OutboxStatus.PENDING,
                next_attempt_at=utc_now() + backoff,
                last_error=error[:500],
            )

    def list(self, organization_id: UUID, *, limit: int = 100) -> list[OutboxMessage]:
        with self._lock:
            rows = [
                item
                for item in self._messages.values()
                if item.organization_id == organization_id
            ]
        return sorted(rows, key=lambda item: item.created_at, reverse=True)[:limit]

    def counts(self, organization_id: UUID | None = None) -> dict[str, int]:
        values = {status.value: 0 for status in OutboxStatus}
        with self._lock:
            messages = list(self._messages.values())
        for message in messages:
            if organization_id is None or message.organization_id == organization_id:
                values[message.status.value] += 1
        return values


class PostgresOutboxRepository:
    """PostgreSQL outbox with SKIP LOCKED claiming for multi-instance safety."""

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

    def claim(self, *, limit: int, stale_after: timedelta) -> list[OutboxMessage]:
        return _run(self._claim(limit=limit, stale_after=stale_after))

    async def _claim(
        self, *, limit: int, stale_after: timedelta
    ) -> list[OutboxMessage]:
        now = utc_now()
        stale_cutoff = now - stale_after
        async with self._session_factory() as database:
            statement = (
                select(OutboxRecord)
                .where(
                    OutboxRecord.status.in_(
                        (OutboxStatus.PENDING.value, OutboxStatus.FAILED.value)
                    ),
                    OutboxRecord.next_attempt_at <= now,
                )
                .order_by(OutboxRecord.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = (await database.scalars(statement)).all()
            processing = (
                await database.scalars(
                    select(OutboxRecord)
                    .where(
                        OutboxRecord.status == OutboxStatus.PROCESSING.value,
                        OutboxRecord.next_attempt_at <= stale_cutoff,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            rows = [*rows, *processing][:limit]
            for row in rows:
                row.status = OutboxStatus.PROCESSING.value
                row.attempts += 1
                row.next_attempt_at = now
            await database.commit()
            return [_message(row) for row in rows]

    def mark_delivered(self, message_id: UUID) -> None:
        _run(self._mark_delivered(message_id))

    async def _mark_delivered(self, message_id: UUID) -> None:
        async with self._session_factory() as database:
            await database.execute(
                update(OutboxRecord)
                .where(OutboxRecord.message_id == message_id)
                .values(status=OutboxStatus.DELIVERED.value, delivered_at=utc_now())
            )
            await database.commit()

    def mark_failed(
        self, message_id: UUID, *, error: str, max_attempts: int, backoff: timedelta
    ) -> None:
        _run(
            self._mark_failed(
                message_id, error=error, max_attempts=max_attempts, backoff=backoff
            )
        )

    async def _mark_failed(
        self, message_id: UUID, *, error: str, max_attempts: int, backoff: timedelta
    ) -> None:
        async with self._session_factory() as database:
            row = await database.get(OutboxRecord, message_id)
            if row is None:
                return
            terminal = row.attempts >= max_attempts
            row.status = (
                OutboxStatus.FAILED.value if terminal else OutboxStatus.PENDING.value
            )
            row.next_attempt_at = utc_now() + backoff
            row.last_error = error[:500]
            await database.commit()

    def list(self, organization_id: UUID, *, limit: int = 100) -> list[OutboxMessage]:
        return _run(self._list(organization_id, limit=limit))

    async def _list(self, organization_id: UUID, *, limit: int) -> list[OutboxMessage]:
        async with self._session_factory() as database:
            rows = (
                await database.scalars(
                    select(OutboxRecord)
                    .where(OutboxRecord.organization_id == organization_id)
                    .order_by(OutboxRecord.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return [_message(row) for row in rows]

    def counts(self, organization_id: UUID | None = None) -> dict[str, int]:
        return _run(self._counts(organization_id))

    async def _counts(self, organization_id: UUID | None) -> dict[str, int]:
        values = {status.value: 0 for status in OutboxStatus}
        async with self._session_factory() as database:
            statement = select(OutboxRecord.status, func.count()).group_by(
                OutboxRecord.status
            )
            if organization_id is not None:
                statement = statement.where(
                    OutboxRecord.organization_id == organization_id
                )
            rows = (await database.execute(statement)).all()
        for status, count in rows:
            values[str(status)] = int(count)
        return values


class OutboxService:
    """Deliver queued events into the existing Events and Observability pipeline."""

    def __init__(
        self,
        repository: InMemoryOutboxRepository | PostgresOutboxRepository,
        event_service: EventService,
        *,
        max_attempts: int,
        batch_size: int,
        redaction_policy: RedactionPolicy = default_redaction_policy,
    ) -> None:
        self._repository = repository
        self._event_service = event_service
        self._max_attempts = max_attempts
        self._batch_size = batch_size
        self._redaction_policy = redaction_policy

    @property
    def repository(self) -> InMemoryOutboxRepository | PostgresOutboxRepository:
        return self._repository

    def process_once(self) -> dict[str, int]:
        delivered = 0
        failed = 0
        messages = self._repository.claim(
            limit=self._batch_size, stale_after=timedelta(minutes=5)
        )
        for message in messages:
            try:
                envelope = self._event_service.publish(
                    Event.model_validate(message.event_json)
                )
                self._event_service.dispatch(envelope)
                self._repository.mark_delivered(message.message_id)
                delivered += 1
            except Exception as error:
                failed += 1
                self._repository.mark_failed(
                    message.message_id,
                    error=self._redaction_policy.redact(str(error)),
                    max_attempts=self._max_attempts,
                    backoff=timedelta(seconds=min(300, 2 ** max(message.attempts, 1))),
                )
        return {"claimed": len(messages), "delivered": delivered, "failed": failed}


def message_from_event(
    event: Event,
    *,
    actor_id: UUID | None,
    aggregate_type: str,
    aggregate_id: str,
    redaction_policy: RedactionPolicy = default_redaction_policy,
) -> OutboxMessage:
    payload = redaction_policy.redact(event.payload)
    event_json = event.model_copy(update={"payload": payload}).model_dump(mode="json")
    key_material = redaction_policy.canonical_json(
        {
            "organization_id": str(event.organization_id),
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event.event_type.value,
            "event_id": str(event.event_id),
        }
    )
    return OutboxMessage(
        message_id=uuid4(),
        organization_id=event.organization_id,
        actor_id=actor_id,
        correlation_id=event.correlation_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event.event_type.value,
        payload=payload,
        status=OutboxStatus.PENDING,
        attempts=0,
        next_attempt_at=utc_now(),
        last_error=None,
        created_at=utc_now(),
        delivered_at=None,
        idempotency_key=sha256(key_material.encode("utf-8")).hexdigest(),
        event_json=event_json,
    )


def _message(row: OutboxRecord) -> OutboxMessage:
    return OutboxMessage(
        message_id=row.message_id,
        organization_id=row.organization_id,
        actor_id=row.actor_id,
        correlation_id=row.correlation_id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        payload=row.payload,
        status=OutboxStatus(row.status),
        attempts=row.attempts,
        next_attempt_at=row.next_attempt_at,
        last_error=row.last_error,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
        idempotency_key=row.idempotency_key,
        event_json=row.event_json,
    )


def _replace_message(message: OutboxMessage, **changes: Any) -> OutboxMessage:
    values = {field: getattr(message, field) for field in message.__dataclass_fields__}
    values.update(changes)
    return OutboxMessage(**values)

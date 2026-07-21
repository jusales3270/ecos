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
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import DateTime, Integer, String, Text, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
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
    outbox_id: UUID
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
    available_at: datetime
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None
    published_at: datetime | None
    idempotency_key: str
    event_json: dict[str, Any]
    event_id: UUID
    schema_version: int
    session_id: UUID | None
    execution_id: UUID | None
    observation_id: UUID | None
    learning_id: UUID | None
    memory_id: UUID | None
    causation_id: UUID | None
    claim_owner: str | None
    claim_expires_at: datetime | None
    version: int


class OutboxRecord(Base):
    """Append-only durable event publication queue."""

    __tablename__ = "transactional_outbox"

    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    outbox_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, unique=True
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
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, unique=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    execution_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    observation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    learning_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    memory_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    causation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    claim_owner: Mapped[str | None] = mapped_column(String(200))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class OutboxConflictError(RuntimeError):
    """Raised when a stable event identity is reused with divergent content."""


class InMemoryOutboxRepository:
    """Thread-safe outbox for explicit local/test use."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._messages: dict[UUID, OutboxMessage] = {}
        self._keys: set[str] = set()

    def enqueue(self, message: OutboxMessage) -> OutboxMessage:
        with self._lock:
            if message.idempotency_key in self._keys:
                existing = next(
                    item
                    for item in self._messages.values()
                    if item.idempotency_key == message.idempotency_key
                )
                if existing.event_json != message.event_json:
                    raise OutboxConflictError(
                        "idempotency key conflicts with different event content"
                    )
                return existing
            same_event = next(
                (
                    item
                    for item in self._messages.values()
                    if item.event_id == message.event_id
                ),
                None,
            )
            if same_event is not None:
                if same_event.event_json != message.event_json:
                    raise OutboxConflictError(
                        "event_id conflicts with different event content"
                    )
                return same_event
            self._messages[message.message_id] = message
            self._keys.add(message.idempotency_key)
            return message

    def claim(
        self, *, limit: int, stale_after: timedelta, owner: str = "in-memory"
    ) -> list[OutboxMessage]:
        now = utc_now()
        claimed: list[OutboxMessage] = []
        with self._lock:
            for message in sorted(
                self._messages.values(), key=lambda item: item.created_at
            ):
                if len(claimed) >= limit:
                    break
                recoverable_claim = (
                    message.status is OutboxStatus.PROCESSING
                    and message.claim_expires_at is not None
                    and message.claim_expires_at <= now
                )
                if message.status is not OutboxStatus.PENDING and not recoverable_claim:
                    continue
                if message.available_at > now:
                    continue
                updated = _replace_message(
                    message,
                    status=OutboxStatus.PROCESSING,
                    attempts=message.attempts + 1,
                    claim_owner=owner,
                    claim_expires_at=now + stale_after,
                    version=message.version + 1,
                )
                self._messages[message.message_id] = updated
                claimed.append(updated)
        return claimed

    def mark_delivered(
        self, message_id: UUID, *, owner: str | None = None, version: int | None = None
    ) -> bool:
        with self._lock:
            message = self._messages[message_id]
            if (owner is not None and message.claim_owner != owner) or (
                version is not None and message.version != version
            ):
                return False
            self._messages[message_id] = _replace_message(
                message,
                status=OutboxStatus.DELIVERED,
                delivered_at=utc_now(),
                published_at=utc_now(),
                claim_owner=None,
                claim_expires_at=None,
                version=message.version + 1,
            )
            return True

    def mark_failed(
        self,
        message_id: UUID,
        *,
        error: str,
        max_attempts: int,
        backoff: timedelta,
        owner: str | None = None,
        version: int | None = None,
    ) -> bool:
        with self._lock:
            message = self._messages[message_id]
            if (owner is not None and message.claim_owner != owner) or (
                version is not None and message.version != version
            ):
                return False
            terminal = message.attempts >= max_attempts
            available_at = utc_now() + backoff
            self._messages[message_id] = _replace_message(
                message,
                status=OutboxStatus.FAILED if terminal else OutboxStatus.PENDING,
                next_attempt_at=available_at,
                available_at=available_at,
                last_error=error[:500],
                claim_owner=None,
                claim_expires_at=None,
                version=message.version + 1,
            )
            return True

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

    def claim(
        self, *, limit: int, stale_after: timedelta, owner: str = "postgres"
    ) -> list[OutboxMessage]:
        return _run(self._claim(limit=limit, stale_after=stale_after, owner=owner))

    async def _claim(
        self, *, limit: int, stale_after: timedelta, owner: str
    ) -> list[OutboxMessage]:
        now = utc_now()
        async with self._session_factory() as database:
            statement = (
                select(OutboxRecord)
                .where(
                    OutboxRecord.status == OutboxStatus.PENDING.value,
                    OutboxRecord.available_at <= now,
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
                        OutboxRecord.claim_expires_at <= now,
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
                row.available_at = now
                row.claim_owner = owner
                row.claim_expires_at = now + stale_after
                row.version += 1
            await database.commit()
            return [_message(row) for row in rows]

    def mark_delivered(
        self, message_id: UUID, *, owner: str | None = None, version: int | None = None
    ) -> bool:
        return _run(self._mark_delivered(message_id, owner=owner, version=version))

    async def _mark_delivered(
        self, message_id: UUID, *, owner: str | None, version: int | None
    ) -> bool:
        async with self._session_factory() as database:
            statement = update(OutboxRecord).where(
                OutboxRecord.message_id == message_id,
                OutboxRecord.status == OutboxStatus.PROCESSING.value,
            )
            if owner is not None:
                statement = statement.where(OutboxRecord.claim_owner == owner)
            if version is not None:
                statement = statement.where(OutboxRecord.version == version)
            result = await database.execute(
                statement.values(
                    status=OutboxStatus.DELIVERED.value,
                    delivered_at=utc_now(),
                    published_at=utc_now(),
                    claim_owner=None,
                    claim_expires_at=None,
                    version=OutboxRecord.version + 1,
                )
            )
            await database.commit()
            return result.rowcount == 1

    def mark_failed(
        self,
        message_id: UUID,
        *,
        error: str,
        max_attempts: int,
        backoff: timedelta,
        owner: str | None = None,
        version: int | None = None,
    ) -> bool:
        return _run(
            self._mark_failed(
                message_id,
                error=error,
                max_attempts=max_attempts,
                backoff=backoff,
                owner=owner,
                version=version,
            )
        )

    async def _mark_failed(
        self,
        message_id: UUID,
        *,
        error: str,
        max_attempts: int,
        backoff: timedelta,
        owner: str | None,
        version: int | None,
    ) -> bool:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(OutboxRecord)
                .where(OutboxRecord.message_id == message_id)
                .with_for_update()
            )
            if row is None:
                return False
            if row.status != OutboxStatus.PROCESSING.value:
                return False
            if owner is not None and row.claim_owner != owner:
                return False
            if version is not None and row.version != version:
                return False
            terminal = row.attempts >= max_attempts
            row.status = (
                OutboxStatus.FAILED.value if terminal else OutboxStatus.PENDING.value
            )
            row.next_attempt_at = utc_now() + backoff
            row.available_at = row.next_attempt_at
            row.last_error = error[:500]
            row.claim_owner = None
            row.claim_expires_at = None
            row.version += 1
            await database.commit()
            return True

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
        self._owner = f"outbox-{uuid4()}"
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    @property
    def repository(self) -> InMemoryOutboxRepository | PostgresOutboxRepository:
        return self._repository

    def process_once(self) -> dict[str, int]:
        delivered = 0
        failed = 0
        messages = self._repository.claim(
            limit=self._batch_size,
            stale_after=timedelta(minutes=5),
            owner=self._owner,
        )
        for message in messages:
            try:
                envelope = self._event_service.publish(
                    Event.model_validate(message.event_json)
                )
                self._event_service.dispatch(envelope)
                if not self._repository.mark_delivered(
                    message.message_id, owner=self._owner, version=message.version
                ):
                    raise RuntimeError("outbox claim was lost before publication ack")
                delivered += 1
            except Exception as error:
                failed += 1
                self._repository.mark_failed(
                    message.message_id,
                    error=self._redaction_policy.redact(str(error)),
                    max_attempts=self._max_attempts,
                    backoff=timedelta(seconds=min(300, 2 ** max(message.attempts, 1))),
                    owner=self._owner,
                    version=message.version,
                )
        return {"claimed": len(messages), "delivered": delivered, "failed": failed}

    def start(self, *, interval: float = 1.0) -> None:
        """Start one non-blocking dispatcher loop for this service instance."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(interval))

    async def stop(self) -> None:
        """Stop the dispatcher after its current bounded drain attempt."""
        if self._task is None:
            return
        assert self._stop_event is not None
        self._stop_event.set()
        await self._task
        self._task = None
        self._stop_event = None

    async def _run_loop(self, interval: float) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.process_once)
            except Exception:
                # A transient repository outage must not permanently stop draining.
                pass
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except TimeoutError:
                continue


def message_from_event(
    event: Event,
    *,
    actor_id: UUID | None,
    aggregate_type: str,
    aggregate_id: str,
    execution_id: UUID | None = None,
    observation_id: UUID | None = None,
    learning_id: UUID | None = None,
    memory_id: UUID | None = None,
    redaction_policy: RedactionPolicy = default_redaction_policy,
) -> OutboxMessage:
    payload = _redact_outbox_payload(redaction_policy.redact(event.payload))
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
    outbox_id = uuid4()
    now = utc_now()
    return OutboxMessage(
        message_id=outbox_id,
        outbox_id=outbox_id,
        organization_id=event.organization_id,
        actor_id=actor_id,
        correlation_id=event.correlation_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event.event_type.value,
        payload=payload,
        status=OutboxStatus.PENDING,
        attempts=0,
        next_attempt_at=now,
        available_at=now,
        last_error=None,
        created_at=now,
        delivered_at=None,
        published_at=None,
        idempotency_key=sha256(key_material.encode("utf-8")).hexdigest(),
        event_json=event_json,
        event_id=event.event_id,
        schema_version=event.schema_version,
        session_id=event.session_id,
        execution_id=execution_id,
        observation_id=observation_id,
        learning_id=learning_id,
        memory_id=memory_id,
        causation_id=event.causation_id,
        claim_owner=None,
        claim_expires_at=None,
        version=1,
    )


def _redact_outbox_payload(value: Any, *, key: str | None = None) -> Any:
    forbidden = {"artifact_content", "artifacts", "memory", "memory_content"}
    if key is not None and key.lower() in forbidden:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            item_key: _redact_outbox_payload(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_outbox_payload(item) for item in value]
    return value


def terminal_event_id(
    *, organization_id: UUID, aggregate_type: str, aggregate_id: UUID, event_type: str
) -> UUID:
    """Return the stable identity of one logical terminal aggregate event."""
    return uuid5(
        NAMESPACE_URL,
        f"ecos:{organization_id}:{aggregate_type}:{aggregate_id}:{event_type}",
    )


def validate_terminal_event(
    event: Event,
    *,
    organization_id: UUID,
    session_id: UUID,
    correlation_id: UUID,
    event_type: str,
) -> None:
    """Reject a terminal event whose identity scope diverges from its aggregate."""
    if any(
        (
            event.organization_id != organization_id,
            event.session_id != session_id,
            event.correlation_id != correlation_id,
            event.event_type.value != event_type,
        )
    ):
        raise OutboxConflictError(
            "terminal event scope or type conflicts with aggregate"
        )


async def append_outbox_event(
    database: AsyncSession,
    event: Event,
    *,
    aggregate_type: str,
    aggregate_id: UUID,
    actor_id: UUID | None = None,
    execution_id: UUID | None = None,
    observation_id: UUID | None = None,
    learning_id: UUID | None = None,
    memory_id: UUID | None = None,
) -> OutboxMessage:
    """Append or validate one event using the aggregate's current transaction."""
    message = message_from_event(
        event,
        actor_id=actor_id,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        execution_id=execution_id,
        observation_id=observation_id,
        learning_id=learning_id,
        memory_id=memory_id,
    )
    values = {field: getattr(message, field) for field in message.__dataclass_fields__}
    values["status"] = message.status.value
    inserted = await database.scalar(
        postgresql_insert(OutboxRecord)
        .values(**values)
        .on_conflict_do_nothing()
        .returning(OutboxRecord.message_id)
    )
    if inserted is not None:
        return message
    existing = await database.scalar(
        select(OutboxRecord).where(OutboxRecord.event_id == event.event_id)
    )
    if existing is None:
        logical = await database.scalar(
            select(OutboxRecord).where(
                OutboxRecord.aggregate_type == aggregate_type,
                OutboxRecord.aggregate_id == str(aggregate_id),
                OutboxRecord.event_type == event.event_type.value,
            )
        )
        if logical is not None:
            raise OutboxConflictError(
                "terminal aggregate event conflicts with a different event_id"
            )
    if existing is None or any(
        (
            existing.organization_id != event.organization_id,
            existing.aggregate_type != aggregate_type,
            existing.aggregate_id != str(aggregate_id),
            existing.event_type != event.event_type.value,
            existing.event_json != message.event_json,
        )
    ):
        raise OutboxConflictError(
            "event_id conflicts with a different aggregate or event payload"
        )
    return _message(existing)


def _message(row: OutboxRecord) -> OutboxMessage:
    return OutboxMessage(
        message_id=row.message_id,
        outbox_id=row.outbox_id,
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
        available_at=row.available_at,
        last_error=row.last_error,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
        published_at=row.published_at,
        idempotency_key=row.idempotency_key,
        event_json=row.event_json,
        event_id=row.event_id,
        schema_version=row.schema_version,
        session_id=row.session_id,
        execution_id=row.execution_id,
        observation_id=row.observation_id,
        learning_id=row.learning_id,
        memory_id=row.memory_id,
        causation_id=row.causation_id,
        claim_owner=row.claim_owner,
        claim_expires_at=row.claim_expires_at,
        version=row.version,
    )


def _replace_message(message: OutboxMessage, **changes: Any) -> OutboxMessage:
    values = {field: getattr(message, field) for field in message.__dataclass_fields__}
    values.update(changes)
    return OutboxMessage(**values)

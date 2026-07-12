"""PostgreSQL adapters for persistent events and observability records."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.events.models import Event
from ecos.observability.exceptions import (
    AppendFailedError,
    AuditConflictError,
    ConflictingEventError,
    EventStoreUnavailableError,
)
from ecos.observability.models import (
    AlertSignal,
    AuditRecord,
    EventQuery,
    HealthSnapshot,
    HealthStatus,
    MetricRecord,
    StructuredLogRecord,
    TraceRecord,
    TraceSpan,
)
from ecos.observability.repository import (
    AuditRepository,
    EventStore,
    ObservabilityRepository,
    event_fingerprint,
)
from ecos.session.orm import Base


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class EventRecord(Base):
    """Persisted immutable event record."""

    __tablename__ = "event_records"

    stored_sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        unique=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    correlation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        index=True,
    )
    causation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    source_component: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True
    )
    source_version: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    stored_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False
    )
    classification: Mapped[str] = mapped_column(String(50), nullable=False)
    security_level: Mapped[str] = mapped_column(String(50), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    retention_class: Mapped[str] = mapped_column(String(50), nullable=False)
    integrity_status: Mapped[str] = mapped_column(String(50), nullable=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AuditRecordRow(Base):
    __tablename__ = "audit_records"

    audit_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    source_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    plan_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    correlation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    timestamp: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    component: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class MetricRecordRow(Base):
    __tablename__ = "metric_records"

    metric_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    source_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    occurred_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class TraceRecordRow(Base):
    __tablename__ = "trace_records"

    trace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    correlation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class TraceSpanRow(Base):
    __tablename__ = "trace_spans"

    span_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    trace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), index=True)
    component: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class StructuredLogRecordRow(Base):
    __tablename__ = "structured_log_records"

    log_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    timestamp: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AlertRecordRow(Base):
    __tablename__ = "alert_records"

    alert_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    source_event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class HealthSnapshotRow(Base):
    __tablename__ = "health_snapshot_records"

    health_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    component: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    checked_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PostgresEventStore(EventStore):
    """Append-only PostgreSQL EventStore using existing SQLAlchemy config."""

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

    def append(self, event: Event):
        return _run(self._append(event))

    async def _append(self, event: Event):
        fingerprint = event_fingerprint(event)
        async with self._session_factory() as database:
            existing = await database.scalar(
                select(EventRecord).where(EventRecord.event_id == event.event_id)
            )
            if existing is not None:
                if existing.fingerprint == fingerprint:
                    return self._stored(existing)
                raise ConflictingEventError(
                    "event_id already exists with different content"
                )
            sequence = (
                await database.scalar(
                    select(EventRecord.stored_sequence).order_by(
                        EventRecord.stored_sequence.desc()
                    )
                )
                or 0
            ) + 1
            row = EventRecord(
                stored_sequence=sequence,
                event_id=event.event_id,
                event_type=event.event_type.value,
                category=event.category.value,
                priority=event.priority.value,
                organization_id=event.organization_id,
                session_id=event.session_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                source_component=event.source_component,
                source_version=event.source_version,
                occurred_at=event.occurred_at,
                stored_at=event.occurred_at,
                event_version=event.event_version,
                schema_version=event.schema_version,
                payload=event.payload,
                metadata_json=event.metadata.model_dump(mode="json"),
                classification=event.classification.value,
                security_level=event.security_level.value,
                fingerprint=fingerprint,
                retention_class="active",
                integrity_status="valid",
                event_json=event.model_dump(mode="json"),
            )
            try:
                database.add(row)
                await database.commit()
            except IntegrityError as error:
                await database.rollback()
                raise ConflictingEventError("event append conflicted") from error
            except SQLAlchemyError as error:
                await database.rollback()
                raise AppendFailedError("event append failed") from error
            return self._stored(row)

    def append_many(self, events: list[Event]):
        return _run(self._append_many(events))

    async def _append_many(self, events: list[Event]):
        async with self._session_factory() as database:
            try:
                stored = []
                for event in events:
                    stored.append(await self._append(event))
                await database.commit()
                return stored
            except Exception:
                await database.rollback()
                raise

    def get_by_id(self, event_id: UUID):
        return _run(self._get_by_id(event_id))

    async def _get_by_id(self, event_id: UUID):
        async with self._session_factory() as database:
            row = await database.scalar(
                select(EventRecord).where(EventRecord.event_id == event_id)
            )
            return None if row is None else self._stored(row)

    def exists(self, event_id: UUID) -> bool:
        return self.get_by_id(event_id) is not None

    def query(self, filters: EventQuery):
        return _run(self._query(filters))

    async def _query(self, filters: EventQuery):
        statement = select(EventRecord).where(
            EventRecord.organization_id == filters.organization_id
        )
        if filters.session_id is not None:
            statement = statement.where(EventRecord.session_id == filters.session_id)
        if filters.correlation_id is not None:
            statement = statement.where(
                EventRecord.correlation_id == filters.correlation_id
            )
        if filters.event_types:
            statement = statement.where(EventRecord.event_type.in_(filters.event_types))
        if filters.categories:
            statement = statement.where(EventRecord.category.in_(filters.categories))
        if filters.source_component:
            statement = statement.where(
                EventRecord.source_component == filters.source_component
            )
        if filters.start_time is not None:
            statement = statement.where(EventRecord.occurred_at >= filters.start_time)
        if filters.end_time is not None:
            statement = statement.where(EventRecord.occurred_at <= filters.end_time)
        if filters.sequence_after is not None:
            statement = statement.where(
                EventRecord.stored_sequence > filters.sequence_after
            )
        if filters.sequence_from is not None:
            statement = statement.where(
                EventRecord.stored_sequence >= filters.sequence_from
            )
        if filters.sequence_to is not None:
            statement = statement.where(
                EventRecord.stored_sequence <= filters.sequence_to
            )
        statement = statement.order_by(
            EventRecord.stored_sequence,
            EventRecord.occurred_at,
            EventRecord.event_id,
        ).limit(filters.limit)
        async with self._session_factory() as database:
            rows = (await database.scalars(statement)).all()
            return [self._stored(row) for row in rows]

    def count(self, filters: EventQuery | None = None) -> int:
        return (
            len(self.query(filters)) if filters is not None else self.latest_sequence()
        )

    def health(self) -> HealthSnapshot:
        try:
            self.latest_sequence()
        except SQLAlchemyError as error:
            raise EventStoreUnavailableError(
                "event store health check failed"
            ) from error
        return HealthSnapshot(
            component="EventStore", status=HealthStatus.HEALTHY, availability=True
        )

    def latest_sequence(self) -> int:
        return _run(self._latest_sequence())

    async def _latest_sequence(self) -> int:
        async with self._session_factory() as database:
            return (
                await database.scalar(
                    select(EventRecord.stored_sequence).order_by(
                        EventRecord.stored_sequence.desc()
                    )
                )
                or 0
            )

    @staticmethod
    def _stored(row: EventRecord):
        from ecos.observability.models import StoredEvent

        return StoredEvent(
            event=Event.model_validate(row.event_json),
            stored_sequence=row.stored_sequence,
            stored_at=row.stored_at,
            fingerprint=row.fingerprint,
            retention_class=row.retention_class,
            integrity_status=row.integrity_status,
            safe_metadata={"store": "postgres"},
        )


class PostgresAuditRepository(AuditRepository):
    """Append-only PostgreSQL audit repository."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_database_engine(database_url)
        self._session_factory = create_session_factory(self.engine)

    def append(self, record: AuditRecord) -> AuditRecord:
        return _run(self._append(record))

    async def _append(self, record: AuditRecord) -> AuditRecord:
        async with self._session_factory() as database:
            if await database.get(AuditRecordRow, record.audit_id):
                return record
            try:
                database.add(
                    AuditRecordRow(
                        audit_id=record.audit_id,
                        source_event_id=record.source_event_id,
                        organization_id=record.organization_id,
                        session_id=record.session_id,
                        plan_id=record.plan_id,
                        correlation_id=record.correlation_id,
                        timestamp=record.timestamp,
                        sequence=record.sequence,
                        component=record.component,
                        action=record.action,
                        fingerprint=record.fingerprint,
                        record_json=record.model_dump(mode="json"),
                    )
                )
                await database.commit()
            except IntegrityError as error:
                await database.rollback()
                raise AuditConflictError("audit append conflicted") from error
        return record

    def append_many(self, records: list[AuditRecord]) -> list[AuditRecord]:
        return [self.append(record) for record in records]

    def get_by_id(self, audit_id: UUID) -> AuditRecord | None:
        return _run(self._get_by_id(audit_id))

    async def _get_by_id(self, audit_id: UUID) -> AuditRecord | None:
        async with self._session_factory() as database:
            row = await database.get(AuditRecordRow, audit_id)
            return None if row is None else AuditRecord.model_validate(row.record_json)

    def list_by_organization(self, organization_id: UUID, *, limit: int = 100):
        return _run(self._list_by_organization(organization_id, limit))

    async def _list_by_organization(self, organization_id: UUID, limit: int):
        async with self._session_factory() as database:
            rows = (
                await database.scalars(
                    select(AuditRecordRow)
                    .where(AuditRecordRow.organization_id == organization_id)
                    .order_by(AuditRecordRow.sequence, AuditRecordRow.timestamp)
                    .limit(limit)
                )
            ).all()
            return [AuditRecord.model_validate(row.record_json) for row in rows]

    def verify_integrity(self, organization_id: UUID) -> bool:
        return all(
            record.fingerprint
            for record in self.list_by_organization(organization_id, limit=1000)
        )

    def health(self) -> HealthSnapshot:
        return HealthSnapshot(
            component="AuditRepository", status=HealthStatus.HEALTHY, availability=True
        )


class PostgresObservabilityRepository(ObservabilityRepository):
    """PostgreSQL repository for projected observability records."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_database_engine(database_url)
        self._session_factory = create_session_factory(self.engine)

    def append_metric(self, record: MetricRecord) -> MetricRecord:
        _run(
            self._insert(
                MetricRecordRow, record.metric_id, record.model_dump(mode="json")
            )
        )
        return record

    def append_log(self, record: StructuredLogRecord) -> StructuredLogRecord:
        _run(
            self._insert(
                StructuredLogRecordRow, record.log_id, record.model_dump(mode="json")
            )
        )
        return record

    def append_trace(self, record: TraceRecord) -> TraceRecord:
        _run(
            self._insert(
                TraceRecordRow, record.trace_id, record.model_dump(mode="json")
            )
        )
        for span in record.spans:
            _run(self._insert_span(span))
        return record

    def append_alert(self, record: AlertSignal) -> AlertSignal:
        _run(
            self._insert(
                AlertRecordRow, record.alert_id, record.model_dump(mode="json")
            )
        )
        return record

    def append_health(self, record: HealthSnapshot) -> HealthSnapshot:
        _run(
            self._insert(
                HealthSnapshotRow, record.health_id, record.model_dump(mode="json")
            )
        )
        return record

    async def _insert(
        self, row_type: type[Base], record_id: UUID, payload: dict[str, Any]
    ) -> None:
        async with self._session_factory() as database:
            if await database.get(row_type, record_id):
                return
            database.add(self._row(row_type, payload))
            await database.commit()

    async def _insert_span(self, span: TraceSpan) -> None:
        async with self._session_factory() as database:
            if await database.get(TraceSpanRow, span.span_id):
                return
            database.add(
                TraceSpanRow(
                    span_id=span.span_id,
                    trace_id=span.trace_id,
                    component=span.component,
                    operation=span.operation,
                    record_json=span.model_dump(mode="json"),
                )
            )
            await database.commit()

    def health(self) -> HealthSnapshot:
        return HealthSnapshot(
            component="ObservabilityRepository",
            status=HealthStatus.HEALTHY,
            availability=True,
        )

    @staticmethod
    def _row(row_type: type[Base], payload: dict[str, Any]) -> Base:
        if row_type is MetricRecordRow:
            return MetricRecordRow(
                metric_id=UUID(payload["metric_id"]),
                organization_id=UUID(payload["organization_id"]),
                source_event_id=UUID(payload["source_event_id"]),
                metric_name=payload["metric_name"],
                occurred_at=_datetime(payload["occurred_at"]),
                value=payload["value"],
                record_json=payload,
            )
        if row_type is StructuredLogRecordRow:
            return StructuredLogRecordRow(
                log_id=UUID(payload["log_id"]),
                organization_id=UUID(payload["organization_id"]),
                timestamp=_datetime(payload["timestamp"]),
                severity=payload["severity"],
                component=payload["component"],
                record_json=payload,
            )
        if row_type is TraceRecordRow:
            return TraceRecordRow(
                trace_id=UUID(payload["trace_id"]),
                organization_id=UUID(payload["organization_id"]),
                correlation_id=UUID(payload["correlation_id"]),
                session_id=None
                if payload.get("session_id") is None
                else UUID(payload["session_id"]),
                record_json=payload,
            )
        if row_type is AlertRecordRow:
            return AlertRecordRow(
                alert_id=UUID(payload["alert_id"]),
                rule_id=payload["rule_id"],
                organization_id=UUID(payload["organization_id"]),
                source_event_id=UUID(payload["source_event_id"]),
                status=payload["status"],
                record_json=payload,
            )
        return HealthSnapshotRow(
            health_id=UUID(payload["health_id"]),
            component=payload["component"],
            checked_at=_datetime(payload["checked_at"]),
            status=payload["status"],
            record_json=payload,
        )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError("expected datetime-compatible value")

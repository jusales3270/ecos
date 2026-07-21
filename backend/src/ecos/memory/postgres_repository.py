"""PostgreSQL implementation of the memory repository contract."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ecos.database import create_database_engine, create_session_factory
from ecos.events import Event, EventMetadata, EventPriority, EventType
from ecos.memory.models import (
    MemoryObject,
    MemoryType,
    ValidatedMemoryStoreResult,
    ValidatedMemoryWrite,
    utc_now,
)
from ecos.memory.orm import MemoryRecord
from ecos.memory.repository import MemoryRepository, ValidatedMemoryConflictError
from ecos.outbox import append_outbox_event, terminal_event_id


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    """Run async persistence while preserving the synchronous public contract."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class PostgresMemoryRepository(MemoryRepository):
    """Persist memory objects in PostgreSQL through SQLAlchemy."""

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

    def store(self, memory: MemoryObject) -> MemoryObject:
        return _run(self._store(memory))

    async def _store(self, memory: MemoryObject) -> MemoryObject:
        async with self._session_factory() as database:
            database.add(self._record(memory))
            await database.commit()
        return memory

    def store_validated(
        self, write: ValidatedMemoryWrite
    ) -> ValidatedMemoryStoreResult:
        with self._sync_lock:
            return _run(self._store_validated(write))

    async def _store_validated(
        self, write: ValidatedMemoryWrite
    ) -> ValidatedMemoryStoreResult:
        now = utc_now()
        memory = MemoryObject(
            id=uuid4(),
            organization_id=write.organization_id,
            type=write.memory_type,
            title=f"Validated learning {write.candidate_id}"[:200],
            description=json.dumps(write.content, sort_keys=True, default=str)[:2000],
            tags=list(write.tags),
            confidence=write.confidence,
            source="learning",
            session_id=write.session_id,
            execution_id=write.execution_id,
            correlation_id=write.correlation_id,
            observation_id=write.observation_id,
            learning_id=write.learning_id,
            learning_candidate_id=write.candidate_id,
            proposal_id=write.proposal_id,
            policy_version=write.policy_version,
            validation_status=write.validation_status,
            evidence_references=list(write.evidence_references),
            source_references=list(write.source_references),
            validated_write_fingerprint=write.fingerprint,
            version=1,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as database:
            inserted = await database.scalar(
                insert(MemoryRecord)
                .values(self._record_values(memory))
                .on_conflict_do_nothing(
                    index_elements=["organization_id", "proposal_id"],
                    index_where=MemoryRecord.proposal_id.is_not(None),
                )
                .returning(MemoryRecord.id)
            )
            record = await database.scalar(
                select(MemoryRecord).where(
                    MemoryRecord.organization_id == write.organization_id,
                    MemoryRecord.proposal_id == write.proposal_id,
                )
            )
            if record is None:
                raise ValidatedMemoryConflictError("validated memory disappeared")
            existing = self._model(record)
            if not self._matches_write(existing, write):
                raise ValidatedMemoryConflictError(
                    "proposal_id conflicts with validated fingerprint or provenance"
                )
            if inserted is not None:
                event = Event(
                    id=terminal_event_id(
                        organization_id=write.organization_id,
                        aggregate_type="memory",
                        aggregate_id=existing.id,
                        event_type=EventType.MEMORY_UPDATED.value,
                    ),
                    event_type=EventType.MEMORY_UPDATED,
                    source="learning",
                    organization_id=write.organization_id,
                    session_id=write.session_id,
                    payload={
                        "organization_id": str(write.organization_id),
                        "memory_id": str(existing.id),
                        "proposal_id": str(write.proposal_id),
                        "learning_id": str(write.learning_id),
                    },
                    metadata=EventMetadata(correlation_id=write.correlation_id),
                    priority=EventPriority.NORMAL,
                )
                await append_outbox_event(
                    database,
                    event,
                    aggregate_type="memory",
                    aggregate_id=existing.id,
                    execution_id=write.execution_id,
                    observation_id=write.observation_id,
                    learning_id=write.learning_id,
                    memory_id=existing.id,
                )
            await database.commit()
        return ValidatedMemoryStoreResult(memory=existing, created=inserted is not None)

    def get(self, memory_id: UUID) -> MemoryObject | None:
        return _run(self._get(memory_id))

    async def _get(self, memory_id: UUID) -> MemoryObject | None:
        async with self._session_factory() as database:
            record = await database.get(MemoryRecord, memory_id)
            return None if record is None else self._model(record)

    def search(
        self,
        query: str,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        return _run(
            self._list(
                organization_id=organization_id,
                memory_type=memory_type,
                tags=tags,
                query=query,
                limit=limit,
            )
        )

    def update(self, memory: MemoryObject) -> MemoryObject:
        return _run(self._update(memory))

    async def _update(self, memory: MemoryObject) -> MemoryObject:
        async with self._session_factory() as database:
            record = await database.get(MemoryRecord, memory.id)
            if record is None:
                raise KeyError(memory.id)
            if record.organization_id != memory.organization_id:
                raise ValidatedMemoryConflictError("memory organization scope conflict")
            if record.proposal_id is not None:
                raise ValidatedMemoryConflictError(
                    "validated Learning memories are immutable"
                )
            for name in (
                "organization_id",
                "type",
                "title",
                "description",
                "source",
                "tags",
                "confidence",
                "created_at",
                "updated_at",
            ):
                value = getattr(memory, name)
                setattr(
                    record,
                    name,
                    value.value if isinstance(value, MemoryType) else value,
                )
            await database.commit()
        return memory

    def delete(self, memory_id: UUID) -> None:
        _run(self._delete(memory_id))

    async def _delete(self, memory_id: UUID) -> None:
        async with self._session_factory() as database:
            await database.execute(
                delete(MemoryRecord).where(MemoryRecord.id == memory_id)
            )
            await database.commit()

    def list(
        self,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        return _run(
            self._list(
                organization_id=organization_id,
                memory_type=memory_type,
                tags=tags,
                limit=limit,
            )
        )

    async def _list(
        self,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None,
        tags: list[str] | None,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        statement = select(MemoryRecord)
        if organization_id is not None:
            statement = statement.where(MemoryRecord.organization_id == organization_id)
        if memory_type is not None:
            statement = statement.where(MemoryRecord.type == memory_type.value)
        if tags is not None:
            statement = statement.where(MemoryRecord.tags.contains(tags))
        if query is not None:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    MemoryRecord.title.ilike(pattern),
                    MemoryRecord.description.ilike(pattern),
                )
            )
        statement = statement.order_by(MemoryRecord.created_at, MemoryRecord.id)
        if limit is not None:
            statement = statement.limit(limit)
        async with self._session_factory() as database:
            records = (await database.scalars(statement)).all()
        return [self._model(record) for record in records]

    @staticmethod
    def _record(memory: MemoryObject) -> MemoryRecord:
        return MemoryRecord(**PostgresMemoryRepository._record_values(memory))

    @staticmethod
    def _record_values(memory: MemoryObject) -> dict[str, object]:
        return {
            **memory.model_dump(mode="python", exclude={"type"}),
            "type": memory.type.value,
        }

    @staticmethod
    def _model(record: MemoryRecord) -> MemoryObject:
        return MemoryObject.model_validate(
            {
                "id": record.id,
                "organization_id": record.organization_id,
                "type": record.type,
                "title": record.title,
                "description": record.description,
                "source": record.source,
                "tags": record.tags,
                "confidence": record.confidence,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "session_id": record.session_id,
                "execution_id": record.execution_id,
                "correlation_id": record.correlation_id,
                "observation_id": record.observation_id,
                "learning_id": record.learning_id,
                "learning_candidate_id": record.learning_candidate_id,
                "proposal_id": record.proposal_id,
                "policy_version": record.policy_version,
                "validation_status": record.validation_status,
                "evidence_references": record.evidence_references,
                "source_references": record.source_references,
                "validated_write_fingerprint": record.validated_write_fingerprint,
                "version": record.version,
            }
        )

    @staticmethod
    def _matches_write(memory: MemoryObject, write: ValidatedMemoryWrite) -> bool:
        return all(
            (
                memory.organization_id == write.organization_id,
                memory.session_id == write.session_id,
                memory.execution_id == write.execution_id,
                memory.correlation_id == write.correlation_id,
                memory.observation_id == write.observation_id,
                memory.learning_id == write.learning_id,
                memory.learning_candidate_id == write.candidate_id,
                memory.proposal_id == write.proposal_id,
                memory.policy_version == write.policy_version,
                memory.validation_status == write.validation_status,
                memory.type == write.memory_type,
                memory.tags == list(write.tags),
                memory.confidence == write.confidence,
                memory.evidence_references == list(write.evidence_references),
                memory.source_references == list(write.source_references),
                memory.validated_write_fingerprint == write.fingerprint,
            )
        )

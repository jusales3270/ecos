"""PostgreSQL implementation of the memory repository contract."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ecos.database import create_database_engine, create_session_factory
from ecos.memory.models import MemoryObject, MemoryType
from ecos.memory.orm import MemoryRecord
from ecos.memory.repository import MemoryRepository


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

    def store(self, memory: MemoryObject) -> MemoryObject:
        return _run(self._store(memory))

    async def _store(self, memory: MemoryObject) -> MemoryObject:
        async with self._session_factory() as database:
            database.add(self._record(memory))
            await database.commit()
        return memory

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
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        return _run(self._list(memory_type=memory_type, tags=tags, query=query))

    def update(self, memory: MemoryObject) -> MemoryObject:
        return _run(self._update(memory))

    async def _update(self, memory: MemoryObject) -> MemoryObject:
        async with self._session_factory() as database:
            record = await database.get(MemoryRecord, memory.id)
            if record is None:
                raise KeyError(memory.id)
            for name in (
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
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        return _run(self._list(memory_type=memory_type, tags=tags))

    async def _list(
        self,
        *,
        memory_type: MemoryType | None,
        tags: list[str] | None,
        query: str | None = None,
    ) -> list[MemoryObject]:
        statement = select(MemoryRecord)
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
        async with self._session_factory() as database:
            records = (await database.scalars(statement)).all()
        return [self._model(record) for record in records]

    @staticmethod
    def _record(memory: MemoryObject) -> MemoryRecord:
        return MemoryRecord(
            **memory.model_dump(mode="python", exclude={"type"}), type=memory.type.value
        )

    @staticmethod
    def _model(record: MemoryRecord) -> MemoryObject:
        return MemoryObject.model_validate(
            {
                "id": record.id,
                "type": record.type,
                "title": record.title,
                "description": record.description,
                "source": record.source,
                "tags": record.tags,
                "confidence": record.confidence,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

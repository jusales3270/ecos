"""PostgreSQL implementation of the session repository contract."""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from ecos.database import create_database_engine, create_session_factory
from ecos.session.models import (
    ManagedSession,
    SessionSnapshot,
    SessionState,
    SessionTransition,
)
from ecos.session.orm import (
    SessionRecord,
    SessionSnapshotRecord,
    SessionStateRecord,
    SessionTransitionRecord,
)
from ecos.session.repository import SessionRepository


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    """Run async persistence while preserving the existing synchronous contract."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class PostgresSessionRepository(SessionRepository):
    """Store cognitive sessions in PostgreSQL through SQLAlchemy async sessions."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Initialize the repository from a URL or injected SQLAlchemy resources."""
        if engine is None and database_url is None:
            msg = "database_url or engine is required"
            raise ValueError(msg)
        self.engine = engine or create_database_engine(database_url or "")
        self._session_factory = session_factory or create_session_factory(self.engine)

    def create(self, session: ManagedSession) -> ManagedSession:
        return _run(self._create(session))

    async def _create(self, managed: ManagedSession) -> ManagedSession:
        record = SessionRecord(
            id=managed.session.id,
            organization_id=managed.context.organization_id,
            managed_id=managed.id,
            session_data=managed.session.model_dump(mode="json"),
            context_data=managed.context.model_dump(mode="json"),
            state=self._state_record(managed.state),
        )
        async with self._session_factory() as database:
            database.add(record)
            await database.commit()
        return managed

    def get(self, session_id: UUID) -> ManagedSession | None:
        return _run(self._get(session_id))

    async def _get(self, session_id: UUID) -> ManagedSession | None:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(SessionRecord)
                .options(selectinload(SessionRecord.state))
                .where(SessionRecord.id == session_id)
            )
            if record is None:
                return None
            return ManagedSession.model_validate(
                {
                    "id": record.managed_id,
                    "session": record.session_data,
                    "state": self._state_data(record.state),
                    "context": record.context_data,
                }
            )

    def update_state(self, state: SessionState) -> SessionState:
        return _run(self._update_state(state))

    async def _update_state(self, state: SessionState) -> SessionState:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(SessionStateRecord).where(
                    SessionStateRecord.session_id == state.session_id
                )
            )
            if record is None:
                raise KeyError(state.session_id)
            record.id = state.id
            record.lifecycle_status = state.lifecycle_status.value
            record.current_stage = state.current_stage.value
            record.active_engine = state.active_engine
            record.progress = state.progress
            record.last_error = state.last_error
            record.updated_at = state.updated_at
            await database.commit()
        return state

    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        return _run(self._save_snapshot(snapshot))

    async def _save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        record = SessionSnapshotRecord(
            id=snapshot.id,
            session_id=snapshot.session_id,
            state_data=snapshot.state.model_dump(mode="json"),
            context_data=snapshot.context.model_dump(mode="json"),
            created_at=snapshot.created_at,
        )
        async with self._session_factory() as database:
            database.add(record)
            await database.commit()
        return snapshot

    def list_transitions(self, session_id: UUID) -> list[SessionTransition]:
        return _run(self._list_transitions(session_id))

    async def _list_transitions(self, session_id: UUID) -> list[SessionTransition]:
        async with self._session_factory() as database:
            records = (
                await database.scalars(
                    select(SessionTransitionRecord)
                    .where(SessionTransitionRecord.session_id == session_id)
                    .order_by(
                        SessionTransitionRecord.created_at,
                        SessionTransitionRecord.id,
                    )
                )
            ).all()
        return [
            SessionTransition.model_validate(
                {
                    "id": record.id,
                    "session_id": record.session_id,
                    "transition_type": record.transition_type,
                    "from_status": record.from_status,
                    "to_status": record.to_status,
                    "reason": record.reason,
                    "created_at": record.created_at,
                }
            )
            for record in records
        ]

    def add_transition(self, transition: SessionTransition) -> SessionTransition:
        return _run(self._add_transition(transition))

    async def _add_transition(self, transition: SessionTransition) -> SessionTransition:
        record = SessionTransitionRecord(
            id=transition.id,
            session_id=transition.session_id,
            transition_type=transition.transition_type.value,
            from_status=transition.from_status.value,
            to_status=transition.to_status.value,
            reason=transition.reason,
            created_at=transition.created_at,
        )
        async with self._session_factory() as database:
            database.add(record)
            await database.commit()
        return transition

    @staticmethod
    def _state_record(state: SessionState) -> SessionStateRecord:
        return SessionStateRecord(
            id=state.id,
            session_id=state.session_id,
            lifecycle_status=state.lifecycle_status.value,
            current_stage=state.current_stage.value,
            active_engine=state.active_engine,
            progress=state.progress,
            last_error=state.last_error,
            updated_at=state.updated_at,
        )

    @staticmethod
    def _state_data(state: SessionStateRecord) -> dict[str, object]:
        return {
            "id": state.id,
            "session_id": state.session_id,
            "lifecycle_status": state.lifecycle_status,
            "current_stage": state.current_stage,
            "active_engine": state.active_engine,
            "progress": state.progress,
            "last_error": state.last_error,
            "updated_at": state.updated_at,
        }

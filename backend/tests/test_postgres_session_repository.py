"""Conditional PostgreSQL integration tests for session persistence."""

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config

from ecos.domain import CognitiveSession, Objective, Organization, SessionStage
from ecos.session import (
    ManagedSession,
    PostgresSessionRepository,
    SessionContext,
    SessionLifecycleStatus,
    SessionSnapshot,
    SessionState,
    SessionTransition,
    TransitionType,
)

database_url = os.getenv("ECOS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    database_url is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)


def async_database_url(value: str) -> str:
    """Normalize a PostgreSQL test URL to the SQLAlchemy asyncpg dialect."""
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


def test_postgres_repository_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist, reconstruct and mutate the full session repository contract."""
    assert database_url is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    repository = PostgresSessionRepository(async_database_url(database_url))

    organization = Organization(name="PostgreSQL test")
    objective = Objective(
        organization_id=organization.id,
        title="Persist cognitive sessions",
    )
    cognitive_session = CognitiveSession(
        organization_id=organization.id,
        objective=objective,
    )
    state = SessionState(
        session_id=cognitive_session.id,
        lifecycle_status=SessionLifecycleStatus.CREATED,
        current_stage=SessionStage.CONTEXT,
    )
    context = SessionContext(
        organization_id=organization.id,
        objective=objective,
        metadata={"source": "postgres-test"},
    )
    managed = ManagedSession(
        session=cognitive_session,
        state=state,
        context=context,
    )

    try:
        assert repository.create(managed) == managed
        assert repository.get(cognitive_session.id) == managed

        updated = state.model_copy(
            update={
                "id": SessionState(
                    session_id=cognitive_session.id,
                    lifecycle_status=SessionLifecycleStatus.INITIALIZED,
                    current_stage=SessionStage.CONTEXT,
                ).id,
                "lifecycle_status": SessionLifecycleStatus.INITIALIZED,
                "progress": 0.2,
                "updated_at": datetime.now(UTC),
            }
        )
        assert repository.update_state(updated) == updated
        assert repository.get(cognitive_session.id).state == updated  # type: ignore[union-attr]

        snapshot = SessionSnapshot(
            session_id=cognitive_session.id,
            state=updated,
            context=context,
        )
        assert repository.save_snapshot(snapshot) == snapshot

        transition = SessionTransition(
            session_id=cognitive_session.id,
            transition_type=TransitionType.INITIALIZE,
            from_status=SessionLifecycleStatus.CREATED,
            to_status=SessionLifecycleStatus.INITIALIZED,
        )
        assert repository.add_transition(transition) == transition
        assert repository.list_transitions(cognitive_session.id) == [transition]
    finally:
        command.downgrade(config, "base")

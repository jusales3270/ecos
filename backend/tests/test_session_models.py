"""Unit tests for ECOS Cognitive Session Manager models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.domain import CognitiveSession, Objective, Organization
from ecos.domain.enums import SessionStage
from ecos.session import (
    ManagedSession,
    SessionContext,
    SessionLifecycleStatus,
    SessionRepository,
    SessionResult,
    SessionService,
    SessionSnapshot,
    SessionState,
    SessionTransition,
    TransitionType,
)


def make_objective() -> Objective:
    """Create a valid objective for session tests."""
    organization = Organization(name="ACME")
    return Objective(
        organization_id=organization.id,
        title="Improve decision quality",
    )


def make_cognitive_session() -> CognitiveSession:
    """Create a valid cognitive session for tests."""
    objective = make_objective()
    return CognitiveSession(
        organization_id=objective.organization_id,
        objective=objective,
    )


def make_session_context(session: CognitiveSession) -> SessionContext:
    """Create a valid session context for tests."""
    return SessionContext(
        organization_id=session.organization_id,
        objective=session.objective,
        metadata={"source": "unit-test"},
    )


def make_session_state(session_id: UUID) -> SessionState:
    """Create a valid session state for tests."""
    return SessionState(
        session_id=session_id,
        lifecycle_status=SessionLifecycleStatus.CREATED,
        current_stage=SessionStage.CONTEXT,
        active_engine="context",
        progress=0.25,
        last_error=None,
    )


def make_managed_session() -> ManagedSession:
    """Create a valid managed session for tests."""
    session = make_cognitive_session()
    return ManagedSession(
        session=session,
        state=make_session_state(session.id),
        context=make_session_context(session),
    )


def make_snapshot(session: ManagedSession) -> SessionSnapshot:
    """Create a valid session snapshot for tests."""
    return SessionSnapshot(
        session_id=session.session.id,
        state=session.state,
        context=session.context,
    )


def make_transition(session_id: UUID) -> SessionTransition:
    """Create a valid session transition for tests."""
    return SessionTransition(
        session_id=session_id,
        transition_type=TransitionType.INITIALIZE,
        from_status=SessionLifecycleStatus.CREATED,
        to_status=SessionLifecycleStatus.INITIALIZED,
        reason="Initial setup completed.",
    )


def test_session_lifecycle_status_values() -> None:
    """SessionLifecycleStatus exposes all supported statuses."""
    assert {status.value for status in SessionLifecycleStatus} == {
        "CREATED",
        "INITIALIZED",
        "PLANNING",
        "EXECUTING",
        "PAUSED",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }


def test_transition_type_values() -> None:
    """TransitionType exposes all supported transition types."""
    assert {transition.value for transition in TransitionType} == {
        "INITIALIZE",
        "START_PLANNING",
        "START_EXECUTION",
        "PAUSE",
        "RESUME",
        "COMPLETE",
        "FAIL",
        "CANCEL",
    }


def test_session_context_validates_metadata() -> None:
    """SessionContext validates objective, organization, and metadata."""
    session = make_cognitive_session()
    context = make_session_context(session)

    assert isinstance(context.id, UUID)
    assert context.organization_id == session.organization_id
    assert context.objective == session.objective
    assert context.metadata == {"source": "unit-test"}

    with pytest.raises(ValidationError):
        SessionContext(
            organization_id=session.organization_id,
            objective=session.objective,
            metadata={"   ": "invalid"},
        )


def test_session_state_contains_required_architecture_fields() -> None:
    """SessionState contains all required lifecycle state fields."""
    session = make_cognitive_session()
    state = make_session_state(session.id)

    assert isinstance(state.id, UUID)
    assert state.session_id == session.id
    assert state.lifecycle_status == SessionLifecycleStatus.CREATED
    assert state.current_stage == SessionStage.CONTEXT
    assert state.active_engine == "context"
    assert state.progress == 0.25
    assert state.last_error is None
    assert state.updated_at.tzinfo is not None
    assert state.updated_at.utcoffset() == UTC.utcoffset(state.updated_at)


def test_session_state_validates_progress_text_and_updated_at() -> None:
    """SessionState validates progress, optional text, and updated_at."""
    session = make_cognitive_session()

    with pytest.raises(ValidationError):
        SessionState(
            session_id=session.id,
            lifecycle_status=SessionLifecycleStatus.CREATED,
            current_stage=SessionStage.CONTEXT,
            progress=1.1,
        )

    with pytest.raises(ValidationError):
        SessionState(
            session_id=session.id,
            lifecycle_status=SessionLifecycleStatus.CREATED,
            current_stage=SessionStage.CONTEXT,
            active_engine="   ",
        )

    with pytest.raises(ValidationError):
        SessionState(
            session_id=session.id,
            lifecycle_status=SessionLifecycleStatus.FAILED,
            current_stage=SessionStage.CONTEXT,
            last_error="   ",
        )

    with pytest.raises(ValidationError):
        SessionState(
            session_id=session.id,
            lifecycle_status=SessionLifecycleStatus.CREATED,
            current_stage=SessionStage.CONTEXT,
            updated_at=datetime.now(),
        )


def test_session_snapshot_contains_state_context_and_created_at() -> None:
    """SessionSnapshot contains session id, state, context, and created_at."""
    managed_session = make_managed_session()
    snapshot = make_snapshot(managed_session)

    assert isinstance(snapshot.id, UUID)
    assert snapshot.session_id == managed_session.session.id
    assert snapshot.state == managed_session.state
    assert snapshot.context == managed_session.context
    assert snapshot.created_at.tzinfo is not None
    assert snapshot.created_at.utcoffset() == UTC.utcoffset(snapshot.created_at)

    with pytest.raises(ValidationError):
        SessionSnapshot(
            session_id=managed_session.session.id,
            state=managed_session.state,
            context=managed_session.context,
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


def test_session_transition_contains_required_architecture_fields() -> None:
    """SessionTransition contains lifecycle transition fields."""
    session = make_cognitive_session()
    transition = make_transition(session.id)

    assert isinstance(transition.id, UUID)
    assert transition.session_id == session.id
    assert transition.transition_type == TransitionType.INITIALIZE
    assert transition.from_status == SessionLifecycleStatus.CREATED
    assert transition.to_status == SessionLifecycleStatus.INITIALIZED
    assert transition.reason == "Initial setup completed."
    assert transition.created_at.tzinfo is not None
    assert transition.created_at.utcoffset() == UTC.utcoffset(transition.created_at)

    with pytest.raises(ValidationError):
        SessionTransition(
            session_id=session.id,
            transition_type=TransitionType.FAIL,
            from_status=SessionLifecycleStatus.EXECUTING,
            to_status=SessionLifecycleStatus.FAILED,
            reason="   ",
        )


def test_session_result_validates_summary_metadata_and_created_at() -> None:
    """SessionResult validates summary, metadata, and created_at."""
    session = make_cognitive_session()
    result = SessionResult(
        session_id=session.id,
        lifecycle_status=SessionLifecycleStatus.COMPLETED,
        summary="Session completed.",
        metadata={"source": "unit-test"},
    )

    assert result.session_id == session.id
    assert result.lifecycle_status == SessionLifecycleStatus.COMPLETED
    assert result.summary == "Session completed."
    assert result.metadata == {"source": "unit-test"}

    with pytest.raises(ValidationError):
        SessionResult(
            session_id=session.id,
            lifecycle_status=SessionLifecycleStatus.COMPLETED,
            summary="   ",
        )

    with pytest.raises(ValidationError):
        SessionResult(
            session_id=session.id,
            lifecycle_status=SessionLifecycleStatus.COMPLETED,
            metadata={"   ": "invalid"},
        )


class NotImplementedSessionRepository(SessionRepository):
    """Concrete test adapter that delegates to interface methods."""

    def create(self, session: ManagedSession) -> ManagedSession:
        """Delegate to the interface method."""
        return super().create(session)

    def get(self, session_id: UUID) -> ManagedSession | None:
        """Delegate to the interface method."""
        return super().get(session_id)

    def update_state(self, state: SessionState) -> SessionState:
        """Delegate to the interface method."""
        return super().update_state(state)

    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        """Delegate to the interface method."""
        return super().save_snapshot(snapshot)

    def list_transitions(self, session_id: UUID) -> list[SessionTransition]:
        """Delegate to the interface method."""
        return super().list_transitions(session_id)

    def add_transition(self, transition: SessionTransition) -> SessionTransition:
        """Delegate to the interface method."""
        return super().add_transition(transition)


def test_session_repository_interface_methods_raise_not_implemented() -> None:
    """SessionRepository interface methods are intentionally unimplemented."""
    repository = NotImplementedSessionRepository()
    managed_session = make_managed_session()
    snapshot = make_snapshot(managed_session)
    transition = make_transition(managed_session.session.id)

    with pytest.raises(NotImplementedError):
        repository.create(managed_session)
    with pytest.raises(NotImplementedError):
        repository.get(managed_session.session.id)
    with pytest.raises(NotImplementedError):
        repository.update_state(managed_session.state)
    with pytest.raises(NotImplementedError):
        repository.save_snapshot(snapshot)
    with pytest.raises(NotImplementedError):
        repository.list_transitions(managed_session.session.id)
    with pytest.raises(NotImplementedError):
        repository.add_transition(transition)


class TestSessionRepository(SessionRepository):
    """Test double for verifying SessionService delegation only."""

    def __init__(self, session: ManagedSession) -> None:
        """Initialize reusable session artifacts."""
        self.session = session
        self.snapshot = make_snapshot(session)
        self.transition = make_transition(session.session.id)

    def create(self, session: ManagedSession) -> ManagedSession:
        """Return the provided managed session."""
        self.session = session
        return session

    def get(self, session_id: UUID) -> ManagedSession | None:
        """Return the managed session when identifiers match."""
        if session_id == self.session.session.id:
            return self.session
        return None

    def update_state(self, state: SessionState) -> SessionState:
        """Return the provided session state."""
        self.session = ManagedSession(
            session=self.session.session,
            state=state,
            context=self.session.context,
        )
        return state

    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        """Return the provided snapshot."""
        self.snapshot = snapshot
        return snapshot

    def list_transitions(self, session_id: UUID) -> list[SessionTransition]:
        """Return configured transitions when identifiers match."""
        if session_id == self.session.session.id:
            return [self.transition]
        return []

    def add_transition(self, transition: SessionTransition) -> SessionTransition:
        """Return the provided transition."""
        self.transition = transition
        return transition


def test_session_service_uses_repository_abstraction() -> None:
    """SessionService delegates operations to the repository abstraction."""
    managed_session = make_managed_session()
    repository = TestSessionRepository(managed_session)
    service = SessionService(repository)
    snapshot = make_snapshot(managed_session)
    transition = make_transition(managed_session.session.id)

    assert service.create_session(managed_session) == managed_session
    assert service.get_session(managed_session.session.id) == managed_session
    assert service.update_state(managed_session.state) == managed_session.state
    assert service.save_snapshot(snapshot) == snapshot
    assert service.record_transition(transition) == transition
    assert service.get_transitions(managed_session.session.id) == [transition]

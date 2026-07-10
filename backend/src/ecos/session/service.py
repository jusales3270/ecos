"""Service layer for the ECOS Cognitive Session Manager architecture."""

from uuid import UUID

from ecos.session.models import (
    ManagedSession,
    SessionSnapshot,
    SessionState,
    SessionTransition,
)
from ecos.session.repository import SessionRepository


class SessionService:
    """Coordinates cognitive session lifecycle operations via a repository only."""

    def __init__(self, repository: SessionRepository) -> None:
        """Initialize the service with a session repository abstraction."""
        self._repository = repository

    def create_session(self, session: ManagedSession) -> ManagedSession:
        """Create a managed session through the repository abstraction."""
        return self._repository.create(session)

    def get_session(self, session_id: UUID) -> ManagedSession | None:
        """Get a managed session through the repository abstraction."""
        return self._repository.get(session_id)

    def update_state(self, state: SessionState) -> SessionState:
        """Update session state through the repository abstraction."""
        return self._repository.update_state(state)

    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        """Save a session snapshot through the repository abstraction."""
        return self._repository.save_snapshot(snapshot)

    def record_transition(self, transition: SessionTransition) -> SessionTransition:
        """Record a session transition through the repository abstraction."""
        return self._repository.add_transition(transition)

    def get_transitions(self, session_id: UUID) -> list[SessionTransition]:
        """List session transitions through the repository abstraction."""
        return self._repository.list_transitions(session_id)

"""Repository interface for the ECOS Cognitive Session Manager."""

from abc import ABC, abstractmethod
from uuid import UUID

from ecos.session.models import (
    ManagedSession,
    SessionSnapshot,
    SessionState,
    SessionTransition,
)


class SessionRepository(ABC):
    """Abstract repository interface for cognitive session lifecycle storage."""

    @abstractmethod
    def create(self, session: ManagedSession) -> ManagedSession:
        """Create a managed session."""
        raise NotImplementedError

    @abstractmethod
    def get(self, session_id: UUID) -> ManagedSession | None:
        """Get a managed session by cognitive session identifier."""
        raise NotImplementedError

    @abstractmethod
    def update_state(self, state: SessionState) -> SessionState:
        """Update session lifecycle state."""
        raise NotImplementedError

    @abstractmethod
    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        """Save a session snapshot."""
        raise NotImplementedError

    @abstractmethod
    def list_transitions(self, session_id: UUID) -> list[SessionTransition]:
        """List lifecycle transitions for a cognitive session."""
        raise NotImplementedError

    @abstractmethod
    def add_transition(self, transition: SessionTransition) -> SessionTransition:
        """Add a lifecycle transition for a cognitive session."""
        raise NotImplementedError

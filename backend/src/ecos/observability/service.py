"""Provider-agnostic observability service facade."""

from __future__ import annotations

from uuid import UUID

from ecos.observability.models import HealthSnapshot, HealthStatus, SessionTrace
from ecos.observability.replay import SessionTraceReconstructor
from ecos.observability.repository import (
    AuditRepository,
    EventStore,
    ObservabilityRepository,
)


class ObservabilityService:
    """Expose technical and cognitive observability without business effects."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        audit_repository: AuditRepository,
        observability_repository: ObservabilityRepository,
        session_reconstructor: SessionTraceReconstructor,
    ) -> None:
        self._event_store = event_store
        self._audit_repository = audit_repository
        self._observability_repository = observability_repository
        self._session_reconstructor = session_reconstructor

    def health(self) -> tuple[HealthSnapshot, ...]:
        """Return snapshots for known observability components."""
        snapshots = (
            self._event_store.health(),
            self._audit_repository.health(),
            self._observability_repository.health(),
        )
        status = (
            HealthStatus.HEALTHY
            if all(item.status is HealthStatus.HEALTHY for item in snapshots)
            else HealthStatus.DEGRADED
        )
        aggregate = HealthSnapshot(
            component="ObservabilityLayer",
            status=status,
            availability=all(item.availability is not False for item in snapshots),
        )
        self._observability_repository.append_health(aggregate)
        return (*snapshots, aggregate)

    def reconstruct_session(
        self,
        *,
        organization_id: UUID,
        session_id: UUID,
    ) -> SessionTrace:
        """Reconstruct a session from persisted events only."""
        return self._session_reconstructor.reconstruct(
            organization_id=organization_id,
            session_id=session_id,
        )

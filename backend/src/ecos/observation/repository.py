"""Persistence contracts for canonical observation results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock
from uuid import UUID

from ecos.events import Event
from ecos.outbox import (
    InMemoryOutboxRepository,
    message_from_event,
    validate_terminal_event,
)

from .models import ObservationResult


class ObservationRepositoryError(RuntimeError):
    """Base error for canonical observation persistence."""


class ObservationConflictError(ObservationRepositoryError):
    """Raised when an execution is reused with divergent observation data."""


class ObservationRepository(ABC):
    """Organization-scoped immutable observation storage."""

    supports_transactional_outbox: bool = False

    @abstractmethod
    def get(
        self, organization_id: UUID, execution_id: UUID
    ) -> ObservationResult | None:
        """Return the canonical observation within the supplied tenant scope."""
        raise NotImplementedError

    @abstractmethod
    def save(self, result: ObservationResult) -> ObservationResult:
        """Persist the first result or return an identical canonical result."""
        raise NotImplementedError

    def save_terminal(
        self, result: ObservationResult, event: Event
    ) -> ObservationResult:
        del event
        return self.save(result)

    @abstractmethod
    def list_by_session(
        self, organization_id: UUID, session_id: UUID
    ) -> list[ObservationResult]:
        """List canonical observations within one tenant and session."""
        raise NotImplementedError


class InMemoryObservationRepository(ObservationRepository):
    """Thread-safe canonical observation repository for local runtimes."""

    def __init__(self, outbox: InMemoryOutboxRepository | None = None) -> None:
        self._results: dict[UUID, ObservationResult] = {}
        self._lock = RLock()
        self._outbox = outbox
        self.supports_transactional_outbox = outbox is not None

    def get(
        self, organization_id: UUID, execution_id: UUID
    ) -> ObservationResult | None:
        with self._lock:
            result = self._results.get(execution_id)
            if result is None or result.organization_id != organization_id:
                return None
            return result.model_copy(deep=True)

    def save(self, result: ObservationResult) -> ObservationResult:
        if result.execution_id is None:
            raise ObservationConflictError(
                "canonical observation requires execution_id"
            )
        with self._lock:
            existing = self._results.get(result.execution_id)
            if existing is None:
                self._results[result.execution_id] = result.model_copy(deep=True)
                return result.model_copy(deep=True)
            _validate_compatible(existing, result)
            return existing.model_copy(deep=True)

    def list_by_session(
        self, organization_id: UUID, session_id: UUID
    ) -> list[ObservationResult]:
        with self._lock:
            return [
                item.model_copy(deep=True)
                for item in self._results.values()
                if item.organization_id == organization_id
                and item.session_id == session_id
            ]

    def save_terminal(
        self, result: ObservationResult, event: Event
    ) -> ObservationResult:
        with self._lock:
            validate_observation_terminal_event(result, event)
            existing = self._results.get(result.execution_id)
            canonical = self.save(result)
            if self._outbox is not None and existing is None:
                self._outbox.enqueue(
                    message_from_event(
                        event,
                        actor_id=None,
                        aggregate_type="observation",
                        aggregate_id=str(result.observation_id),
                        execution_id=result.execution_id,
                        observation_id=result.observation_id,
                    )
                )
            return canonical


def validate_observation_terminal_event(
    result: ObservationResult, event: Event
) -> None:
    expected_type = (
        "OBSERVATION_FAILED"
        if result.status.value == "failed"
        else "OBSERVATION_COMPLETED"
    )
    validate_terminal_event(
        event,
        organization_id=result.organization_id,
        session_id=result.session_id,
        correlation_id=result.correlation_id,
        event_type=expected_type,
    )


def _validate_compatible(
    existing: ObservationResult, result: ObservationResult
) -> None:
    if (
        existing.organization_id != result.organization_id
        or existing.session_id != result.session_id
        or existing.execution_id != result.execution_id
        or existing.correlation_id != result.correlation_id
        or existing.execution_result_fingerprint != result.execution_result_fingerprint
        or existing.fingerprint != result.fingerprint
    ):
        raise ObservationConflictError("observation identity or fingerprint conflict")

"""Persistence contracts for canonical observation results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock
from uuid import UUID

from .models import ObservationResult


class ObservationRepositoryError(RuntimeError):
    """Base error for canonical observation persistence."""


class ObservationConflictError(ObservationRepositoryError):
    """Raised when an execution is reused with divergent observation data."""


class ObservationRepository(ABC):
    """Organization-scoped immutable observation storage."""

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


class InMemoryObservationRepository(ObservationRepository):
    """Thread-safe canonical observation repository for local runtimes."""

    def __init__(self) -> None:
        self._results: dict[UUID, ObservationResult] = {}
        self._lock = RLock()

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

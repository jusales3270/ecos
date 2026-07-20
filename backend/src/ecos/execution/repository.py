"""Immutable persistence contracts for canonical execution results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock
from uuid import UUID

from ecos.execution.models import ExecutionResult
from ecos.execution.provider import deterministic_fingerprint


class ExecutionResultRepositoryError(RuntimeError):
    """Base error for canonical execution result persistence."""


class ExecutionResultConflictError(ExecutionResultRepositoryError):
    """Raised when an execution identity is reused with divergent data or scope."""


class ExecutionResultRepository(ABC):
    """Organization-scoped immutable storage for complete execution results."""

    @abstractmethod
    def get(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> ExecutionResult | None:
        """Return a result only when both organization and execution match."""
        raise NotImplementedError

    @abstractmethod
    def save(self, result: ExecutionResult) -> ExecutionResult:
        """Persist the first result or return an identical canonical result."""
        raise NotImplementedError


class InMemoryExecutionResultRepository(ExecutionResultRepository):
    """Thread-safe immutable repository used by tests and local runtime."""

    def __init__(self) -> None:
        self._results: dict[UUID, ExecutionResult] = {}
        self._lock = RLock()

    def get(
        self,
        organization_id: UUID,
        execution_id: UUID,
    ) -> ExecutionResult | None:
        with self._lock:
            result = self._results.get(execution_id)
            if result is None or result.organization_id != organization_id:
                return None
            validate_execution_result_fingerprint(result)
            return result.model_copy(deep=True)

    def save(self, result: ExecutionResult) -> ExecutionResult:
        with self._lock:
            validate_execution_result_fingerprint(result)
            existing = self._results.get(result.execution_id)
            if existing is None:
                self._results[result.execution_id] = result.model_copy(deep=True)
                return result.model_copy(deep=True)
            if (
                existing.organization_id != result.organization_id
                or existing.session_id != result.session_id
                or existing.plan_id != result.plan_id
                or existing.correlation_id != result.correlation_id
                or existing.fingerprint != result.fingerprint
            ):
                raise ExecutionResultConflictError(
                    "execution result identity or fingerprint conflict"
                )
            return existing.model_copy(deep=True)


def validate_execution_result_fingerprint(result: ExecutionResult) -> None:
    """Reject results whose declared fingerprint does not match their payload."""
    expected = deterministic_fingerprint(
        result.model_dump(mode="json", exclude={"fingerprint"})
    )
    if result.fingerprint != expected:
        raise ExecutionResultConflictError(
            "execution result fingerprint does not match payload"
        )

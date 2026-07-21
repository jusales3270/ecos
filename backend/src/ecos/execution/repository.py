"""Immutable persistence contracts for canonical execution results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock
from uuid import UUID

from ecos.events import Event
from ecos.execution.models import ExecutionResult
from ecos.execution.provider import deterministic_fingerprint
from ecos.outbox import (
    InMemoryOutboxRepository,
    message_from_event,
    validate_terminal_event,
)


class ExecutionResultRepositoryError(RuntimeError):
    """Base error for canonical execution result persistence."""


class ExecutionResultConflictError(ExecutionResultRepositoryError):
    """Raised when an execution identity is reused with divergent data or scope."""


class ExecutionResultRepository(ABC):
    """Organization-scoped immutable storage for complete execution results."""

    supports_transactional_outbox: bool = False

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

    def save_terminal(self, result: ExecutionResult, event: Event) -> ExecutionResult:
        """Persist a terminal result, with an atomic event when supported."""
        del event
        return self.save(result)


class InMemoryExecutionResultRepository(ExecutionResultRepository):
    """Thread-safe immutable repository used by tests and local runtime."""

    def __init__(self, outbox: InMemoryOutboxRepository | None = None) -> None:
        self._results: dict[UUID, ExecutionResult] = {}
        self._lock = RLock()
        self._outbox = outbox
        self.supports_transactional_outbox = outbox is not None

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

    def save_terminal(self, result: ExecutionResult, event: Event) -> ExecutionResult:
        with self._lock:
            validate_execution_terminal_event(result, event)
            canonical = self.save(result)
            if self._outbox is not None:
                self._outbox.enqueue(
                    message_from_event(
                        event,
                        actor_id=None,
                        aggregate_type="execution",
                        aggregate_id=str(result.execution_id),
                        execution_id=result.execution_id,
                    )
                )
            return canonical


def validate_execution_terminal_event(result: ExecutionResult, event: Event) -> None:
    expected_type = (
        "EXECUTION_COMPLETED"
        if result.status.value == "completed"
        else "EXECUTION_FAILED"
    )
    validate_terminal_event(
        event,
        organization_id=result.organization_id,
        session_id=result.session_id,
        correlation_id=result.correlation_id,
        event_type=expected_type,
    )
    if result.terminal_event_id != event.event_id:
        raise ExecutionResultConflictError("execution terminal event_id conflict")


def validate_execution_result_fingerprint(result: ExecutionResult) -> None:
    """Reject results whose declared fingerprint does not match their payload."""
    expected = deterministic_fingerprint(
        result.model_dump(mode="json", exclude={"fingerprint"})
    )
    if result.fingerprint != expected:
        raise ExecutionResultConflictError(
            "execution result fingerprint does not match payload"
        )

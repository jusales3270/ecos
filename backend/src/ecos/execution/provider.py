"""Injected providers for Execution idempotency and human tasks."""

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ecos.execution.exceptions import DuplicateExecutionError, IdempotencyConflictError
from ecos.execution.models import (
    HumanTask,
    HumanTaskStatus,
    IdempotencyRecord,
    IdempotencyRecordStatus,
)


class IdempotencyProvider(ABC):
    """Port for idempotency records."""

    @abstractmethod
    def reserve(self, record: IdempotencyRecord) -> IdempotencyRecord:
        """Reserve an idempotency key or return the existing record."""
        raise NotImplementedError

    @abstractmethod
    def complete(self, key: str, result: Any, now: datetime) -> IdempotencyRecord:
        """Mark a record completed."""
        raise NotImplementedError

    @abstractmethod
    def fail(self, key: str, now: datetime) -> IdempotencyRecord:
        """Mark a record failed."""
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str) -> IdempotencyRecord | None:
        """Return an idempotency record."""
        raise NotImplementedError


class InMemoryIdempotencyProvider(IdempotencyProvider):
    """Deterministic in-memory idempotency provider."""

    def __init__(self) -> None:
        self.records: dict[str, IdempotencyRecord] = {}

    def reserve(self, record: IdempotencyRecord) -> IdempotencyRecord:
        existing = self.records.get(record.key)
        if existing is None:
            self.records[record.key] = record
            return record
        if existing.fingerprint != record.fingerprint:
            raise IdempotencyConflictError("idempotency key payload conflict")
        if existing.status is IdempotencyRecordStatus.IN_PROGRESS:
            raise DuplicateExecutionError("idempotent execution already in progress")
        return existing

    def complete(self, key: str, result: Any, now: datetime) -> IdempotencyRecord:
        record = self.records[key]
        updated = record.model_copy(
            update={
                "status": IdempotencyRecordStatus.COMPLETED,
                "result": result,
                "updated_at": now,
            }
        )
        self.records[key] = updated
        return updated

    def fail(self, key: str, now: datetime) -> IdempotencyRecord:
        record = self.records[key]
        updated = record.model_copy(
            update={"status": IdempotencyRecordStatus.FAILED, "updated_at": now}
        )
        self.records[key] = updated
        return updated

    def get(self, key: str) -> IdempotencyRecord | None:
        return self.records.get(key)


class HumanTaskProvider(ABC):
    """Port for human tasks."""

    @abstractmethod
    def create(self, task: HumanTask) -> HumanTask:
        """Create a human task."""
        raise NotImplementedError

    @abstractmethod
    def get(self, task_id: object) -> HumanTask | None:
        """Return a task by id."""
        raise NotImplementedError

    @abstractmethod
    def complete(self, task_id: object, evidence: str | None) -> HumanTask:
        """Complete a task with explicit evidence."""
        raise NotImplementedError

    @abstractmethod
    def reject(self, task_id: object, evidence: str | None) -> HumanTask:
        """Reject a task with explicit evidence."""
        raise NotImplementedError


class InMemoryHumanTaskProvider(HumanTaskProvider):
    """In-memory human task provider for tests and default wiring."""

    def __init__(self) -> None:
        self.tasks: dict[object, HumanTask] = {}

    def create(self, task: HumanTask) -> HumanTask:
        self.tasks[task.task_id] = task
        return task

    def get(self, task_id: object) -> HumanTask | None:
        return self.tasks.get(task_id)

    def complete(self, task_id: object, evidence: str | None) -> HumanTask:
        task = self.tasks[task_id]
        updated = task.model_copy(
            update={"status": HumanTaskStatus.COMPLETED, "evidence": evidence}
        )
        self.tasks[task_id] = updated
        return updated

    def reject(self, task_id: object, evidence: str | None) -> HumanTask:
        task = self.tasks[task_id]
        updated = task.model_copy(
            update={"status": HumanTaskStatus.REJECTED, "evidence": evidence}
        )
        self.tasks[task_id] = updated
        return updated


def deterministic_fingerprint(payload: dict[str, Any]) -> str:
    """Create a stable cryptographic fingerprint from safe payload fields."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

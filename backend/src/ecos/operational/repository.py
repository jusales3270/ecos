"""Repository contracts for persistent operational workflows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from typing import Any
from uuid import UUID

from ecos.operational.exceptions import IdempotencyConflictError
from ecos.operational.models import OperationalSessionView


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def payload_fingerprint(payload: dict[str, Any]) -> str:
    """Create a deterministic SHA-256 fingerprint for safe command payloads."""
    import json

    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Persisted idempotency result or reference for a mutable operation."""

    organization_id: UUID
    user_id: UUID
    operation: str
    key: str
    request_hash: str
    response_payload: dict[str, Any] | None
    resource_id: UUID | None
    status_code: int
    created_at: datetime
    expires_at: datetime


class OperationalRepository(ABC):
    """Persistence port for the operational API aggregate."""

    @abstractmethod
    def save_session(
        self, session: OperationalSessionView, *, expected_version: int | None = None
    ) -> tuple[OperationalSessionView, int]:
        """Insert or update a session using optimistic versioning."""
        raise NotImplementedError

    @abstractmethod
    def get_session(
        self, organization_id: UUID, session_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        """Return one session in the requested organization."""
        raise NotImplementedError

    @abstractmethod
    def list_sessions(
        self, organization_id: UUID, *, status: str | None = None
    ) -> list[OperationalSessionView]:
        """List organization-scoped sessions."""
        raise NotImplementedError

    @abstractmethod
    def find_by_approval(
        self, organization_id: UUID, approval_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        """Find a session by approval id within one organization."""
        raise NotImplementedError

    @abstractmethod
    def find_by_execution(
        self, organization_id: UUID, execution_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        """Find a session by execution id within one organization."""
        raise NotImplementedError

    @abstractmethod
    def get_idempotency(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        operation: str,
        key: str,
    ) -> IdempotencyRecord | None:
        """Return a non-expired idempotency record when present."""
        raise NotImplementedError

    @abstractmethod
    def store_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        """Persist the first result for an idempotent command."""
        raise NotImplementedError

    @abstractmethod
    def cleanup_expired_idempotency(self, *, now: datetime | None = None) -> int:
        """Delete expired idempotency records according to retention policy."""
        raise NotImplementedError

    @abstractmethod
    def interrupted_sessions(
        self, organization_id: UUID | None = None
    ) -> list[OperationalSessionView]:
        """Return sessions in states that require startup/admin reconciliation."""
        raise NotImplementedError


class InMemoryOperationalRepository(OperationalRepository):
    """Thread-safe in-memory operational repository for explicit development/tests."""

    def __init__(self, *, idempotency_ttl: timedelta = timedelta(hours=24)) -> None:
        self._lock = RLock()
        self._sessions: dict[UUID, OperationalSessionView] = {}
        self._versions: dict[UUID, int] = {}
        self._idempotency: dict[tuple[UUID, UUID, str, str], IdempotencyRecord] = {}
        self._idempotency_ttl = idempotency_ttl

    def save_session(
        self, session: OperationalSessionView, *, expected_version: int | None = None
    ) -> tuple[OperationalSessionView, int]:
        with self._lock:
            current = self._versions.get(session.session_id, 0)
            if expected_version is not None and expected_version != current:
                from ecos.operational.exceptions import OperationalConflictError

                raise OperationalConflictError("session was modified concurrently")
            self._sessions[session.session_id] = session
            next_version = current + 1
            self._versions[session.session_id] = next_version
            return session, next_version

    def get_session(
        self, organization_id: UUID, session_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.organization_id != organization_id:
                return None
            return session, self._versions.get(session_id, 0)

    def list_sessions(
        self, organization_id: UUID, *, status: str | None = None
    ) -> list[OperationalSessionView]:
        with self._lock:
            sessions = [
                item
                for item in self._sessions.values()
                if item.organization_id == organization_id
            ]
        if status is not None:
            sessions = [item for item in sessions if item.status.value == status]
        return sorted(sessions, key=lambda item: item.created_at, reverse=True)

    def find_by_approval(
        self, organization_id: UUID, approval_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        with self._lock:
            for session in self._sessions.values():
                if (
                    session.organization_id == organization_id
                    and session.approval is not None
                    and session.approval.approval_id == approval_id
                ):
                    return session, self._versions.get(session.session_id, 0)
        return None

    def find_by_execution(
        self, organization_id: UUID, execution_id: UUID
    ) -> tuple[OperationalSessionView, int] | None:
        with self._lock:
            for session in self._sessions.values():
                if (
                    session.organization_id == organization_id
                    and session.execution is not None
                    and session.execution.execution_id == execution_id
                ):
                    return session, self._versions.get(session.session_id, 0)
        return None

    def get_idempotency(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        operation: str,
        key: str,
    ) -> IdempotencyRecord | None:
        now = utc_now()
        with self._lock:
            record = self._idempotency.get((organization_id, user_id, operation, key))
            if record is None or record.expires_at <= now:
                return None
            return record

    def store_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        scoped_key = (
            record.organization_id,
            record.user_id,
            record.operation,
            record.key,
        )
        with self._lock:
            existing = self._idempotency.get(scoped_key)
            if existing is not None:
                if existing.request_hash != record.request_hash:
                    raise IdempotencyConflictError()
                return existing
            self._idempotency[scoped_key] = record
            return record

    def cleanup_expired_idempotency(self, *, now: datetime | None = None) -> int:
        cutoff = now or utc_now()
        with self._lock:
            expired = [
                key
                for key, record in self._idempotency.items()
                if record.expires_at <= cutoff
            ]
            for key in expired:
                del self._idempotency[key]
            return len(expired)

    def interrupted_sessions(
        self, organization_id: UUID | None = None
    ) -> list[OperationalSessionView]:
        resumable = {
            "processing",
            "waiting_approval",
            "approved",
            "executing",
            "observing",
            "learning",
        }
        with self._lock:
            sessions = list(self._sessions.values())
        if organization_id is not None:
            sessions = [
                item for item in sessions if item.organization_id == organization_id
            ]
        return [item for item in sessions if item.status.value in resumable]


def idempotency_record(
    *,
    organization_id: UUID,
    user_id: UUID,
    operation: str,
    key: str,
    request_hash: str,
    response_payload: dict[str, Any],
    resource_id: UUID | None,
    ttl: timedelta,
) -> IdempotencyRecord:
    """Build a completed idempotency record."""
    now = utc_now()
    return IdempotencyRecord(
        organization_id=organization_id,
        user_id=user_id,
        operation=operation,
        key=key,
        request_hash=request_hash,
        response_payload=response_payload,
        resource_id=resource_id,
        status_code=200,
        created_at=now,
        expires_at=now + ttl,
    )

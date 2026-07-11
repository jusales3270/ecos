"""Repository ports and in-memory implementations for observability data."""

from __future__ import annotations

import hashlib
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from ecos.events.models import Event
from ecos.observability.exceptions import (
    AuditConflictError,
    ConflictingEventError,
    QueryInvalidError,
)
from ecos.observability.models import (
    AlertSignal,
    AuditRecord,
    EventQuery,
    HealthSnapshot,
    HealthStatus,
    MetricRecord,
    RetentionClass,
    StoredEvent,
    StructuredLogRecord,
    TraceRecord,
)
from ecos.observability.redaction import RedactionPolicy, default_redaction_policy


def event_fingerprint(
    event: Event,
    *,
    redaction_policy: RedactionPolicy = default_redaction_policy,
) -> str:
    """Create a deterministic SHA-256 fingerprint from safe event content."""
    canonical = {
        "event_id": str(event.event_id),
        "event_type": event.event_type.value,
        "organization_id": None
        if event.organization_id is None
        else str(event.organization_id),
        "session_id": None if event.session_id is None else str(event.session_id),
        "correlation_id": None
        if event.correlation_id is None
        else str(event.correlation_id),
        "source_component": event.source_component,
        "occurred_at": event.occurred_at.isoformat(),
        "event_version": event.event_version,
        "schema_version": event.schema_version,
        "payload": redaction_policy.redact(event.payload),
        "metadata": redaction_policy.redact(event.metadata.model_dump(mode="python")),
    }
    material = redaction_policy.canonical_json(canonical)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record_fingerprint(
    value: dict[str, Any],
    *,
    redaction_policy: RedactionPolicy = default_redaction_policy,
) -> str:
    """Create a deterministic SHA-256 fingerprint for safe record data."""
    material = redaction_policy.canonical_json(value)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class EventStore(ABC):
    """Append-only event store port."""

    @abstractmethod
    def append(self, event: Event) -> StoredEvent:
        raise NotImplementedError

    @abstractmethod
    def append_many(self, events: list[Event]) -> list[StoredEvent]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, event_id: UUID) -> StoredEvent | None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, event_id: UUID) -> bool:
        raise NotImplementedError

    @abstractmethod
    def query(self, filters: EventQuery) -> list[StoredEvent]:
        raise NotImplementedError

    def list_by_organization(
        self,
        organization_id: UUID,
        *,
        limit: int = 100,
    ) -> list[StoredEvent]:
        return self.query(EventQuery(organization_id=organization_id, limit=limit))

    def list_by_session(
        self,
        organization_id: UUID,
        session_id: UUID,
        *,
        limit: int = 100,
    ) -> list[StoredEvent]:
        return self.query(
            EventQuery(
                organization_id=organization_id,
                session_id=session_id,
                limit=limit,
            )
        )

    def list_by_correlation(
        self,
        organization_id: UUID,
        correlation_id: UUID,
        *,
        limit: int = 100,
    ) -> list[StoredEvent]:
        return self.query(
            EventQuery(
                organization_id=organization_id,
                correlation_id=correlation_id,
                limit=limit,
            )
        )

    def list_by_type(
        self,
        organization_id: UUID,
        event_type: str,
        *,
        limit: int = 100,
    ) -> list[StoredEvent]:
        return self.query(
            EventQuery(
                organization_id=organization_id,
                event_types=(event_type,),
                limit=limit,
            )
        )

    def list_by_category(
        self,
        organization_id: UUID,
        category: str,
        *,
        limit: int = 100,
    ) -> list[StoredEvent]:
        return self.query(
            EventQuery(
                organization_id=organization_id,
                categories=(category,),
                limit=limit,
            )
        )

    def list_by_source(
        self,
        organization_id: UUID,
        source_component: str,
        *,
        limit: int = 100,
    ) -> list[StoredEvent]:
        return self.query(
            EventQuery(
                organization_id=organization_id,
                source_component=source_component,
                limit=limit,
            )
        )

    def list_by_time_range(
        self,
        organization_id: UUID,
        start_time: datetime,
        end_time: datetime,
        *,
        limit: int = 100,
    ) -> list[StoredEvent]:
        return self.query(
            EventQuery(
                organization_id=organization_id,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
        )

    def stream(self, filters: EventQuery) -> list[StoredEvent]:
        return self.query(filters)

    @abstractmethod
    def count(self, filters: EventQuery | None = None) -> int:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> HealthSnapshot:
        raise NotImplementedError

    @abstractmethod
    def latest_sequence(self) -> int:
        raise NotImplementedError

    def replay_range(
        self,
        organization_id: UUID,
        *,
        sequence_from: int,
        sequence_to: int,
        limit: int = 1000,
    ) -> list[StoredEvent]:
        return self.query(
            EventQuery(
                organization_id=organization_id,
                sequence_from=sequence_from,
                sequence_to=sequence_to,
                limit=limit,
            )
        )


class InMemoryEventStore(EventStore):
    """Thread-safe append-only event store for development and tests."""

    def __init__(self, redaction_policy: RedactionPolicy | None = None) -> None:
        self._redaction_policy = redaction_policy or default_redaction_policy
        self._lock = threading.RLock()
        self._events: list[StoredEvent] = []
        self._by_id: dict[UUID, StoredEvent] = {}

    def append(self, event: Event) -> StoredEvent:
        fingerprint = event_fingerprint(event, redaction_policy=self._redaction_policy)
        with self._lock:
            existing = self._by_id.get(event.event_id)
            if existing is not None:
                if existing.fingerprint == fingerprint:
                    return existing
                raise ConflictingEventError(
                    "event_id already exists with different content"
                )
            stored = StoredEvent(
                event=event,
                stored_sequence=len(self._events) + 1,
                fingerprint=fingerprint,
                retention_class=RetentionClass.ACTIVE,
                safe_metadata={"store": "memory"},
            )
            self._events.append(stored)
            self._by_id[event.event_id] = stored
            return stored

    def append_many(self, events: list[Event]) -> list[StoredEvent]:
        with self._lock:
            fingerprints = [
                event_fingerprint(event, redaction_policy=self._redaction_policy)
                for event in events
            ]
            for event, fingerprint in zip(events, fingerprints, strict=True):
                existing = self._by_id.get(event.event_id)
                if existing is not None and existing.fingerprint != fingerprint:
                    raise ConflictingEventError(
                        "event_id already exists with different content"
                    )
            return [self.append(event) for event in events]

    def get_by_id(self, event_id: UUID) -> StoredEvent | None:
        with self._lock:
            return self._by_id.get(event_id)

    def exists(self, event_id: UUID) -> bool:
        with self._lock:
            return event_id in self._by_id

    def query(self, filters: EventQuery) -> list[StoredEvent]:
        with self._lock:
            events = list(self._events)
        events = [
            item
            for item in events
            if item.event.organization_id == filters.organization_id
        ]
        if filters.session_id is not None:
            events = [
                item for item in events if item.event.session_id == filters.session_id
            ]
        if filters.correlation_id is not None:
            events = [
                item
                for item in events
                if item.event.correlation_id == filters.correlation_id
            ]
        if filters.event_types:
            events = [
                item
                for item in events
                if item.event.event_type.value in filters.event_types
            ]
        if filters.categories:
            events = [
                item
                for item in events
                if item.event.category.value in filters.categories
            ]
        if filters.source_component is not None:
            events = [
                item
                for item in events
                if item.event.source_component == filters.source_component
            ]
        if filters.retention_class is not None:
            events = [
                item
                for item in events
                if item.retention_class == filters.retention_class
            ]
        if filters.start_time is not None:
            events = [
                item for item in events if item.event.occurred_at >= filters.start_time
            ]
        if filters.end_time is not None:
            events = [
                item for item in events if item.event.occurred_at <= filters.end_time
            ]
        if filters.sequence_after is not None:
            events = [
                item for item in events if item.stored_sequence > filters.sequence_after
            ]
        if filters.sequence_from is not None:
            events = [
                item for item in events if item.stored_sequence >= filters.sequence_from
            ]
        if filters.sequence_to is not None:
            events = [
                item for item in events if item.stored_sequence <= filters.sequence_to
            ]
        return _ordered(events)[: filters.limit]

    def count(self, filters: EventQuery | None = None) -> int:
        if filters is None:
            with self._lock:
                return len(self._events)
        return len(self.query(filters))

    def health(self) -> HealthSnapshot:
        return HealthSnapshot(
            component="EventStore",
            status=HealthStatus.HEALTHY,
            availability=True,
            safe_metadata={"implementation": "memory", "count": self.count()},
        )

    def latest_sequence(self) -> int:
        with self._lock:
            return len(self._events)


class AuditRepository(ABC):
    """Append-only audit repository port."""

    @abstractmethod
    def append(self, record: AuditRecord) -> AuditRecord:
        raise NotImplementedError

    @abstractmethod
    def append_many(self, records: list[AuditRecord]) -> list[AuditRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, audit_id: UUID) -> AuditRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_by_organization(
        self,
        organization_id: UUID,
        *,
        limit: int = 100,
    ) -> list[AuditRecord]:
        raise NotImplementedError

    @abstractmethod
    def verify_integrity(self, organization_id: UUID) -> bool:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> HealthSnapshot:
        raise NotImplementedError


class InMemoryAuditRepository(AuditRepository):
    """Thread-safe append-only audit repository."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: list[AuditRecord] = []
        self._by_id: dict[UUID, AuditRecord] = {}
        self._by_source_action: dict[tuple[UUID, str], AuditRecord] = {}

    def append(self, record: AuditRecord) -> AuditRecord:
        key = (record.source_event_id, record.action)
        with self._lock:
            existing = self._by_source_action.get(key)
            if existing is not None:
                if existing.fingerprint == record.fingerprint:
                    return existing
                raise AuditConflictError("audit projection conflicts with prior record")
            self._records.append(record)
            self._by_id[record.audit_id] = record
            self._by_source_action[key] = record
            return record

    def append_many(self, records: list[AuditRecord]) -> list[AuditRecord]:
        return [self.append(record) for record in records]

    def get_by_id(self, audit_id: UUID) -> AuditRecord | None:
        with self._lock:
            return self._by_id.get(audit_id)

    def list_by_organization(
        self,
        organization_id: UUID,
        *,
        limit: int = 100,
    ) -> list[AuditRecord]:
        with self._lock:
            records = [
                item
                for item in self._records
                if item.organization_id == organization_id
            ]
        return sorted(records, key=lambda item: (item.sequence, item.timestamp))[:limit]

    def list_by_session(
        self,
        organization_id: UUID,
        session_id: UUID,
        *,
        limit: int = 100,
    ) -> list[AuditRecord]:
        return [
            item
            for item in self.list_by_organization(organization_id, limit=limit)
            if item.session_id == session_id
        ]

    def list_by_actor(
        self,
        organization_id: UUID,
        actor_id: str,
        *,
        limit: int = 100,
    ) -> list[AuditRecord]:
        return [
            item
            for item in self.list_by_organization(organization_id, limit=limit)
            if item.actor_id == actor_id
        ]

    def list_by_action(
        self,
        organization_id: UUID,
        action: str,
        *,
        limit: int = 100,
    ) -> list[AuditRecord]:
        return [
            item
            for item in self.list_by_organization(organization_id, limit=limit)
            if item.action == action
        ]

    def list_by_source_event(self, source_event_id: UUID) -> list[AuditRecord]:
        with self._lock:
            return [
                item
                for item in self._records
                if item.source_event_id == source_event_id
            ]

    def verify_integrity(self, organization_id: UUID) -> bool:
        records = self.list_by_organization(organization_id, limit=1000)
        for record in records:
            material = _audit_hash_material(record)
            if record.fingerprint != record_fingerprint(material):
                return False
        return True

    def health(self) -> HealthSnapshot:
        return HealthSnapshot(
            component="AuditRepository",
            status=HealthStatus.HEALTHY,
            availability=True,
            safe_metadata={"implementation": "memory"},
        )


class ObservabilityRepository(ABC):
    """Append-only repository for projected metrics, logs, traces, alerts and health."""

    @abstractmethod
    def append_metric(self, record: MetricRecord) -> MetricRecord:
        raise NotImplementedError

    @abstractmethod
    def append_log(self, record: StructuredLogRecord) -> StructuredLogRecord:
        raise NotImplementedError

    @abstractmethod
    def append_trace(self, record: TraceRecord) -> TraceRecord:
        raise NotImplementedError

    @abstractmethod
    def append_alert(self, record: AlertSignal) -> AlertSignal:
        raise NotImplementedError

    @abstractmethod
    def append_health(self, record: HealthSnapshot) -> HealthSnapshot:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> HealthSnapshot:
        raise NotImplementedError


class InMemoryObservabilityRepository(ObservabilityRepository):
    """In-memory append-only repository for observability projections."""

    def __init__(self) -> None:
        self.metrics: list[MetricRecord] = []
        self.logs: list[StructuredLogRecord] = []
        self.traces: dict[UUID, TraceRecord] = {}
        self.alerts: dict[tuple[str, UUID], AlertSignal] = {}
        self.health_snapshots: list[HealthSnapshot] = []

    def append_metric(self, record: MetricRecord) -> MetricRecord:
        if not any(item.metric_id == record.metric_id for item in self.metrics):
            self.metrics.append(record)
        return record

    def append_log(self, record: StructuredLogRecord) -> StructuredLogRecord:
        if not any(item.log_id == record.log_id for item in self.logs):
            self.logs.append(record)
        return record

    def append_trace(self, record: TraceRecord) -> TraceRecord:
        self.traces.setdefault(record.trace_id, record)
        return self.traces[record.trace_id]

    def append_alert(self, record: AlertSignal) -> AlertSignal:
        key = (record.rule_id, record.source_event_id)
        self.alerts.setdefault(key, record)
        return self.alerts[key]

    def append_health(self, record: HealthSnapshot) -> HealthSnapshot:
        self.health_snapshots.append(record)
        return record

    def health(self) -> HealthSnapshot:
        return HealthSnapshot(
            component="ObservabilityRepository",
            status=HealthStatus.HEALTHY,
            availability=True,
            safe_metadata={"implementation": "memory"},
        )


def _ordered(events: list[StoredEvent]) -> list[StoredEvent]:
    return sorted(
        events,
        key=lambda item: (
            item.stored_sequence,
            item.event.occurred_at,
            str(item.event.event_id),
        ),
    )


def _audit_hash_material(record: AuditRecord) -> dict[str, Any]:
    return {
        "source_event_id": str(record.source_event_id),
        "organization_id": str(record.organization_id),
        "session_id": None if record.session_id is None else str(record.session_id),
        "plan_id": None if record.plan_id is None else str(record.plan_id),
        "correlation_id": None
        if record.correlation_id is None
        else str(record.correlation_id),
        "timestamp": record.timestamp.isoformat(),
        "sequence": record.sequence,
        "component": record.component,
        "action": record.action,
        "decision": record.decision.value,
        "outcome": record.outcome,
        "policy_references": list(record.policy_references),
        "reason_codes": list(record.reason_codes),
        "safe_metadata": record.safe_metadata,
    }


def audit_hash_material(record: AuditRecord) -> dict[str, Any]:
    """Expose deterministic audit hash material for projectors/tests."""
    return _audit_hash_material(record)


def validate_query_organization(organization_id: UUID | None) -> UUID:
    """Require explicit organization scope for queries."""
    if organization_id is None:
        raise QueryInvalidError("organization_id is required")
    return organization_id

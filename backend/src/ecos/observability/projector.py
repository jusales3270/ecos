"""Deterministic projectors from immutable events to observability records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid5

from ecos.events.models import Event, EventType
from ecos.observability.models import (
    AlertSeverity,
    AlertSignal,
    AuditDecision,
    AuditRecord,
    LogSeverity,
    MetricRecord,
    MetricType,
    ObservabilityLevel,
    StructuredLogRecord,
    TraceRecord,
    TraceSpan,
    TraceStatus,
)
from ecos.observability.repository import (
    AuditRepository,
    ObservabilityRepository,
    audit_hash_material,
    record_fingerprint,
)

_PROJECTOR_NAMESPACE = UUID("11111111-2222-4333-8444-555555555555")

_AUDITABLE: dict[EventType, tuple[str, AuditDecision]] = {
    EventType.SESSION_CREATED: ("session_created", AuditDecision.RECORDED),
    EventType.PIPELINE_STARTED: ("session_started", AuditDecision.RECORDED),
    EventType.PIPELINE_COMPLETED: ("session_completed", AuditDecision.RECORDED),
    EventType.PIPELINE_CANCELLED: ("session_cancelled", AuditDecision.RECORDED),
    EventType.AUTHORIZATION_GRANTED: ("authorization_granted", AuditDecision.GRANTED),
    EventType.AUTHORIZATION_DENIED: ("authorization_denied", AuditDecision.DENIED),
    EventType.POLICY_VIOLATION_DETECTED: ("policy_violation", AuditDecision.DENIED),
    EventType.APPROVAL_REQUESTED: ("approval_requested", AuditDecision.REQUESTED),
    EventType.APPROVAL_GRANTED: ("approval_granted", AuditDecision.GRANTED),
    EventType.APPROVAL_REJECTED: ("approval_rejected", AuditDecision.DENIED),
    EventType.APPROVAL_REVOKED: ("approval_revoked", AuditDecision.DENIED),
    EventType.APPROVAL_EXPIRED: ("approval_expired", AuditDecision.DENIED),
    EventType.EXECUTION_STARTED: ("execution_started", AuditDecision.RECORDED),
    EventType.EXECUTION_COMPLETED: ("execution_completed", AuditDecision.RECORDED),
    EventType.EXECUTION_FAILED: ("execution_failed", AuditDecision.FAILED),
    EventType.EXECUTION_ROLLED_BACK: ("execution_rolled_back", AuditDecision.RECORDED),
    EventType.ROLLBACK_FAILED: ("rollback_failed", AuditDecision.FAILED),
    EventType.HUMAN_TASK_CREATED: ("human_task_created", AuditDecision.REQUESTED),
    EventType.HUMAN_TASK_COMPLETED: ("human_task_completed", AuditDecision.RECORDED),
    EventType.ARTIFACT_GENERATED: ("artifact_created", AuditDecision.RECORDED),
    EventType.OBSERVATION_COMPLETED: ("observation_completed", AuditDecision.RECORDED),
    EventType.LEARNING_VALIDATED: ("learning_validated", AuditDecision.GRANTED),
    EventType.LEARNING_REJECTED: ("learning_rejected", AuditDecision.DENIED),
    EventType.MEMORY_UPDATED: ("memory_update_confirmed", AuditDecision.RECORDED),
    EventType.MEMORY_IMPROVED: ("memory_improved", AuditDecision.RECORDED),
    EventType.AUTHENTICATION_SUCCEEDED: (
        "authentication_succeeded",
        AuditDecision.GRANTED,
    ),
    EventType.AUTHENTICATION_FAILED: ("authentication_failed", AuditDecision.DENIED),
    EventType.ACCESS_DENIED: ("access_denied", AuditDecision.DENIED),
    EventType.CROSS_TENANT_ACCESS_ATTEMPTED: (
        "cross_tenant_access_attempted",
        AuditDecision.DENIED,
    ),
    EventType.AUTH_SESSION_CREATED: ("auth_session_created", AuditDecision.RECORDED),
    EventType.AUTH_SESSION_REVOKED: ("auth_session_revoked", AuditDecision.RECORDED),
    EventType.SECURITY_ROLE_CHANGED: ("security_role_changed", AuditDecision.RECORDED),
    EventType.PRIVILEGED_EXECUTION_REQUESTED: (
        "privileged_execution_requested",
        AuditDecision.REQUESTED,
    ),
}

_COUNTER_METRICS: dict[EventType, tuple[str, ObservabilityLevel]] = {
    EventType.SESSION_CREATED: ("sessions.created", ObservabilityLevel.PLATFORM),
    EventType.SESSION_COMPLETED: ("sessions.completed", ObservabilityLevel.PLATFORM),
    EventType.PIPELINE_FAILED: ("sessions.failed", ObservabilityLevel.PLATFORM),
    EventType.ENGINE_INVOKED: ("engine.invocations", ObservabilityLevel.COGNITIVE),
    EventType.ENGINE_COMPLETED: ("engine.completed", ObservabilityLevel.COGNITIVE),
    EventType.ENGINE_FAILED: ("engine.failed", ObservabilityLevel.COGNITIVE),
    EventType.ENGINE_RETRYING: ("engine.retries", ObservabilityLevel.COGNITIVE),
    EventType.ENGINE_TIMED_OUT: ("engine.timeouts", ObservabilityLevel.COGNITIVE),
    EventType.AUTHORIZATION_GRANTED: (
        "governance.authorization_granted",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.AUTHORIZATION_DENIED: (
        "governance.authorization_denied",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.APPROVAL_REQUESTED: (
        "governance.approval_requested",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.APPROVAL_GRANTED: (
        "governance.approval_granted",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.APPROVAL_REJECTED: (
        "governance.approval_rejected",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.EXECUTION_STARTED: ("execution.started", ObservabilityLevel.PLATFORM),
    EventType.EXECUTION_COMPLETED: ("execution.completed", ObservabilityLevel.PLATFORM),
    EventType.EXECUTION_FAILED: ("execution.failed", ObservabilityLevel.PLATFORM),
    EventType.EXECUTION_ROLLED_BACK: (
        "execution.rolled_back",
        ObservabilityLevel.PLATFORM,
    ),
    EventType.OBSERVATION_COMPLETED: (
        "observation.completed",
        ObservabilityLevel.COGNITIVE,
    ),
    EventType.OBSERVATION_INCONCLUSIVE: (
        "observation.inconclusive",
        ObservabilityLevel.COGNITIVE,
    ),
    EventType.LEARNING_COMPLETED: ("learning.completed", ObservabilityLevel.COGNITIVE),
    EventType.LEARNING_VALIDATED: (
        "learning.validated_candidates",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.LEARNING_REJECTED: (
        "learning.rejected_candidates",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.MEMORY_UPDATED: ("memory.updates", ObservabilityLevel.ORGANIZATIONAL),
    EventType.KNOWLEDGE_ENTITY_CREATED: (
        "knowledge.entities.created",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.KNOWLEDGE_ENTITY_VERSIONED: (
        "knowledge.entities.versioned",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.KNOWLEDGE_RELATIONSHIP_CREATED: (
        "knowledge.relationships.created",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.KNOWLEDGE_RELATIONSHIP_VERSIONED: (
        "knowledge.relationships.versioned",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.SEMANTIC_SEARCH_COMPLETED: (
        "knowledge.searches",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.CONTEXT_EXPANDED: (
        "knowledge.context_expansions",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.GRAPH_INTEGRITY_FAILED: (
        "knowledge.integrity.failures",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.KNOWLEDGE_PROJECTION_FAILED: (
        "knowledge.projections.failed",
        ObservabilityLevel.ORGANIZATIONAL,
    ),
    EventType.AUTHENTICATION_SUCCEEDED: (
        "security.authentication_succeeded",
        ObservabilityLevel.PLATFORM,
    ),
    EventType.AUTHENTICATION_FAILED: (
        "security.authentication_failed",
        ObservabilityLevel.PLATFORM,
    ),
    EventType.ACCESS_DENIED: ("security.access_denied", ObservabilityLevel.PLATFORM),
    EventType.CROSS_TENANT_ACCESS_ATTEMPTED: (
        "security.cross_tenant_attempts",
        ObservabilityLevel.PLATFORM,
    ),
    EventType.AUTH_SESSION_CREATED: (
        "security.sessions_created",
        ObservabilityLevel.PLATFORM,
    ),
    EventType.AUTH_SESSION_REVOKED: (
        "security.sessions_revoked",
        ObservabilityLevel.PLATFORM,
    ),
}

_START_EVENTS: dict[EventType, str] = {
    EventType.PLANNING_STARTED: "planning",
    EventType.PIPELINE_STARTED: "pipeline",
    EventType.ENGINE_INVOKED: "engine",
    EventType.GOVERNANCE_STARTED: "governance",
    EventType.EXECUTION_STARTED: "execution",
    EventType.OBSERVATION_STARTED: "observation",
    EventType.LEARNING_STARTED: "learning",
}

_END_EVENTS: dict[EventType, TraceStatus] = {
    EventType.PLANNING_COMPLETED: TraceStatus.COMPLETED,
    EventType.PIPELINE_COMPLETED: TraceStatus.COMPLETED,
    EventType.PIPELINE_FAILED: TraceStatus.FAILED,
    EventType.ENGINE_COMPLETED: TraceStatus.COMPLETED,
    EventType.ENGINE_FAILED: TraceStatus.FAILED,
    EventType.ENGINE_TIMED_OUT: TraceStatus.FAILED,
    EventType.GOVERNANCE_COMPLETED: TraceStatus.COMPLETED,
    EventType.GOVERNANCE_FAILED: TraceStatus.FAILED,
    EventType.EXECUTION_COMPLETED: TraceStatus.COMPLETED,
    EventType.EXECUTION_FAILED: TraceStatus.FAILED,
    EventType.OBSERVATION_COMPLETED: TraceStatus.COMPLETED,
    EventType.OBSERVATION_FAILED: TraceStatus.FAILED,
    EventType.LEARNING_COMPLETED: TraceStatus.COMPLETED,
    EventType.LEARNING_FAILED: TraceStatus.FAILED,
}


class AuditProjector:
    """Project auditable events to persistent audit records."""

    projector_id = "audit"
    replay_safe = True

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    def project(
        self, event: Event, *, stored_sequence: int, is_replay: bool = False
    ) -> None:
        if event.event_type not in _AUDITABLE or event.organization_id is None:
            return
        action, decision = _AUDITABLE[event.event_type]
        record_id = uuid5(_PROJECTOR_NAMESPACE, f"audit:{event.event_id}:{action}")
        draft = AuditRecord(
            audit_id=record_id,
            source_event_id=event.event_id,
            governance_id=_uuid_payload(event, "governance_id"),
            execution_id=_uuid_payload(event, "execution_id"),
            organization_id=event.organization_id,
            session_id=event.session_id,
            plan_id=_uuid_payload(event, "plan_id"),
            correlation_id=event.correlation_id,
            timestamp=event.occurred_at,
            sequence=stored_sequence,
            component=event.source_component,
            action=action,
            resource_type=_resource_type(event),
            resource_reference=_resource_reference(event),
            decision=decision,
            outcome=str(event.payload.get("status") or event.event_type.value),
            policy_references=_split_payload(event, "policy_references"),
            reason_codes=event.reason_codes or _split_payload(event, "reason_codes"),
            fingerprint="0" * 64,
            safe_metadata={"projection": "audit", "is_replay": is_replay},
        )
        fingerprint = record_fingerprint(audit_hash_material(draft))
        record = draft.model_copy(update={"fingerprint": fingerprint})
        self._repository.append(record)


class MetricProjector:
    """Project factual events into technical and cognitive metrics."""

    projector_id = "metrics"
    replay_safe = True

    def __init__(self, repository: ObservabilityRepository) -> None:
        self._repository = repository

    def project(
        self, event: Event, *, stored_sequence: int, is_replay: bool = False
    ) -> None:
        del stored_sequence, is_replay
        if event.organization_id is None:
            return
        if event.event_type in _COUNTER_METRICS:
            metric_name, level = _COUNTER_METRICS[event.event_type]
            self._repository.append_metric(
                MetricRecord(
                    metric_id=uuid5(
                        _PROJECTOR_NAMESPACE,
                        f"metric:{event.event_id}:{metric_name}",
                    ),
                    metric_name=metric_name,
                    metric_type=MetricType.COUNTER,
                    level=level,
                    organization_id=event.organization_id,
                    session_id=event.session_id,
                    correlation_id=event.correlation_id,
                    component=event.source_component,
                    value=1.0,
                    unit="count",
                    occurred_at=event.occurred_at,
                    dimensions=_safe_dimensions(event),
                    source_event_id=event.event_id,
                )
            )
        for payload_key, metric_name in (
            ("duration_seconds", "engine.duration_seconds"),
            ("quality_score", "observation.quality_score"),
            ("confidence", "recommendation.confidence"),
            ("context_completeness", "context.completeness"),
            ("duration_seconds", "knowledge.search.duration_seconds"),
            ("entity_count", "knowledge.context.entity_count"),
            ("relationship_count", "knowledge.context.relationship_count"),
            ("cost_units", "relative.cost_units"),
        ):
            value = event.payload.get(payload_key)
            if not isinstance(value, int | float):
                continue
            metric_type = (
                MetricType.DURATION if "duration" in payload_key else MetricType.SCORE
            )
            if payload_key in {"entity_count", "relationship_count"}:
                metric_type = MetricType.GAUGE
            if payload_key == "cost_units":
                metric_type = MetricType.COST_UNITS
            self._repository.append_metric(
                MetricRecord(
                    metric_id=uuid5(
                        _PROJECTOR_NAMESPACE,
                        f"metric:{event.event_id}:{metric_name}",
                    ),
                    metric_name=metric_name,
                    metric_type=metric_type,
                    level=ObservabilityLevel.COGNITIVE,
                    organization_id=event.organization_id,
                    session_id=event.session_id,
                    correlation_id=event.correlation_id,
                    component=event.source_component,
                    value=float(value),
                    unit="seconds" if metric_type is MetricType.DURATION else None,
                    occurred_at=event.occurred_at,
                    dimensions=_safe_dimensions(event),
                    source_event_id=event.event_id,
                )
            )


class TraceProjector:
    """Project trace snapshots from each event correlation context."""

    projector_id = "trace"
    replay_safe = True

    def __init__(self, repository: ObservabilityRepository) -> None:
        self._repository = repository

    def project(
        self, event: Event, *, stored_sequence: int, is_replay: bool = False
    ) -> None:
        del stored_sequence, is_replay
        if event.organization_id is None or event.correlation_id is None:
            return
        operation = _START_EVENTS.get(event.event_type)
        status = TraceStatus.RUNNING
        started_at: datetime | None = event.occurred_at
        completed_at: datetime | None = None
        if event.event_type in _END_EVENTS:
            operation = _end_operation(event)
            status = _END_EVENTS[event.event_type]
            started_at = event.occurred_at
            completed_at = event.occurred_at
        if operation is None:
            return
        trace_id = uuid5(_PROJECTOR_NAMESPACE, f"trace:{event.correlation_id}")
        span = TraceSpan(
            span_id=uuid5(
                _PROJECTOR_NAMESPACE,
                f"span:{event.correlation_id}:{event.event_id}",
            ),
            trace_id=trace_id,
            component=event.source_component,
            operation=operation,
            stage_id=_string_payload(event, "stage_id"),
            engine=_string_payload(event, "engine"),
            started_at=started_at,
            completed_at=completed_at,
            duration=0.0 if completed_at is not None else None,
            status=status,
            attempt=int(event.payload.get("attempt") or 1),
            source_event_ids=(event.event_id,),
        )
        record = TraceRecord(
            trace_id=trace_id,
            organization_id=event.organization_id,
            session_id=event.session_id,
            correlation_id=event.correlation_id,
            started_at=event.occurred_at if started_at else None,
            completed_at=completed_at,
            status=status if status is not TraceStatus.RUNNING else TraceStatus.RUNNING,
            spans=(span,),
            root_component=event.source_component,
            event_count=1,
            error_count=1 if status is TraceStatus.FAILED else 0,
        )
        self._repository.append_trace(record)


class AlertProjector:
    """Project deterministic alert signals without external delivery."""

    projector_id = "alerts"
    replay_safe = True

    def __init__(self, repository: ObservabilityRepository) -> None:
        self._repository = repository

    def project(
        self, event: Event, *, stored_sequence: int, is_replay: bool = False
    ) -> None:
        del stored_sequence, is_replay
        if event.organization_id is None:
            return
        rule_id: str | None = None
        severity = AlertSeverity.WARNING
        if event.event_type in {EventType.ENGINE_FAILED, EventType.GOVERNANCE_FAILED}:
            rule_id = "engine_failure"
            severity = AlertSeverity.ERROR
        elif event.event_type is EventType.ENGINE_TIMED_OUT:
            rule_id = "repeated_timeout"
        elif event.event_type is EventType.POLICY_VIOLATION_DETECTED:
            rule_id = "policy_violation"
            severity = AlertSeverity.ERROR
        elif event.event_type is EventType.EXECUTION_FAILED:
            rule_id = "execution_failure"
            severity = AlertSeverity.ERROR
        elif event.event_type is EventType.ROLLBACK_FAILED:
            rule_id = "rollback_failure"
            severity = AlertSeverity.CRITICAL
        elif event.event_type is EventType.TRACE_INCOMPLETE:
            rule_id = "trace_incomplete"
        if rule_id is None:
            return
        self._repository.append_alert(
            AlertSignal(
                alert_id=uuid5(
                    _PROJECTOR_NAMESPACE, f"alert:{rule_id}:{event.event_id}"
                ),
                rule_id=rule_id,
                organization_id=event.organization_id,
                session_id=event.session_id,
                correlation_id=event.correlation_id,
                severity=severity,
                component=event.source_component,
                source_event_id=event.event_id,
                safe_message=f"{rule_id} detected",
                reason_codes=(event.event_type.value,),
            )
        )


class StructuredLogProjector:
    """Project selected diagnostic logs without duplicating every event."""

    projector_id = "structured_logs"
    replay_safe = True

    def __init__(self, repository: ObservabilityRepository) -> None:
        self._repository = repository

    def project(
        self, event: Event, *, stored_sequence: int, is_replay: bool = False
    ) -> None:
        del stored_sequence
        if event.organization_id is None:
            return
        if event.event_type not in {
            EventType.ENGINE_FAILED,
            EventType.PIPELINE_FAILED,
            EventType.GOVERNANCE_FAILED,
            EventType.EXECUTION_FAILED,
            EventType.OBSERVABILITY_DEGRADED,
        }:
            return
        self._repository.append_log(
            StructuredLogRecord(
                log_id=uuid5(_PROJECTOR_NAMESPACE, f"log:{event.event_id}"),
                timestamp=event.occurred_at,
                severity=LogSeverity.ERROR,
                organization_id=event.organization_id,
                session_id=event.session_id,
                correlation_id=event.correlation_id,
                component=event.source_component,
                event_id=event.event_id,
                message_code=event.event_type.value,
                safe_message=f"{event.event_type.value} reported",
                classification=event.classification.value,
                reason_codes=(event.event_type.value,),
                safe_metadata={"is_replay": is_replay},
            )
        )


def _uuid_payload(event: Event, key: str) -> UUID | None:
    value = event.payload.get(key)
    if value in (None, ""):
        return None
    return UUID(str(value))


def _string_payload(event: Event, key: str) -> str | None:
    value = event.payload.get(key)
    return None if value in (None, "") else str(value)


def _split_payload(event: Event, key: str) -> tuple[str, ...]:
    value = event.payload.get(key)
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(item for item in value.split(",") if item)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return (str(value),)


def _safe_dimensions(event: Event) -> dict[str, str]:
    dimensions: dict[str, str] = {"component": event.source_component}
    for key in ("engine", "status", "stage_id"):
        value = event.payload.get(key)
        if value is not None:
            dimensions[key] = str(value)[:100]
    return dimensions


def _resource_type(event: Event) -> str | None:
    if event.event_type.name.startswith("APPROVAL"):
        return "approval"
    if event.event_type.name.startswith("EXECUTION"):
        return "execution"
    if event.event_type.name.startswith("MEMORY"):
        return "memory"
    return None


def _resource_reference(event: Event) -> str | None:
    for key in ("governance_id", "execution_id", "memory_id", "plan_id"):
        value = event.payload.get(key)
        if value is not None:
            return str(value)
    return None


def _end_operation(event: Event) -> str:
    name = event.event_type.value.lower()
    for suffix in ("_completed", "_failed", "_timed_out"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name

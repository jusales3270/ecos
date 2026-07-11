"""Exceptions for persistent event, audit and observability infrastructure."""

from ecos.core.exceptions import EcosError


class ObservabilityError(EcosError):
    """Base error for observability infrastructure failures."""

    def __init__(
        self,
        message: str,
        code: str = "OBSERVABILITY_ERROR",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details or {})


class InvalidEventError(ObservabilityError):
    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message, "INVALID_EVENT", details)


class MissingOrganizationError(InvalidEventError):
    code = "missing_organization"


class MissingCorrelationError(InvalidEventError):
    code = "missing_correlation"


class SerializationError(InvalidEventError):
    code = "serialization_error"


class SensitiveFieldError(InvalidEventError):
    code = "sensitive_field"


class ConflictingEventError(ObservabilityError):
    code = "conflicting_event"


class EventStoreUnavailableError(ObservabilityError):
    code = "event_store_unavailable"


class AppendFailedError(ObservabilityError):
    code = "append_failed"


class QueryInvalidError(ObservabilityError):
    code = "query_invalid"


class InvalidReplayError(ObservabilityError):
    code = "invalid_replay"


class DuplicateConsumerError(ObservabilityError):
    code = "duplicate_consumer"


class ConsumerNotReplaySafeError(ObservabilityError):
    code = "consumer_not_replay_safe"


class DuplicateProjectorError(ObservabilityError):
    code = "duplicate_projector"


class ProjectorFailedError(ObservabilityError):
    code = "projector_failed"


class InvalidAuditRecordError(ObservabilityError):
    code = "invalid_audit_record"


class AuditConflictError(ObservabilityError):
    code = "audit_conflict"


class AuditIntegrityError(ObservabilityError):
    code = "audit_integrity_failed"


class InvalidMetricError(ObservabilityError):
    code = "invalid_metric"


class InvalidTraceError(ObservabilityError):
    code = "invalid_trace"


class InvalidStructuredLogError(ObservabilityError):
    code = "invalid_structured_log"


class InvalidAlertRuleError(ObservabilityError):
    code = "invalid_alert_rule"


class HealthCheckFailedError(ObservabilityError):
    code = "health_check_failed"

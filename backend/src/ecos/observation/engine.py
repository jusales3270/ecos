"""Real deterministic ECOS Observation Engine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from math import isfinite
from uuid import UUID

from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.observation.exceptions import (
    ObservationIdempotencyConflictError,
    ObservationValidationError,
)
from ecos.observation.models import (
    AnomalySignal,
    ComparisonOperator,
    ComparisonStatus,
    Deviation,
    DeviationDirection,
    ExpectedOutcome,
    Measurement,
    ObservationEvidence,
    ObservationQuality,
    ObservationRequest,
    ObservationResult,
    ObservationSourceType,
    ObservationTimelineEntry,
    ObservedOutcome,
    ObservedOutcomeStatus,
    OutcomeComparison,
)
from ecos.observation.provider import (
    FeedbackProvider,
    MeasurementProvider,
    ObservationIdempotencyProvider,
)
from ecos.observation.repository import (
    InMemoryObservationRepository,
    ObservationRepository,
)
from ecos.outbox import terminal_event_id

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]

_SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "private_key"}


class ObservationConfig:
    """Immutable observation quality and anomaly policy."""

    def __init__(
        self,
        *,
        anomaly_relative_threshold: float = 0.25,
        low_quality_threshold: float = 0.5,
    ) -> None:
        self.anomaly_relative_threshold = anomaly_relative_threshold
        self.low_quality_threshold = low_quality_threshold


class ObservationEngine:
    """Measure declared organizational outcomes without strategic reasoning."""

    def __init__(
        self,
        *,
        measurement_provider: MeasurementProvider,
        feedback_provider: FeedbackProvider,
        idempotency_provider: ObservationIdempotencyProvider,
        event_service: EventService,
        clock: Clock,
        id_generator: IdGenerator,
        config: ObservationConfig,
        repository: ObservationRepository | None = None,
    ) -> None:
        self._measurement_provider = measurement_provider
        self._feedback_provider = feedback_provider
        self._idempotency_provider = idempotency_provider
        self._event_service = event_service
        self._clock = clock
        self._id_generator = id_generator
        self._config = config
        self._repository = repository or InMemoryObservationRepository()

    def observe(self, request: ObservationRequest) -> ObservationResult:
        """Observe facts and return an immutable ObservationResult."""
        self._validate_request(request)
        execution_fingerprint = self._execution_result_fingerprint(request)
        canonical_fingerprint = self._canonical_fingerprint(
            request, execution_fingerprint
        )
        if self._repository is not None and request.execution_id is not None:
            persisted = self._repository.get(
                request.organization_id, request.execution_id
            )
            if persisted is not None:
                self._validate_persisted(
                    request,
                    persisted,
                    canonical_fingerprint,
                    execution_fingerprint,
                )
                return persisted
        key = self._idempotency_key(request)
        fingerprint = self._fingerprint(request)
        existing = self._idempotency_provider.get(key)
        if existing is not None:
            existing_fingerprint, existing_result = existing
            if existing_fingerprint != fingerprint:
                self._publish(request, EventType.IDEMPOTENCY_CONFLICT, {})
                msg = "observation idempotency conflict"
                raise ObservationIdempotencyConflictError(msg)
            self._publish(request, EventType.IDEMPOTENCY_HIT, {})
            return existing_result  # type: ignore[return-value]

        started_at = self._clock()
        timeline: list[ObservationTimelineEntry] = []
        self._append(timeline, started_at, "started", "running", request.source_id)
        self._publish(
            request, EventType.OBSERVATION_STARTED, {"source_id": request.source_id}
        )
        measurements = self._measurement_provider.collect(request)
        feedback = self._feedback_provider.collect(request)
        self._validate_measurements(request, measurements)
        evidence = self._evidence(request, measurements, feedback)
        for measurement in measurements:
            self._publish(
                request,
                EventType.MEASUREMENT_COLLECTED,
                {
                    "measurement_id": measurement.measurement_id,
                    "metric_key": measurement.metric_key,
                    "verified": measurement.verified,
                },
            )
        for item in evidence:
            self._publish(
                request,
                EventType.EVIDENCE_RECORDED,
                {"evidence_id": item.evidence_id, "verified": item.verified},
            )
        for item in feedback:
            self._publish(
                request,
                EventType.FEEDBACK_RECORDED,
                {"feedback_id": item.feedback_id, "verified": item.verified_identity},
            )
        comparisons = tuple(
            self._compare(
                expectation, self._select_measurement(expectation, measurements)
            )
            for expectation in request.expected_outcomes
        )
        for comparison in comparisons:
            self._publish(
                request,
                EventType.OUTCOME_COMPARED,
                {
                    "metric_key": comparison.metric_key,
                    "status": comparison.status.value,
                },
            )
        deviations = tuple(
            self._deviation(index, item) for index, item in enumerate(comparisons, 1)
        )
        for deviation in deviations:
            if deviation.direction is not DeviationDirection.NEUTRAL:
                self._publish(
                    request,
                    EventType.DEVIATION_DETECTED,
                    {
                        "metric_key": deviation.metric_key,
                        "direction": deviation.direction.value,
                    },
                )
        anomalies = self._anomalies(comparisons)
        for anomaly in anomalies:
            self._publish(
                request,
                EventType.ANOMALY_DETECTED,
                {"metric_key": anomaly.metric_key, "signal": anomaly.signal},
            )
        quality = self._quality(request, measurements, comparisons, evidence)
        outcome_score = self._outcome_score(
            request.expected_outcomes, comparisons, quality
        )
        status = self._status(request, comparisons, outcome_score)
        if self._execution_failed(request):
            outcome_score = 0.0
        confidence = self._confidence(measurements, quality)
        if status in {
            ObservedOutcomeStatus.INCONCLUSIVE,
            ObservedOutcomeStatus.NOT_OBSERVED,
        }:
            self._publish(
                request,
                EventType.OBSERVATION_INCONCLUSIVE,
                {"status": status.value},
            )
        completed_at = self._clock()
        self._append(
            timeline, completed_at, "completed", status.value, request.source_id
        )
        observed = ObservedOutcome(
            outcome_id=f"outcome:{request.source_id}",
            status=status,
            score=outcome_score,
            confidence=confidence,
            evidence_references=tuple(
                item.evidence_id for item in evidence if not item.sensitive
            ),
            reason_codes=(f"observation_{status.value}",),
        )
        observation_id = self._id_generator()
        result = ObservationResult(
            observation_id=observation_id,
            observation_request_id=request.observation_request_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            correlation_id=request.correlation_id,
            execution_id=request.execution_id,
            source_event_id=request.source_event_id,
            source_type=request.source_type,
            source_id=request.source_id,
            status=status,
            fingerprint=canonical_fingerprint,
            execution_result_fingerprint=execution_fingerprint,
            observed_outcomes=(observed,),
            comparisons=comparisons,
            deviations=deviations,
            anomalies=anomalies,
            measurements=measurements,
            evidence=evidence,
            feedback=feedback,
            quality=quality,
            outcome_score=outcome_score,
            confidence=confidence,
            started_at=started_at,
            completed_at=completed_at,
            duration=max((completed_at - started_at).total_seconds(), 0.0),
            timeline=tuple(timeline),
            reason_codes=(f"observation_{status.value}",),
            warnings=quality.warnings,
            safe_metadata=dict(request.safe_metadata),
        )
        if self._repository is not None and request.execution_id is not None:
            terminal_type = (
                EventType.OBSERVATION_FAILED
                if result.status is ObservedOutcomeStatus.FAILED
                else EventType.OBSERVATION_COMPLETED
            )
            event = self._terminal_event(request, terminal_type, result)
            result = self._repository.save_terminal(result, event)
            if result.observation_id != observation_id:
                self._idempotency_provider.put(key, fingerprint, result)
                return result
            if not self._repository.supports_transactional_outbox:
                envelope = self._event_service.publish(event)
                self._event_service.dispatch(envelope)
        self._idempotency_provider.put(key, fingerprint, result)
        if request.execution_id is None:
            self._publish(
                request,
                EventType.OBSERVATION_COMPLETED,
                self._terminal_payload(result),
            )
        return result

    def _validate_request(self, request: ObservationRequest) -> None:
        if request.source_type not in set(ObservationSourceType):
            msg = "unknown observation source type"
            raise ObservationValidationError(msg)
        if self._has_sensitive_metadata(request.safe_metadata):
            msg = "safe_metadata contains sensitive keys"
            raise ObservationValidationError(msg)
        if (
            request.execution_result is None
            and request.decision_package is None
            and request.recommendation is None
            and not request.expected_outcomes
            and not request.observed_measurements
            and not request.feedback
            and not request.organizational_metrics
            and not request.simulation_results
        ):
            msg = "observation requires at least one observable source"
            raise ObservationValidationError(msg)
        if request.execution_result is not None:
            for attr, expected in (
                ("organization_id", request.organization_id),
                ("session_id", request.session_id),
                ("plan_id", request.plan_id),
            ):
                actual = getattr(request.execution_result, attr, expected)
                if actual != expected:
                    msg = f"execution_result {attr} mismatch"
                    raise ObservationValidationError(msg)
            if request.execution_id != getattr(
                request.execution_result, "execution_id", None
            ):
                raise ObservationValidationError(
                    "execution_result execution_id mismatch"
                )
        for outcome in request.expected_outcomes:
            if self._has_sensitive_metadata(outcome.safe_metadata):
                msg = "expected outcome metadata contains sensitive keys"
                raise ObservationValidationError(msg)

    def _validate_measurements(
        self,
        request: ObservationRequest,
        measurements: tuple[Measurement, ...],
    ) -> None:
        ids = [item.measurement_id for item in measurements]
        if len(ids) != len(set(ids)):
            msg = "duplicate measurement_id"
            raise ObservationValidationError(msg)
        evidence_ids = {
            reference for item in measurements for reference in item.evidence_references
        }
        if "" in evidence_ids:
            msg = "evidence references cannot be blank"
            raise ObservationValidationError(msg)
        for item in measurements:
            if self._has_sensitive_metadata(item.safe_metadata):
                msg = "measurement metadata contains sensitive keys"
                raise ObservationValidationError(msg)
            if request.observation_window is not None:
                if not (
                    request.observation_window.started_at
                    <= item.observed_at
                    <= request.observation_window.ended_at
                ):
                    msg = "measurement timestamp outside observation window"
                    raise ObservationValidationError(msg)

    def _evidence(
        self,
        request: ObservationRequest,
        measurements: tuple[Measurement, ...],
        feedback: tuple[object, ...],
    ) -> tuple[ObservationEvidence, ...]:
        recorded_at = self._clock()
        evidence: list[ObservationEvidence] = []
        for measurement in measurements:
            for reference in measurement.evidence_references:
                evidence.append(
                    ObservationEvidence(
                        evidence_id=reference,
                        source_reference=measurement.source.source_id,
                        description=f"measurement:{measurement.metric_key}",
                        recorded_at=recorded_at,
                        verified=measurement.verified,
                        sensitive=measurement.sensitive,
                        reason_codes=measurement.reason_codes,
                    )
                )
        for item in feedback:
            feedback_id = item.feedback_id
            evidence.append(
                ObservationEvidence(
                    evidence_id=f"feedback:{feedback_id}",
                    source_reference=request.source_id,
                    description="feedback reference",
                    recorded_at=recorded_at,
                    verified=item.verified_identity,
                    sensitive=item.sensitive,
                    reason_codes=item.reason_codes,
                )
            )
        return tuple(sorted(evidence, key=lambda item: item.evidence_id))

    def _select_measurement(
        self,
        expectation: ExpectedOutcome,
        measurements: tuple[Measurement, ...],
    ) -> Measurement | None:
        candidates = [
            item for item in measurements if item.metric_key == expectation.metric_key
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                not item.verified,
                -item.confidence,
                item.observed_at.isoformat(),
                item.measurement_id,
            ),
        )[0]

    def _compare(
        self,
        expectation: ExpectedOutcome,
        measurement: Measurement | None,
    ) -> OutcomeComparison:
        if measurement is None:
            status = (
                ComparisonStatus.NOT_OBSERVED
                if expectation.required
                else ComparisonStatus.INCONCLUSIVE
            )
            return OutcomeComparison(
                expected_outcome_id=expectation.expected_outcome_id,
                metric_key=expectation.metric_key,
                operator=expectation.comparison_operator,
                status=status,
                expected_value=expectation.expected_value,
                normalized_score=0.0,
                reason_codes=("measurement_missing",),
            )
        expected = (
            expectation.expected_status
            if expectation.expected_status is not None
            else expectation.expected_value
        )
        observed = measurement.value
        matched, exceeded = self._match(
            expectation.comparison_operator,
            expected,
            observed,
            expectation.tolerance,
        )
        absolute, relative = self._numeric_deviation(expected, observed)
        score = self._comparison_score(
            matched, absolute, relative, expectation.tolerance
        )
        if exceeded:
            status = ComparisonStatus.EXCEEDED
        elif matched:
            status = ComparisonStatus.MATCHED
        elif score > 0.0:
            status = ComparisonStatus.PARTIALLY_MET
        else:
            status = ComparisonStatus.MISSED
        return OutcomeComparison(
            expected_outcome_id=expectation.expected_outcome_id,
            metric_key=expectation.metric_key,
            operator=expectation.comparison_operator,
            status=status,
            expected_value=expected,
            observed_value=observed,
            normalized_score=score,
            absolute_deviation=absolute,
            relative_deviation=relative,
            direction=self._direction(
                expected, observed, expectation.comparison_operator, matched
            ),
            evidence_references=measurement.evidence_references
            if not measurement.sensitive
            else (),
            reason_codes=(f"comparison_{status.value}",),
        )

    def _match(
        self,
        operator: ComparisonOperator,
        expected: object,
        observed: object,
        tolerance: float,
    ) -> tuple[bool, bool]:
        if operator is ComparisonOperator.EXISTS:
            return observed is not None, False
        if operator is ComparisonOperator.NOT_EXISTS:
            return observed is None, False
        if operator is ComparisonOperator.EQUALS:
            return observed == expected, False
        if operator is ComparisonOperator.NOT_EQUALS:
            return observed != expected, False
        if operator is ComparisonOperator.CONTAINS:
            return str(expected) in str(observed), False
        if operator is ComparisonOperator.NOT_CONTAINS:
            return str(expected) not in str(observed), False
        if operator is ComparisonOperator.IN:
            return observed in expected if isinstance(
                expected, list | tuple | set
            ) else False, False
        if operator is ComparisonOperator.NOT_IN:
            return observed not in expected if isinstance(
                expected, list | tuple | set
            ) else False, False
        expected_number = self._number(expected)
        observed_number = self._number(observed)
        if expected_number is None or observed_number is None:
            return False, False
        if operator is ComparisonOperator.GREATER_THAN:
            return observed_number > expected_number, observed_number > expected_number
        if operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
            return observed_number >= expected_number, observed_number > expected_number
        if operator is ComparisonOperator.LESS_THAN:
            return observed_number < expected_number, observed_number < expected_number
        if operator is ComparisonOperator.LESS_THAN_OR_EQUAL:
            return observed_number <= expected_number, observed_number < expected_number
        if operator is ComparisonOperator.WITHIN_TOLERANCE:
            return abs(observed_number - expected_number) <= tolerance, False
        return False, False

    def _comparison_score(
        self,
        matched: bool,
        absolute: float | None,
        relative: float | None,
        tolerance: float,
    ) -> float:
        if matched:
            return 1.0
        if absolute is None:
            return 0.0
        allowance = max(tolerance, 0.0)
        if allowance > 0.0:
            return _clamp(1.0 - (absolute / max(allowance * 2.0, 1e-9)))
        if relative is None:
            return 0.0
        return _clamp(1.0 - min(relative, 1.0))

    def _numeric_deviation(
        self, expected: object, observed: object
    ) -> tuple[float | None, float | None]:
        expected_number = self._number(expected)
        observed_number = self._number(observed)
        if expected_number is None or observed_number is None:
            return None, None
        absolute = abs(observed_number - expected_number)
        if expected_number == 0:
            relative = None
        else:
            relative = abs(absolute / expected_number)
        return absolute, relative

    def _direction(
        self,
        expected: object,
        observed: object,
        operator: ComparisonOperator,
        matched: bool,
    ) -> DeviationDirection:
        expected_number = self._number(expected)
        observed_number = self._number(observed)
        if expected_number is None or observed_number is None:
            return DeviationDirection.NEUTRAL if matched else DeviationDirection.UNKNOWN
        if observed_number == expected_number:
            return DeviationDirection.NEUTRAL
        favorable_high = operator in {
            ComparisonOperator.GREATER_THAN,
            ComparisonOperator.GREATER_THAN_OR_EQUAL,
        }
        favorable_low = operator in {
            ComparisonOperator.LESS_THAN,
            ComparisonOperator.LESS_THAN_OR_EQUAL,
        }
        if favorable_high:
            return (
                DeviationDirection.POSITIVE
                if observed_number > expected_number
                else DeviationDirection.NEGATIVE
            )
        if favorable_low:
            return (
                DeviationDirection.POSITIVE
                if observed_number < expected_number
                else DeviationDirection.NEGATIVE
            )
        return (
            DeviationDirection.NEGATIVE if not matched else DeviationDirection.NEUTRAL
        )

    def _deviation(self, index: int, comparison: OutcomeComparison) -> Deviation:
        return Deviation(
            deviation_id=f"deviation:{index}:{comparison.metric_key}",
            metric_key=comparison.metric_key,
            direction=comparison.direction,
            magnitude=comparison.absolute_deviation,
            relative_magnitude=comparison.relative_deviation,
            comparison_id=comparison.expected_outcome_id,
            reason_codes=comparison.reason_codes,
        )

    def _anomalies(
        self, comparisons: tuple[OutcomeComparison, ...]
    ) -> tuple[AnomalySignal, ...]:
        anomalies: list[AnomalySignal] = []
        for index, comparison in enumerate(comparisons, 1):
            if (
                comparison.relative_deviation is not None
                and comparison.relative_deviation
                > self._config.anomaly_relative_threshold
            ):
                anomalies.append(
                    AnomalySignal(
                        anomaly_id=f"anomaly:{index}:{comparison.metric_key}",
                        metric_key=comparison.metric_key,
                        signal="relative_deviation_above_threshold",
                        severity=_clamp(comparison.relative_deviation),
                        evidence_references=comparison.evidence_references,
                        reason_codes=("relative_deviation_threshold",),
                    )
                )
            if comparison.status is ComparisonStatus.MISSED:
                anomalies.append(
                    AnomalySignal(
                        anomaly_id=f"anomaly:{index}:{comparison.metric_key}:missed",
                        metric_key=comparison.metric_key,
                        signal="status_incompatible",
                        severity=1.0,
                        evidence_references=comparison.evidence_references,
                        reason_codes=("expected_outcome_missed",),
                    )
                )
        return tuple(anomalies)

    def _quality(
        self,
        request: ObservationRequest,
        measurements: tuple[Measurement, ...],
        comparisons: tuple[OutcomeComparison, ...],
        evidence: tuple[ObservationEvidence, ...],
    ) -> ObservationQuality:
        required_metrics = tuple(
            item.metric_key for item in request.expected_outcomes if item.required
        )
        observed_metrics = {item.metric_key for item in measurements}
        missing = tuple(
            metric for metric in required_metrics if metric not in observed_metrics
        )
        completeness = (
            1.0
            if not required_metrics
            else _clamp(1.0 - (len(missing) / len(required_metrics)))
        )
        verified_count = sum(1 for item in measurements if item.verified)
        verified_ratio = 1.0 if not measurements else verified_count / len(measurements)
        evidence_quality = (
            0.0
            if not evidence
            else sum(1.0 if item.verified else 0.5 for item in evidence) / len(evidence)
        )
        reliability = (
            0.0
            if not measurements
            else sum(item.source.reliability for item in measurements)
            / len(measurements)
        )
        consistency = 0.5 if self._has_conflict(comparisons) else 1.0
        warnings = []
        if missing:
            warnings.append("required metrics missing")
        if consistency < 1.0:
            warnings.append("conflicting evidence")
        reason_codes = ["quality_calculated"]
        if missing:
            reason_codes.append("missing_required_metrics")
        return ObservationQuality(
            completeness_score=_clamp(completeness),
            evidence_quality_score=_clamp(evidence_quality),
            source_reliability_score=_clamp(reliability),
            timeliness_score=1.0,
            consistency_score=consistency,
            verified_measurement_ratio=_clamp(verified_ratio),
            missing_metrics=missing,
            conflicting_evidence=tuple(
                item.metric_key for item in comparisons if self._has_conflict((item,))
            ),
            warnings=tuple(warnings),
            reason_codes=tuple(reason_codes),
        )

    def _outcome_score(
        self,
        expectations: tuple[ExpectedOutcome, ...],
        comparisons: tuple[OutcomeComparison, ...],
        quality: ObservationQuality,
    ) -> float:
        if not expectations:
            return 0.0
        total_weight = sum(item.weight for item in expectations)
        if total_weight <= 0.0:
            return 0.0
        by_id = {item.expected_outcome_id: item for item in expectations}
        weighted = sum(
            comparison.normalized_score * by_id[comparison.expected_outcome_id].weight
            for comparison in comparisons
        )
        required_penalty = 1.0
        if quality.missing_metrics:
            required_penalty = max(0.0, 1.0 - (0.5 * len(quality.missing_metrics)))
        quality_factor = (
            quality.completeness_score
            + quality.evidence_quality_score
            + quality.verified_measurement_ratio
        ) / 3.0
        return _clamp((weighted / total_weight) * required_penalty * quality_factor)

    def _status(
        self,
        request: ObservationRequest,
        comparisons: tuple[OutcomeComparison, ...],
        outcome_score: float,
    ) -> ObservedOutcomeStatus:
        status_value = self._execution_status(request)
        if "rolled_back" in status_value or "rollback" in status_value:
            return ObservedOutcomeStatus.ROLLED_BACK
        if "cancelled" in status_value or "canceled" in status_value:
            return ObservedOutcomeStatus.CANCELLED
        if self._execution_failed(request):
            return ObservedOutcomeStatus.FAILED
        if not comparisons:
            return ObservedOutcomeStatus.NOT_OBSERVED
        required = [item for item in request.expected_outcomes if item.required]
        by_id = {item.expected_outcome_id: item for item in comparisons}
        required_statuses = [
            by_id[item.expected_outcome_id].status for item in required
        ]
        if any(item is ComparisonStatus.NOT_OBSERVED for item in required_statuses):
            return ObservedOutcomeStatus.INCONCLUSIVE
        if any(item is ComparisonStatus.MISSED for item in required_statuses):
            return ObservedOutcomeStatus.FAILED
        if required and all(
            item in {ComparisonStatus.MATCHED, ComparisonStatus.EXCEEDED}
            for item in required_statuses
        ):
            return ObservedOutcomeStatus.SUCCESSFUL
        if outcome_score > 0.0:
            return ObservedOutcomeStatus.PARTIALLY_SUCCESSFUL
        return ObservedOutcomeStatus.INCONCLUSIVE

    def _confidence(
        self,
        measurements: tuple[Measurement, ...],
        quality: ObservationQuality,
    ) -> float:
        measurement_confidence = (
            0.0
            if not measurements
            else sum(item.confidence for item in measurements) / len(measurements)
        )
        quality_score = (
            quality.completeness_score
            + quality.evidence_quality_score
            + quality.source_reliability_score
            + quality.consistency_score
            + quality.verified_measurement_ratio
        ) / 5.0
        return _clamp(measurement_confidence * quality_score)

    def _append(
        self,
        timeline: list[ObservationTimelineEntry],
        timestamp: datetime,
        action: str,
        status: str,
        source_reference: str,
    ) -> None:
        timeline.append(
            ObservationTimelineEntry(
                sequence=len(timeline) + 1,
                timestamp=timestamp,
                component="observation",
                action=action,
                status=status,
                source_reference=source_reference,
            )
        )

    def _publish(
        self,
        request: ObservationRequest,
        event_type: EventType,
        payload: dict[str, str | int | float | bool | None],
    ) -> None:
        safe_payload = {
            key: value
            for key, value in payload.items()
            if key.lower() not in _SENSITIVE_KEYS
        }
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="observation",
                session_id=request.session_id,
                organization_id=request.organization_id,
                payload=safe_payload,
                metadata=EventMetadata(
                    correlation_id=request.correlation_id,
                    causation_id=request.source_event_id,
                    attributes={
                        "organization_id": str(request.organization_id),
                        "plan_id": str(request.plan_id),
                    },
                ),
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)

    @staticmethod
    def _terminal_payload(
        result: ObservationResult,
    ) -> dict[str, str | int | float | bool | None]:
        return {
            "observation_id": str(result.observation_id),
            "execution_id": None
            if result.execution_id is None
            else str(result.execution_id),
            "status": result.status.value,
            "fingerprint": result.fingerprint,
            "durable_reference": f"observation:{result.observation_id}",
        }

    def _terminal_event(
        self,
        request: ObservationRequest,
        event_type: EventType,
        result: ObservationResult,
    ) -> Event:
        return Event(
            id=terminal_event_id(
                organization_id=request.organization_id,
                aggregate_type="observation",
                aggregate_id=result.observation_id,
                event_type=event_type.value,
            ),
            event_type=event_type,
            source="observation",
            session_id=request.session_id,
            organization_id=request.organization_id,
            payload=self._terminal_payload(result),
            metadata=EventMetadata(
                correlation_id=request.correlation_id,
                causation_id=request.source_event_id,
                attributes={
                    "organization_id": str(request.organization_id),
                    "plan_id": str(request.plan_id),
                },
            ),
            priority=EventPriority.NORMAL,
        )

    def _idempotency_key(self, request: ObservationRequest) -> str:
        window = (
            request.observation_window.model_dump(mode="json")
            if request.observation_window
            else {}
        )
        payload = {
            "organization_id": str(request.organization_id),
            "session_id": str(request.session_id),
            "plan_id": str(request.plan_id),
            "execution_id": None
            if request.execution_id is None
            else str(request.execution_id),
            "source_type": request.source_type.value,
            "source_id": request.source_id,
            "window": window,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _fingerprint(self, request: ObservationRequest) -> str:
        data = request.model_dump(
            mode="json",
            exclude={
                "execution_result",
                "decision_package",
                "recommendation",
                "simulation_results",
            },
        )
        execution_result = request.execution_result
        data["execution_id"] = (
            None if request.execution_id is None else str(request.execution_id)
        )
        data["execution_result_fingerprint"] = getattr(
            execution_result, "fingerprint", None
        )
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _execution_result_fingerprint(request: ObservationRequest) -> str:
        value = getattr(request.execution_result, "fingerprint", None)
        if isinstance(value, str) and len(value) == 64:
            return value
        return hashlib.sha256(b"no-execution-result").hexdigest()

    @staticmethod
    def _canonical_fingerprint(
        request: ObservationRequest, execution_result_fingerprint: str
    ) -> str:
        payload = {
            "organization_id": str(request.organization_id),
            "session_id": str(request.session_id),
            "execution_id": None
            if request.execution_id is None
            else str(request.execution_id),
            "correlation_id": str(request.correlation_id),
            "execution_result_fingerprint": execution_result_fingerprint,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _validate_persisted(
        request: ObservationRequest,
        result: ObservationResult,
        fingerprint: str,
        execution_result_fingerprint: str,
    ) -> None:
        if (
            result.organization_id != request.organization_id
            or result.session_id != request.session_id
            or result.execution_id != request.execution_id
            or result.correlation_id != request.correlation_id
            or result.fingerprint != fingerprint
            or result.execution_result_fingerprint != execution_result_fingerprint
        ):
            raise ObservationIdempotencyConflictError(
                "persisted observation scope or fingerprint conflict"
            )

    @staticmethod
    def _execution_status(request: ObservationRequest) -> str:
        status = getattr(request.execution_result, "status", "")
        return str(getattr(status, "value", status)).lower()

    def _execution_failed(self, request: ObservationRequest) -> bool:
        result = request.execution_result
        if result is None:
            return False
        status = self._execution_status(request)
        if status in {
            "failed",
            "cancelled",
            "canceled",
            "rolling_back",
            "rolled_back",
            "rollback_failed",
        }:
            return True
        failures = tuple(getattr(result, "failures", ()) or ())
        rollback_results = tuple(getattr(result, "rollback_results", ()) or ())
        return bool(failures or rollback_results)

    def _number(self, value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        number = float(value)
        return number if isfinite(number) else None

    def _has_conflict(self, comparisons: tuple[OutcomeComparison, ...]) -> bool:
        by_metric: dict[str, set[ComparisonStatus]] = {}
        for item in comparisons:
            by_metric.setdefault(item.metric_key, set()).add(item.status)
        return any(len(statuses) > 1 for statuses in by_metric.values())

    def _has_sensitive_metadata(
        self, metadata: dict[str, str | int | float | bool | None]
    ) -> bool:
        return any(key.lower() in _SENSITIVE_KEYS for key in metadata)


def _clamp(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)

"""Observation provider ports and deterministic in-memory implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ecos.observation.models import FeedbackRecord, Measurement, ObservationRequest


class MeasurementProvider(ABC):
    """Port for deterministic measurement collection."""

    @abstractmethod
    def collect(self, request: ObservationRequest) -> tuple[Measurement, ...]:
        """Return measurements available for a request."""
        raise NotImplementedError


class FeedbackProvider(ABC):
    """Port for deterministic feedback collection."""

    @abstractmethod
    def collect(self, request: ObservationRequest) -> tuple[FeedbackRecord, ...]:
        """Return feedback available for a request."""
        raise NotImplementedError


class ObservationIdempotencyProvider(ABC):
    """Port for in-memory observation idempotency."""

    @abstractmethod
    def get(self, key: str) -> tuple[str, object] | None:
        """Return fingerprint and result for a key."""
        raise NotImplementedError

    @abstractmethod
    def put(self, key: str, fingerprint: str, result: object) -> None:
        """Store fingerprint and result for a key."""
        raise NotImplementedError


class InMemoryMeasurementProvider(MeasurementProvider):
    """Deterministic provider that returns request-bound measurements."""

    def collect(self, request: ObservationRequest) -> tuple[Measurement, ...]:
        """Return supplied request measurements in deterministic order."""
        return tuple(
            sorted(
                (*request.observed_measurements, *request.organizational_metrics),
                key=lambda item: (
                    item.metric_key,
                    item.observed_at.isoformat(),
                    item.measurement_id,
                ),
            )
        )


class InMemoryFeedbackProvider(FeedbackProvider):
    """Deterministic provider that returns request-bound feedback."""

    def collect(self, request: ObservationRequest) -> tuple[FeedbackRecord, ...]:
        """Return supplied feedback in deterministic order."""
        return tuple(
            sorted(
                request.feedback,
                key=lambda item: (item.submitted_at.isoformat(), item.feedback_id),
            )
        )


class InMemoryObservationIdempotencyProvider(ObservationIdempotencyProvider):
    """Process-local idempotency store for observation retries."""

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, object]] = {}

    def get(self, key: str) -> tuple[str, object] | None:
        """Return an idempotency record."""
        return self._records.get(key)

    def put(self, key: str, fingerprint: str, result: object) -> None:
        """Store an idempotency record."""
        self._records[key] = (fingerprint, result)

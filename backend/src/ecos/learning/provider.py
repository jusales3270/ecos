"""Learning provider ports and deterministic in-memory implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ecos.learning.models import LearningCandidate


class LearningHistoryProvider(ABC):
    """Port for learning recurrence history."""

    @abstractmethod
    def recurrence_count(self, signature: str) -> int:
        """Return recurrence count for a deterministic signature."""
        raise NotImplementedError

    @abstractmethod
    def distinct_sources(self, signature: str) -> int:
        """Return distinct source count for a signature."""
        raise NotImplementedError

    @abstractmethod
    def record(self, signature: str, source_reference: str) -> None:
        """Record a candidate occurrence."""
        raise NotImplementedError


class LearningPolicyProvider(ABC):
    """Narrow policy port for learning validation."""

    @abstractmethod
    def blocks(self, candidate: LearningCandidate) -> bool:
        """Return whether policy blocks a candidate."""
        raise NotImplementedError

    @abstractmethod
    def requires_human_review(self, candidate: LearningCandidate) -> bool:
        """Return whether candidate needs human review."""
        raise NotImplementedError


class LearningIdempotencyProvider(ABC):
    """Port for in-memory learning idempotency."""

    @abstractmethod
    def get(self, key: str) -> tuple[str, object] | None:
        """Return fingerprint and result for a key."""
        raise NotImplementedError

    @abstractmethod
    def put(self, key: str, fingerprint: str, result: object) -> None:
        """Store fingerprint and result for a key."""
        raise NotImplementedError


class InMemoryLearningHistoryProvider(LearningHistoryProvider):
    """Process-local recurrence history."""

    def __init__(self) -> None:
        self._sources_by_signature: dict[str, set[str]] = {}
        self._counts: dict[str, int] = {}

    def recurrence_count(self, signature: str) -> int:
        """Return occurrence count."""
        return self._counts.get(signature, 0)

    def distinct_sources(self, signature: str) -> int:
        """Return distinct source count."""
        return len(self._sources_by_signature.get(signature, set()))

    def record(self, signature: str, source_reference: str) -> None:
        """Record an occurrence."""
        self._counts[signature] = self._counts.get(signature, 0) + 1
        self._sources_by_signature.setdefault(signature, set()).add(source_reference)


class DefaultLearningPolicyProvider(LearningPolicyProvider):
    """Deterministic policy with review for strategic or critical work."""

    def blocks(self, candidate: LearningCandidate) -> bool:
        """Block candidates explicitly marked as policy blocked."""
        return "policy_blocked" in candidate.reason_codes

    def requires_human_review(self, candidate: LearningCandidate) -> bool:
        """Require human review for strategic, critical or flagged candidates."""
        impact = candidate.safe_metadata.get("impact")
        return (
            candidate.category.value == "strategy"
            or impact == "critical"
            or candidate.human_review_required
        )


class InMemoryLearningIdempotencyProvider(LearningIdempotencyProvider):
    """Process-local idempotency store for learning retries."""

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, object]] = {}

    def get(self, key: str) -> tuple[str, object] | None:
        """Return an idempotency record."""
        return self._records.get(key)

    def put(self, key: str, fingerprint: str, result: object) -> None:
        """Store an idempotency record."""
        self._records[key] = (fingerprint, result)

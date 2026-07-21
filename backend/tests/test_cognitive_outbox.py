"""Focused delivery, claim, retry, and identity tests for the cognitive outbox."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from ecos.events import Event, EventMetadata, EventService, EventType
from ecos.observability import InMemoryEventStore, RedactionPolicy
from ecos.outbox import (
    InMemoryOutboxRepository,
    OutboxConflictError,
    OutboxService,
    OutboxStatus,
    message_from_event,
    terminal_event_id,
)
from ecos.runtime import FakeEventBus

ORG_ID = UUID("00000000-0000-4000-8000-000000000101")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000102")
EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000103")
CORRELATION_ID = UUID("00000000-0000-4000-8000-000000000104")


def _event(*, payload: dict[str, object] | None = None) -> Event:
    return Event(
        id=terminal_event_id(
            organization_id=ORG_ID,
            aggregate_type="execution",
            aggregate_id=EXECUTION_ID,
            event_type=EventType.EXECUTION_COMPLETED.value,
        ),
        event_type=EventType.EXECUTION_COMPLETED,
        source="execution",
        organization_id=ORG_ID,
        session_id=SESSION_ID,
        payload=payload
        or {
            "execution_id": str(EXECUTION_ID),
            "status": "completed",
            "artifact": "reference-only",
        },
        metadata=EventMetadata(correlation_id=CORRELATION_ID),
        created_at=datetime.now(UTC),
    )


def _message(event: Event | None = None):
    return message_from_event(
        event or _event(),
        actor_id=None,
        aggregate_type="execution",
        aggregate_id=str(EXECUTION_ID),
        execution_id=EXECUTION_ID,
    )


def test_atomic_claim_lease_recovery_and_version_fencing() -> None:
    repository = InMemoryOutboxRepository()
    message = repository.enqueue(_message())

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(
                lambda owner: repository.claim(
                    limit=1, stale_after=timedelta(minutes=5), owner=owner
                ),
                ("worker-a", "worker-b"),
            )
        )
    claimed = [item for batch in claims for item in batch]
    assert len(claimed) == 1
    active = claimed[0]
    assert (
        repository.claim(limit=1, stale_after=timedelta(minutes=5), owner="worker-c")
        == []
    )
    assert not repository.mark_delivered(
        message.message_id, owner="worker-a", version=active.version - 1
    )

    repository._messages[message.message_id] = replace(
        active, claim_expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    recovered = repository.claim(
        limit=1, stale_after=timedelta(minutes=5), owner="worker-c"
    )
    assert len(recovered) == 1
    assert recovered[0].event_id == message.event_id
    assert recovered[0].attempts == 2
    assert repository.mark_delivered(
        message.message_id, owner="worker-c", version=recovered[0].version
    )
    assert not repository.mark_delivered(
        message.message_id, owner="worker-c", version=recovered[0].version
    )


def test_retry_after_ambiguous_timeout_keeps_event_id_and_event_record_unique() -> None:
    class AmbiguousBus(FakeEventBus):
        def __init__(self) -> None:
            super().__init__()
            self.fail_once = True

        def publish(self, event: Event):
            envelope = super().publish(event)
            if self.fail_once:
                self.fail_once = False
                raise TimeoutError("ambiguous transport timeout")
            return envelope

    repository = InMemoryOutboxRepository()
    message = repository.enqueue(_message())
    event_store = InMemoryEventStore(RedactionPolicy())
    bus = AmbiguousBus()
    service = OutboxService(
        repository,
        EventService(bus, event_store),
        max_attempts=3,
        batch_size=1,
    )

    first = service.process_once()
    assert first == {"claimed": 1, "delivered": 0, "failed": 1}
    failed = repository.list(ORG_ID)[0]
    assert failed.attempts == 1
    assert failed.event_id == message.event_id
    assert failed.last_error == "ambiguous transport timeout"
    assert failed.available_at > datetime.now(UTC)

    retry_at = datetime.now(UTC) - timedelta(seconds=1)
    repository._messages[message.message_id] = replace(
        failed, next_attempt_at=retry_at, available_at=retry_at
    )
    second = service.process_once()
    assert second == {"claimed": 1, "delivered": 1, "failed": 0}
    published = repository.list(ORG_ID)[0]
    assert published.status is OutboxStatus.DELIVERED
    assert published.event_id == message.event_id
    assert event_store.latest_sequence() == 1


def test_replay_is_idempotent_but_divergent_stable_event_conflicts() -> None:
    repository = InMemoryOutboxRepository()
    event = _event()
    original = repository.enqueue(_message(event))
    assert repository.enqueue(_message(event)) == original

    divergent = _event(payload={"execution_id": str(EXECUTION_ID), "status": "failed"})
    try:
        repository.enqueue(_message(divergent))
    except OutboxConflictError as error:
        assert "different event content" in str(error)
    else:
        raise AssertionError("divergent stable event_id was accepted")


def test_payload_is_reference_only_and_redacted() -> None:
    message = _message(
        _event(
            payload={
                "execution_id": str(EXECUTION_ID),
                "memory_content": "must-not-leak",
                "password": "must-not-leak",
            }
        )
    )
    assert message.payload["password"] == "[REDACTED]"
    assert message.payload["memory_content"] == "[REDACTED]"
    assert message.correlation_id == CORRELATION_ID
    assert message.organization_id == ORG_ID

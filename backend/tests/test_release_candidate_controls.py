"""Release candidate reliability/security controls."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest

from ecos.events import Event, EventMetadata, EventService, EventType
from ecos.observability import InMemoryEventStore, RedactionPolicy
from ecos.outbox import InMemoryOutboxRepository, OutboxService, message_from_event
from ecos.runtime import FakeEventBus
from ecos.security import AuthenticationError, Role, SecurityService
from ecos.security.controls import InMemorySecurityControlRepository, safe_hash
from ecos.security.repository import InMemorySecurityRepository


def test_jwt_key_ring_adds_kid_and_rejects_unknown_key() -> None:
    repository = InMemorySecurityRepository()
    service = SecurityService(
        repository,
        token_secret="active-secret-value-with-enough-length",
        token_key_ring={
            "active": "active-secret-value-with-enough-length",
            "previous": "previous-secret-value-with-enough-length",
        },
        active_key_id="active",
        issuer="ecos.test",
        audience="ecos.api",
        token_ttl=timedelta(minutes=5),
    )
    user, organization, _ = service.create_local_user(
        email="user@example.test",
        display_name="User",
        password="password",
        organization_name="Org",
        roles=(Role.ADMIN,),
    )
    token, _ = service.login(
        email=user.email,
        password="password",
        organization_id=organization.organization_id,
        correlation_id=UUID("00000000-0000-4000-8000-000000000001"),
    )

    assert jwt.get_unverified_header(token)["kid"] == "active"
    assert service.authenticate_bearer_token(
        token,
        correlation_id=UUID("00000000-0000-4000-8000-000000000002"),
    )

    payload = jwt.decode(
        token,
        options={"verify_signature": False},
        algorithms=["HS256"],
    )
    unknown = jwt.encode(
        payload,
        "unknown-secret-value-with-enough-length",
        algorithm="HS256",
        headers={"kid": "unknown"},
    )
    with pytest.raises(AuthenticationError):
        service.authenticate_bearer_token(
            unknown,
            correlation_id=UUID("00000000-0000-4000-8000-000000000003"),
        )


def test_login_throttle_blocks_and_resets_normalized_scope() -> None:
    repository = InMemorySecurityControlRepository()
    scope = safe_hash("login", "USER@EXAMPLE.TEST", "127.0.0.1")
    same_scope = safe_hash("login", "user@example.test", "127.0.0.1")

    for _ in range(2):
        decision = repository.record_login_failure(
            same_scope,
            organization_id=None,
            window=timedelta(minutes=5),
            limit=3,
            block_for=timedelta(minutes=1),
        )
        assert decision.allowed
    blocked = repository.record_login_failure(
        scope,
        organization_id=None,
        window=timedelta(minutes=5),
        limit=3,
        block_for=timedelta(minutes=1),
    )

    assert not blocked.allowed
    assert blocked.retry_after_seconds > 0
    repository.reset_login(scope)
    assert repository.check_login(scope, window=timedelta(minutes=5)).allowed


def test_rate_limit_returns_retry_after_for_fixed_window() -> None:
    repository = InMemorySecurityControlRepository()
    scope = safe_hash("user", "org", "POST", "/api/v1/sessions")

    first = repository.consume_rate_limit(
        scope,
        route_group="api_v1",
        limit=1,
        window=timedelta(minutes=1),
    )
    second = repository.consume_rate_limit(
        scope,
        route_group="api_v1",
        limit=1,
        window=timedelta(minutes=1),
    )

    assert first.allowed
    assert not second.allowed
    assert second.retry_after_seconds > 0


def test_in_memory_outbox_replays_event_idempotently() -> None:
    redaction = RedactionPolicy()
    event_store = InMemoryEventStore(redaction)
    event_service = EventService(
        FakeEventBus(),
        event_store,
        redaction_policy=redaction,
    )
    repository = InMemoryOutboxRepository()
    outbox = OutboxService(
        repository,
        event_service,
        max_attempts=3,
        batch_size=10,
    )
    event = Event(
        event_type=EventType.SESSION_CREATED,
        source="test",
        organization_id=UUID("00000000-0000-4000-8000-000000000010"),
        session_id=UUID("00000000-0000-4000-8000-000000000011"),
        payload={"password": "secret", "safe": "value"},
        metadata=EventMetadata(
            correlation_id=UUID("00000000-0000-4000-8000-000000000012")
        ),
        created_at=datetime.now(UTC),
    )
    message = message_from_event(
        event,
        actor_id=None,
        aggregate_type="session",
        aggregate_id=str(event.session_id),
    )

    repository.enqueue(message)
    repository.enqueue(message)
    result = outbox.process_once()
    second = outbox.process_once()

    assert result["delivered"] == 1
    assert second["claimed"] == 0
    assert event_store.latest_sequence() == 1
    stored = event_store.get_by_id(event.event_id)
    assert stored is not None
    assert stored.event.payload["password"] == "[REDACTED]"

"""Sprint 18B operational persistence, idempotency and reconciliation tests."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ecos.main import app
from ecos.operational.exceptions import (
    IdempotencyConflictError,
    OperationalConflictError,
)
from ecos.operational.models import OperationalSessionView
from ecos.operational.repository import (
    InMemoryOperationalRepository,
    idempotency_record,
    payload_fingerprint,
)

ORG = UUID("10000000-0000-4000-8000-000000000001")
USER = UUID("10000000-0000-4000-8000-000000000101")


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    csrf = response.cookies.get("ecos_csrf")
    assert csrf
    return csrf


def test_in_memory_operational_repository_persists_session_and_version() -> None:
    repository = InMemoryOperationalRepository()
    session = OperationalSessionView(
        organization_id=ORG,
        created_by=USER,
        created_by_email="operator@demo.ecos.local",
        objective="Persist state",
        correlation_id=uuid4(),
    )

    stored, version = repository.save_session(session, expected_version=0)
    loaded = repository.get_session(ORG, session.session_id)

    assert stored == session
    assert version == 1
    assert loaded == (session, 1)
    assert repository.list_sessions(ORG) == [session]


def test_in_memory_operational_repository_rejects_stale_version() -> None:
    repository = InMemoryOperationalRepository()
    session = OperationalSessionView(
        organization_id=ORG,
        created_by=USER,
        created_by_email="operator@demo.ecos.local",
        objective="Lock state",
        correlation_id=uuid4(),
    )
    repository.save_session(session, expected_version=0)

    with pytest.raises(OperationalConflictError, match="concurrently"):
        repository.save_session(session, expected_version=0)


def test_idempotency_key_replay_and_payload_conflict() -> None:
    repository = InMemoryOperationalRepository()
    payload = {"objective": "same"}
    record = idempotency_record(
        organization_id=ORG,
        user_id=USER,
        operation="session.create",
        key="same-key",
        request_hash=payload_fingerprint(payload),
        response_payload={"ok": True},
        resource_id=None,
        ttl=repository._idempotency_ttl,
    )

    assert repository.store_idempotency(record).response_payload == {"ok": True}
    assert repository.store_idempotency(record).response_payload == {"ok": True}

    with pytest.raises(IdempotencyConflictError):
        repository.store_idempotency(
            idempotency_record(
                organization_id=ORG,
                user_id=USER,
                operation="session.create",
                key="same-key",
                request_hash=payload_fingerprint({"objective": "different"}),
                response_payload={"ok": False},
                resource_id=None,
                ttl=repository._idempotency_ttl,
            )
        )


def test_api_idempotent_create_session_replays_same_result() -> None:
    with TestClient(app) as client:
        csrf = login(client, "operator@demo.ecos.local", "operator-demo-password")
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "create-session-key"}
        first = client.post(
            "/api/v1/sessions",
            json={"objective": "Idempotent create"},
            headers=headers,
        )
        second = client.post(
            "/api/v1/sessions",
            json={"objective": "Idempotent create"},
            headers=headers,
        )
        conflict = client.post(
            "/api/v1/sessions",
            json={"objective": "Different payload"},
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]
    assert conflict.status_code == 409


def test_second_approval_without_same_idempotency_key_conflicts() -> None:
    with TestClient(app) as client:
        operator_csrf = login(
            client, "operator@demo.ecos.local", "operator-demo-password"
        )
        created = client.post(
            "/api/v1/sessions",
            json={"objective": "Concurrent approval"},
            headers={"X-CSRF-Token": operator_csrf},
        ).json()
        started = client.post(
            f"/api/v1/sessions/{created['session_id']}/start",
            headers={"X-CSRF-Token": operator_csrf},
        ).json()
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": operator_csrf})
        approver_csrf = login(
            client, "approver@demo.ecos.local", "approver-demo-password"
        )
        approval_id = started["approval"]["approval_id"]
        first = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            headers={"X-CSRF-Token": approver_csrf},
        )
        second = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            headers={"X-CSRF-Token": approver_csrf},
        )

    assert first.status_code == 200
    assert second.status_code == 409

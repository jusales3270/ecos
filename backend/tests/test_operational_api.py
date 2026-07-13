"""Sprint 18A operational API tests."""

from fastapi.testclient import TestClient

from ecos.main import app


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    csrf = response.cookies.get("ecos_csrf")
    assert csrf
    return csrf


def test_api_v1_requires_authentication_and_csrf() -> None:
    with TestClient(app) as client:
        missing = client.get("/api/v1/overview")
        csrf = login(client, "operator@demo.ecos.local", "operator-demo-password")
        no_csrf = client.post(
            "/api/v1/sessions",
            json={"objective": "No csrf", "description": "blocked"},
        )
        created = client.post(
            "/api/v1/sessions",
            json={"objective": "With csrf", "description": "ok"},
            headers={"X-CSRF-Token": csrf},
        )

    assert missing.status_code == 401
    assert no_csrf.status_code == 401
    assert created.status_code == 200
    assert created.json()["organization_id"]


def test_operational_cycle_enforces_independent_approval_and_execution_gate() -> None:
    with TestClient(app) as client:
        operator_csrf = login(
            client,
            "operator@demo.ecos.local",
            "operator-demo-password",
        )
        created = client.post(
            "/api/v1/sessions",
            json={
                "objective": "Validate E2E",
                "description": "payload organization_id must be ignored",
                "organization_id": "20000000-0000-4000-8000-000000000002",
            },
            headers={"X-CSRF-Token": operator_csrf},
        ).json()
        started = client.post(
            f"/api/v1/sessions/{created['session_id']}/start",
            headers={"X-CSRF-Token": operator_csrf},
        ).json()
        approval_id = started["approval"]["approval_id"]
        execution_id = started["execution"]["execution_id"]

        blocked_execution = client.post(
            f"/api/v1/executions/{execution_id}/start",
            headers={"X-CSRF-Token": operator_csrf},
        )
        requester_approval = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            headers={"X-CSRF-Token": operator_csrf},
        )
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": operator_csrf})

        approver_csrf = login(
            client,
            "approver@demo.ecos.local",
            "approver-demo-password",
        )
        approved = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            headers={"X-CSRF-Token": approver_csrf},
        )
        executed = client.post(
            f"/api/v1/executions/{execution_id}/start",
            headers={"X-CSRF-Token": approver_csrf},
        )
        events = client.get("/api/v1/events")

    assert created["organization_id"] != "20000000-0000-4000-8000-000000000002"
    assert blocked_execution.status_code == 403
    assert requester_approval.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"
    assert executed.json()["observations"]
    assert executed.json()["learning"]
    assert any(item["event_type"] == "EXECUTION_COMPLETED" for item in events.json())


def test_rejection_and_cross_tenant_failure_are_safe() -> None:
    with TestClient(app) as client:
        operator_csrf = login(
            client, "operator@demo.ecos.local", "operator-demo-password"
        )
        session = client.post(
            "/api/v1/sessions",
            json={"objective": "Reject path"},
            headers={"X-CSRF-Token": operator_csrf},
        ).json()
        started = client.post(
            f"/api/v1/sessions/{session['session_id']}/start",
            headers={"X-CSRF-Token": operator_csrf},
        ).json()
        approval_id = started["approval"]["approval_id"]
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": operator_csrf})

        approver_csrf = login(
            client, "approver@demo.ecos.local", "approver-demo-password"
        )
        rejected = client.post(
            f"/api/v1/approvals/{approval_id}/reject",
            json={"reason": "insufficient evidence"},
            headers={"X-CSRF-Token": approver_csrf},
        )
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": approver_csrf})

        tenant_b_csrf = login(
            client,
            "operator@tenant-b.ecos.local",
            "tenant-b-demo-password",
        )
        cross = client.get(f"/api/v1/sessions/{session['session_id']}")
        metrics = client.get(
            "/api/v1/metrics",
            headers={"X-CSRF-Token": tenant_b_csrf},
        )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert cross.status_code == 403
    assert metrics.status_code == 403


def test_health_metrics_and_runtime_demo_contract() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        version = client.get("/health/version")
        metrics = client.get("/metrics")
        demo = client.post(
            "/runtime/demo",
            json={"objective": "Improve organizational decision quality"},
        )

    assert live.status_code == 200
    assert ready.status_code == 200
    assert version.status_code == 200
    assert "ecos_requests_total" in metrics.text
    assert demo.status_code == 200
    assert demo.json()["recommendation"] == (
        "Proceed using ECOS context, reasoning, debate and governance."
    )


def test_sara_interaction_requires_auth_and_creates_governed_session() -> None:
    with TestClient(app) as client:
        denied = client.post("/api/v1/sara/interactions", json={"message": "test"})
        csrf = login(client, "operator@demo.ecos.local", "operator-demo-password")
        result = client.post(
            "/api/v1/sara/interactions",
            json={
                "message": "Assess a bounded risk",
                "history": [],
                "route_context": "/governance",
            },
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "sara-test-create"},
        )
        session = client.get(f"/api/v1/sessions/{result.json()['session_id']}")
        resumed = client.post(
            "/api/v1/sara/interactions",
            json={
                "message": "Add context without execution",
                "session_id": result.json()["session_id"],
            },
            headers={"X-CSRF-Token": csrf},
        )
        updated = client.get(f"/api/v1/sessions/{result.json()['session_id']}")

    assert denied.status_code == 401
    assert result.status_code == 200
    assert result.json()["cognitive_state"] == "created"
    assert result.json()["ui_actions"] == [
        {"type": "open_session", "session_id": result.json()["session_id"]}
    ]
    assert session.json()["status"] == "created"
    assert session.json()["approval"] is None
    assert session.json()["execution"] is None
    assert resumed.status_code == 200
    assert updated.json()["timeline"][-1]["event_type"] == ("sara.interaction.received")
    assert "Add context" not in str(updated.json())


def test_sara_validation_history_limit_and_tenant_isolation() -> None:
    with TestClient(app) as client:
        csrf = login(client, "operator@demo.ecos.local", "operator-demo-password")
        created = client.post(
            "/api/v1/sara/interactions",
            json={"message": "tenant A"},
            headers={"X-CSRF-Token": csrf},
        ).json()
        invalid = client.post(
            "/api/v1/sara/interactions",
            json={"message": "", "history": [{"role": "user", "content": "x"}] * 13},
            headers={"X-CSRF-Token": csrf},
        )
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        other_csrf = login(
            client, "operator@tenant-b.ecos.local", "tenant-b-demo-password"
        )
        cross = client.post(
            "/api/v1/sara/interactions",
            json={"message": "cross", "session_id": created["session_id"]},
            headers={"X-CSRF-Token": other_csrf},
        )

    assert invalid.status_code == 422
    assert cross.status_code == 403

"""End-to-end API tests for governed runtime approval and execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

from ecos.events import EventType
from ecos.execution import ExecutionResult
from ecos.governance import ApprovalRequestStatus, GovernanceResult
from ecos.learning import LearningResult
from ecos.main import app
from ecos.observation import ObservationResult
from ecos.operational.service import DEMO_ORG_A
from ecos.runtime import RuntimeCheckpointStatus
from ecos.security import Role


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _logout(client: TestClient, csrf: str) -> None:
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200


def _create_board_user(container, index: int) -> tuple[UUID, str, str]:
    user_id = uuid4()
    email = f"governed-board-{user_id}@example.test"
    password = f"governed-board-password-{index}"
    container.security_service.create_local_user(
        email=email,
        display_name=f"Governed board member {index}",
        password=password,
        organization_name="ECOS Demo Organization",
        roles=(Role.EXECUTIVE_BOARD, Role.OPERATOR),
        user_id=user_id,
        organization_id=DEMO_ORG_A,
    )
    return user_id, email, password


def _start_runtime(client: TestClient, csrf: str, key: str) -> tuple[str, dict]:
    interaction = client.post(
        "/api/v1/sara/interactions",
        json={"message": f"Governed runtime {key}"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
    )
    assert interaction.status_code == 200
    session_id = str(interaction.json()["session_id"])
    approvals = client.get("/api/v1/approvals")
    assert approvals.status_code == 200
    approval = next(
        item for item in approvals.json() if item["session_id"] == session_id
    )
    return session_id, approval


def _governance(container, session_id: str) -> tuple[object, GovernanceResult]:
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        DEMO_ORG_A, UUID(session_id)
    )
    assert checkpoint is not None
    governance = container.authenticated_runtime_service.governance_result(checkpoint)
    return checkpoint, governance


def test_runtime_quorum_persists_partial_and_executes_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        container = client.app.state.container
        original_execute = container.execution_engine.execute_async
        execution_calls = 0

        async def count_execution(request):
            nonlocal execution_calls
            execution_calls += 1
            return await original_execute(request)

        monkeypatch.setattr(
            container.execution_engine, "execute_async", count_execution
        )
        operator_csrf = _login(
            client, "operator@demo.ecos.local", "operator-demo-password"
        )
        session_id, approval = _start_runtime(client, operator_csrf, "runtime-quorum")
        approval_id = approval["approval_id"]
        assert approval["status"] == "pending"
        assert approval["runtime_status"] == "waiting_approval"
        minimum = int(approval["minimum_approvals"])
        users = [_create_board_user(container, index) for index in range(minimum)]
        _logout(client, operator_csrf)

        final_response = None
        final_key = ""
        for index, (_, email, password) in enumerate(users, start=1):
            csrf = _login(client, email, password)
            key = f"runtime-approval-{index}"
            response = client.post(
                f"/api/v1/approvals/{approval_id}/approve",
                json={"reason": f"reviewed by board member {index}"},
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
            )
            assert response.status_code == 200
            if index < minimum:
                assert response.json()["status"] == "partially_approved"
                assert response.json()["runtime_status"] == "waiting_approval"
                assert execution_calls == 0
                _logout(client, csrf)
            else:
                final_response = response
                final_key = key

        assert final_response is not None
        assert final_response.json()["status"] == "approved"
        assert final_response.json()["runtime_status"] == "completed"
        assert execution_calls == 1
        replay = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": f"reviewed by board member {minimum}"},
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": final_key,
            },
        )
        assert replay.status_code == 200
        assert replay.json() == final_response.json()
        assert execution_calls == 1

        checkpoint, governance = _governance(container, session_id)
        assert checkpoint.status is RuntimeCheckpointStatus.COMPLETED
        assert checkpoint.resumable_state is None
        assert governance.approval_request is not None
        assert governance.approval_request.status is ApprovalRequestStatus.GRANTED
        assert len(governance.approval_request.current_approvals) == minimum
        artifacts = {
            item.engine: container.runtime_artifact_codec.decode(item.output)
            for item in checkpoint.stage_results
        }
        execution = artifacts["execution"]
        observation = artifacts["observation"]
        learning = artifacts["learning"]
        assert isinstance(execution, ExecutionResult)
        assert isinstance(observation, ObservationResult)
        assert isinstance(learning, LearningResult)
        assert observation.execution_id == execution.execution_id
        assert learning.execution_id == execution.execution_id
        assert learning.observation_id == observation.observation_id
        assert execution.correlation_id == checkpoint.correlation_id
        assert observation.correlation_id == checkpoint.correlation_id
        assert learning.correlation_id == checkpoint.correlation_id
        terminal_event = next(
            envelope.event
            for envelope in container.event_bus.envelopes
            if envelope.event.event_type is EventType.EXECUTION_COMPLETED
            and envelope.event.payload.get("execution_id")
            == str(execution.execution_id)
        )
        assert terminal_event.metadata.correlation_id == checkpoint.correlation_id


def test_runtime_approval_idempotency_and_actor_are_enforced() -> None:
    with TestClient(app) as client:
        container = client.app.state.container
        operator_csrf = _login(
            client, "operator@demo.ecos.local", "operator-demo-password"
        )
        session_id, approval = _start_runtime(
            client, operator_csrf, "runtime-idempotency"
        )
        approval_id = approval["approval_id"]
        actor_id, email, password = _create_board_user(container, 1)
        _logout(client, operator_csrf)
        csrf = _login(client, email, password)
        key = "stable-runtime-decision"
        missing_key = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "missing key"},
            headers={"X-CSRF-Token": csrf},
        )
        injected_identity = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "invalid identity", "actor_role": "executive_board"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "injected-key"},
        )
        first = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "first reviewed payload"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
        )
        payload_conflict = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "different payload"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
        )
        actor_conflict = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "same actor new key"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "other-key"},
        )

        assert missing_key.status_code == 409
        assert injected_identity.status_code == 422
        assert first.status_code == 200
        assert payload_conflict.status_code == 409
        assert actor_conflict.status_code == 409
        _, governance = _governance(container, session_id)
        assert governance.approval_request is not None
        decision = governance.approval_request.current_approvals[0]
        assert decision.approval_decision_id == uuid5(
            UUID(approval_id), f"{actor_id}:{key}"
        )
        assert decision.identity_reference == f"local:{actor_id}"
        assert decision.reason == "first reviewed payload"
        assert decision.actor_role == Role.EXECUTIVE_BOARD.value


def test_runtime_rejection_is_terminal_error_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        container = client.app.state.container
        execution_calls = 0

        async def reject_execution(_request):
            nonlocal execution_calls
            execution_calls += 1
            raise AssertionError("rejected runtime must not execute")

        monkeypatch.setattr(
            container.execution_engine, "execute_async", reject_execution
        )
        operator_csrf = _login(
            client, "operator@demo.ecos.local", "operator-demo-password"
        )
        session_id, approval = _start_runtime(client, operator_csrf, "runtime-reject")
        _, email, password = _create_board_user(container, 1)
        _logout(client, operator_csrf)
        csrf = _login(client, email, password)
        rejected = client.post(
            f"/api/v1/approvals/{approval['approval_id']}/reject",
            json={"reason": "residual risk is unacceptable"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "reject-key"},
        )
        state = client.get(f"/api/v1/sara/sessions/{session_id}/state")

        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["runtime_status"] == "error"
        assert rejected.json()["error_code"] == "RUNTIME_REJECTED"
        assert state.status_code == 200
        assert state.json()["runtime"]["state"] == "error"
        assert state.json()["runtime"]["error_code"] == "RUNTIME_REJECTED"
        assert execution_calls == 0
        checkpoint, governance = _governance(container, session_id)
        assert checkpoint.status is RuntimeCheckpointStatus.FAILED
        assert governance.approval_request is not None
        assert governance.approval_request.status is ApprovalRequestStatus.REJECTED
        assert governance.approval_request.current_rejections[0].reason == (
            "residual risk is unacceptable"
        )
        assert governance.audit_records[-1].action == "approval_rejected"


def test_runtime_approval_authority_expiry_and_tenant_isolation() -> None:
    with TestClient(app) as client:
        container = client.app.state.container
        requester_id, requester_email, requester_password = _create_board_user(
            container, 10
        )
        csrf = _login(client, requester_email, requester_password)
        session_id, approval = _start_runtime(client, csrf, "runtime-authority")
        approval_id = approval["approval_id"]
        self_approval = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "self approval"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "self-key"},
        )
        assert self_approval.status_code == 403
        assert str(requester_id) == approval["requester_id"]

        _logout(client, csrf)
        manager_csrf = _login(
            client,
            "approver@demo.ecos.local",
            "approver-demo-password",
        )
        wrong_role = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "manager outside required roles"},
            headers={
                "X-CSRF-Token": manager_csrf,
                "Idempotency-Key": "wrong-role-key",
            },
        )
        assert wrong_role.status_code == 403

        checkpoint, governance = _governance(container, session_id)
        request = governance.approval_request
        assert request is not None
        expired_request = request.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        expired_governance = governance.model_copy(
            update={
                "approval_request": expired_request,
                "approval_state": governance.approval_state.model_copy(
                    update={"approval_request": expired_request}
                )
                if governance.approval_state is not None
                else None,
            }
        )
        replacement = container.authenticated_runtime_service._replace_governance(
            checkpoint, expired_governance
        )
        container.runtime_checkpoint_repository.save(
            replacement, expected_version=checkpoint.version
        )
        _, approver_email, approver_password = _create_board_user(container, 11)
        _logout(client, manager_csrf)
        approver_csrf = _login(client, approver_email, approver_password)
        expired = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "expired approval"},
            headers={
                "X-CSRF-Token": approver_csrf,
                "Idempotency-Key": "expired-key",
            },
        )
        assert expired.status_code == 409

        _logout(client, approver_csrf)
        tenant_csrf = _login(
            client,
            "operator@tenant-b.ecos.local",
            "tenant-b-demo-password",
        )
        listed = client.get("/api/v1/approvals")
        cross = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reason": "cross tenant"},
            headers={
                "X-CSRF-Token": tenant_csrf,
                "Idempotency-Key": "tenant-key",
            },
        )
        assert all(item["approval_id"] != approval_id for item in listed.json())
        assert cross.status_code == 403

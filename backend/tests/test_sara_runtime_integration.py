"""Sprint 19D authenticated SARA runtime API integration tests."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from fastapi.testclient import TestClient

from ecos.core import Container, Settings
from ecos.domain import CognitiveSession, Objective, SessionStage
from ecos.main import app
from ecos.operational.exceptions import OperationalConflictError
from ecos.operational.service import DEMO_OPERATOR, DEMO_ORG_A
from ecos.runtime import (
    PostgresRuntimeCheckpointRepository,
    RuntimeCheckpointConflictError,
    RuntimeCheckpointStatus,
)
from ecos.security import AuthorizationError
from ecos.session import (
    ManagedSession,
    PostgresSessionRepository,
    SessionContext,
    SessionLifecycleStatus,
    SessionState,
)

TEST_DATABASE_URL = os.getenv("ECOS_TEST_DATABASE_URL")


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    csrf = response.cookies.get("ecos_csrf")
    assert csrf
    return csrf


def _create_interaction(
    client: TestClient,
    csrf: str,
    *,
    key: str = "sara-runtime-create",
) -> dict[str, object]:
    response = client.post(
        "/api/v1/sara/interactions",
        json={
            "message": "Assess authenticated runtime integration",
            "history": [{"role": "user", "content": "bounded UI context"}],
            "route_context": "/sessions",
        },
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
    )
    assert response.status_code == 200
    return response.json()


def _set_runtime_status(
    container,
    session_id: UUID,
    *,
    checkpoint_status: RuntimeCheckpointStatus,
    lifecycle_status: SessionLifecycleStatus,
) -> None:
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        DEMO_ORG_A, session_id
    )
    assert checkpoint is not None
    container.runtime_checkpoint_repository.save(
        checkpoint.model_copy(
            update={
                "status": checkpoint_status,
                "version": checkpoint.version + 1,
                "updated_at": datetime.now(UTC),
            }
        ),
        expected_version=checkpoint.version,
    )
    managed = container.session_service.get_session(session_id)
    assert managed is not None
    container.session_service.update_state(
        managed.state.model_copy(
            update={
                "lifecycle_status": lifecycle_status,
                "updated_at": datetime.now(UTC),
            }
        )
    )


def _principal(container: Container):
    _, principal = container.security_service.login(
        email="operator@demo.ecos.local",
        password="operator-demo-password",
        organization_id=DEMO_ORG_A,
        correlation_id=uuid4(),
    )
    return principal


def test_concurrent_interactions_acquire_runtime_start_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container(settings=Settings())
    principal = _principal(container)
    operational = container.operational_service.create_session(
        principal,
        objective="Concurrent SARA runtime",
        description="Atomic startup",
        correlation_id=uuid4(),
    )
    original_plan = container.planner_service.create_plan
    original_execute = container.orchestrator_service.execute
    planner_entered = Event()
    release_planner = Event()
    counter_lock = Lock()
    planner_calls = 0
    orchestrator_calls = 0

    def blocking_plan(planner_input):
        nonlocal planner_calls
        with counter_lock:
            planner_calls += 1
        planner_entered.set()
        assert release_planner.wait(timeout=10)
        return original_plan(planner_input)

    def count_execute(orchestration_input):
        nonlocal orchestrator_calls
        with counter_lock:
            orchestrator_calls += 1
        return original_execute(orchestration_input)

    monkeypatch.setattr(container.planner_service, "create_plan", blocking_plan)
    monkeypatch.setattr(container.orchestrator_service, "execute", count_execute)

    def interact(key: str):
        return container.operational_service.sara_interaction(
            principal,
            message=operational.objective,
            history=(),
            session_id=operational.session_id,
            route_context="/sessions",
            correlation_id=uuid4(),
            idempotency_key=key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner_future = executor.submit(interact, "concurrent-winner")
        assert planner_entered.wait(timeout=10)
        loser = interact("concurrent-loser")
        release_planner.set()
        winner = winner_future.result(timeout=10)

    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        DEMO_ORG_A, operational.session_id
    )
    assert planner_calls == 1
    assert orchestrator_calls == 1
    assert len(container.session_repository.sessions) == 1
    assert loser.runtime.state == "thinking"
    assert loser.runtime.lifecycle_status == SessionLifecycleStatus.CREATED.value
    assert winner.runtime.state == "waiting_approval"
    assert checkpoint is not None
    assert checkpoint.status is RuntimeCheckpointStatus.WAITING_APPROVAL


def test_runtime_start_claim_failure_is_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container(settings=Settings())
    principal = _principal(container)
    operational = container.operational_service.create_session(
        principal,
        objective="Recover atomic claim",
        description=None,
        correlation_id=uuid4(),
    )
    repository = container.runtime_checkpoint_repository
    original_acquire = repository.acquire_start_claim
    acquire_calls = 0

    def fail_once(**kwargs):
        nonlocal acquire_calls
        acquire_calls += 1
        if acquire_calls == 1:
            raise RuntimeCheckpointConflictError("claim persistence failed")
        return original_acquire(**kwargs)

    monkeypatch.setattr(repository, "acquire_start_claim", fail_once)
    command = {
        "message": operational.objective,
        "history": (),
        "session_id": operational.session_id,
        "route_context": "/sessions",
    }

    with pytest.raises(OperationalConflictError, match="persisted state"):
        container.operational_service.sara_interaction(
            principal,
            correlation_id=uuid4(),
            idempotency_key="claim-failure",
            **command,
        )

    managed = container.session_service.get_session(operational.session_id)
    assert managed is not None
    assert managed.state.lifecycle_status is SessionLifecycleStatus.CREATED
    assert (
        container.authenticated_runtime_service.get_checkpoint(
            DEMO_ORG_A, operational.session_id
        )
        is None
    )

    recovered = container.operational_service.sara_interaction(
        principal,
        correlation_id=uuid4(),
        idempotency_key="claim-recovery",
        **command,
    )

    assert recovered.runtime.state == "waiting_approval"
    assert acquire_calls == 2


def test_failure_after_claim_is_auditable_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container(settings=Settings())
    principal = _principal(container)
    operational = container.operational_service.create_session(
        principal,
        objective="Retry claimed startup",
        description=None,
        correlation_id=uuid4(),
    )
    repository = container.runtime_checkpoint_repository
    original_acquire = repository.acquire_start_claim
    original_plan = container.planner_service.create_plan
    attempts: list[int] = []
    planner_calls = 0

    def capture_acquire(**kwargs):
        result = original_acquire(**kwargs)
        attempts.append(result.claim.attempt)
        return result

    def fail_plan_once(planner_input):
        nonlocal planner_calls
        planner_calls += 1
        if planner_calls == 1:
            raise RuntimeError("planner unavailable after claim")
        return original_plan(planner_input)

    monkeypatch.setattr(repository, "acquire_start_claim", capture_acquire)
    monkeypatch.setattr(container.planner_service, "create_plan", fail_plan_once)
    payload = {
        "message": operational.objective,
        "history": (),
        "session_id": operational.session_id,
        "route_context": "/sessions",
    }

    with pytest.raises(RuntimeError, match="planner unavailable"):
        container.operational_service.sara_interaction(
            principal,
            correlation_id=uuid4(),
            idempotency_key="claimed-failure",
            **payload,
        )

    managed = container.session_service.get_session(operational.session_id)
    assert managed is not None
    assert managed.state.lifecycle_status is SessionLifecycleStatus.CREATED

    recovered = container.operational_service.sara_interaction(
        principal,
        correlation_id=uuid4(),
        idempotency_key="claimed-retry",
        **payload,
    )

    assert recovered.runtime.state == "waiting_approval"
    assert attempts == [1, 2]
    assert planner_calls == 2


def test_cognitive_session_objective_conflict_is_not_concurrency() -> None:
    container = Container(settings=Settings())
    principal = _principal(container)
    operational = container.operational_service.create_session(
        principal,
        objective="Operational objective",
        description=None,
        correlation_id=uuid4(),
    )
    conflicting_objective = Objective(
        organization_id=DEMO_ORG_A,
        title="Different cognitive objective",
    )
    container.session_service.create_session(
        ManagedSession(
            session=CognitiveSession(
                id=operational.session_id,
                organization_id=DEMO_ORG_A,
                objective=conflicting_objective,
            ),
            state=SessionState(
                session_id=operational.session_id,
                lifecycle_status=SessionLifecycleStatus.CREATED,
                current_stage=SessionStage.CONTEXT,
            ),
            context=SessionContext(
                organization_id=DEMO_ORG_A,
                objective=conflicting_objective,
            ),
        )
    )

    with pytest.raises(OperationalConflictError, match="objective conflicts"):
        container.operational_service.sara_interaction(
            principal,
            message=operational.objective,
            history=(),
            session_id=operational.session_id,
            route_context="/sessions",
            correlation_id=uuid4(),
        )


def test_cognitive_session_organization_conflict_remains_blocked() -> None:
    container = Container(settings=Settings())
    principal = _principal(container)
    operational = container.operational_service.create_session(
        principal,
        objective="Organization scoped objective",
        description=None,
        correlation_id=uuid4(),
    )
    foreign_organization = UUID("20000000-0000-4000-8000-000000000002")
    foreign_objective = Objective(
        organization_id=foreign_organization,
        title=operational.objective,
    )
    container.session_service.create_session(
        ManagedSession(
            session=CognitiveSession(
                id=operational.session_id,
                organization_id=foreign_organization,
                objective=foreign_objective,
            ),
            state=SessionState(
                session_id=operational.session_id,
                lifecycle_status=SessionLifecycleStatus.CREATED,
                current_stage=SessionStage.CONTEXT,
            ),
            context=SessionContext(
                organization_id=foreign_organization,
                objective=foreign_objective,
            ),
        )
    )

    with pytest.raises(AuthorizationError, match="not available"):
        container.operational_service.sara_interaction(
            principal,
            message=operational.objective,
            history=(),
            session_id=operational.session_id,
            route_context="/sessions",
            correlation_id=uuid4(),
        )


@pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)
def test_postgres_atomic_runtime_claim_and_cognitive_create() -> None:
    assert TEST_DATABASE_URL is not None
    config = Config("alembic.ini")
    alembic_command.upgrade(config, "head")
    database_url = TEST_DATABASE_URL.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    session_id = uuid4()
    objective = Objective(
        organization_id=DEMO_ORG_A,
        title="PostgreSQL atomic startup",
    )
    managed = ManagedSession(
        session=CognitiveSession(
            id=session_id,
            organization_id=DEMO_ORG_A,
            objective=objective,
        ),
        state=SessionState(
            session_id=session_id,
            lifecycle_status=SessionLifecycleStatus.CREATED,
            current_stage=SessionStage.CONTEXT,
        ),
        context=SessionContext(
            organization_id=DEMO_ORG_A,
            objective=objective,
        ),
    )
    competing = managed.model_copy(
        update={
            "id": uuid4(),
            "state": managed.state.model_copy(update={"id": uuid4()}),
        },
        deep=True,
    )

    def create_session_in_worker(
        candidate: ManagedSession,
    ) -> tuple[ManagedSession, bool]:
        repository = PostgresSessionRepository(database_url)
        return repository.create_if_absent(candidate)

    def acquire_claim_in_worker(_: int):
        repository = PostgresRuntimeCheckpointRepository(database_url)
        return repository.acquire_start_claim(
            organization_id=DEMO_ORG_A,
            session_id=session_id,
            user_id=DEMO_OPERATOR,
            correlation_id=uuid4(),
            objective=objective.title,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            session_results = tuple(
                executor.map(
                    create_session_in_worker,
                    (managed, competing),
                )
            )
            claim_results = tuple(executor.map(acquire_claim_in_worker, range(2)))

        assert sum(1 for _, created in session_results if created) == 1
        assert sum(1 for item in claim_results if item.acquired) == 1
        assert all(item.claim.session_id == session_id for item in claim_results)
    finally:
        alembic_command.downgrade(config, "base")


def test_new_interaction_uses_principal_identity_and_starts_runtime_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        csrf = _login(
            client,
            "operator@demo.ecos.local",
            "operator-demo-password",
        )
        container = client.app.state.container
        original_start = container.authenticated_runtime_service.start_existing_session
        runtime_start_calls = 0

        def count_start(command):
            nonlocal runtime_start_calls
            runtime_start_calls += 1
            return original_start(command)

        monkeypatch.setattr(
            container.authenticated_runtime_service,
            "start_existing_session",
            count_start,
        )
        first = _create_interaction(client, csrf)
        repeated = _create_interaction(client, csrf)
        session_id = UUID(str(first["session_id"]))
        continued_response = client.post(
            "/api/v1/sara/interactions",
            json={
                "message": "Observe the same governed session",
                "session_id": str(session_id),
                "history": [],
                "route_context": "/governance",
            },
            headers={"X-CSRF-Token": csrf},
        )
        operational = client.get(f"/api/v1/sessions/{session_id}").json()

        managed = container.session_service.get_session(session_id)
        checkpoint = container.authenticated_runtime_service.get_checkpoint(
            DEMO_ORG_A, session_id
        )

    assert continued_response.status_code == 200
    assert runtime_start_calls == 1
    assert repeated == first
    assert set(first) == {
        "interaction_id",
        "session_id",
        "response",
        "runtime",
        "ui_actions",
        "incomplete_context",
        "unavailable",
    }
    assert first["runtime"]["state"] == "waiting_approval"
    assert first["unavailable"] is False
    assert managed is not None
    assert managed.session.id == session_id
    assert managed.state.session_id == session_id
    assert managed.session.organization_id == DEMO_ORG_A
    assert checkpoint is not None
    assert checkpoint.session_id == session_id
    assert checkpoint.organization_id == DEMO_ORG_A
    assert checkpoint.user_id == DEMO_OPERATOR
    assert checkpoint.status is RuntimeCheckpointStatus.WAITING_APPROVAL
    assert all(item.engine != "execution" for item in checkpoint.stage_results)
    assert operational["organization_id"] == str(DEMO_ORG_A)
    assert operational["created_by"] == str(DEMO_OPERATOR)
    assert operational["status"] == "waiting_approval"
    serialized = str(first).lower()
    for forbidden in (
        "governance_result",
        "stage_results",
        "resumable_state",
        "prompt",
        "provider",
    ):
        assert forbidden not in serialized
    allowed_actions = {
        "open_session",
        "open_approvals",
        "open_executions",
        "minimize_panel",
        "close_panel",
    }
    forbidden_actions = {
        "approve",
        "reject",
        "start_execution",
        "shell",
        "external_url",
        "dom_selector",
        "browser_automation",
    }
    action_types = {item["type"] for item in first["ui_actions"]}
    assert action_types <= allowed_actions
    assert action_types.isdisjoint(forbidden_actions)


def test_client_identity_fields_are_rejected() -> None:
    with TestClient(app) as client:
        csrf = _login(
            client,
            "operator@demo.ecos.local",
            "operator-demo-password",
        )
        for field in ("organization_id", "user_id"):
            response = client.post(
                "/api/v1/sara/interactions",
                json={
                    "message": "Do not trust client identity",
                    field: "20000000-0000-4000-8000-000000000002",
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert response.status_code == 422


@pytest.mark.parametrize(
    ("checkpoint_status", "lifecycle_status", "expected_state", "retry_after"),
    [
        (
            RuntimeCheckpointStatus.WAITING_APPROVAL,
            SessionLifecycleStatus.PAUSED,
            "waiting_approval",
            "5",
        ),
        (
            RuntimeCheckpointStatus.EXECUTING,
            SessionLifecycleStatus.EXECUTING,
            "executing",
            "2",
        ),
        (
            RuntimeCheckpointStatus.COMPLETED,
            SessionLifecycleStatus.COMPLETED,
            "completed",
            None,
        ),
        (
            RuntimeCheckpointStatus.FAILED,
            SessionLifecycleStatus.FAILED,
            "error",
            None,
        ),
    ],
)
def test_state_endpoint_projects_confirmed_checkpoint_status(
    checkpoint_status: RuntimeCheckpointStatus,
    lifecycle_status: SessionLifecycleStatus,
    expected_state: str,
    retry_after: str | None,
) -> None:
    with TestClient(app) as client:
        csrf = _login(
            client,
            "operator@demo.ecos.local",
            "operator-demo-password",
        )
        interaction = _create_interaction(
            client,
            csrf,
            key=f"state-{checkpoint_status.value}",
        )
        session_id = UUID(str(interaction["session_id"]))
        container = client.app.state.container
        if checkpoint_status is not RuntimeCheckpointStatus.WAITING_APPROVAL:
            _set_runtime_status(
                container,
                session_id,
                checkpoint_status=checkpoint_status,
                lifecycle_status=lifecycle_status,
            )
        response = client.get(f"/api/v1/sara/sessions/{session_id}/state")
        etag = response.headers.get("ETag")
        cached = client.get(
            f"/api/v1/sara/sessions/{session_id}/state",
            headers={"If-None-Match": etag or ""},
        )

    assert response.status_code == 200
    assert response.json()["session_id"] == str(session_id)
    runtime = response.json()["runtime"]
    assert set(runtime) == {
        "state",
        "lifecycle_status",
        "stage",
        "active_engine",
        "progress",
        "version",
        "updated_at",
        "error_code",
    }
    assert runtime["state"] == expected_state
    assert runtime["lifecycle_status"] == lifecycle_status.value
    assert etag
    assert cached.status_code == 304
    assert cached.content == b""
    assert response.headers.get("Retry-After") == retry_after
    if expected_state == "error":
        assert runtime["error_code"] == "RUNTIME_FAILED"
    else:
        assert runtime["error_code"] is None


def test_state_endpoint_blocks_cross_tenant_access() -> None:
    with TestClient(app) as client:
        csrf = _login(
            client,
            "operator@demo.ecos.local",
            "operator-demo-password",
        )
        interaction = _create_interaction(client, csrf, key="cross-tenant-state")
        session_id = interaction["session_id"]
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        _login(
            client,
            "operator@tenant-b.ecos.local",
            "tenant-b-demo-password",
        )
        response = client.get(f"/api/v1/sara/sessions/{session_id}/state")

    assert response.status_code == 403
    assert "artifact" not in response.text.lower()


def test_existing_operational_endpoints_and_runtime_demo_regressions() -> None:
    with TestClient(app) as client:
        csrf = _login(
            client,
            "operator@demo.ecos.local",
            "operator-demo-password",
        )
        created = client.post(
            "/api/v1/sessions",
            json={"objective": "Legacy operational regression"},
            headers={"X-CSRF-Token": csrf},
        )
        started = client.post(
            f"/api/v1/sessions/{created.json()['session_id']}/start",
            headers={"X-CSRF-Token": csrf},
        )
        demo = client.post(
            "/runtime/demo",
            json={"objective": "Improve organizational decision quality"},
        )

    assert created.status_code == 200
    assert started.status_code == 200
    assert started.json()["status"] == "waiting_approval"
    assert started.json()["approval"] is not None
    assert demo.status_code == 200
    assert demo.json() == {
        "session_id": demo.json()["session_id"],
        "status": "completed",
        "recommendation": (
            "Proceed using ECOS context, reasoning, debate and governance."
        ),
        "confidence": 0.91,
    }

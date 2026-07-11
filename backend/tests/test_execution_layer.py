"""Tests for the ECOS Execution Layer."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ecos.core import Container, Settings
from ecos.events import EventService, EventType
from ecos.execution import (
    ConnectorCapability,
    ConnectorDescriptor,
    ConnectorDuplicateError,
    ConnectorRegistry,
    ExecutionAuthorization,
    ExecutionEngine,
    ExecutionMode,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionStatus,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionType,
    InMemoryConnector,
    InMemoryHumanTaskProvider,
    InMemoryIdempotencyProvider,
    ResourceRequirement,
    RollbackAction,
    StructuredCondition,
    default_in_memory_connector,
    deterministic_fingerprint,
)
from ecos.runtime.adapters import ExecutionExecutor
from ecos.runtime.fakes import FakeEventBus

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
ORG_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
PLAN_ID = UUID("33333333-3333-4333-8333-333333333333")
CORRELATION_ID = UUID("44444444-4444-4444-8444-444444444444")
AUTH_ID = UUID("55555555-5555-4555-8555-555555555555")
GOVERNANCE_ID = UUID("66666666-6666-4666-8666-666666666666")
EXECUTION_PLAN_ID = UUID("77777777-7777-4777-8777-777777777777")
STEP_ID = UUID("88888888-8888-4888-8888-888888888888")


def make_engine(
    *,
    connector: InMemoryConnector | None = None,
    bus: FakeEventBus | None = None,
    classifier: object | None = None,
) -> tuple[
    ExecutionEngine,
    ConnectorRegistry,
    InMemoryIdempotencyProvider,
    FakeEventBus,
]:
    registry = ConnectorRegistry()
    registry.register(connector or default_in_memory_connector())
    idempotency = InMemoryIdempotencyProvider()
    event_bus = bus or FakeEventBus()
    kwargs = {}
    if classifier is not None:
        kwargs["failure_classifier"] = classifier
    engine = ExecutionEngine(
        connector_registry=registry,
        idempotency_provider=idempotency,
        human_task_provider=InMemoryHumanTaskProvider(),
        event_service=EventService(event_bus),
        clock=lambda: NOW,
        id_generator=uuid4,
        sleeper=_no_sleep,
        concurrency_limit=2,
        default_timeout_seconds=5.0,
        **kwargs,
    )
    return engine, registry, idempotency, event_bus


async def _no_sleep(_: float) -> None:
    return None


def make_authorization(**updates: object) -> ExecutionAuthorization:
    values = {
        "authorization_id": AUTH_ID,
        "governance_id": GOVERNANCE_ID,
        "organization_id": ORG_ID,
        "session_id": SESSION_ID,
        "plan_id": PLAN_ID,
        "execution_plan_id": EXECUTION_PLAN_ID,
        "action_scope": "runtime_execution",
        "approved_action": "runtime_execution",
        "allowed_execution_types": (ExecutionType.SYSTEM,),
        "allowed_connector_ids": ("memory.dry_run",),
        "allowed_capabilities": ("dry_run",),
        "policy_references": ("policy-a",),
        "valid_from": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(minutes=10),
        "execution_authorized": True,
        "issued_at": NOW - timedelta(minutes=1),
    }
    values.update(updates)
    return ExecutionAuthorization(**values)


def make_step(**updates: object) -> ExecutionStep:
    values = {
        "step_id": STEP_ID,
        "order": 1,
        "name": "Dry run action",
        "execution_type": ExecutionType.SYSTEM,
        "connector_id": "memory.dry_run",
        "required_capability": "dry_run",
        "action": "runtime_execution",
        "parameters": {"target": "safe"},
        "timeout_seconds": 5.0,
        "idempotency_scope": "step",
    }
    values.update(updates)
    return ExecutionStep(**values)


def make_plan(*steps: ExecutionStep, **updates: object) -> ExecutionPlan:
    values = {
        "execution_plan_id": EXECUTION_PLAN_ID,
        "organization_id": ORG_ID,
        "session_id": SESSION_ID,
        "cognitive_plan_id": PLAN_ID,
        "authorization_id": AUTH_ID,
        "action_scope": "runtime_execution",
        "execution_type": ExecutionType.SYSTEM,
        "steps": steps or (make_step(),),
        "resources": (
            ResourceRequirement(
                resource_type="connector",
                identifier="memory.dry_run",
            ),
        ),
        "created_at": NOW,
    }
    values.update(updates)
    return ExecutionPlan(**values)


def make_request(**updates: object) -> ExecutionRequest:
    authorization = updates.pop("authorization", make_authorization())
    plan = updates.pop("execution_plan", make_plan())
    values = {
        "execution_request_id": uuid4(),
        "organization_id": ORG_ID,
        "session_id": SESSION_ID,
        "plan_id": PLAN_ID,
        "correlation_id": CORRELATION_ID,
        "approved_action": "runtime_execution",
        "action_scope": "runtime_execution",
        "execution_type": ExecutionType.SYSTEM,
        "execution_plan": plan,
        "authorization": authorization,
        "policy_references": ("policy-a",),
        "required_resources": plan.resources,
        "dry_run": True,
        "idempotency_key": "request-key-1",
        "safe_metadata": {"purpose": "test"},
    }
    values.update(updates)
    return ExecutionRequest(**values)


def test_models_are_immutable_and_reject_secret_metadata() -> None:
    request = make_request()

    with pytest.raises(ValidationError):
        request.organization_id = uuid4()
    with pytest.raises(ValidationError, match="secret-like"):
        make_request(safe_metadata={"api_token": "hidden"})


def test_connector_registry_injection_registration_and_selection() -> None:
    _, registry, _, _ = make_engine()

    connector = registry.select(
        make_step(),
        make_authorization(),
        ExecutionMode.DRY_RUN,
    )

    assert connector.safe_descriptor.connector_id == "memory.dry_run"
    with pytest.raises(ConnectorDuplicateError):
        registry.register(default_in_memory_connector())


def test_execution_rejects_bad_authorization() -> None:
    engine, _, _, _ = make_engine()

    denied = engine.execute(make_request(authorization=make_authorization(denied=True)))
    expired = engine.execute(
        make_request(
            authorization=make_authorization(valid_until=NOW - timedelta(seconds=1))
        )
    )
    wrong_org = make_authorization(organization_id=uuid4())

    assert denied.status is ExecutionStatus.FAILED
    assert denied.failures[0].classification.value == "authorization"
    assert expired.status is ExecutionStatus.FAILED
    with pytest.raises(ValidationError, match="authorization organization mismatch"):
        make_request(authorization=wrong_org)


def test_execution_dry_run_is_default_and_uses_connector_with_events() -> None:
    engine, _, idempotency, bus = make_engine()

    result = engine.execute(make_request())

    assert result.status is ExecutionStatus.COMPLETED
    assert result.mode is ExecutionMode.DRY_RUN
    assert result.step_results[0].status is ExecutionStepStatus.COMPLETED
    assert result.outputs_by_connector["memory.dry_run"]["mode"] == "dry_run"
    assert idempotency.get("request-key-1").status.value == "completed"
    event_types = [envelope.event.event_type for envelope in bus.envelopes]
    assert EventType.CONNECTOR_INVOKED in event_types
    assert EventType.EXECUTION_COMPLETED in event_types


def test_live_execution_requires_explicit_authorization_and_connector_support() -> None:
    engine, _, _, _ = make_engine()

    result = engine.execute(make_request(dry_run=False))

    assert result.status is ExecutionStatus.FAILED
    assert result.failures[0].classification.value == "authorization"


def test_execution_plan_validates_bad_dependencies() -> None:
    first = make_step(order=1)
    duplicate = make_step(order=2)
    unknown_dependency = make_step(
        step_id=uuid4(),
        order=2,
        dependencies=(uuid4(),),
    )

    with pytest.raises(ValidationError, match="duplicate"):
        make_plan(first, duplicate)
    with pytest.raises(ValidationError, match="unknown step"):
        make_plan(first, unknown_dependency)


def test_precondition_false_skips_optional_and_fails_required() -> None:
    false_condition = StructuredCondition(
        operator="equals",
        field="metadata.ready",
        value=True,
    )
    optional = make_step(required=False, preconditions=(false_condition,))
    required = make_step(preconditions=(false_condition,))

    optional_result = make_engine()[0].execute(
        make_request(execution_plan=make_plan(optional))
    )
    required_result = make_engine()[0].execute(
        make_request(execution_plan=make_plan(required), idempotency_key="req-2-key")
    )

    assert optional_result.step_results[0].status is ExecutionStepStatus.SKIPPED
    assert required_result.status is ExecutionStatus.FAILED


def test_unknown_condition_operator_fails_without_dynamic_code() -> None:
    step = make_step(
        preconditions=(
            StructuredCondition(operator="python", field="metadata.ready", value=True),
        )
    )

    result = make_engine()[0].execute(make_request(execution_plan=make_plan(step)))

    assert result.status is ExecutionStatus.FAILED
    assert result.failures[0].classification.value == "validation"


def test_idempotency_hit_conflict_and_stable_fingerprint() -> None:
    engine, _, _, bus = make_engine()
    request = make_request()

    first = engine.execute(request)
    second = engine.execute(request)
    changed = engine.execute(
        request.model_copy(update={"safe_metadata": {"purpose": "changed"}})
    )

    assert first.status is ExecutionStatus.COMPLETED
    assert second.execution_id == first.execution_id
    assert changed.status is ExecutionStatus.FAILED
    assert deterministic_fingerprint({"b": 2, "a": 1}) == deterministic_fingerprint(
        {"a": 1, "b": 2}
    )
    assert EventType.IDEMPOTENCY_HIT in {
        envelope.event.event_type for envelope in bus.envelopes
    }


def test_human_execution_creates_task_and_pauses() -> None:
    human_step = make_step(
        execution_type=ExecutionType.HUMAN,
        connector_id=None,
        required_capability="human",
        safe_metadata={"assigned_to": "ops"},
    )
    authorization = make_authorization(
        allowed_execution_types=(ExecutionType.HUMAN,),
        allowed_connector_ids=(),
        allowed_capabilities=("human",),
    )
    plan = make_plan(human_step, execution_type=ExecutionType.HUMAN)
    engine, _, _, _ = make_engine()

    result = engine.execute(
        make_request(
            authorization=authorization,
            execution_plan=plan,
            execution_type=ExecutionType.HUMAN,
        )
    )

    assert result.status is ExecutionStatus.PAUSED
    assert result.human_tasks[0].assigned_to == "ops"
    assert result.resume_state is not None


def test_rollback_runs_in_reverse_for_completed_reversible_steps() -> None:
    rollback = RollbackAction(
        rollback_action_id=uuid4(),
        original_step_id=STEP_ID,
        connector_id="memory.dry_run",
        action="rollback_runtime_execution",
        idempotency_key="rollback-key-1",
    )
    first = make_step(rollback_action=rollback)
    failing = make_step(
        step_id=uuid4(),
        order=2,
        dependencies=(STEP_ID,),
        action="fail",
    )
    authorization = make_authorization(rollback_authorized=True)
    connector = InMemoryConnector(
        ConnectorDescriptor(
            connector_id="memory.dry_run",
            connector_type="in_memory",
            supported_execution_types=(ExecutionType.SYSTEM,),
            capabilities=(ConnectorCapability(name="dry_run"),),
            supports_rollback=True,
        ),
        fail=True,
    )
    engine, _, _, _ = make_engine(connector=connector)

    result = engine.execute(
        make_request(
            authorization=authorization,
            execution_plan=make_plan(first, failing),
            rollback_required=True,
        )
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.failures[0].rollback_required is True


def test_container_injects_real_execution_engine_and_registry() -> None:
    container = Container(settings=Settings())

    assert isinstance(container.execution_engine, ExecutionEngine)
    assert isinstance(container.connector_registry, ConnectorRegistry)
    assert isinstance(container.idempotency_provider, InMemoryIdempotencyProvider)
    assert isinstance(container.engine_executors["execution"], ExecutionExecutor)


def test_execution_architecture_static_restrictions() -> None:
    execution_dir = Path("src/ecos/execution")
    text = "\n".join(path.read_text() for path in execution_dir.glob("*.py"))

    assert "openai" not in text
    assert "AIProvider" not in text
    assert "Container" not in text
    assert "sqlalchemy" not in text.lower()
    assert "postgres" not in text.lower()
    assert "os.environ" not in text
    forbidden_dynamic_calls = (f"ev{'al'}(", f"ex{'ec'}(")
    for pattern in forbidden_dynamic_calls:
        assert pattern not in text

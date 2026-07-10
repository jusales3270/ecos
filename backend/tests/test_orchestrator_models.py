"""Unit tests for ECOS Orchestrator models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.orchestrator import (
    EngineExecution,
    ExecutionEvent,
    ExecutionMode,
    ExecutionPlan,
    ExecutionResult,
    ExecutionState,
    ExecutionStatus,
    ExecutionStep,
    OrchestratorProvider,
    OrchestratorService,
)

SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")


def make_execution_state() -> ExecutionState:
    """Create a valid execution state for tests."""
    return ExecutionState(
        status=ExecutionStatus.CREATED,
        message="Created",
        metadata={"source": "unit-test"},
    )


def make_execution_step() -> ExecutionStep:
    """Create a valid execution step for tests."""
    return ExecutionStep(
        order=1,
        engine="context",
        state=make_execution_state(),
        retries=1,
        timeout=30,
        optional=False,
    )


def make_execution_plan() -> ExecutionPlan:
    """Create a valid execution plan for tests."""
    step = make_execution_step()
    return ExecutionPlan(
        session_id=SESSION_ID,
        execution_mode=ExecutionMode.SEQUENTIAL,
        steps=[step],
        current_step=step.id,
        status=ExecutionStatus.CREATED,
    )


def make_engine_execution(plan_id: UUID, step_id: UUID) -> EngineExecution:
    """Create a valid engine execution for tests."""
    started_at = datetime.now(UTC)
    return EngineExecution(
        execution_plan_id=plan_id,
        execution_step_id=step_id,
        engine="context",
        status=ExecutionStatus.COMPLETED,
        started_at=started_at,
        completed_at=started_at,
    )


def make_execution_result(plan: ExecutionPlan) -> ExecutionResult:
    """Create a valid execution result for tests."""
    return ExecutionResult(
        execution_plan_id=plan.id,
        status=ExecutionStatus.COMPLETED,
        engine_executions=[make_engine_execution(plan.id, plan.steps[0].id)],
        summary="Execution completed.",
    )


def test_execution_status_values() -> None:
    """ExecutionStatus exposes all supported execution statuses."""
    assert {status.value for status in ExecutionStatus} == {
        "CREATED",
        "WAITING",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }


def test_execution_mode_values() -> None:
    """ExecutionMode exposes all supported execution modes."""
    assert {mode.value for mode in ExecutionMode} == {
        "SEQUENTIAL",
        "PARALLEL",
        "CONDITIONAL",
        "ITERATIVE",
    }


def test_execution_state_validates_message_metadata_and_timestamp() -> None:
    """ExecutionState validates status, message, metadata, and created_at."""
    state = make_execution_state()

    assert isinstance(state.id, UUID)
    assert state.status == ExecutionStatus.CREATED
    assert state.message == "Created"
    assert state.metadata == {"source": "unit-test"}
    assert state.created_at.tzinfo is not None
    assert state.created_at.utcoffset() == UTC.utcoffset(state.created_at)

    with pytest.raises(ValidationError):
        ExecutionState(status=ExecutionStatus.CREATED, message="   ")

    with pytest.raises(ValidationError):
        ExecutionState(status=ExecutionStatus.CREATED, metadata={"   ": "invalid"})


def test_execution_step_contains_required_architecture_fields() -> None:
    """ExecutionStep contains required orchestration fields."""
    dependency_id = UUID("00000000-0000-4000-8000-000000000002")
    step = ExecutionStep(
        order=2,
        engine="reasoning",
        depends_on=[dependency_id],
        state=make_execution_state(),
        retries=2,
        timeout=60,
        optional=True,
    )

    assert isinstance(step.id, UUID)
    assert step.order == 2
    assert step.engine == "reasoning"
    assert step.depends_on == [dependency_id]
    assert step.state.status == ExecutionStatus.CREATED
    assert step.retries == 2
    assert step.timeout == 60
    assert step.optional is True

    with pytest.raises(ValidationError):
        ExecutionStep(order=0, engine="context", state=make_execution_state())

    with pytest.raises(ValidationError):
        ExecutionStep(order=1, engine="   ", state=make_execution_state())

    with pytest.raises(ValidationError):
        ExecutionStep(
            order=1,
            engine="context",
            state=make_execution_state(),
            retries=-1,
        )

    with pytest.raises(ValidationError):
        ExecutionStep(
            order=1,
            engine="context",
            state=make_execution_state(),
            timeout=-1,
        )


def test_execution_plan_contains_required_architecture_fields() -> None:
    """ExecutionPlan contains id, session, mode, steps, current step, and status."""
    plan = make_execution_plan()

    assert isinstance(plan.id, UUID)
    assert plan.session_id == SESSION_ID
    assert plan.execution_mode == ExecutionMode.SEQUENTIAL
    assert len(plan.steps) == 1
    assert plan.current_step == plan.steps[0].id
    assert plan.status == ExecutionStatus.CREATED
    assert plan.created_at.tzinfo is not None
    assert plan.created_at.utcoffset() == UTC.utcoffset(plan.created_at)


def test_execution_plan_validates_unique_step_order() -> None:
    """ExecutionPlan rejects duplicate step order values."""
    with pytest.raises(ValidationError):
        ExecutionPlan(
            session_id=SESSION_ID,
            execution_mode=ExecutionMode.SEQUENTIAL,
            steps=[
                ExecutionStep(order=1, engine="context", state=make_execution_state()),
                ExecutionStep(
                    order=1,
                    engine="reasoning",
                    state=make_execution_state(),
                ),
            ],
        )


def test_engine_execution_validates_fields_and_timestamps() -> None:
    """EngineExecution validates engine fields and optional timestamps."""
    plan = make_execution_plan()
    execution = make_engine_execution(plan.id, plan.steps[0].id)

    assert execution.execution_plan_id == plan.id
    assert execution.execution_step_id == plan.steps[0].id
    assert execution.engine == "context"
    assert execution.status == ExecutionStatus.COMPLETED

    with pytest.raises(ValidationError):
        EngineExecution(
            execution_plan_id=plan.id,
            execution_step_id=plan.steps[0].id,
            engine="   ",
            status=ExecutionStatus.RUNNING,
        )

    with pytest.raises(ValidationError):
        EngineExecution(
            execution_plan_id=plan.id,
            execution_step_id=plan.steps[0].id,
            engine="context",
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(),
        )

    with pytest.raises(ValidationError):
        EngineExecution(
            execution_plan_id=plan.id,
            execution_step_id=plan.steps[0].id,
            engine="context",
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC) - timedelta(seconds=1),
        )


def test_execution_result_validates_summary() -> None:
    """ExecutionResult captures engine executions and validates summary."""
    plan = make_execution_plan()
    result = make_execution_result(plan)

    assert result.execution_plan_id == plan.id
    assert result.status == ExecutionStatus.COMPLETED
    assert len(result.engine_executions) == 1
    assert result.summary == "Execution completed."

    with pytest.raises(ValidationError):
        ExecutionResult(
            execution_plan_id=plan.id,
            status=ExecutionStatus.COMPLETED,
            summary="   ",
        )


def test_execution_event_validates_fields_and_metadata() -> None:
    """ExecutionEvent validates message and metadata."""
    plan = make_execution_plan()
    event = ExecutionEvent(
        execution_plan_id=plan.id,
        execution_step_id=plan.steps[0].id,
        status=ExecutionStatus.RUNNING,
        message="Step started.",
        metadata={"engine": "context"},
    )

    assert event.execution_plan_id == plan.id
    assert event.execution_step_id == plan.steps[0].id
    assert event.status == ExecutionStatus.RUNNING
    assert event.message == "Step started."

    with pytest.raises(ValidationError):
        ExecutionEvent(
            execution_plan_id=plan.id,
            status=ExecutionStatus.RUNNING,
            message="   ",
        )

    with pytest.raises(ValidationError):
        ExecutionEvent(
            execution_plan_id=plan.id,
            status=ExecutionStatus.RUNNING,
            message="Message",
            metadata={"   ": "invalid"},
        )


def test_orchestrator_models_reject_invalid_created_at() -> None:
    """Orchestrator models reject non-UTC and naive created_at values."""
    with pytest.raises(ValidationError):
        ExecutionState(status=ExecutionStatus.CREATED, created_at=datetime.now())

    with pytest.raises(ValidationError):
        ExecutionState(
            status=ExecutionStatus.CREATED,
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


class NotImplementedOrchestratorProvider(OrchestratorProvider):
    """Concrete test adapter that delegates to interface methods."""

    def start(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Delegate to the interface method."""
        return super().start(plan)

    def execute_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
    ) -> ExecutionStep:
        """Delegate to the interface method."""
        return super().execute_step(plan, step)

    def pause(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Delegate to the interface method."""
        return super().pause(plan)

    def resume(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Delegate to the interface method."""
        return super().resume(plan)

    def cancel(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Delegate to the interface method."""
        return super().cancel(plan)

    def complete(self, plan: ExecutionPlan) -> ExecutionResult:
        """Delegate to the interface method."""
        return super().complete(plan)


def test_orchestrator_provider_interface_methods_raise_not_implemented() -> None:
    """OrchestratorProvider interface methods are intentionally unimplemented."""
    provider = NotImplementedOrchestratorProvider()
    plan = make_execution_plan()
    step = plan.steps[0]

    with pytest.raises(NotImplementedError):
        provider.start(plan)
    with pytest.raises(NotImplementedError):
        provider.execute_step(plan, step)
    with pytest.raises(NotImplementedError):
        provider.pause(plan)
    with pytest.raises(NotImplementedError):
        provider.resume(plan)
    with pytest.raises(NotImplementedError):
        provider.cancel(plan)
    with pytest.raises(NotImplementedError):
        provider.complete(plan)


class TestOrchestratorProvider(OrchestratorProvider):
    """Test double for verifying OrchestratorService delegation only."""

    def start(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Return the provided plan."""
        return plan

    def execute_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
    ) -> ExecutionStep:
        """Return the provided step."""
        del plan
        return step

    def pause(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Return the provided plan."""
        return plan

    def resume(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Return the provided plan."""
        return plan

    def cancel(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Return the provided plan."""
        return plan

    def complete(self, plan: ExecutionPlan) -> ExecutionResult:
        """Return a configured execution result."""
        return make_execution_result(plan)


def test_orchestrator_service_uses_provider_abstraction() -> None:
    """OrchestratorService delegates operations to the provider abstraction."""
    service = OrchestratorService(TestOrchestratorProvider())
    plan = make_execution_plan()
    step = plan.steps[0]

    assert service.start(plan) == plan
    assert service.execute_step(plan, step) == step
    assert service.pause(plan) == plan
    assert service.resume(plan) == plan
    assert service.cancel(plan) == plan
    assert service.complete(plan).execution_plan_id == plan.id

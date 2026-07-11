"""Tests for the real ECOS Orchestrator."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from ecos.domain import CognitiveSession, Objective, SessionStage
from ecos.domain.enums import SessionStatus
from ecos.events import EventService, EventType
from ecos.orchestrator import (
    ApprovalState,
    ApprovalStatus,
    EngineExecutor,
    EngineInvocationContext,
    EngineStageResult,
    FailureClassification,
    GovernanceState,
    OrchestrationConfig,
    OrchestrationInput,
    OrchestrationMode,
    Orchestrator,
    PipelineExecutionStatus,
    StageExecutionStatus,
)
from ecos.planner import (
    ApprovalRequirements,
    CognitivePlan,
    EngineSelection,
    ExecutionStrategy,
    GovernanceRequirements,
    Pipeline,
    PipelineStep,
    PlanningStrategy,
)
from ecos.planner.models import RetryPolicy, StageCondition
from ecos.runtime import FakeEventBus, FakeSessionRepository
from ecos.session import (
    ManagedSession,
    SessionContext,
    SessionLifecycleStatus,
    SessionService,
    SessionState,
)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


class RecordingExecutor(EngineExecutor):
    """Executor test double that records invocations."""

    def __init__(
        self,
        engine_type: str,
        output: object | None = None,
        *,
        fail_times: int = 0,
        delay: float = 0.0,
    ) -> None:
        self._engine_type = engine_type
        self.output = output if output is not None else {"engine": engine_type}
        self.fail_times = fail_times
        self.delay = delay
        self.calls: list[EngineInvocationContext] = []

    @property
    def engine_type(self) -> str:
        return self._engine_type

    @property
    def available(self) -> bool:
        return True

    async def execute(self, context: EngineInvocationContext) -> EngineStageResult:
        self.calls.append(context)
        if self.delay:
            await asyncio.sleep(self.delay)
        if len(self.calls) <= self.fail_times:
            raise RuntimeError("recoverable failure")
        return EngineStageResult(
            stage_id=context.stage.stage_id,
            engine=self.engine_type,
            status=StageExecutionStatus.COMPLETED,
            output=self.output,
            started_at=NOW,
            completed_at=NOW,
            duration=0.0,
            attempt=context.attempt,
        )


def make_session() -> ManagedSession:
    organization_id = UUID("00000000-0000-4000-8000-000000000101")
    objective = Objective(organization_id=organization_id, title="Coordinate work")
    session = CognitiveSession(
        organization_id=organization_id,
        objective=objective,
        status=SessionStatus.INITIALIZED,
        current_stage=SessionStage.CONTEXT,
    )
    state = SessionState(
        session_id=session.id,
        lifecycle_status=SessionLifecycleStatus.INITIALIZED,
        current_stage=SessionStage.CONTEXT,
    )
    return ManagedSession(
        session=session,
        state=state,
        context=SessionContext(organization_id=organization_id, objective=objective),
    )


def make_plan(
    session: ManagedSession,
    steps: tuple[PipelineStep, ...],
    *,
    governance: GovernanceRequirements | None = None,
    approval: ApprovalRequirements | None = None,
) -> CognitivePlan:
    strategy = ExecutionStrategy(
        strategy=PlanningStrategy.BALANCED,
        rationale="Test strategy.",
    )
    return CognitivePlan(
        session_id=session.session.id,
        organization_id=session.session.organization_id,
        objective=session.session.objective,
        strategy=strategy,
        selected_engines=tuple(
            EngineSelection(engine=step.engine, reason="test") for step in steps
        ),
        pipeline=Pipeline(steps=steps),
        governance_requirements=governance or GovernanceRequirements(),
        approval_requirements=approval or ApprovalRequirements(),
    )


def make_input(
    plan: CognitivePlan,
    session: ManagedSession,
    *,
    approval: ApprovalState | None = None,
    governance: GovernanceState | None = None,
) -> OrchestrationInput:
    return OrchestrationInput(
        cognitive_plan=plan,
        active_session=session,
        organization_id=session.session.organization_id,
        session_id=session.session.id,
        correlation_id=session.session.id,
        approval_state=approval or ApprovalState(),
        governance_state=governance,
        resources_available=("test",),
        safe_metadata={"test": True},
    )


def make_orchestrator(
    executors: dict[str, EngineExecutor],
    session_service: SessionService,
    *,
    mode: OrchestrationMode = OrchestrationMode.SEQUENTIAL,
    default_timeout: float = 1.0,
    sleeper_calls: list[float] | None = None,
) -> tuple[Orchestrator, FakeEventBus]:
    bus = FakeEventBus()

    async def sleeper(seconds: float) -> None:
        if sleeper_calls is not None:
            sleeper_calls.append(seconds)

    orchestrator = Orchestrator(
        executors=executors,
        event_service=EventService(bus),
        session_service=session_service,
        clock=lambda: NOW,
        id_generator=uuid4,
        sleeper=sleeper,
        config=OrchestrationConfig(
            mode=mode,
            concurrency_limit=2,
            default_timeout_seconds=default_timeout,
        ),
        failure_classifier=lambda error: (
            FailureClassification.RECOVERABLE
            if "recoverable" in str(error)
            else FailureClassification.NON_RECOVERABLE
        ),
    )
    return orchestrator, bus


def test_orchestrator_executes_sequential_dag_and_preserves_outputs() -> None:
    session = make_session()
    repo = FakeSessionRepository()
    repo.create(session)
    context = PipelineStep(order=1, engine="context")
    reasoning = PipelineStep(
        order=2,
        engine="reasoning",
        dependencies=(context.stage_id,),
    )
    plan = make_plan(session, (context, reasoning))
    executors = {
        "context": RecordingExecutor("context", {"context": 1}),
        "reasoning": RecordingExecutor("reasoning", {"reasoning": 2}),
    }
    orchestrator, bus = make_orchestrator(executors, SessionService(repo))

    result = orchestrator.execute(make_input(plan, session))

    assert result.status is PipelineExecutionStatus.COMPLETED
    assert result.outputs_by_engine == {
        "context": {"context": 1},
        "reasoning": {"reasoning": 2},
    }
    assert executors["reasoning"].calls[0].dependency_outputs == {
        context.stage_id: {"context": 1}
    }
    assert [entry.sequence for entry in result.timeline] == list(
        range(1, len(result.timeline) + 1)
    )
    assert bus.envelopes[-1].event.event_type is EventType.PIPELINE_COMPLETED
    assert repo.get(session.session.id).state.lifecycle_status is (
        SessionLifecycleStatus.COMPLETED
    )


def test_orchestrator_rejects_missing_engine_and_cycles() -> None:
    session = make_session()
    repo = FakeSessionRepository()
    repo.create(session)
    missing = PipelineStep(order=1, engine="missing")
    plan = make_plan(session, (missing,))
    orchestrator, _ = make_orchestrator({}, SessionService(repo))

    result = orchestrator.execute(make_input(plan, session))

    assert result.status is PipelineExecutionStatus.FAILED
    assert result.failure_report.cause_type == "EngineNotRegisteredError"

    first = PipelineStep(order=1, engine="context")
    second = PipelineStep(order=2, engine="reasoning", dependencies=(first.stage_id,))
    first = first.model_copy(update={"dependencies": (second.stage_id,)})
    cycle_plan = make_plan(session, (first, second))
    orchestrator, _ = make_orchestrator(
        {
            "context": RecordingExecutor("context"),
            "reasoning": RecordingExecutor("reasoning"),
        },
        SessionService(repo),
    )

    result = orchestrator.execute(make_input(cycle_plan, session))

    assert result.status is PipelineExecutionStatus.FAILED
    assert result.failure_report.cause_type == "CycleDetectedError"


def test_parallel_mode_runs_independent_ready_stages() -> None:
    session = make_session()
    repo = FakeSessionRepository()
    repo.create(session)
    first = PipelineStep(order=1, engine="context")
    second = PipelineStep(order=2, engine="reasoning")
    plan = make_plan(session, (first, second))
    executors = {
        "context": RecordingExecutor("context"),
        "reasoning": RecordingExecutor("reasoning"),
    }
    orchestrator, _ = make_orchestrator(
        executors,
        SessionService(repo),
        mode=OrchestrationMode.PARALLEL,
    )

    result = orchestrator.execute(make_input(plan, session))

    assert result.status is PipelineExecutionStatus.COMPLETED
    assert [item.engine for item in result.stage_results] == ["context", "reasoning"]
    assert len(executors["context"].calls) == 1
    assert len(executors["reasoning"].calls) == 1


def test_conditional_optional_stage_is_skipped_without_dynamic_code() -> None:
    session = make_session()
    repo = FakeSessionRepository()
    repo.create(session)
    stage = PipelineStep(
        order=1,
        engine="context",
        required=False,
        conditional=True,
        condition=StageCondition(
            type="equals",
            requirements=("metadata.flag", "literal:on"),
        ),
    )
    plan = make_plan(session, (stage,))
    executor = RecordingExecutor("context")
    orchestrator, _ = make_orchestrator({"context": executor}, SessionService(repo))

    result = orchestrator.execute(make_input(plan, session))

    assert result.stage_results[0].status is StageExecutionStatus.SKIPPED
    assert executor.calls == []
    source = Path("src/ecos/orchestrator/engine.py").read_text()
    assert ("ev" + "al(") not in source


def test_retry_uses_injected_sleeper_and_timeout_fails_stage() -> None:
    session = make_session()
    repo = FakeSessionRepository()
    repo.create(session)
    stage = PipelineStep(
        order=1,
        engine="context",
        retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=3),
    )
    plan = make_plan(session, (stage,))
    sleeper_calls: list[float] = []
    executor = RecordingExecutor("context", fail_times=1)
    orchestrator, _ = make_orchestrator(
        {"context": executor},
        SessionService(repo),
        sleeper_calls=sleeper_calls,
    )

    result = orchestrator.execute(make_input(plan, session))

    assert result.status is PipelineExecutionStatus.COMPLETED
    assert len(executor.calls) == 2
    assert sleeper_calls == [3.0]

    timeout_plan = make_plan(
        session,
        (PipelineStep(order=1, engine="context", timeout_seconds=0),),
    )
    timeout_orchestrator, _ = make_orchestrator(
        {"context": RecordingExecutor("context", delay=0.05)},
        SessionService(repo),
        default_timeout=0.001,
    )

    result = timeout_orchestrator.execute(make_input(timeout_plan, session))

    assert result.status is PipelineExecutionStatus.FAILED
    assert result.failure_report.cause_type == "RequiredStageFailedError"
    assert result.stage_results[0].status is StageExecutionStatus.TIMED_OUT


def test_execution_waits_for_governance_and_human_approval() -> None:
    session = make_session()
    repo = FakeSessionRepository()
    repo.create(session)
    governance_stage = PipelineStep(order=1, engine="governance")
    execution_stage = PipelineStep(
        order=2,
        engine="execution",
        dependencies=(governance_stage.stage_id,),
    )
    plan = make_plan(
        session,
        (governance_stage, execution_stage),
        governance=GovernanceRequirements(
            governance_required=True,
            approval_required=True,
            execution_blocked_until_approval=True,
        ),
        approval=ApprovalRequirements(required=True),
    )
    orchestrator, _ = make_orchestrator(
        {
            "governance": RecordingExecutor("governance"),
            "execution": RecordingExecutor("execution"),
        },
        SessionService(repo),
    )

    result = orchestrator.execute(make_input(plan, session))

    assert result.status is PipelineExecutionStatus.WAITING_APPROVAL
    assert result.resumable_state is not None
    assert repo.get(session.session.id).state.lifecycle_status is (
        SessionLifecycleStatus.PAUSED
    )

    approved = ApprovalState(
        status=ApprovalStatus.APPROVED,
        organization_id=session.session.organization_id,
        session_id=session.session.id,
        plan_id=plan.plan_id,
        approved_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    governance = GovernanceState(
        satisfied=True,
        organization_id=session.session.organization_id,
        session_id=session.session.id,
        plan_id=plan.plan_id,
    )
    resumed = asyncio.run(
        orchestrator.resume_async(
            make_input(plan, session, approval=approved, governance=governance),
            result.resumable_state,
        )
    )

    assert resumed.status is PipelineExecutionStatus.COMPLETED
    assert [item.engine for item in resumed.stage_results] == [
        "governance",
        "execution",
    ]


def test_orchestrator_module_has_no_forbidden_dependencies() -> None:
    source = "\n".join(
        path.read_text() for path in Path("src/ecos/orchestrator").glob("*.py")
    )

    assert "openai" not in source.lower()
    assert "AIProvider" not in source
    assert "Container" not in source
    assert "sqlalchemy" not in source.lower()
    assert "os.environ" not in source
    assert ("ev" + "al(") not in source

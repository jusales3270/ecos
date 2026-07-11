"""Executable runtime pipeline entrypoint for ECOS."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ecos.context import ContextProvider, ContextService
from ecos.debate import DebateService
from ecos.decision import DecisionService
from ecos.domain import CognitiveSession, Objective, Organization, SessionStage
from ecos.domain.enums import SessionStatus
from ecos.events import Event, EventBus, EventPriority, EventService, EventType
from ecos.learning import LearningService
from ecos.memory import MemoryRepository, MemoryService
from ecos.orchestrator import (
    ApprovalState,
    GovernanceState,
    OrchestrationConfig,
    OrchestrationInput,
    OrchestrationMode,
    Orchestrator,
    OrchestratorService,
    PipelineExecutionStatus,
)
from ecos.planner import CognitivePlan, ExecutionStrategy, PlannerInput, PlannerService
from ecos.providers import AIProvider, AIService, ProviderRegistry, ProviderType
from ecos.reasoning import ReasoningService
from ecos.runtime.adapters import (
    ContextExecutor,
    DebateExecutor,
    DecisionExecutor,
    LearningExecutor,
    NoopExecutor,
    ReasoningExecutor,
    SimulationExecutor,
    SpecialistsExecutor,
)
from ecos.runtime.fakes import (
    FakeAIProvider,
    FakeContextProvider,
    FakeDebateProvider,
    FakeDecisionProvider,
    FakeEventBus,
    FakeMemoryRepository,
    FakeOrchestratorProvider,
    FakePlannerProvider,
    FakeReasoningProvider,
    FakeSessionRepository,
    FakeSpecialistProvider,
    FakeWarEngine,
)
from ecos.runtime.models import ExecutionContext, RuntimeResult
from ecos.session import (
    ManagedSession,
    SessionContext,
    SessionLifecycleStatus,
    SessionRepository,
    SessionService,
    SessionSnapshot,
    SessionState,
    SessionTransition,
    TransitionType,
)
from ecos.simulation import SimulationService
from ecos.specialists import SpecialistRegistry, SpecialistService


class CognitivePipeline:
    """Coordinates the first deterministic ECOS cognitive pipeline."""

    def __init__(
        self,
        *,
        memory_repository: MemoryRepository,
        session_repository: SessionRepository,
        event_bus: EventBus,
        context_provider: ContextProvider,
        ai_provider: AIProvider,
        memory_service: MemoryService,
        learning_service: LearningService,
        session_service: SessionService,
        event_service: EventService,
        context_service: ContextService,
        planner_service: PlannerService,
        reasoning_service: ReasoningService,
        specialist_service: SpecialistService,
        debate_service: DebateService,
        simulation_service: SimulationService,
        decision_service: DecisionService,
        orchestrator_service: OrchestratorService,
        ai_service: AIService,
    ) -> None:
        """Initialize the pipeline with externally registered dependencies."""
        self.memory_repository = memory_repository
        self.session_repository = session_repository
        self.event_bus = event_bus
        self.context_provider = context_provider
        self.ai_provider = ai_provider
        self.memory_service = memory_service
        self.learning_service = learning_service
        self.session_service = session_service
        self.event_service = event_service
        self.context_service = context_service
        self.planner_service = planner_service
        self.reasoning_service = reasoning_service
        self.specialist_service = specialist_service
        self.debate_service = debate_service
        self.simulation_service = simulation_service
        self.decision_service = decision_service
        self.orchestrator_service = orchestrator_service
        self.ai_service = ai_service

    @classmethod
    def with_fakes(cls) -> "CognitivePipeline":
        """Create a standalone fake pipeline for tests and demos."""
        memory_repository = FakeMemoryRepository()
        session_repository = FakeSessionRepository()
        event_bus = FakeEventBus()
        context_provider = FakeContextProvider()
        planner_provider = FakePlannerProvider()
        reasoning_provider = FakeReasoningProvider()
        specialist_provider = FakeSpecialistProvider()
        debate_provider = FakeDebateProvider()
        simulation_provider = FakeWarEngine()
        decision_provider = FakeDecisionProvider()
        orchestrator_provider = FakeOrchestratorProvider()
        ai_provider = FakeAIProvider()

        ai_service = AIService(ProviderRegistry())
        ai_service.register(ProviderType.CUSTOM, ai_provider, default=True)

        memory_service = MemoryService(memory_repository)
        event_service = EventService(event_bus)
        context_service = ContextService(context_provider)
        reasoning_service = ReasoningService(reasoning_provider)
        specialist_service = SpecialistService(
            specialist_provider,
            SpecialistRegistry(),
        )
        debate_service = DebateService(debate_provider)
        simulation_service = SimulationService(simulation_provider)
        decision_service = DecisionService(decision_provider)
        learning_service = LearningService(memory_service, event_service)
        session_service = SessionService(session_repository)
        executors = {
            "context": ContextExecutor(context_service),
            "reasoning": ReasoningExecutor(reasoning_service),
            "specialists": SpecialistsExecutor(specialist_service),
            "debate": DebateExecutor(debate_service),
            "simulation": SimulationExecutor(simulation_service),
            "decision": DecisionExecutor(decision_service),
            "memory": LearningExecutor(learning_service),
            "governance": NoopExecutor("governance"),
            "execution": NoopExecutor("execution"),
            "observation": NoopExecutor("observation"),
        }
        orchestrator = Orchestrator(
            executors=executors,
            event_service=event_service,
            session_service=session_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            sleeper=asyncio.sleep,
            config=OrchestrationConfig(mode=OrchestrationMode.SEQUENTIAL),
        )
        return cls(
            memory_repository=memory_repository,
            session_repository=session_repository,
            event_bus=event_bus,
            context_provider=context_provider,
            ai_provider=ai_provider,
            memory_service=memory_service,
            learning_service=learning_service,
            session_service=session_service,
            event_service=event_service,
            context_service=context_service,
            planner_service=PlannerService(planner_provider),
            reasoning_service=reasoning_service,
            specialist_service=specialist_service,
            debate_service=debate_service,
            simulation_service=simulation_service,
            decision_service=decision_service,
            orchestrator_service=OrchestratorService(
                orchestrator_provider,
                orchestrator,
            ),
            ai_service=ai_service,
        )

    def run(self, objective: str) -> RuntimeResult:
        """Run the deterministic cognitive pipeline for an objective."""
        execution = self._create_execution_context(objective)
        session_id = execution.cognitive_session.id

        self._record_transition(
            session_id=session_id,
            transition_type=TransitionType.INITIALIZE,
            from_status=SessionLifecycleStatus.CREATED,
            to_status=SessionLifecycleStatus.INITIALIZED,
            reason="Runtime session initialized.",
        )
        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.PLANNING,
            current_stage=SessionStage.CONTEXT,
            active_engine="planner",
            progress=0.1,
        )

        plan = self._create_plan(
            execution.cognitive_session,
            execution.cognitive_session.objective,
        )
        execution.plan = plan
        self._configure_orchestrator()
        orchestration_result = self.orchestrator_service.execute(
            OrchestrationInput(
                cognitive_plan=plan,
                active_session=execution.managed_session,
                organization_id=execution.cognitive_session.organization_id,
                session_id=session_id,
                correlation_id=session_id,
                approval_state=ApprovalState(),
                governance_state=GovernanceState(
                    satisfied=False,
                    organization_id=execution.cognitive_session.organization_id,
                    session_id=session_id,
                    plan_id=plan.plan_id,
                    metadata={"runtime": True},
                ),
                resources_available=("runtime",),
                safe_metadata={"runtime": True},
            )
        )
        if orchestration_result.status is not PipelineExecutionStatus.COMPLETED:
            if orchestration_result.failure_report is not None:
                raise RuntimeError(orchestration_result.failure_report.safe_message)
            raise RuntimeError(
                f"runtime orchestration did not complete: "
                f"{orchestration_result.status.value}"
            )
        decision_package = orchestration_result.outputs_by_engine.get(
            "decision"
        ) or orchestration_result.outputs_by_engine.get("decision_support")
        if decision_package is None:
            raise RuntimeError("runtime orchestration did not produce a decision")
        recommendation = decision_package.recommendation
        memory = orchestration_result.outputs_by_engine.get(
            "memory"
        ) or orchestration_result.outputs_by_engine.get("learning")
        learning_planned = any(
            step.engine in {"memory", "learning"} for step in plan.pipeline.steps
        )
        if memory is None and learning_planned:
            raise RuntimeError("runtime learning was rejected")
        execution.context = orchestration_result.outputs_by_engine.get("context")
        execution.reasoning = orchestration_result.outputs_by_engine.get("reasoning")
        execution.simulation = orchestration_result.outputs_by_engine.get("simulation")
        execution.recommendation = recommendation
        execution.memory = memory

        updated_session = self.session_service.get_session(session_id)
        if updated_session is not None:
            execution.managed_session = updated_session
        self._record_transition(
            session_id=session_id,
            transition_type=TransitionType.COMPLETE,
            from_status=SessionLifecycleStatus.EXECUTING,
            to_status=SessionLifecycleStatus.COMPLETED,
            reason="Runtime pipeline completed.",
        )
        self.session_service.save_snapshot(
            SessionSnapshot(
                session_id=session_id,
                state=execution.managed_session.state,
                context=execution.managed_session.context,
            )
        )
        self._publish(EventType.SESSION_COMPLETED, session_id, {"status": "completed"})

        return RuntimeResult(
            session_id=str(session_id),
            status="completed",
            recommendation=recommendation.summary,
            confidence=recommendation.confidence,
        )

    def _create_execution_context(self, objective_text: str) -> ExecutionContext:
        """Create the initial domain and managed session objects."""
        normalized_objective = objective_text.strip()
        if normalized_objective == "":
            msg = "objective cannot be blank"
            raise ValueError(msg)

        organization = Organization(name="ECOS Demo Organization")
        objective = Objective(
            organization_id=organization.id,
            title=normalized_objective,
            description="Runtime demo objective.",
            priority=3,
        )
        cognitive_session = CognitiveSession(
            organization_id=organization.id,
            objective=objective,
            status=SessionStatus.INITIALIZED,
            current_stage=SessionStage.CONTEXT,
            confidence=0.0,
        )
        state = SessionState(
            session_id=cognitive_session.id,
            lifecycle_status=SessionLifecycleStatus.CREATED,
            current_stage=SessionStage.CONTEXT,
            active_engine=None,
            progress=0.0,
        )
        session_context = SessionContext(
            organization_id=organization.id,
            objective=objective,
            metadata={"runtime": True},
        )
        managed_session = ManagedSession(
            session=cognitive_session,
            state=state,
            context=session_context,
        )
        managed_session = self.session_service.create_session(managed_session)
        self._publish(
            EventType.SESSION_CREATED,
            cognitive_session.id,
            {"objective": normalized_objective},
        )
        return ExecutionContext(
            managed_session=managed_session,
            cognitive_session=cognitive_session,
        )

    def _create_plan(
        self,
        session: CognitiveSession,
        objective: Objective,
    ) -> CognitivePlan:
        """Create a cognitive plan through the planner provider abstraction."""
        try:
            return self.planner_service.create_plan(
                PlannerInput(
                    session_id=session.id,
                    organization_id=session.organization_id,
                    objective=objective,
                    description=objective.description,
                    priority=objective.priority,
                    desired_outcome="Produce a governed recommendation.",
                    constraints=("No external calls", "No real AI providers"),
                    policies=("human_approval_required",),
                    resources_available=("runtime",),
                    domains=("strategy", "risk"),
                    context_available=True,
                    context_gap_count=0,
                    critical_context_gap_count=0,
                    execution_requested=False,
                    stakeholders_count=3,
                    temporal_horizon="quarter",
                    impact="high",
                    reversible=True,
                    metadata={"runtime": True},
                    correlation_id=session.id,
                )
            )
        except RuntimeError as error:
            if "real cognitive planner is not configured" not in str(error):
                raise
        planning_strategy = self.planner_service.classify_objective(objective)
        complexity = self.planner_service.estimate_complexity(objective)
        strategy = ExecutionStrategy(
            strategy=planning_strategy,
            rationale="Runtime demo uses a balanced deterministic strategy.",
            constraints=["No external calls", "No real AI providers"],
        )
        engines = self.planner_service.select_engines(objective, strategy, complexity)
        specialists = self.planner_service.select_specialists(
            objective,
            strategy,
            complexity,
        )
        pipeline = self.planner_service.build_pipeline(engines, specialists)
        self._record_transition(
            session_id=session.id,
            transition_type=TransitionType.START_PLANNING,
            from_status=SessionLifecycleStatus.INITIALIZED,
            to_status=SessionLifecycleStatus.PLANNING,
            reason="Runtime plan created.",
        )
        return CognitivePlan(
            session_id=session.id,
            objective=objective,
            complexity=complexity,
            strategy=strategy,
            selected_engines=engines,
            selected_specialists=specialists,
            pipeline=pipeline,
            estimated_duration=60,
            estimated_cost=0.0,
            confidence_target=0.9,
        )

    def _configure_orchestrator(self) -> None:
        """Inject a fresh executor registry from the current runtime services."""
        executors = {
            "context": ContextExecutor(self.context_service),
            "reasoning": ReasoningExecutor(self.reasoning_service),
            "specialists": SpecialistsExecutor(self.specialist_service),
            "debate": DebateExecutor(self.debate_service),
            "simulation": SimulationExecutor(self.simulation_service),
            "decision": DecisionExecutor(self.decision_service),
            "decision_support": DecisionExecutor(
                self.decision_service,
                engine_type="decision_support",
            ),
            "memory": LearningExecutor(self.learning_service),
            "learning": LearningExecutor(
                self.learning_service,
                engine_type="learning",
            ),
            "governance": NoopExecutor("governance"),
            "execution": NoopExecutor("execution"),
            "observation": NoopExecutor("observation"),
        }
        orchestrator = Orchestrator(
            executors=executors,
            event_service=self.event_service,
            session_service=self.session_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            sleeper=asyncio.sleep,
            config=OrchestrationConfig(mode=OrchestrationMode.SEQUENTIAL),
        )
        self.orchestrator_service = OrchestratorService(
            self.orchestrator_service._provider,
            orchestrator,
        )

    def _update_session_state(
        self,
        execution: ExecutionContext,
        *,
        lifecycle_status: SessionLifecycleStatus,
        current_stage: SessionStage,
        active_engine: str | None,
        progress: float,
    ) -> None:
        """Update managed session state through the session service."""
        state = SessionState(
            session_id=execution.cognitive_session.id,
            lifecycle_status=lifecycle_status,
            current_stage=current_stage,
            active_engine=active_engine,
            progress=progress,
        )
        self.session_service.update_state(state)
        execution.managed_session = execution.managed_session.model_copy(
            update={"state": state}
        )
        self._publish(
            EventType.SESSION_UPDATED,
            execution.cognitive_session.id,
            {"status": lifecycle_status.value, "progress": progress},
        )

    def _record_transition(
        self,
        *,
        session_id: UUID,
        transition_type: TransitionType,
        from_status: SessionLifecycleStatus,
        to_status: SessionLifecycleStatus,
        reason: str,
    ) -> None:
        """Record a lifecycle transition through the session service."""
        self.session_service.record_transition(
            SessionTransition(
                session_id=session_id,
                transition_type=transition_type,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
            )
        )

    def _publish(
        self,
        event_type: EventType,
        session_id: UUID,
        payload: dict[str, str | int | float | bool | None],
    ) -> None:
        """Publish and dispatch a runtime event through the event service."""
        envelope = self.event_service.publish(
            Event(
                event_type=event_type,
                source="runtime",
                session_id=session_id,
                payload=payload,
                priority=EventPriority.NORMAL,
            )
        )
        self.event_service.dispatch(envelope)


class RuntimeEngine:
    """Public runtime engine entrypoint for the demo cognitive pipeline."""

    def __init__(self, pipeline: CognitivePipeline) -> None:
        """Initialize the engine with an externally provided pipeline."""
        self.pipeline = pipeline

    @classmethod
    def with_fakes(cls) -> "RuntimeEngine":
        """Create a standalone runtime engine backed by fake dependencies."""
        return cls(CognitivePipeline.with_fakes())

    def run(self, objective: str) -> RuntimeResult:
        """Run the first executable ECOS cognitive pipeline."""
        return self.pipeline.run(objective)

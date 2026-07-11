"""Executable fake runtime pipeline for ECOS."""

from uuid import UUID

from ecos.context import ContextBuildRequest, ContextProvider, ContextService
from ecos.debate import Debate, DebateService
from ecos.decision import DecisionContext, DecisionService
from ecos.domain import CognitiveSession, Objective, Organization, SessionStage
from ecos.domain.enums import SessionStatus
from ecos.events import Event, EventBus, EventPriority, EventService, EventType
from ecos.learning import LearningObject, LearningService
from ecos.memory import MemoryRepository, MemoryService, MemoryType
from ecos.orchestrator import (
    ExecutionMode,
    ExecutionPlan,
    ExecutionState,
    ExecutionStatus,
    ExecutionStep,
    OrchestratorService,
)
from ecos.planner import CognitivePlan, ExecutionStrategy, PlannerInput, PlannerService
from ecos.providers import AIProvider, AIService, ProviderRegistry, ProviderType
from ecos.reasoning import ReasoningContext, ReasoningService, ReasoningType
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
from ecos.simulation import SimulationContext, SimulationService
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
        return cls(
            memory_repository=memory_repository,
            session_repository=session_repository,
            event_bus=event_bus,
            context_provider=context_provider,
            ai_provider=ai_provider,
            memory_service=memory_service,
            learning_service=LearningService(memory_service, event_service),
            session_service=SessionService(session_repository),
            event_service=event_service,
            context_service=ContextService(context_provider),
            planner_service=PlannerService(planner_provider),
            reasoning_service=ReasoningService(reasoning_provider),
            specialist_service=SpecialistService(
                specialist_provider,
                SpecialistRegistry(),
            ),
            debate_service=DebateService(debate_provider),
            simulation_service=SimulationService(simulation_provider),
            decision_service=DecisionService(decision_provider),
            orchestrator_service=OrchestratorService(orchestrator_provider),
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
        if plan.metadata.get("planner") != "deterministic":
            self._run_orchestrator(plan)

        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.CONTEXT,
            active_engine="context",
            progress=0.2,
        )
        if not self._plan_has_engine(plan, "context"):
            msg = "planned pipeline does not include context"
            raise RuntimeError(msg)
        if isinstance(self.context_provider, FakeContextProvider):
            self.context_provider.configure(
                session_id,
                execution.cognitive_session.objective,
            )
            context = self.context_service.build()
        else:
            context_request = ContextBuildRequest(
                session_id=session_id,
                organization_id=execution.cognitive_session.organization_id,
                objective=execution.cognitive_session.objective,
                user_information=[
                    execution.cognitive_session.objective.description or ""
                ]
                if execution.cognitive_session.objective.description
                else [],
                constraints=list(plan.strategy.constraints),
                policies=[],
                resources=[step.engine for step in plan.pipeline.steps],
                external_signals=[],
                relevant_entities=[execution.cognitive_session.objective.title],
                required_context_fields=["objective", "memory"],
                correlation_id=session_id,
            )
            context = self.context_service.build(context_request)
        if not self.context_service.validate(context):
            msg = "runtime context validation failed"
            raise RuntimeError(msg)
        execution.context = context
        if isinstance(self.context_provider, FakeContextProvider):
            self._publish(
                EventType.CONTEXT_CREATED,
                session_id,
                {"confidence": context.confidence},
            )

        if not self._plan_has_engine(plan, "reasoning"):
            msg = "planned pipeline does not include reasoning"
            raise RuntimeError(msg)
        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.REASONING,
            active_engine="reasoning",
            progress=0.4,
        )
        reasoning_context = ReasoningContext(
            session_id=session_id,
            context=context,
            reasoning_type=ReasoningType.STRATEGIC,
            constraints=list(context.constraints),
            memory=[
                str(reference.memory_id) for reference in context.memory_references
            ],
        )
        self._publish(
            EventType.REASONING_STARTED,
            session_id,
            {"status": "started"},
        )
        reasoning = self.reasoning_service.analyze(reasoning_context)
        execution.reasoning = reasoning
        completed_payload = {"confidence": reasoning.confidence}
        completed_payload.update(reasoning.metadata)
        self._publish(
            EventType.REASONING_COMPLETED,
            session_id,
            completed_payload,
        )

        specialists = []
        contributions = []
        if self._plan_has_engine(plan, "specialists"):
            planned_types = {
                selection.specialist_type for selection in plan.selected_specialists
            }
            specialists = [
                specialist
                for specialist in self.specialist_service.load()
                if not planned_types or specialist.type in planned_types
            ]
            contributions = [
                self.specialist_service.contribute(
                    specialist.id,
                    {"objective": objective, "reasoning": reasoning.summary},
                )
                for specialist in specialists
            ]
            self._publish(
                EventType.SPECIALIST_CONTRIBUTED,
                session_id,
                {"count": len(contributions)},
            )

        if not self._plan_has_engine(plan, "debate"):
            msg = "planned pipeline does not include debate"
            raise RuntimeError(msg)
        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.DEBATE,
            active_engine="debate",
            progress=0.6,
        )
        debate = Debate(
            session_id=session_id,
            specialists=specialists,
            objective=objective,
            unified_context=context.model_dump(mode="json"),
            organizational_constraints=reasoning_context.constraints,
            reasoning_result=reasoning,
            contributions=contributions,
        )
        self._publish(
            EventType.DEBATE_STARTED,
            session_id,
            {"status": "started", "participants": len(specialists)},
        )
        debate = self.debate_service.start(debate)
        arguments = self.debate_service.collect_arguments(debate)
        debate = debate.model_copy(update={"arguments": arguments})
        debate_result = self.debate_service.finalize(debate)
        debate_payload = {"confidence": debate_result.confidence}
        debate_payload.update(debate_result.metadata)
        self._publish(
            EventType.DEBATE_COMPLETED,
            session_id,
            debate_payload,
        )

        if not self._plan_has_engine(plan, "simulation"):
            msg = "planned pipeline does not include simulation"
            raise RuntimeError(msg)
        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.SIMULATION,
            active_engine="simulation",
            progress=0.7,
        )
        simulation_context = SimulationContext(
            session_id=session_id,
            objective=execution.cognitive_session.objective.model_dump(mode="json"),
            unified_context=context.model_dump(mode="json"),
            organizational_constraints=reasoning_context.constraints,
            relevant_policies=[
                element.content
                for element in context.elements
                if element.source_type.value == "POLICY"
            ],
            memory=[item.model_dump(mode="json") for item in context.memory_references],
            reasoning_report=reasoning,
            debate_report=debate_result,
            external_signals=[
                element.model_dump(mode="json")
                for element in context.elements
                if element.source_type.value == "EXTERNAL"
            ],
            correlation_id=reasoning.correlation_id,
        )
        self._publish(EventType.SIMULATION_STARTED, session_id, {"status": "started"})
        simulation = self.simulation_service.simulate(simulation_context)
        execution.simulation = simulation
        self._publish(
            EventType.SIMULATION_COMPLETED,
            session_id,
            {
                "status": "completed",
                "scenario_count": len(simulation.scenarios),
                "risk_count": len(simulation.cross_scenario_risks)
                + sum(len(item.risks) for item in simulation.scenarios),
                "contingency_count": len(simulation.contingencies),
                "resilience_score": simulation.resilience_score,
                "confidence": simulation.confidence,
                **simulation.metadata,
            },
        )

        if not (
            self._plan_has_engine(plan, "decision_support")
            or self._plan_has_engine(plan, "decision")
        ):
            msg = "planned pipeline does not include decision support"
            raise RuntimeError(msg)
        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.RECOMMENDATION,
            active_engine="decision",
            progress=0.8,
        )
        decision_context = DecisionContext(
            session_id=session_id,
            objective=execution.cognitive_session.objective.model_dump(mode="json"),
            unified_context=context,
            constraints=reasoning_context.constraints,
            relevant_policies=[
                element.content
                for element in context.elements
                if element.source_type.value == "POLICY"
            ],
            memory=[item.model_dump(mode="json") for item in context.memory_references],
            reasoning_report=reasoning,
            debate_report=debate_result,
            simulation_report=simulation,
            correlation_id=reasoning.correlation_id,
        )
        self._publish(
            EventType.RECOMMENDATION_STARTED,
            session_id,
            {"status": "started"},
        )
        recommendation = self.decision_service.build_recommendation(
            reasoning,
            debate_result,
            decision_context,
        )
        executive_brief = self.decision_service.build_executive_brief(recommendation)
        decision_package = self.decision_service.build_decision_package(
            recommendation,
            executive_brief,
        )
        execution.recommendation = recommendation
        self._publish(
            EventType.RECOMMENDATION_CREATED,
            session_id,
            {
                "confidence": recommendation.confidence,
                "alternative_count": len(recommendation.alternatives),
                "risk_count": len(recommendation.risks),
                **decision_package.metadata,
            },
        )

        memory = self.learning_service.learn(
            LearningObject(
                session_id=session_id,
                memory_type=MemoryType.EPISODIC,
                title="Runtime cognitive pipeline completed",
                description=recommendation.summary,
                evidence=[reasoning.summary, *debate_result.recommendations],
                tags=["runtime", "demo", "cognitive-pipeline"],
                confidence=recommendation.confidence,
                origin="runtime",
                organization_id=execution.cognitive_session.organization_id,
            )
        )
        if memory is None:
            raise RuntimeError("runtime learning was rejected")
        execution.memory = memory

        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.COMPLETED,
            current_stage=SessionStage.LEARNING,
            active_engine=None,
            progress=1.0,
        )
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

    def _plan_has_engine(self, plan: CognitivePlan, engine: str) -> bool:
        """Return whether a normalized engine is present in the plan."""
        return engine in {selection.engine for selection in plan.selected_engines}

    def _run_orchestrator(self, plan: CognitivePlan) -> None:
        """Run the fake orchestrator provider over the planned pipeline."""
        steps = [
            ExecutionStep(
                order=step.order,
                engine=step.engine,
                depends_on=step.depends_on,
                state=ExecutionState(status=ExecutionStatus.CREATED),
                optional=step.optional,
            )
            for step in plan.pipeline.steps
        ]
        execution_plan = ExecutionPlan(
            session_id=plan.session_id,
            execution_mode=ExecutionMode.SEQUENTIAL,
            steps=steps,
        )
        execution_plan = self.orchestrator_service.start(execution_plan)
        for step in execution_plan.steps:
            self.orchestrator_service.execute_step(execution_plan, step)
        self.orchestrator_service.complete(execution_plan)
        self._publish(
            EventType.EXECUTION_STARTED,
            plan.session_id,
            {"steps": len(steps)},
        )
        self._publish(
            EventType.EXECUTION_COMPLETED,
            plan.session_id,
            {"steps": len(steps)},
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

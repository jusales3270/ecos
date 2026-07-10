"""Executable fake runtime pipeline for ECOS."""

from uuid import UUID

from ecos.context import ContextService
from ecos.debate import Debate, DebateService
from ecos.decision import DecisionService
from ecos.domain import CognitiveSession, Objective, Organization, SessionStage
from ecos.domain.enums import SessionStatus

from ecos.orchestrator import (
    ExecutionMode,
    ExecutionPlan,
    ExecutionState,
    ExecutionStatus,
    ExecutionStep,
    OrchestratorService,
)
from ecos.planner import CognitivePlan, ExecutionStrategy, PlannerService

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
)
from ecos.runtime.models import ExecutionContext, RuntimeResult
from ecos.session import (
    ManagedSession,
    SessionContext,
    SessionLifecycleStatus,

    SessionService,
    SessionSnapshot,
    SessionState,
    SessionTransition,
    TransitionType,
)
from ecos.specialists import SpecialistRegistry, SpecialistService


class CognitivePipeline:
    """Coordinates the first deterministic ECOS cognitive pipeline."""



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
        self._run_orchestrator(plan)

        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.CONTEXT,
            active_engine="context",
            progress=0.2,
        )

            msg = "runtime context validation failed"
            raise RuntimeError(msg)
        execution.context = context
        self._publish(
            EventType.CONTEXT_CREATED,
            session_id,
            {"confidence": context.confidence},
        )

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
        )
        reasoning = self.reasoning_service.analyze(reasoning_context)
        execution.reasoning = reasoning
        self._publish(
            EventType.REASONING_COMPLETED,
            session_id,
            {"confidence": reasoning.confidence},
        )

        specialists = self.specialist_service.load()
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

        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.DEBATE,
            active_engine="debate",
            progress=0.6,
        )
        debate = Debate(session_id=session_id, specialists=specialists)
        debate = self.debate_service.start(debate)
        arguments = self.debate_service.collect_arguments(debate)
        debate = debate.model_copy(update={"arguments": arguments})
        debate_result = self.debate_service.finalize(debate)
        self._publish(
            EventType.DEBATE_COMPLETED,
            session_id,
            {"confidence": debate_result.confidence},
        )

        self._update_session_state(
            execution,
            lifecycle_status=SessionLifecycleStatus.EXECUTING,
            current_stage=SessionStage.RECOMMENDATION,
            active_engine="decision",
            progress=0.8,
        )
        recommendation = self.decision_service.build_recommendation(
            reasoning,
            debate_result,
        )
        executive_brief = self.decision_service.build_executive_brief(recommendation)
        self.decision_service.build_decision_package(recommendation, executive_brief)
        execution.recommendation = recommendation
        self._publish(
            EventType.RECOMMENDATION_CREATED,
            session_id,
            {"confidence": recommendation.confidence},
        )

        memory = self.memory_service.store(
            MemoryObject(
                type=MemoryType.EPISODIC,
                title="Runtime cognitive pipeline completed",
                description=recommendation.summary,
                tags=["runtime", "demo", "cognitive-pipeline"],
                confidence=recommendation.confidence,
                source="runtime",
            )
        )
        execution.memory = memory
        self._publish(
            EventType.MEMORY_UPDATED,
            session_id,
            {"memory_id": str(memory.id)},
        )

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
        self._publish(EventType.SESSION_COMPLETED, session_id, {"status": "completed"})
        self.session_service.save_snapshot(
            SessionSnapshot(
                session_id=session_id,
                state=execution.managed_session.state,
                context=execution.managed_session.context,
            )
        )

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



"""Fake and in-memory runtime implementations for ECOS architecture contracts."""

from collections.abc import Iterator
from uuid import UUID

from ecos.context import (
    ContextBuildRequest,
    ContextElement,
    ContextObject,
    ContextPriority,
    ContextProvider,
    ContextSourceType,
)
from ecos.debate import (
    Argument,
    Consensus,
    ConsensusLevel,
    Debate,
    DebateProvider,
    DebateResult,
    DebateStatus,
)
from ecos.decision import (
    AlternativeAnalysis,
    DecisionContext,
    DecisionImpact,
    DecisionPackage,
    DecisionProvider,
    ExecutiveBrief,
    Recommendation,
    RecommendationType,
    RiskSummary,
)
from ecos.domain import Objective
from ecos.events import Event, EventBus, EventEnvelope, EventSubscription
from ecos.memory import MemoryObject, MemoryRepository, MemoryType
from ecos.orchestrator import (
    EngineExecution,
    ExecutionPlan,
    ExecutionResult,
    ExecutionState,
    ExecutionStatus,
    ExecutionStep,
    OrchestratorProvider,
)
from ecos.planner import (
    ComplexityLevel,
    EngineSelection,
    ExecutionStrategy,
    Pipeline,
    PipelineStep,
    PlannerProvider,
    PlanningStrategy,
    SpecialistSelection,
)
from ecos.providers import (
    AIProvider,
    AIRequest,
    AIResponse,
    ProviderHealth,
    ProviderStatus,
    ProviderType,
    TokenUsage,
)
from ecos.reasoning import (
    Alternative,
    Hypothesis,
    ReasoningContext,
    ReasoningEvidence,
    ReasoningProvider,
    ReasoningResult,
    Tradeoff,
)
from ecos.session import (
    ManagedSession,
    SessionRepository,
    SessionSnapshot,
    SessionState,
    SessionTransition,
)
from ecos.simulation import (
    Contingency,
    Scenario,
    ScenarioType,
    SimulationContext,
    SimulationProvider,
    SimulationReport,
)
from ecos.specialists import (
    Capability,
    Contribution,
    ContributionType,
    Specialist,
    SpecialistProvider,
    SpecialistType,
)


class FakeMemoryRepository(MemoryRepository):
    """In-memory memory repository used only by the runtime demo."""

    def __init__(self) -> None:
        """Initialize empty memory storage."""
        self.memories: dict[UUID, MemoryObject] = {}

    def store(self, memory: MemoryObject) -> MemoryObject:
        """Store a memory object in memory."""
        self.memories[memory.id] = memory
        return memory

    def get(self, memory_id: UUID) -> MemoryObject | None:
        """Return a stored memory object by id."""
        return self.memories.get(memory_id)

    def search(
        self,
        query: str,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        """Search stored memories using deterministic in-memory filters."""
        normalized_query = query.lower().strip()
        memories = [
            memory
            for memory in self.list(
                organization_id=organization_id,
                memory_type=memory_type,
                tags=tags,
                limit=None,
            )
            if normalized_query in memory.title.lower()
            or normalized_query in memory.description.lower()
        ]
        if limit is not None:
            return memories[:limit]
        return memories

    def update(self, memory: MemoryObject) -> MemoryObject:
        """Update an existing memory object in memory."""
        self.memories[memory.id] = memory
        return memory

    def delete(self, memory_id: UUID) -> None:
        """Delete a memory object from memory."""
        self.memories.pop(memory_id, None)

    def list(
        self,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        """List stored memories using deterministic in-memory filters."""
        memories = list(self.memories.values())
        if organization_id is not None:
            memories = [
                memory
                for memory in memories
                if memory.organization_id == organization_id
            ]
        if memory_type is not None:
            memories = [memory for memory in memories if memory.type == memory_type]
        if tags is not None:
            required_tags = set(tags)
            memories = [
                memory for memory in memories if required_tags.issubset(memory.tags)
            ]
        if limit is not None:
            memories = memories[:limit]
        return memories


class FakeContextProvider(ContextProvider):
    """Fake context provider that builds deterministic context objects."""

    def __init__(
        self,
        session_id: UUID | None = None,
        objective: Objective | None = None,
    ) -> None:
        """Initialize the provider with optional runtime session data."""
        self._session_id = session_id
        self._objective = objective

    def configure(
        self,
        session_id: UUID,
        objective: Objective,
    ) -> "FakeContextProvider":
        """Configure runtime session data without creating a new provider."""
        self._session_id = session_id
        self._objective = objective
        return self

    def build(self, request: ContextBuildRequest | None = None) -> ContextObject:
        """Build a deterministic context object."""
        if request is not None:
            self.configure(request.session_id, request.objective)
        if self._session_id is None or self._objective is None:
            msg = "fake context provider is not configured"
            raise RuntimeError(msg)
        element = ContextElement(
            source_type=ContextSourceType.USER,
            priority=ContextPriority.HIGH,
            title="Runtime objective",
            content=self._objective.title,
            confidence=0.9,
            metadata={"runtime": True},
        )
        return ContextObject(
            session_id=self._session_id,
            objective=self._objective,
            elements=[element],
            confidence=0.9,
        )

    def expand(self, context: ContextObject) -> ContextObject:
        """Return the context unchanged for the fake runtime."""
        return context

    def compress(self, context: ContextObject) -> ContextObject:
        """Return the context unchanged for the fake runtime."""
        return context

    def validate(self, context: ContextObject) -> bool:
        """Validate that the context belongs to the current session."""
        return context.session_id == self._session_id and bool(context.elements)


class FakePlannerProvider(PlannerProvider):
    """Fake planner provider that creates a deterministic cognitive plan."""

    def classify_objective(self, objective: Objective) -> PlanningStrategy:
        """Classify every demo objective as balanced."""
        return PlanningStrategy.BALANCED

    def estimate_complexity(self, objective: Objective) -> ComplexityLevel:
        """Estimate every demo objective as level 2 complexity."""
        return ComplexityLevel.LEVEL_2

    def select_engines(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[EngineSelection]:
        """Select deterministic engines for the runtime pipeline."""
        return [
            EngineSelection(engine="context", reason="Build execution context."),
            EngineSelection(engine="reasoning", reason="Analyze objective."),
            EngineSelection(engine="specialists", reason="Collect specialist input."),
            EngineSelection(engine="debate", reason="Compare specialist arguments."),
            EngineSelection(engine="simulation", reason="Explore possible scenarios."),
            EngineSelection(engine="decision", reason="Prepare recommendation."),
            EngineSelection(
                engine="governance",
                reason="Validate governed continuation.",
            ),
            EngineSelection(engine="memory", reason="Record execution memory."),
        ]

    def select_specialists(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[SpecialistSelection]:
        """Select deterministic specialists for the runtime pipeline."""
        return [
            SpecialistSelection(
                specialist_type=SpecialistType.STRATEGY,
                reason="Evaluate strategic fit.",
            ),
            SpecialistSelection(
                specialist_type=SpecialistType.RISK,
                reason="Identify execution risks.",
            ),
        ]

    def build_pipeline(
        self,
        engines: list[EngineSelection],
        specialists: list[SpecialistSelection],
    ) -> Pipeline:
        """Build an ordered deterministic pipeline."""
        steps = []
        previous_stage_id: UUID | None = None
        for index, engine in enumerate(engines, start=1):
            step = PipelineStep(
                order=index,
                engine=engine.engine,
                dependencies=() if previous_stage_id is None else (previous_stage_id,),
            )
            steps.append(step)
            previous_stage_id = step.stage_id
        return Pipeline(steps=steps, metadata={"runtime": True})


class FakeReasoningProvider(ReasoningProvider):
    """Fake reasoning provider that returns deterministic analysis artifacts."""

    def analyze(self, context: ReasoningContext) -> ReasoningResult:
        """Analyze context deterministically without AI."""
        hypotheses = self.generate_hypotheses(context)
        alternatives = self.evaluate_alternatives(context, hypotheses)
        evidence = [
            ReasoningEvidence(
                source="runtime-context",
                content=context.context.objective.title,
                confidence=0.9,
            )
        ]
        tradeoffs = [
            Tradeoff(
                dimension="execution",
                benefit="Coordinated execution across ECOS engines.",
                cost="Requires governance before real-world execution.",
                severity=0.2,
            )
        ]
        return ReasoningResult(
            session_id=context.session_id,
            reasoning_type=context.reasoning_type,
            hypotheses=hypotheses,
            alternatives=alternatives,
            tradeoffs=tradeoffs,
            evidence=evidence,
            confidence=0.91,
            summary="Deterministic reasoning completed for the objective.",
        )

    def generate_hypotheses(self, context: ReasoningContext) -> list[Hypothesis]:
        """Generate deterministic hypotheses."""
        return [
            Hypothesis(
                statement="A structured execution path improves decision quality.",
                rationale=(
                    f"The objective is explicit: {context.context.objective.title}"
                ),
                confidence=0.9,
            )
        ]

    def evaluate_alternatives(
        self,
        context: ReasoningContext,
        hypotheses: list[Hypothesis],
    ) -> list[Alternative]:
        """Evaluate deterministic alternatives."""
        return [
            Alternative(
                title="Proceed with governed execution",
                description="Use ECOS modules to refine and govern the objective.",
                score=0.91,
            )
        ]

    def calculate_confidence(self, result: ReasoningResult) -> float:
        """Return the deterministic result confidence."""
        return result.confidence


class FakeSpecialistProvider(SpecialistProvider):
    """Fake specialist provider with deterministic specialists and contributions."""

    def load(self) -> list[Specialist]:
        """Load deterministic specialists."""
        return [
            Specialist(
                name="Strategy Specialist",
                type=SpecialistType.STRATEGY,
                description="Evaluates strategic implications.",
                capabilities=[
                    Capability(
                        name="Strategic analysis",
                        description="Assesses strategic alignment.",
                    )
                ],
            ),
            Specialist(
                name="Risk Specialist",
                type=SpecialistType.RISK,
                description="Evaluates execution risk.",
                capabilities=[
                    Capability(
                        name="Risk analysis",
                        description="Assesses operational risks.",
                    )
                ],
            ),
        ]

    def analyze(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> list[Contribution]:
        """Analyze input data with deterministic contributions."""
        return [self.contribute(specialist, input_data)]

    def contribute(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> Contribution:
        """Produce a deterministic specialist contribution."""
        return Contribution(
            specialist_id=specialist.id,
            contribution_type=ContributionType.RECOMMENDATION,
            content=f"{specialist.name} supports a governed next step.",
            confidence=0.9,
            metadata={"runtime": True},
        )


class FakeDebateProvider(DebateProvider):
    """Fake debate provider that deterministically finalizes consensus."""

    def start(self, debate: Debate) -> Debate:
        """Mark the debate as running."""
        return debate.model_copy(update={"status": DebateStatus.RUNNING})

    def collect_arguments(self, debate: Debate) -> list[Argument]:
        """Collect deterministic arguments from debate specialists."""
        return [
            Argument(
                specialist_id=specialist.id,
                position="Support",
                content=f"{specialist.name} supports the recommendation.",
                confidence=0.9,
            )
            for specialist in debate.specialists
        ]

    def evaluate_consensus(self, debate: Debate) -> Consensus:
        """Produce deterministic high consensus."""
        return Consensus(
            level=ConsensusLevel.HIGH,
            summary="Specialists agree on governed execution.",
            agreements=["Proceed with explicit governance."],
        )

    def finalize(self, debate: Debate) -> DebateResult:
        """Finalize debate deterministically."""
        consensus = self.evaluate_consensus(debate)
        return DebateResult(
            debate_id=debate.id,
            consensus=consensus,
            recommendations=["Proceed with a governed execution plan."],
            unresolved_questions=[],
            confidence=0.91,
        )


class FakeWarEngine(SimulationProvider):
    """Deterministic exploratory simulation used by fake/demo mode."""

    def simulate(self, context: SimulationContext) -> SimulationReport:
        scenarios = [
            Scenario(
                scenario_id=scenario_type.value,
                scenario_type=scenario_type,
                name=scenario_type.value.replace("_", " ").title(),
                description="Deterministic exploratory scenario.",
                assumptions=[],
                trigger_conditions=[],
                probability=probability,
                early_warning_signals=[],
                impacts={},
                risks=[],
                opportunities=[],
                second_order_effects=[],
                failure_modes=[],
                success_factors=[],
                mitigation_actions=[],
                recovery_options=[],
            )
            for scenario_type, probability in (
                (ScenarioType.BEST_CASE, 0.3),
                (ScenarioType.EXPECTED_CASE, 0.6),
                (ScenarioType.WORST_CASE, 0.2),
                (ScenarioType.BLACK_SWAN, 0.01),
            )
        ]
        return SimulationReport(
            session_id=context.session_id,
            objective=str(context.objective.get("title", "Runtime objective")),
            critical_assumptions=[],
            scenarios=scenarios,
            cross_scenario_risks=[],
            cross_scenario_opportunities=[],
            second_order_effects=[],
            failure_modes=[],
            success_factors=[],
            contingencies=[
                Contingency(
                    primary_plan="Proceed through governance.",
                    fallback_plan="Pause and reassess.",
                    emergency_plan="Stop execution.",
                    recovery_plan="Restore the prior stable state.",
                    exit_strategy="Exit through governance.",
                    activation_conditions=["Material deviation"],
                )
            ],
            resilience_score=0.8,
            confidence=0.8,
            executive_assessment=(
                "Exploratory simulation; not a prediction or decision."
            ),
        )


class FakeDecisionProvider(DecisionProvider):
    """Fake decision provider that produces deterministic recommendations."""

    def build_recommendation(
        self,
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
        decision_context: DecisionContext | None = None,
    ) -> Recommendation:
        """Build a deterministic executive recommendation."""
        del debate_result, decision_context
        risk = RiskSummary(
            title="Execution governance",
            description="Governance is required before operational execution.",
            impact=DecisionImpact.MEDIUM,
            probability=0.2,
            mitigation="Use approval checkpoints before execution.",
        )
        alternative = AlternativeAnalysis(
            title="Delay execution",
            summary="Delay until more information is available.",
            pros=["More certainty."],
            cons=["Slower organizational learning."],
            score=0.45,
        )
        return Recommendation(
            session_id=reasoning_result.session_id,
            recommendation_type=RecommendationType.STRATEGIC,
            title="Proceed with governed execution",
            summary="Proceed using ECOS context, reasoning, debate and governance.",
            confidence=0.91,
            risks=[risk],
            alternatives=[alternative],
            expected_impact=DecisionImpact.HIGH,
        )

    def build_executive_brief(
        self,
        recommendation: Recommendation,
    ) -> ExecutiveBrief:
        """Build a deterministic executive brief."""
        return ExecutiveBrief(
            title="Runtime recommendation brief",
            summary=recommendation.summary,
            key_points=["Context assembled", "Reasoning completed", "Debate aligned"],
            decision_required=True,
        )

    def build_decision_package(
        self,
        recommendation: Recommendation,
        executive_brief: ExecutiveBrief,
    ) -> DecisionPackage:
        """Build a deterministic decision package."""
        return DecisionPackage(
            recommendation=recommendation,
            executive_brief=executive_brief,
            supporting_evidence=["Runtime context", "Runtime reasoning"],
            required_approvals=["Executive sponsor"],
            metadata={"runtime": True},
        )


class FakeOrchestratorProvider(OrchestratorProvider):
    """Fake orchestrator provider that updates execution state only."""

    def start(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Mark an execution plan as running."""
        current_step = plan.steps[0].id if plan.steps else None
        return plan.model_copy(
            update={"status": ExecutionStatus.RUNNING, "current_step": current_step}
        )

    def execute_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
    ) -> ExecutionStep:
        """Mark a single step as completed."""
        state = ExecutionState(status=ExecutionStatus.COMPLETED, message="completed")
        return step.model_copy(update={"state": state})

    def pause(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Mark an execution plan as waiting."""
        return plan.model_copy(update={"status": ExecutionStatus.WAITING})

    def resume(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Mark an execution plan as running."""
        return plan.model_copy(update={"status": ExecutionStatus.RUNNING})

    def cancel(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Mark an execution plan as cancelled."""
        return plan.model_copy(update={"status": ExecutionStatus.CANCELLED})

    def complete(self, plan: ExecutionPlan) -> ExecutionResult:
        """Complete an execution plan deterministically."""
        executions = [
            EngineExecution(
                execution_plan_id=plan.id,
                execution_step_id=step.id,
                engine=step.engine,
                status=ExecutionStatus.COMPLETED,
            )
            for step in plan.steps
        ]
        return ExecutionResult(
            execution_plan_id=plan.id,
            status=ExecutionStatus.COMPLETED,
            engine_executions=executions,
            summary="Runtime execution completed.",
        )


class FakeSessionRepository(SessionRepository):
    """In-memory session repository used only by the runtime demo."""

    def __init__(self) -> None:
        """Initialize empty session storage."""
        self.sessions: dict[UUID, ManagedSession] = {}
        self.snapshots: list[SessionSnapshot] = []
        self.transitions: dict[UUID, list[SessionTransition]] = {}

    def create(self, session: ManagedSession) -> ManagedSession:
        """Create a managed session in memory."""
        self.sessions[session.session.id] = session
        return session

    def get(self, session_id: UUID) -> ManagedSession | None:
        """Get a managed session by id."""
        return self.sessions.get(session_id)

    def update_state(self, state: SessionState) -> SessionState:
        """Update stored state for a managed session."""
        managed = self.sessions[state.session_id]
        self.sessions[state.session_id] = managed.model_copy(update={"state": state})
        return state

    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        """Save a session snapshot in memory."""
        self.snapshots.append(snapshot)
        return snapshot

    def list_transitions(self, session_id: UUID) -> list[SessionTransition]:
        """List session transitions from memory."""
        return self.transitions.get(session_id, [])

    def add_transition(self, transition: SessionTransition) -> SessionTransition:
        """Add a session transition in memory."""
        self.transitions.setdefault(transition.session_id, []).append(transition)
        return transition


class FakeEventBus(EventBus):
    """Fake in-memory event bus used only by the runtime demo."""

    def __init__(self) -> None:
        """Initialize empty event bus state."""
        self.envelopes: list[EventEnvelope] = []
        self.subscriptions: dict[UUID, EventSubscription] = {}
        self.dispatched: list[EventEnvelope] = []

    def publish(self, event: Event) -> EventEnvelope:
        """Publish an event into in-memory envelopes."""
        envelope = EventEnvelope(event=event, headers={"runtime": True})
        self.envelopes.append(envelope)
        return envelope

    def subscribe(self, subscription: EventSubscription) -> EventSubscription:
        """Store a subscription in memory."""
        self.subscriptions[subscription.id] = subscription
        return subscription

    def unsubscribe(self, subscription_id: UUID) -> None:
        """Remove a subscription from memory."""
        self.subscriptions.pop(subscription_id, None)

    def dispatch(self, envelope: EventEnvelope) -> None:
        """Record a dispatched envelope in memory."""
        self.dispatched.append(envelope)


class FakeAIProvider(AIProvider):
    """Fake AI provider that satisfies the interface without using AI."""

    def health(self) -> ProviderHealth:
        """Return deterministic available health."""
        return ProviderHealth(
            provider=ProviderType.CUSTOM,
            status=ProviderStatus.AVAILABLE,
        )

    def generate(self, request: AIRequest) -> AIResponse:
        """Return deterministic non-AI content for interface completeness."""
        return AIResponse(
            request_id=request.id,
            provider=request.provider,
            model=request.model,
            content="Fake provider response.",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            latency_ms=0,
        )

    def stream(self, request: AIRequest) -> Iterator[str]:
        """Yield deterministic non-AI chunks for interface completeness."""
        yield "Fake"
        yield " provider"
        yield " response."

    def embeddings(self, input_text: str) -> list[float]:
        """Return an empty fake embedding vector without computing embeddings."""
        return []

    def list_models(self) -> list[str]:
        """List deterministic fake model names."""
        return ["fake-runtime-model"]

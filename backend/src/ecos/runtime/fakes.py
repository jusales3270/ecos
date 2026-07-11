"""Fake and in-memory runtime implementations for ECOS architecture contracts."""

from collections.abc import Iterator
from uuid import UUID

from ecos.context import (
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
from ecos.specialists import (
    Capability,
    Contribution,
    ContributionType,
    Specialist,
    SpecialistProvider,
    SpecialistType,
)


class FakeMemoryRepository(MemoryRepository):
    """In-memory memory repository used by the local runtime."""

    def __init__(self) -> None:
        self.memories: dict[UUID, MemoryObject] = {}

    def store(self, memory: MemoryObject) -> MemoryObject:
        self.memories[memory.id] = memory
        return memory

    def get(self, memory_id: UUID) -> MemoryObject | None:
        return self.memories.get(memory_id)

    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        normalized = query.lower().strip()
        return [
            memory
            for memory in self.list(memory_type=memory_type, tags=tags)
            if normalized in memory.title.lower()
            or normalized in memory.description.lower()
        ]

    def update(self, memory: MemoryObject) -> MemoryObject:
        self.memories[memory.id] = memory
        return memory

    def delete(self, memory_id: UUID) -> None:
        self.memories.pop(memory_id, None)

    def list(
        self,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        memories = list(self.memories.values())
        if memory_type is not None:
            memories = [memory for memory in memories if memory.type == memory_type]
        if tags is not None:
            required_tags = set(tags)
            memories = [
                memory for memory in memories if required_tags.issubset(memory.tags)
            ]
        return memories


class FakeContextProvider(ContextProvider):
    """Configurable deterministic context provider."""

    def __init__(
        self,
        session_id: UUID | None = None,
        objective: Objective | None = None,
    ) -> None:
        self._session_id = session_id
        self._objective = objective

    def configure(self, session_id: UUID, objective: Objective) -> None:
        self._session_id = session_id
        self._objective = objective

    def build(self) -> ContextObject:
        if self._session_id is None or self._objective is None:
            raise RuntimeError("context provider is not configured")
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
        return context

    def compress(self, context: ContextObject) -> ContextObject:
        return context

    def validate(self, context: ContextObject) -> bool:
        return self._session_id is not None and (
            context.session_id == self._session_id and bool(context.elements)
        )


class FakePlannerProvider(PlannerProvider):
    def classify_objective(self, objective: Objective) -> PlanningStrategy:
        return PlanningStrategy.BALANCED

    def estimate_complexity(self, objective: Objective) -> ComplexityLevel:
        return ComplexityLevel.LEVEL_2

    def select_engines(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[EngineSelection]:
        return [
            EngineSelection(engine="context", reason="Build execution context."),
            EngineSelection(engine="reasoning", reason="Analyze objective."),
            EngineSelection(engine="specialists", reason="Collect specialist input."),
            EngineSelection(engine="debate", reason="Compare specialist arguments."),
            EngineSelection(engine="decision", reason="Prepare recommendation."),
            EngineSelection(engine="memory", reason="Record execution memory."),
        ]

    def select_specialists(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[SpecialistSelection]:
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
        return Pipeline(
            steps=[
                PipelineStep(order=index, engine=engine.engine)
                for index, engine in enumerate(engines, start=1)
            ],
            metadata={"runtime": True},
        )


class FakeReasoningProvider(ReasoningProvider):
    def analyze(self, context: ReasoningContext) -> ReasoningResult:
        hypotheses = self.generate_hypotheses(context)
        alternatives = self.evaluate_alternatives(context, hypotheses)
        return ReasoningResult(
            session_id=context.session_id,
            reasoning_type=context.reasoning_type,
            hypotheses=hypotheses,
            alternatives=alternatives,
            tradeoffs=[
                Tradeoff(
                    dimension="execution",
                    benefit="Coordinated execution across ECOS engines.",
                    cost="Requires governance before real-world execution.",
                    severity=0.2,
                )
            ],
            evidence=[
                ReasoningEvidence(
                    source="runtime-context",
                    content=context.context.objective.title,
                    confidence=0.9,
                )
            ],
            confidence=0.91,
            summary="Deterministic reasoning completed for the objective.",
        )

    def generate_hypotheses(self, context: ReasoningContext) -> list[Hypothesis]:
        return [
            Hypothesis(
                statement="A structured execution path improves decision quality.",
                rationale=f"The objective is explicit: {context.context.objective.title}",
                confidence=0.9,
            )
        ]

    def evaluate_alternatives(
        self,
        context: ReasoningContext,
        hypotheses: list[Hypothesis],
    ) -> list[Alternative]:
        return [
            Alternative(
                title="Proceed with governed execution",
                description="Use ECOS modules to refine and govern the objective.",
                score=0.91,
            )
        ]

    def calculate_confidence(self, result: ReasoningResult) -> float:
        return result.confidence


class FakeSpecialistProvider(SpecialistProvider):
    def load(self) -> list[Specialist]:
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
        return [self.contribute(specialist, input_data)]

    def contribute(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> Contribution:
        return Contribution(
            specialist_id=specialist.id,
            contribution_type=ContributionType.RECOMMENDATION,
            content=f"{specialist.name} supports a governed next step.",
            confidence=0.9,
            metadata={"runtime": True},
        )


class FakeDebateProvider(DebateProvider):
    def start(self, debate: Debate) -> Debate:
        return debate.model_copy(update={"status": DebateStatus.RUNNING})

    def collect_arguments(self, debate: Debate) -> list[Argument]:
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
        return Consensus(
            level=ConsensusLevel.HIGH,
            summary="Specialists agree on governed execution.",
            agreements=["Proceed with explicit governance."],
        )

    def finalize(self, debate: Debate) -> DebateResult:
        return DebateResult(
            debate_id=debate.id,
            consensus=self.evaluate_consensus(debate),
            recommendations=["Proceed with a governed execution plan."],
            unresolved_questions=[],
            confidence=0.91,
        )


class FakeDecisionProvider(DecisionProvider):
    def build_recommendation(
        self,
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
    ) -> Recommendation:
        return Recommendation(
            session_id=reasoning_result.session_id,
            recommendation_type=RecommendationType.STRATEGIC,
            title="Proceed with governed execution",
            summary="Proceed using ECOS context, reasoning, debate and governance.",
            confidence=0.91,
            risks=[
                RiskSummary(
                    title="Execution governance",
                    description=(
                        "Governance is required before operational execution."
                    ),
                    impact=DecisionImpact.MEDIUM,
                    probability=0.2,
                    mitigation="Use approval checkpoints before execution.",
                )
            ],
            alternatives=[
                AlternativeAnalysis(
                    title="Delay execution",
                    summary="Delay until more information is available.",
                    pros=["More certainty."],
                    cons=["Slower organizational learning."],
                    score=0.45,
                )
            ],
            expected_impact=DecisionImpact.HIGH,
        )

    def build_executive_brief(
        self,
        recommendation: Recommendation,
    ) -> ExecutiveBrief:
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
        return DecisionPackage(
            recommendation=recommendation,
            executive_brief=executive_brief,
            supporting_evidence=["Runtime context", "Runtime reasoning"],
            required_approvals=["Executive sponsor"],
            metadata={"runtime": True},
        )


class FakeOrchestratorProvider(OrchestratorProvider):
    def start(self, plan: ExecutionPlan) -> ExecutionPlan:
        current_step = plan.steps[0].id if plan.steps else None
        return plan.model_copy(
            update={"status": ExecutionStatus.RUNNING, "current_step": current_step}
        )

    def execute_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
    ) -> ExecutionStep:
        return step.model_copy(
            update={
                "state": ExecutionState(
                    status=ExecutionStatus.COMPLETED,
                    message="completed",
                )
            }
        )

    def pause(self, plan: ExecutionPlan) -> ExecutionPlan:
        return plan.model_copy(update={"status": ExecutionStatus.WAITING})

    def resume(self, plan: ExecutionPlan) -> ExecutionPlan:
        return plan.model_copy(update={"status": ExecutionStatus.RUNNING})

    def cancel(self, plan: ExecutionPlan) -> ExecutionPlan:
        return plan.model_copy(update={"status": ExecutionStatus.CANCELLED})

    def complete(self, plan: ExecutionPlan) -> ExecutionResult:
        return ExecutionResult(
            execution_plan_id=plan.id,
            status=ExecutionStatus.COMPLETED,
            engine_executions=[
                EngineExecution(
                    execution_plan_id=plan.id,
                    execution_step_id=step.id,
                    engine=step.engine,
                    status=ExecutionStatus.COMPLETED,
                )
                for step in plan.steps
            ],
            summary="Runtime execution completed.",
        )


class FakeSessionRepository(SessionRepository):
    def __init__(self) -> None:
        self.sessions: dict[UUID, ManagedSession] = {}
        self.snapshots: list[SessionSnapshot] = []
        self.transitions: dict[UUID, list[SessionTransition]] = {}

    def create(self, session: ManagedSession) -> ManagedSession:
        self.sessions[session.session.id] = session
        return session

    def get(self, session_id: UUID) -> ManagedSession | None:
        return self.sessions.get(session_id)

    def update_state(self, state: SessionState) -> SessionState:
        managed = self.sessions[state.session_id]
        self.sessions[state.session_id] = managed.model_copy(update={"state": state})
        return state

    def save_snapshot(self, snapshot: SessionSnapshot) -> SessionSnapshot:
        self.snapshots.append(snapshot)
        return snapshot

    def list_transitions(self, session_id: UUID) -> list[SessionTransition]:
        return list(self.transitions.get(session_id, []))

    def add_transition(self, transition: SessionTransition) -> SessionTransition:
        self.transitions.setdefault(transition.session_id, []).append(transition)
        return transition


class FakeEventBus(EventBus):
    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []
        self.subscriptions: dict[UUID, EventSubscription] = {}
        self.dispatched: list[EventEnvelope] = []

    def publish(self, event: Event) -> EventEnvelope:
        envelope = EventEnvelope(event=event, headers={"runtime": True})
        self.envelopes.append(envelope)
        return envelope

    def subscribe(self, subscription: EventSubscription) -> EventSubscription:
        self.subscriptions[subscription.id] = subscription
        return subscription

    def unsubscribe(self, subscription_id: UUID) -> None:
        self.subscriptions.pop(subscription_id, None)

    def dispatch(self, envelope: EventEnvelope) -> None:
        self.dispatched.append(envelope)


class FakeAIProvider(AIProvider):
    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=ProviderType.CUSTOM,
            status=ProviderStatus.AVAILABLE,
        )

    def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            request_id=request.id,
            provider=request.provider,
            model=request.model,
            content="Fake provider response.",
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
            latency_ms=0,
        )

    def stream(self, request: AIRequest) -> Iterator[str]:
        yield "Fake"
        yield " provider"
        yield " response."

    def embeddings(self, input_text: str) -> list[float]:
        return []

    def list_models(self) -> list[str]:
        return ["fake-runtime-model"]

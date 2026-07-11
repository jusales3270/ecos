"""Dependency injection container for ECOS services and fake providers."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ecos.context import ContextEngine, ContextService
from ecos.core.exceptions import ConfigurationError
from ecos.core.settings import Settings
from ecos.debate import AIDebateEngine, DebateService
from ecos.decision import AIDecisionSupportEngine, DecisionService
from ecos.domain import Objective, Organization
from ecos.events import EventService
from ecos.execution import (
    ConnectorRegistry,
    ExecutionEngine,
    InMemoryHumanTaskProvider,
    InMemoryIdempotencyProvider,
    default_in_memory_connector,
)
from ecos.governance import (
    DefaultApprovalPolicyProvider,
    GovernanceConfig,
    GovernanceEngine,
    InMemoryPolicyProvider,
    StaticIdentityPort,
    demo_policy,
)
from ecos.learning import LearningService
from ecos.memory import MemoryRepository, MemoryService, PostgresMemoryRepository
from ecos.orchestrator import (
    OrchestrationConfig,
    OrchestrationMode,
    Orchestrator,
    OrchestratorService,
)
from ecos.planner import CognitivePlanner, PlannerService
from ecos.providers import (
    AIProvider,
    AIService,
    OpenAIProvider,
    ProviderRegistry,
    ProviderStatus,
    ProviderType,
)
from ecos.reasoning import AIReasoningEngine, ReasoningService
from ecos.runtime import (
    CognitivePipeline,
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
    RuntimeEngine,
)
from ecos.runtime.adapters import (
    ContextExecutor,
    DebateExecutor,
    DecisionExecutor,
    ExecutionExecutor,
    GovernanceExecutor,
    LearningExecutor,
    NoopExecutor,
    ReasoningExecutor,
    SimulationExecutor,
    SpecialistsExecutor,
)
from ecos.session import PostgresSessionRepository, SessionRepository, SessionService
from ecos.simulation import AIWarEngine, SimulationService
from ecos.specialists import (
    Capability,
    Specialist,
    SpecialistRegistry,
    SpecialistService,
    SpecialistType,
)


@dataclass
class Container:
    """Application dependency container for services and fake providers."""

    settings: Settings = field(default_factory=Settings)

    def __post_init__(self) -> None:
        """Register fake providers, repositories, services and runtime engine."""
        organization = Organization(name="ECOS Container Organization")
        objective = Objective(
            organization_id=organization.id,
            title="Container runtime objective",
        )
        self.memory_repository: MemoryRepository
        if self.settings.memory_repository == "postgres":
            self.memory_repository = PostgresMemoryRepository(
                self.settings.database_url
            )
        else:
            self.memory_repository = FakeMemoryRepository()
        self.event_bus = FakeEventBus()
        self.session_repository: SessionRepository
        if self.settings.session_repository == "postgres":
            self.session_repository = PostgresSessionRepository(
                self.settings.database_url
            )
        else:
            self.session_repository = FakeSessionRepository()
        self.planner_provider = FakePlannerProvider()
        self.specialist_provider = FakeSpecialistProvider()
        self.decision_provider = FakeDecisionProvider()
        self.orchestrator_provider = FakeOrchestratorProvider()
        self.ai_provider: AIProvider
        ai_provider_type: ProviderType
        if self.settings.ai_provider == "openai":
            if not self.settings.openai_api_key:
                raise ConfigurationError(
                    "ECOS_OPENAI_API_KEY is required when ECOS_AI_PROVIDER=openai."
                )
            self.ai_provider = OpenAIProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_model,
                embedding_model=self.settings.openai_embedding_model,
                timeout_seconds=self.settings.openai_timeout_seconds,
                max_retries=self.settings.openai_max_retries,
            )
            ai_provider_type = ProviderType.OPENAI
        else:
            self.ai_provider = FakeAIProvider()
            ai_provider_type = ProviderType.CUSTOM
        self.ai_provider_type = ai_provider_type

        self.memory_service = MemoryService(self.memory_repository)
        self.event_service = EventService(self.event_bus)
        if self.settings.memory_repository == "postgres":
            self.context_provider = ContextEngine(
                self.memory_repository,
                event_service=self.event_service,
            )
        else:
            self.context_provider = FakeContextProvider(organization.id, objective)
        self.learning_service = LearningService(self.memory_service, self.event_service)
        self.session_service = SessionService(self.session_repository)
        self.context_service = ContextService(self.context_provider)
        self.specialist_registry = SpecialistRegistry()
        for specialist in self.specialist_provider.load():
            self.specialist_registry.register(specialist)
        registered_types = {
            specialist.type for specialist in self.specialist_registry.list()
        }
        for specialist_type in SpecialistType:
            if specialist_type in registered_types:
                continue
            self.specialist_registry.register(
                Specialist(
                    name=f"{specialist_type.value.title()} Specialist",
                    type=specialist_type,
                    description=f"{specialist_type.value} specialist.",
                    capabilities=[
                        Capability(
                            name=f"{specialist_type.value} analysis",
                            description="Deterministic specialist capability.",
                        )
                    ],
                )
            )
        self.cognitive_planner = CognitivePlanner(
            specialist_registry=self.specialist_registry,
            event_service=self.event_service,
            clock=lambda: datetime.now(UTC),
        )
        self.planner_service = PlannerService(
            self.planner_provider,
            self.cognitive_planner,
        )
        self.specialist_service = SpecialistService(
            self.specialist_provider,
            self.specialist_registry,
        )
        self.decision_service = DecisionService(self.decision_provider)
        self.provider_registry = ProviderRegistry()
        self.ai_service = AIService(self.provider_registry)
        self.ai_service.register(ai_provider_type, self.ai_provider, default=True)
        registered_provider = self.provider_registry.get(ai_provider_type)
        if registered_provider is None:
            raise ConfigurationError("Configured AI provider was not registered.")
        if self.settings.ai_provider == "openai":
            self.reasoning_provider = AIReasoningEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
            self.debate_provider = AIDebateEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
            self.simulation_provider = AIWarEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
            self.decision_provider = AIDecisionSupportEngine(
                registered_provider,
                ai_provider_type,
                self.settings.openai_model,
            )
        else:
            self.reasoning_provider = FakeReasoningProvider()
            self.debate_provider = FakeDebateProvider()
            self.simulation_provider = FakeWarEngine()
        self.decision_service = DecisionService(self.decision_provider)
        self.reasoning_service = ReasoningService(self.reasoning_provider)
        self.debate_service = DebateService(self.debate_provider)
        self.simulation_service = SimulationService(self.simulation_provider)
        self.governance_config = GovernanceConfig()
        self.policy_provider = InMemoryPolicyProvider((demo_policy(organization.id),))
        self.approval_policy_provider = DefaultApprovalPolicyProvider(
            self.governance_config
        )
        self.identity_port = StaticIdentityPort()
        self.governance_engine = GovernanceEngine(
            policy_provider=self.policy_provider,
            approval_policy_provider=self.approval_policy_provider,
            event_service=self.event_service,
            identity_port=self.identity_port,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            config=self.governance_config,
        )
        self.connector_registry = ConnectorRegistry()
        self.connector_registry.register(default_in_memory_connector())
        self.idempotency_provider = InMemoryIdempotencyProvider()
        self.human_task_provider = InMemoryHumanTaskProvider()
        self.execution_engine = ExecutionEngine(
            connector_registry=self.connector_registry,
            idempotency_provider=self.idempotency_provider,
            human_task_provider=self.human_task_provider,
            event_service=self.event_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            sleeper=asyncio.sleep,
            concurrency_limit=1,
            default_timeout_seconds=30.0,
        )
        self.engine_executors = {
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
            "governance": GovernanceExecutor(self.governance_engine),
            "execution": ExecutionExecutor(self.execution_engine),
            "observation": NoopExecutor("observation"),
        }
        self.orchestrator = Orchestrator(
            executors=self.engine_executors,
            event_service=self.event_service,
            session_service=self.session_service,
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            sleeper=asyncio.sleep,
            config=OrchestrationConfig(mode=OrchestrationMode.SEQUENTIAL),
        )
        self.orchestrator_service = OrchestratorService(
            self.orchestrator_provider,
            self.orchestrator,
        )
        self.runtime_pipeline = CognitivePipeline(
            memory_repository=self.memory_repository,
            session_repository=self.session_repository,
            event_bus=self.event_bus,
            context_provider=self.context_provider,
            ai_provider=self.ai_provider,
            memory_service=self.memory_service,
            learning_service=self.learning_service,
            session_service=self.session_service,
            event_service=self.event_service,
            context_service=self.context_service,
            planner_service=self.planner_service,
            reasoning_service=self.reasoning_service,
            specialist_service=self.specialist_service,
            debate_service=self.debate_service,
            simulation_service=self.simulation_service,
            decision_service=self.decision_service,
            orchestrator_service=self.orchestrator_service,
            ai_service=self.ai_service,
        )
        self.runtime_engine = RuntimeEngine(self.runtime_pipeline)

    def health(self) -> dict[str, Any]:
        """Return container, provider and runtime health information."""
        provider_health = self.ai_service.health(self.ai_provider_type)
        return {
            "container": "ok",
            "providers": {
                self.ai_provider_type.value: provider_health.status
                is ProviderStatus.AVAILABLE,
            },
            "runtime": isinstance(self.runtime_engine, RuntimeEngine),
        }

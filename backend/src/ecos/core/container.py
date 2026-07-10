"""Dependency injection container for ECOS services and fake providers."""

from dataclasses import dataclass, field
from typing import Any

from ecos.context import ContextService
from ecos.core.settings import Settings
from ecos.debate import DebateService
from ecos.decision import DecisionService
from ecos.domain import Objective, Organization
from ecos.events import EventService
from ecos.memory import MemoryService
from ecos.orchestrator import OrchestratorService
from ecos.planner import PlannerService
from ecos.providers import AIService, ProviderRegistry, ProviderStatus, ProviderType
from ecos.reasoning import ReasoningService
from ecos.runtime import (
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
    CognitivePipeline,
    RuntimeEngine,
)
from ecos.session import SessionService
from ecos.specialists import SpecialistRegistry, SpecialistService


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
        self.memory_repository = FakeMemoryRepository()
        self.event_bus = FakeEventBus()
        self.session_repository = FakeSessionRepository()
        self.context_provider = FakeContextProvider(organization.id, objective)
        self.planner_provider = FakePlannerProvider()
        self.reasoning_provider = FakeReasoningProvider()
        self.specialist_provider = FakeSpecialistProvider()
        self.debate_provider = FakeDebateProvider()
        self.decision_provider = FakeDecisionProvider()
        self.orchestrator_provider = FakeOrchestratorProvider()
        self.ai_provider = FakeAIProvider()

        self.memory_service = MemoryService(self.memory_repository)
        self.event_service = EventService(self.event_bus)
        self.session_service = SessionService(self.session_repository)
        self.context_service = ContextService(self.context_provider)
        self.planner_service = PlannerService(self.planner_provider)
        self.reasoning_service = ReasoningService(self.reasoning_provider)
        self.specialist_service = SpecialistService(
            self.specialist_provider,
            SpecialistRegistry(),
        )
        self.debate_service = DebateService(self.debate_provider)
        self.decision_service = DecisionService(self.decision_provider)
        self.orchestrator_service = OrchestratorService(self.orchestrator_provider)
        self.ai_service = AIService(ProviderRegistry())
        self.ai_service.register(ProviderType.CUSTOM, self.ai_provider, default=True)
        self.runtime_pipeline = CognitivePipeline(
            memory_repository=self.memory_repository,
            session_repository=self.session_repository,
            event_bus=self.event_bus,
            context_provider=self.context_provider,
            ai_provider=self.ai_provider,
            memory_service=self.memory_service,
            session_service=self.session_service,
            event_service=self.event_service,
            context_service=self.context_service,
            planner_service=self.planner_service,
            reasoning_service=self.reasoning_service,
            specialist_service=self.specialist_service,
            debate_service=self.debate_service,
            decision_service=self.decision_service,
            orchestrator_service=self.orchestrator_service,
            ai_service=self.ai_service,
        )
        self.runtime_engine = RuntimeEngine(self.runtime_pipeline)

    def health(self) -> dict[str, Any]:
        """Return container, provider and runtime health information."""
        provider_health = self.ai_service.health(ProviderType.CUSTOM)
        return {
            "container": "ok",
            "providers": {
                ProviderType.CUSTOM.value: provider_health.status
                is ProviderStatus.AVAILABLE,
            },
            "runtime": isinstance(self.runtime_engine, RuntimeEngine),
        }

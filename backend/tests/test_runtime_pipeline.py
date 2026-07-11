"""Tests for the first executable ECOS runtime cognitive pipeline."""

from uuid import UUID

import pytest

from ecos.context import ContextProvider
from ecos.debate import Debate, DebateProvider, DebateResult, DebateService
from ecos.decision import DecisionProvider
from ecos.events import EventBus, EventType
from ecos.memory import MemoryRepository, MemoryType
from ecos.orchestrator import OrchestratorProvider
from ecos.planner import PlannerProvider
from ecos.providers import AIProvider, ProviderStatus, ProviderType
from ecos.reasoning import ReasoningProvider
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
    RuntimeEngine,
)
from ecos.session import SessionLifecycleStatus, SessionRepository, TransitionType
from ecos.specialists import SpecialistProvider


class CapturingDebateProvider(FakeDebateProvider):
    """Capture the immutable debate input received from the runtime."""

    received: Debate | None = None

    def finalize(self, debate: Debate) -> DebateResult:
        self.received = debate
        return super().finalize(debate)


class FailingDebateProvider(FakeDebateProvider):
    """Fail finalization to verify event chronology."""

    def finalize(self, debate: Debate) -> DebateResult:
        del debate
        raise RuntimeError("debate failed")


def test_fake_runtime_implementations_satisfy_architecture_interfaces() -> None:
    """Runtime fakes implement existing provider, repository and bus interfaces."""
    assert issubclass(FakeMemoryRepository, MemoryRepository)
    assert issubclass(FakeContextProvider, ContextProvider)
    assert issubclass(FakePlannerProvider, PlannerProvider)
    assert issubclass(FakeReasoningProvider, ReasoningProvider)
    assert issubclass(FakeSpecialistProvider, SpecialistProvider)
    assert issubclass(FakeDebateProvider, DebateProvider)
    assert issubclass(FakeDecisionProvider, DecisionProvider)
    assert issubclass(FakeOrchestratorProvider, OrchestratorProvider)
    assert issubclass(FakeSessionRepository, SessionRepository)
    assert issubclass(FakeEventBus, EventBus)
    assert issubclass(FakeAIProvider, AIProvider)


def test_runtime_engine_with_fakes_returns_completed_recommendation() -> None:
    """RuntimeEngine.with_fakes runs the complete deterministic pipeline."""
    result = RuntimeEngine.with_fakes().run("Improve organizational decision quality")

    assert UUID(result.session_id)
    assert result.status == "completed"
    assert result.recommendation == (
        "Proceed using ECOS context, reasoning, debate and governance."
    )
    assert result.confidence == 0.91


def test_cognitive_pipeline_with_fakes_executes_full_flow() -> None:
    """CognitivePipeline.with_fakes records session, memory, events and snapshot."""
    pipeline = CognitivePipeline.with_fakes()
    result = pipeline.run("Coordinate a governed market expansion decision")
    session_id = UUID(result.session_id)

    managed_session = pipeline.session_service.get_session(session_id)
    memories = pipeline.memory_service.list(memory_type=MemoryType.EPISODIC)
    event_types = [
        envelope.event.event_type for envelope in pipeline.event_bus.envelopes
    ]
    transitions = pipeline.session_service.get_transitions(session_id)

    assert managed_session is not None
    assert managed_session.state.lifecycle_status is SessionLifecycleStatus.COMPLETED
    assert managed_session.state.progress == 1.0
    assert len(memories) == 1
    assert memories[0].type is MemoryType.EPISODIC
    assert memories[0].confidence == 0.91
    assert event_types == [
        EventType.SESSION_CREATED,
        EventType.SESSION_UPDATED,
        EventType.EXECUTION_STARTED,
        EventType.EXECUTION_COMPLETED,
        EventType.SESSION_UPDATED,
        EventType.CONTEXT_CREATED,
        EventType.SESSION_UPDATED,
        EventType.REASONING_STARTED,
        EventType.REASONING_COMPLETED,
        EventType.SPECIALIST_CONTRIBUTED,
        EventType.SESSION_UPDATED,
        EventType.DEBATE_STARTED,
        EventType.DEBATE_COMPLETED,
        EventType.SESSION_UPDATED,
        EventType.RECOMMENDATION_CREATED,
        EventType.LEARNING_STARTED,
        EventType.LEARNING_VALIDATED,
        EventType.MEMORY_UPDATED,
        EventType.LEARNING_COMPLETED,
        EventType.SESSION_UPDATED,
        EventType.SESSION_COMPLETED,
    ]
    assert [transition.transition_type for transition in transitions] == [
        TransitionType.INITIALIZE,
        TransitionType.START_PLANNING,
        TransitionType.COMPLETE,
    ]
    assert len(pipeline.session_repository.snapshots) == 1
    assert pipeline.session_repository.snapshots[0].session_id == session_id


def test_runtime_engine_rejects_blank_objective() -> None:
    """RuntimeEngine rejects blank objectives before creating a session."""
    with pytest.raises(ValueError, match="objective cannot be blank"):
        RuntimeEngine.with_fakes().run("   ")


def test_pipeline_factory_does_not_duplicate_repositories_or_event_bus() -> None:
    """Pipeline services reuse the same repositories and event bus references."""
    pipeline = CognitivePipeline.with_fakes()

    assert pipeline.memory_service._repository is pipeline.memory_repository
    assert pipeline.learning_service._memory_service is pipeline.memory_service
    assert pipeline.session_service._repository is pipeline.session_repository
    assert pipeline.event_service._event_bus is pipeline.event_bus
    assert pipeline.context_service._provider is pipeline.context_provider


def test_fake_context_provider_fails_without_configuration() -> None:
    """FakeContextProvider raises a clear error when build is called too early."""
    provider = FakeContextProvider()

    with pytest.raises(RuntimeError, match="fake context provider is not configured"):
        provider.build()


def test_fake_ai_provider_is_registered_as_default_provider() -> None:
    """CognitivePipeline.with_fakes registers FakeAIProvider as the default."""
    pipeline = CognitivePipeline.with_fakes()
    provider = pipeline.ai_service.default_provider()
    health = pipeline.ai_service.health(ProviderType.CUSTOM)

    assert provider is pipeline.ai_provider
    assert isinstance(provider, FakeAIProvider)
    assert health.provider is ProviderType.CUSTOM
    assert health.status is ProviderStatus.AVAILABLE


def test_runtime_delegates_permanent_memory_write_to_learning_engine() -> None:
    """Runtime emits a learning boundary before the repository receives memory."""
    pipeline = CognitivePipeline.with_fakes()

    pipeline.run("Learn only through the validated boundary")

    event_sources = [
        envelope.event.source
        for envelope in pipeline.event_bus.envelopes
        if envelope.event.event_type is EventType.MEMORY_UPDATED
    ]
    assert event_sources == ["learning"]


def test_runtime_delivers_all_independent_contributions_to_debate() -> None:
    pipeline = CognitivePipeline.with_fakes()
    provider = CapturingDebateProvider()
    pipeline.debate_service = DebateService(provider)

    pipeline.run("Preserve specialist input")

    assert provider.received is not None
    assert len(provider.received.contributions) == len(provider.received.specialists)
    assert {item.specialist_id for item in provider.received.contributions} == {
        item.id for item in provider.received.specialists
    }
    assert provider.received.reasoning_result is not None


def test_runtime_emits_debate_started_but_not_completed_on_failure() -> None:
    pipeline = CognitivePipeline.with_fakes()
    pipeline.debate_service = DebateService(FailingDebateProvider())

    with pytest.raises(RuntimeError, match="debate failed"):
        pipeline.run("Verify debate failure events")

    event_types = [item.event.event_type for item in pipeline.event_bus.envelopes]
    assert EventType.DEBATE_STARTED in event_types
    assert EventType.DEBATE_COMPLETED not in event_types

"""Tests for the first executable ECOS runtime cognitive pipeline."""

from uuid import UUID

from fastapi.testclient import TestClient

from ecos.context import ContextProvider
from ecos.debate import DebateProvider
from ecos.decision import DecisionProvider
from ecos.events import EventBus, EventType
from ecos.main import app
from ecos.memory import MemoryRepository, MemoryType
from ecos.orchestrator import OrchestratorProvider
from ecos.planner import PlannerProvider
from ecos.providers import AIProvider
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
from ecos.session import SessionLifecycleStatus, SessionRepository
from ecos.specialists import SpecialistProvider


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


def test_runtime_engine_run_returns_completed_recommendation() -> None:
    """RuntimeEngine runs the full fake cognitive flow without external calls."""
    result = RuntimeEngine().run("Improve organizational decision quality")

    assert UUID(result.session_id)
    assert result.status == "completed"
    assert result.recommendation == (
        "Proceed using ECOS context, reasoning, debate and governance."
    )
    assert result.confidence == 0.91


def test_cognitive_pipeline_records_memory_events_and_session_completion() -> None:
    """CognitivePipeline records memory, events and final session state."""
    pipeline = CognitivePipeline()
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
    assert memories[0].confidence == 0.91
    assert EventType.SESSION_CREATED in event_types
    assert EventType.CONTEXT_CREATED in event_types
    assert EventType.REASONING_COMPLETED in event_types
    assert EventType.SPECIALIST_CONTRIBUTED in event_types
    assert EventType.DEBATE_COMPLETED in event_types
    assert EventType.RECOMMENDATION_CREATED in event_types
    assert EventType.MEMORY_UPDATED in event_types
    assert EventType.EXECUTION_STARTED in event_types
    assert EventType.EXECUTION_COMPLETED in event_types
    assert EventType.SESSION_COMPLETED in event_types
    assert len(transitions) == 3


def test_runtime_engine_rejects_blank_objective() -> None:
    """RuntimeEngine rejects blank objectives before creating a session."""
    try:
        RuntimeEngine().run("   ")
    except ValueError as exc:
        assert str(exc) == "objective cannot be blank"
    else:
        raise AssertionError("blank objective did not raise ValueError")


def test_runtime_demo_endpoint_returns_expected_contract() -> None:
    """POST /runtime/demo returns the expected public response contract."""
    client = TestClient(app)

    response = client.post(
        "/runtime/demo",
        json={"objective": "Improve onboarding decisions"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert UUID(payload["session_id"])
    assert payload == {
        "session_id": payload["session_id"],
        "status": "completed",
        "recommendation": (
            "Proceed using ECOS context, reasoning, debate and governance."
        ),
        "confidence": 0.91,
    }

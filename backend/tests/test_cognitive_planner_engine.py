"""Tests for the deterministic Sprint 16G Cognitive Planner."""

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.core import Container, Settings
from ecos.core.exceptions import PlannerValidationError
from ecos.domain import Objective
from ecos.events import EventService, EventType
from ecos.planner import (
    CognitivePlanner,
    ObjectiveClassification,
    PlannerInput,
    PlanningStrategy,
    RiskLevel,
)
from ecos.runtime import FakeEventBus
from ecos.specialists import Capability, Specialist, SpecialistRegistry, SpecialistType

SESSION_ID = UUID("00000000-0000-4000-8000-000000000111")
ORG_ID = UUID("00000000-0000-4000-8000-000000000222")


def fixed_clock() -> datetime:
    return datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


class Ids:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> UUID:
        self.index += 1
        return UUID(f"00000000-0000-4000-8000-{self.index:012d}")


def registry(*types: SpecialistType) -> SpecialistRegistry:
    specialist_registry = SpecialistRegistry()
    for specialist_type in types:
        specialist_registry.register(
            Specialist(
                name=f"{specialist_type.value.title()} Specialist",
                type=specialist_type,
                description=f"{specialist_type.value} perspective.",
                capabilities=[
                    Capability(
                        name=f"{specialist_type.value} analysis",
                        description="Deterministic specialist capability.",
                    )
                ],
            )
        )
    return specialist_registry


def objective(title: str = "Analyze market expansion") -> Objective:
    return Objective(
        organization_id=ORG_ID,
        title=title,
        description="Deterministic objective details.",
        priority=3,
    )


def planner(
    specialist_registry: SpecialistRegistry | None = None,
    event_bus: FakeEventBus | None = None,
) -> CognitivePlanner:
    return CognitivePlanner(
        specialist_registry=specialist_registry
        or registry(
            SpecialistType.STRATEGY,
            SpecialistType.RISK,
            SpecialistType.FINANCE,
            SpecialistType.LEGAL,
            SpecialistType.TECHNOLOGY,
            SpecialistType.OPERATIONS,
            SpecialistType.HR,
        ),
        event_service=EventService(event_bus) if event_bus is not None else None,
        clock=fixed_clock,
        id_generator=Ids(),
    )


def make_input(**overrides: object) -> PlannerInput:
    base = {
        "session_id": SESSION_ID,
        "organization_id": ORG_ID,
        "objective": objective(),
        "priority": 3,
        "domains": ("strategy",),
        "context_available": True,
        "metadata": {"safe": True},
    }
    base.update(overrides)
    return PlannerInput(**base)


def plan_for(**overrides: object):
    return planner().create_plan(make_input(**overrides))


@pytest.mark.parametrize(
    ("title", "classification"),
    [
        ("What is the current status?", ObjectiveClassification.QUESTION),
        ("Analyze operational performance", ObjectiveClassification.ANALYSIS),
        ("Recommend a market option", ObjectiveClassification.RECOMMENDATION),
        ("Decide between strategic options", ObjectiveClassification.DECISION_SUPPORT),
        ("Simulate market downside", ObjectiveClassification.SIMULATION),
        ("Plan the rollout", ObjectiveClassification.PLANNING),
        ("Execute the approved rollout", ObjectiveClassification.EXECUTION),
        ("Monitor service health", ObjectiveClassification.MONITORING),
        ("Optimize onboarding cost", ObjectiveClassification.OPTIMIZATION),
    ],
)
def test_objective_classification_is_explicit_or_deterministic(
    title: str,
    classification: ObjectiveClassification,
) -> None:
    explicit = plan_for(declared_category=classification)
    inferred = plan_for(objective=objective(title))

    assert explicit.objective_classification is classification
    assert "CLASS_DECLARED_CATEGORY" in explicit.reason_codes
    assert inferred.objective_classification is classification


def test_constructs_immutable_plan_without_mutating_input() -> None:
    planner_input = make_input(
        constraints=("budget",),
        policies=("approval",),
        domains=("finance", "strategy"),
    )
    original = planner_input.model_dump()

    plan = planner().create_plan(planner_input)

    assert plan.plan_id != plan.id
    assert plan.organization_id == ORG_ID
    assert plan.created_at == fixed_clock()
    assert planner_input.model_dump() == original
    with pytest.raises(ValidationError):
        plan.reason_codes += ("MUTATE",)


@pytest.mark.parametrize(
    ("overrides", "level"),
    [
        ({}, 1),
        ({"constraints": ("c1", "c2", "c3"), "priority": 4}, 2),
        (
            {
                "domains": ("finance", "strategy", "technology"),
                "stakeholders_count": 6,
                "policies": ("p1",),
                "impact": "high",
                "declared_risk": RiskLevel.HIGH,
                "priority": 4,
                "context_gap_count": 3,
                "constraints": ("c1", "c2", "c3"),
            },
            3,
        ),
        ({"declared_risk": RiskLevel.CRITICAL}, 4),
        (
            {
                "declared_risk": RiskLevel.CRITICAL,
                "domains": ("finance", "strategy", "technology", "legal", "hr"),
                "constraints": ("c1", "c2", "c3", "c4", "c5"),
                "policies": ("p1", "p2", "p3", "p4", "p5"),
                "priority": 5,
                "urgency": "critical",
                "stakeholders_count": 10,
                "critical_context_gap_count": 5,
                "execution_requested": True,
                "temporal_horizon": "strategic",
                "impact": "critical",
                "reversible": False,
            },
            5,
        ),
    ],
)
def test_complexity_levels_and_scores(overrides: dict[str, object], level: int) -> None:
    plan = plan_for(**overrides)

    assert plan.complexity_level == level
    assert 0 <= plan.complexity_score <= 1
    assert plan.cognitive_depth == level


@pytest.mark.parametrize(
    ("overrides", "strategy"),
    [
        ({}, PlanningStrategy.FAST_RESPONSE),
        ({"constraints": ("c1", "c2", "c3"), "priority": 4}, PlanningStrategy.BALANCED),
        (
            {
                "domains": ("finance", "strategy", "technology"),
                "stakeholders_count": 6,
                "policies": ("p1",),
                "impact": "high",
                "declared_risk": RiskLevel.HIGH,
                "priority": 4,
                "context_gap_count": 3,
                "constraints": ("c1", "c2", "c3"),
            },
            PlanningStrategy.DEEP,
        ),
        ({"declared_risk": RiskLevel.CRITICAL}, PlanningStrategy.EXECUTIVE_ADVISORY),
        (
            {
                "declared_risk": RiskLevel.HIGH,
                "priority": 5,
                "impact": "high",
            },
            PlanningStrategy.CRISIS_MODE,
        ),
        ({"recurring": True}, PlanningStrategy.CONTINUOUS_MONITORING),
    ],
)
def test_strategy_selection(
    overrides: dict[str, object], strategy: PlanningStrategy
) -> None:
    plan = plan_for(**overrides)

    assert plan.strategy.strategy is strategy
    assert plan.strategy.reason_codes


def test_engine_selection_pipeline_dependencies_and_execution_block() -> None:
    plan = plan_for(
        objective=objective("Execute a strategic technology rollout"),
        execution_requested=True,
        declared_risk=RiskLevel.HIGH,
        domains=("technology", "security", "strategy"),
        policies=("approval",),
        temporal_horizon="quarter",
        impact="strategic",
    )

    engines = [selection.engine for selection in plan.selected_engines]
    assert engines == [
        "context",
        "reasoning",
        "specialists",
        "debate",
        "simulation",
        "decision_support",
        "governance",
        "execution",
        "observation",
        "learning",
    ]
    assert len(engines) == len(set(engines))
    assert [stage.order for stage in plan.stages] == list(
        range(1, len(plan.stages) + 1)
    )
    for stage in plan.stages:
        for dependency in stage.dependencies:
            dependency_stage = next(
                item for item in plan.stages if item.stage_id == dependency
            )
            assert dependency_stage.order < stage.order
    execution = next(stage for stage in plan.stages if stage.engine == "execution")
    assert execution.conditional is True
    assert execution.status.value == "blocked"
    assert plan.governance_requirements.execution_blocked_until_approval is True
    assert plan.approval_requirements.required is True
    assert plan.approval_requirements.granted is False


def test_specialist_selection_uses_registry_and_rejects_missing_specialist() -> None:
    plan = plan_for(
        domains=("finance", "strategy"),
        declared_risk=RiskLevel.HIGH,
        impact="high",
    )

    selected = [selection.specialist_type for selection in plan.selected_specialists]
    assert SpecialistType.FINANCE in selected
    assert SpecialistType.RISK in selected
    assert len(selected) == len(set(selected))
    assert all(
        selection.specialist_id is not None for selection in plan.selected_specialists
    )

    missing_registry_planner = planner(
        specialist_registry=registry(SpecialistType.STRATEGY)
    )
    with pytest.raises(PlannerValidationError, match="selected specialist"):
        missing_registry_planner.create_plan(
            make_input(domains=("finance",), declared_risk=RiskLevel.HIGH)
        )


def test_estimates_and_confidence_are_deterministic_and_relative() -> None:
    simple = plan_for()
    complex_plan = plan_for(
        domains=("finance", "strategy", "technology"),
        declared_risk=RiskLevel.HIGH,
        policies=("p1", "p2"),
        impact="high",
    )
    repeated = plan_for(
        domains=("finance", "strategy", "technology"),
        declared_risk=RiskLevel.HIGH,
        policies=("p1", "p2"),
        impact="high",
    )

    assert simple.estimated_duration_seconds < complex_plan.estimated_duration_seconds
    assert simple.estimated_cost_units < complex_plan.estimated_cost_units
    assert 0 <= complex_plan.confidence_target <= 1
    assert (
        complex_plan.estimated_duration_seconds == repeated.estimated_duration_seconds
    )
    assert complex_plan.estimated_cost_units == repeated.estimated_cost_units
    assert complex_plan.metadata["cost_units"] == "relative"


def test_events_are_safe_ordered_and_no_completion_on_failure() -> None:
    event_bus = FakeEventBus()
    real_planner = planner(event_bus=event_bus)

    real_planner.create_plan(
        make_input(
            domains=("finance", "strategy"),
            declared_risk=RiskLevel.HIGH,
            impact="high",
        )
    )
    event_types = [envelope.event.event_type for envelope in event_bus.envelopes]
    assert event_types == [
        EventType.PLANNING_STARTED,
        EventType.OBJECTIVE_CLASSIFIED,
        EventType.COMPLEXITY_CALCULATED,
        EventType.PIPELINE_GENERATED,
        EventType.SPECIALISTS_SELECTED,
        EventType.PLANNING_COMPLETED,
    ]
    completed = event_bus.envelopes[-1].event.payload
    assert "objective" not in completed
    assert completed["engine_count"] > 0

    failing_bus = FakeEventBus()
    failing_planner = planner(
        specialist_registry=registry(SpecialistType.STRATEGY),
        event_bus=failing_bus,
    )
    with pytest.raises(PlannerValidationError):
        failing_planner.create_plan(
            make_input(domains=("finance",), declared_risk=RiskLevel.HIGH)
        )
    assert EventType.PLANNING_COMPLETED not in [
        envelope.event.event_type for envelope in failing_bus.envelopes
    ]


def test_container_uses_real_planner_and_runtime_result_is_preserved() -> None:
    container = Container(settings=Settings())

    assert isinstance(container.cognitive_planner, CognitivePlanner)
    result = container.runtime_engine.run(
        "Coordinate a governed market expansion decision"
    )
    assert result.status == "completed"
    assert result.recommendation == (
        "Proceed using ECOS context, reasoning, debate and governance."
    )
    assert result.confidence == 0.91


def test_planner_module_does_not_import_openai_or_ai_provider() -> None:
    planner_dir = Path(__file__).parents[1] / "src" / "ecos" / "planner"

    for path in planner_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        imported_modules = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        assert "openai" not in imports
        assert not any(name.startswith("openai.") for name in imports)
        assert "ecos.providers" not in imported_modules
        assert "AIProvider" not in path.read_text()

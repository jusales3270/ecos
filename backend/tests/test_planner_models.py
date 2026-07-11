"""Unit tests for ECOS Cognitive Planner models and abstractions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.domain import Objective, Organization
from ecos.planner import (
    CognitivePlan,
    ComplexityLevel,
    EngineSelection,
    ExecutionStrategy,
    Pipeline,
    PipelineStep,
    PlannerProvider,
    PlannerService,
    PlanningStrategy,
    SpecialistSelection,
)
from ecos.specialists import SpecialistType

SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")


def make_objective() -> Objective:
    """Create a valid objective for planner tests."""
    organization = Organization(name="ACME")
    return Objective(
        organization_id=organization.id,
        title="Improve decision quality",
    )


def make_execution_strategy() -> ExecutionStrategy:
    """Create a valid execution strategy for planner tests."""
    return ExecutionStrategy(
        strategy=PlanningStrategy.BALANCED,
        rationale="Balance speed and confidence.",
        constraints=["Use only architecture-level components"],
    )


def make_engine_selection() -> EngineSelection:
    """Create a valid engine selection for planner tests."""
    return EngineSelection(
        engine="context",
        reason="Context is required before reasoning.",
        required=True,
    )


def make_specialist_selection() -> SpecialistSelection:
    """Create a valid specialist selection for planner tests."""
    return SpecialistSelection(
        specialist_type=SpecialistType.STRATEGY,
        reason="Strategy perspective is required.",
        required=True,
    )


def make_pipeline_step() -> PipelineStep:
    """Create a valid pipeline step for planner tests."""
    return PipelineStep(order=1, engine="context", optional=False)


def make_pipeline() -> Pipeline:
    """Create a valid pipeline for planner tests."""
    return Pipeline(steps=[make_pipeline_step()], metadata={"source": "unit-test"})


def make_cognitive_plan() -> CognitivePlan:
    """Create a valid cognitive plan for tests."""
    return CognitivePlan(
        session_id=SESSION_ID,
        objective=make_objective(),
        complexity=ComplexityLevel.LEVEL_3,
        strategy=make_execution_strategy(),
        selected_engines=[make_engine_selection()],
        selected_specialists=[make_specialist_selection()],
        pipeline=make_pipeline(),
        estimated_duration=120,
        estimated_cost=10.5,
        confidence_target=0.8,
    )


def test_planning_strategy_values() -> None:
    """PlanningStrategy exposes all supported planning strategies."""
    assert {strategy.value for strategy in PlanningStrategy} == {
        "FAST",
        "BALANCED",
        "DEEP_ANALYSIS",
        "EXECUTIVE",
        "CRISIS",
        "fast_response",
        "deep_analysis",
        "executive_advisory",
        "crisis_mode",
        "continuous_monitoring",
    }


def test_complexity_level_values() -> None:
    """ComplexityLevel exposes all supported complexity levels."""
    assert {complexity.value for complexity in ComplexityLevel} == {
        "LEVEL_1",
        "LEVEL_2",
        "LEVEL_3",
        "LEVEL_4",
        "LEVEL_5",
    }


def test_execution_strategy_validates_rationale_and_constraints() -> None:
    """ExecutionStrategy validates rationale and constraints."""
    strategy = make_execution_strategy()

    assert isinstance(strategy.id, UUID)
    assert strategy.strategy == PlanningStrategy.BALANCED
    assert strategy.constraints == ("Use only architecture-level components",)
    assert strategy.created_at.tzinfo is not None
    assert strategy.created_at.utcoffset() == UTC.utcoffset(strategy.created_at)

    with pytest.raises(ValidationError):
        ExecutionStrategy(strategy=PlanningStrategy.FAST, rationale="   ")

    with pytest.raises(ValidationError):
        ExecutionStrategy(
            strategy=PlanningStrategy.FAST,
            rationale="Fast path.",
            constraints=["   "],
        )


def test_engine_selection_validates_fields() -> None:
    """EngineSelection validates engine and reason fields."""
    selection = make_engine_selection()

    assert selection.engine == "context"
    assert selection.reason == "Context is required before reasoning."
    assert selection.required is True

    with pytest.raises(ValidationError):
        EngineSelection(engine="   ", reason="Reason")

    with pytest.raises(ValidationError):
        EngineSelection(engine="context", reason="   ")


def test_specialist_selection_validates_fields() -> None:
    """SpecialistSelection validates specialist type and reason fields."""
    selection = make_specialist_selection()

    assert selection.specialist_type == SpecialistType.STRATEGY
    assert selection.reason == "Strategy perspective is required."
    assert selection.required is True

    with pytest.raises(ValidationError):
        SpecialistSelection(specialist_type=SpecialistType.RISK, reason="   ")


def test_pipeline_step_contains_required_architecture_fields() -> None:
    """PipelineStep contains id, order, engine, depends_on, optional, and created_at."""
    step = make_pipeline_step()
    dependency_id = UUID("00000000-0000-4000-8000-000000000002")
    dependent_step = PipelineStep(
        order=2,
        engine="reasoning",
        depends_on=[dependency_id],
        optional=True,
    )

    assert isinstance(step.id, UUID)
    assert step.order == 1
    assert step.engine == "context"
    assert step.depends_on == ()
    assert step.optional is False
    assert step.created_at.tzinfo is not None
    assert step.created_at.utcoffset() == UTC.utcoffset(step.created_at)
    assert dependent_step.depends_on == (dependency_id,)
    assert dependent_step.optional is True

    with pytest.raises(ValidationError):
        PipelineStep(order=0, engine="context")

    with pytest.raises(ValidationError):
        PipelineStep(order=1, engine="   ")


def test_pipeline_validates_metadata_and_unique_order() -> None:
    """Pipeline validates metadata and unique step order values."""
    pipeline = make_pipeline()

    assert len(pipeline.steps) == 1
    assert pipeline.metadata == {"source": "unit-test"}

    with pytest.raises(ValidationError):
        Pipeline(metadata={"   ": "invalid"})

    with pytest.raises(ValidationError):
        Pipeline(
            steps=[
                PipelineStep(order=1, engine="context"),
                PipelineStep(order=1, engine="reasoning"),
            ]
        )


def test_cognitive_plan_contains_required_architecture_fields() -> None:
    """CognitivePlan contains all required architecture fields."""
    plan = make_cognitive_plan()

    assert isinstance(plan.id, UUID)
    assert plan.session_id == SESSION_ID
    assert isinstance(plan.objective, Objective)
    assert plan.complexity == ComplexityLevel.LEVEL_3
    assert plan.strategy.strategy == PlanningStrategy.BALANCED
    assert len(plan.selected_engines) == 1
    assert len(plan.selected_specialists) == 1
    assert len(plan.pipeline.steps) == 1
    assert plan.estimated_duration == 120
    assert plan.estimated_cost == 10.5
    assert plan.confidence_target == 0.8
    assert plan.created_at.tzinfo is not None
    assert plan.created_at.utcoffset() == UTC.utcoffset(plan.created_at)


def test_cognitive_plan_validates_estimates_and_confidence_target() -> None:
    """CognitivePlan validates duration, cost, and confidence target."""
    kwargs = {
        "session_id": SESSION_ID,
        "objective": make_objective(),
        "complexity": ComplexityLevel.LEVEL_3,
        "strategy": make_execution_strategy(),
        "pipeline": make_pipeline(),
    }

    with pytest.raises(ValidationError):
        CognitivePlan(**kwargs, estimated_duration=-1)

    with pytest.raises(ValidationError):
        CognitivePlan(**kwargs, estimated_cost=-0.1)

    with pytest.raises(ValidationError):
        CognitivePlan(**kwargs, confidence_target=1.1)


def test_planner_models_reject_invalid_created_at() -> None:
    """Planner models reject non-UTC and naive created_at values."""
    with pytest.raises(ValidationError):
        PipelineStep(order=1, engine="context", created_at=datetime.now())

    with pytest.raises(ValidationError):
        PipelineStep(
            order=1,
            engine="context",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


class NotImplementedPlannerProvider(PlannerProvider):
    """Concrete test adapter that delegates to interface methods."""

    def classify_objective(self, objective: Objective) -> PlanningStrategy:
        """Delegate to the interface method."""
        return super().classify_objective(objective)

    def estimate_complexity(self, objective: Objective) -> ComplexityLevel:
        """Delegate to the interface method."""
        return super().estimate_complexity(objective)

    def select_engines(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[EngineSelection]:
        """Delegate to the interface method."""
        return super().select_engines(objective, strategy, complexity)

    def select_specialists(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[SpecialistSelection]:
        """Delegate to the interface method."""
        return super().select_specialists(objective, strategy, complexity)

    def build_pipeline(
        self,
        engines: list[EngineSelection],
        specialists: list[SpecialistSelection],
    ) -> Pipeline:
        """Delegate to the interface method."""
        return super().build_pipeline(engines, specialists)


def test_planner_provider_interface_methods_raise_not_implemented() -> None:
    """PlannerProvider interface methods are intentionally unimplemented."""
    provider = NotImplementedPlannerProvider()
    objective = make_objective()
    strategy = make_execution_strategy()
    complexity = ComplexityLevel.LEVEL_3
    engines = [make_engine_selection()]
    specialists = [make_specialist_selection()]

    with pytest.raises(NotImplementedError):
        provider.classify_objective(objective)
    with pytest.raises(NotImplementedError):
        provider.estimate_complexity(objective)
    with pytest.raises(NotImplementedError):
        provider.select_engines(objective, strategy, complexity)
    with pytest.raises(NotImplementedError):
        provider.select_specialists(objective, strategy, complexity)
    with pytest.raises(NotImplementedError):
        provider.build_pipeline(engines, specialists)


class TestPlannerProvider(PlannerProvider):
    """Test double for verifying PlannerService delegation only."""

    def classify_objective(self, objective: Objective) -> PlanningStrategy:
        """Return a configured planning strategy."""
        del objective
        return PlanningStrategy.BALANCED

    def estimate_complexity(self, objective: Objective) -> ComplexityLevel:
        """Return a configured complexity level."""
        del objective
        return ComplexityLevel.LEVEL_3

    def select_engines(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[EngineSelection]:
        """Return configured engine selections."""
        del objective, strategy, complexity
        return [make_engine_selection()]

    def select_specialists(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[SpecialistSelection]:
        """Return configured specialist selections."""
        del objective, strategy, complexity
        return [make_specialist_selection()]

    def build_pipeline(
        self,
        engines: list[EngineSelection],
        specialists: list[SpecialistSelection],
    ) -> Pipeline:
        """Return a configured pipeline."""
        del engines, specialists
        return make_pipeline()


def test_planner_service_uses_provider_abstraction() -> None:
    """PlannerService delegates operations to the provider abstraction."""
    service = PlannerService(TestPlannerProvider())
    objective = make_objective()
    strategy = make_execution_strategy()
    complexity = ComplexityLevel.LEVEL_3
    engines = service.select_engines(objective, strategy, complexity)
    specialists = service.select_specialists(objective, strategy, complexity)

    assert service.classify_objective(objective) == PlanningStrategy.BALANCED
    assert service.estimate_complexity(objective) == ComplexityLevel.LEVEL_3
    assert len(engines) == 1
    assert len(specialists) == 1
    assert len(service.build_pipeline(engines, specialists).steps) == 1

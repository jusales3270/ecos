"""Service layer for the ECOS Cognitive Planner architecture."""

from ecos.domain import Objective
from ecos.planner.models import (
    ComplexityLevel,
    EngineSelection,
    ExecutionStrategy,
    Pipeline,
    PlanningStrategy,
    SpecialistSelection,
)
from ecos.planner.provider import PlannerProvider


class PlannerService:
    """Coordinates cognitive planning through a provider abstraction only."""

    def __init__(self, provider: PlannerProvider) -> None:
        """Initialize the service with a planner provider abstraction."""
        self._provider = provider

    def classify_objective(self, objective: Objective) -> PlanningStrategy:
        """Classify an objective through the provider abstraction."""
        return self._provider.classify_objective(objective)

    def estimate_complexity(self, objective: Objective) -> ComplexityLevel:
        """Estimate complexity through the provider abstraction."""
        return self._provider.estimate_complexity(objective)

    def select_engines(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[EngineSelection]:
        """Select engines through the provider abstraction."""
        return self._provider.select_engines(objective, strategy, complexity)

    def select_specialists(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[SpecialistSelection]:
        """Select specialists through the provider abstraction."""
        return self._provider.select_specialists(objective, strategy, complexity)

    def build_pipeline(
        self,
        engines: list[EngineSelection],
        specialists: list[SpecialistSelection],
    ) -> Pipeline:
        """Build a pipeline through the provider abstraction."""
        return self._provider.build_pipeline(engines, specialists)

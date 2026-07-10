"""Provider interface for the ECOS Cognitive Planner."""

from abc import ABC, abstractmethod

from ecos.domain import Objective
from ecos.planner.models import (
    ComplexityLevel,
    EngineSelection,
    ExecutionStrategy,
    Pipeline,
    PlanningStrategy,
    SpecialistSelection,
)


class PlannerProvider(ABC):
    """Abstract provider interface for cognitive planning operations."""

    @abstractmethod
    def classify_objective(self, objective: Objective) -> PlanningStrategy:
        """Classify an objective into a planning strategy."""
        raise NotImplementedError

    @abstractmethod
    def estimate_complexity(self, objective: Objective) -> ComplexityLevel:
        """Estimate objective complexity."""
        raise NotImplementedError

    @abstractmethod
    def select_engines(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[EngineSelection]:
        """Select engines for a planned cognitive execution."""
        raise NotImplementedError

    @abstractmethod
    def select_specialists(
        self,
        objective: Objective,
        strategy: ExecutionStrategy,
        complexity: ComplexityLevel,
    ) -> list[SpecialistSelection]:
        """Select specialists for a planned cognitive execution."""
        raise NotImplementedError

    @abstractmethod
    def build_pipeline(
        self,
        engines: list[EngineSelection],
        specialists: list[SpecialistSelection],
    ) -> Pipeline:
        """Build a cognitive execution pipeline."""
        raise NotImplementedError

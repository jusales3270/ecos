"""Simulation provider boundary."""

from abc import ABC, abstractmethod

from ecos.simulation.models import SimulationContext, SimulationReport


class SimulationProvider(ABC):
    @abstractmethod
    def simulate(self, context: SimulationContext) -> SimulationReport:
        """Explore possible futures without making a decision."""

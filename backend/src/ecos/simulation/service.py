"""Simulation service."""

from ecos.simulation.models import SimulationContext, SimulationReport
from ecos.simulation.provider import SimulationProvider


class SimulationService:
    def __init__(self, provider: SimulationProvider) -> None:
        self._provider = provider

    def simulate(self, context: SimulationContext) -> SimulationReport:
        return self._provider.simulate(context)

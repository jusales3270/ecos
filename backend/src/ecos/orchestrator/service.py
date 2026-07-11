"""Service layer for the ECOS Orchestrator architecture."""

from ecos.orchestrator.models import ExecutionPlan, ExecutionResult, ExecutionStep
from ecos.orchestrator.provider import OrchestratorProvider


class OrchestratorService:
    """Coordinates execution plans through a provider abstraction only."""

    def __init__(self, provider: OrchestratorProvider) -> None:
        """Initialize the service with an orchestrator provider abstraction."""
        self._provider = provider

    def start(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Start an execution plan through the provider abstraction."""
        return self._provider.start(plan)

    def execute_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
    ) -> ExecutionStep:
        """Execute a step through the provider abstraction."""
        return self._provider.execute_step(plan, step)

    def pause(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Pause an execution plan through the provider abstraction."""
        return self._provider.pause(plan)

    def resume(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Resume an execution plan through the provider abstraction."""
        return self._provider.resume(plan)

    def cancel(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Cancel an execution plan through the provider abstraction."""
        return self._provider.cancel(plan)

    def complete(self, plan: ExecutionPlan) -> ExecutionResult:
        """Complete an execution plan through the provider abstraction."""
        return self._provider.complete(plan)

"""Service layer for the ECOS Orchestrator architecture."""

from ecos.orchestrator.engine import Orchestrator
from ecos.orchestrator.models import (
    ExecutionPlan,
    ExecutionResult,
    ExecutionStep,
    OrchestrationInput,
    OrchestrationResult,
)
from ecos.orchestrator.provider import OrchestratorProvider


class OrchestratorService:
    """Coordinates execution plans through a provider abstraction only."""

    def __init__(
        self,
        provider: OrchestratorProvider,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        """Initialize the service with an orchestrator provider abstraction."""
        self._provider = provider
        self._orchestrator = orchestrator

    def execute(self, orchestration_input: OrchestrationInput) -> OrchestrationResult:
        """Execute a CognitivePlan through the real Orchestrator."""
        if self._orchestrator is None:
            msg = "real orchestrator is not configured"
            raise RuntimeError(msg)
        return self._orchestrator.execute(orchestration_input)

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

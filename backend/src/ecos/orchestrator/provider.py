"""Provider interface for the ECOS Orchestrator."""

from abc import ABC, abstractmethod

from ecos.orchestrator.models import ExecutionPlan, ExecutionResult, ExecutionStep


class OrchestratorProvider(ABC):
    """Abstract provider interface for orchestration operations."""

    @abstractmethod
    def start(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Start an execution plan."""
        raise NotImplementedError

    @abstractmethod
    def execute_step(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
    ) -> ExecutionStep:
        """Execute one step from an execution plan."""
        raise NotImplementedError

    @abstractmethod
    def pause(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Pause an execution plan."""
        raise NotImplementedError

    @abstractmethod
    def resume(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Resume an execution plan."""
        raise NotImplementedError

    @abstractmethod
    def cancel(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Cancel an execution plan."""
        raise NotImplementedError

    @abstractmethod
    def complete(self, plan: ExecutionPlan) -> ExecutionResult:
        """Complete an execution plan and return its result."""
        raise NotImplementedError

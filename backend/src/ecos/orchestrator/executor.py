"""Generic engine executor contract for the ECOS Orchestrator."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable

from ecos.orchestrator.models import EngineInvocationContext, EngineStageResult


class EngineExecutor(ABC):
    """Port used by the Orchestrator to invoke any cognitive engine."""

    @property
    @abstractmethod
    def engine_type(self) -> str:
        """Return the canonical engine type handled by this executor."""
        raise NotImplementedError

    @property
    @abstractmethod
    def available(self) -> bool:
        """Return whether the executor can currently run."""
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        context: EngineInvocationContext,
    ) -> EngineStageResult | Awaitable[EngineStageResult]:
        """Execute a stage and return its typed result."""
        raise NotImplementedError

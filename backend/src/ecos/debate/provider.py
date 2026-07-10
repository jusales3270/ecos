"""Provider interface for the ECOS Debate Engine."""

from abc import ABC, abstractmethod

from ecos.debate.models import Argument, Consensus, Debate, DebateResult


class DebateProvider(ABC):
    """Abstract provider interface for debate operations."""

    @abstractmethod
    def start(self, debate: Debate) -> Debate:
        """Start a debate."""
        raise NotImplementedError

    @abstractmethod
    def collect_arguments(self, debate: Debate) -> list[Argument]:
        """Collect arguments for a debate."""
        raise NotImplementedError

    @abstractmethod
    def evaluate_consensus(self, debate: Debate) -> Consensus:
        """Evaluate consensus for a debate."""
        raise NotImplementedError

    @abstractmethod
    def finalize(self, debate: Debate) -> DebateResult:
        """Finalize a debate and produce a result."""
        raise NotImplementedError

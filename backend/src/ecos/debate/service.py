"""Service layer for the ECOS Debate Engine architecture."""

from ecos.debate.models import Argument, Consensus, Debate, DebateResult
from ecos.debate.provider import DebateProvider


class DebateService:
    """Coordinates debate operations through a provider abstraction only."""

    def __init__(self, provider: DebateProvider) -> None:
        """Initialize the service with a debate provider abstraction."""
        self._provider = provider

    def start(self, debate: Debate) -> Debate:
        """Start a debate through the provider abstraction."""
        return self._provider.start(debate)

    def collect_arguments(self, debate: Debate) -> list[Argument]:
        """Collect arguments through the provider abstraction."""
        return self._provider.collect_arguments(debate)

    def evaluate_consensus(self, debate: Debate) -> Consensus:
        """Evaluate consensus through the provider abstraction."""
        return self._provider.evaluate_consensus(debate)

    def finalize(self, debate: Debate) -> DebateResult:
        """Finalize a debate through the provider abstraction."""
        return self._provider.finalize(debate)

"""Service layer for the ECOS Reasoning Engine architecture."""

from ecos.reasoning.models import (
    Alternative,
    Hypothesis,
    ReasoningContext,
    ReasoningResult,
)
from ecos.reasoning.provider import ReasoningProvider


class ReasoningService:
    """Coordinates reasoning operations through a provider abstraction only."""

    def __init__(self, provider: ReasoningProvider) -> None:
        """Initialize the service with a reasoning provider abstraction."""
        self._provider = provider

    def analyze(self, context: ReasoningContext) -> ReasoningResult:
        """Analyze a reasoning context through the provider abstraction."""
        return self._provider.analyze(context)

    def generate_hypotheses(self, context: ReasoningContext) -> list[Hypothesis]:
        """Generate hypotheses through the provider abstraction."""
        return self._provider.generate_hypotheses(context)

    def evaluate_alternatives(
        self,
        context: ReasoningContext,
        hypotheses: list[Hypothesis],
    ) -> list[Alternative]:
        """Evaluate alternatives through the provider abstraction."""
        return self._provider.evaluate_alternatives(context, hypotheses)

    def calculate_confidence(self, result: ReasoningResult) -> float:
        """Calculate confidence through the provider abstraction."""
        return self._provider.calculate_confidence(result)

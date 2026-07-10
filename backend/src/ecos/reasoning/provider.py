"""Provider interface for the ECOS Reasoning Engine."""

from abc import ABC, abstractmethod

from ecos.reasoning.models import (
    Alternative,
    Hypothesis,
    ReasoningContext,
    ReasoningResult,
)


class ReasoningProvider(ABC):
    """Abstract provider interface for reasoning operations."""

    @abstractmethod
    def analyze(self, context: ReasoningContext) -> ReasoningResult:
        """Analyze a reasoning context and produce a result."""
        raise NotImplementedError

    @abstractmethod
    def generate_hypotheses(self, context: ReasoningContext) -> list[Hypothesis]:
        """Generate hypotheses for a reasoning context."""
        raise NotImplementedError

    @abstractmethod
    def evaluate_alternatives(
        self,
        context: ReasoningContext,
        hypotheses: list[Hypothesis],
    ) -> list[Alternative]:
        """Evaluate alternatives for a reasoning context and hypotheses."""
        raise NotImplementedError

    @abstractmethod
    def calculate_confidence(self, result: ReasoningResult) -> float:
        """Calculate confidence for a reasoning result."""
        raise NotImplementedError

"""Provider interface for the ECOS Decision Support Engine."""

from abc import ABC, abstractmethod

from ecos.debate import DebateResult
from ecos.decision.models import DecisionPackage, ExecutiveBrief, Recommendation
from ecos.reasoning import ReasoningResult


class DecisionProvider(ABC):
    """Abstract provider interface for decision support operations."""

    @abstractmethod
    def build_recommendation(
        self,
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
    ) -> Recommendation:
        """Build a recommendation from reasoning and debate outputs."""
        raise NotImplementedError

    @abstractmethod
    def build_executive_brief(
        self,
        recommendation: Recommendation,
    ) -> ExecutiveBrief:
        """Build an executive brief from a recommendation."""
        raise NotImplementedError

    @abstractmethod
    def build_decision_package(
        self,
        recommendation: Recommendation,
        executive_brief: ExecutiveBrief,
    ) -> DecisionPackage:
        """Build a decision package from recommendation and brief."""
        raise NotImplementedError

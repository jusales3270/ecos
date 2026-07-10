"""Service layer for the ECOS Decision Support Engine architecture."""

from ecos.debate import DebateResult
from ecos.decision.models import DecisionPackage, ExecutiveBrief, Recommendation
from ecos.decision.provider import DecisionProvider
from ecos.reasoning import ReasoningResult


class DecisionService:
    """Coordinates decision support operations through a provider only."""

    def __init__(self, provider: DecisionProvider) -> None:
        """Initialize the service with a decision provider abstraction."""
        self._provider = provider

    def build_recommendation(
        self,
        reasoning_result: ReasoningResult,
        debate_result: DebateResult,
    ) -> Recommendation:
        """Build a recommendation through the provider abstraction."""
        return self._provider.build_recommendation(reasoning_result, debate_result)

    def build_executive_brief(
        self,
        recommendation: Recommendation,
    ) -> ExecutiveBrief:
        """Build an executive brief through the provider abstraction."""
        return self._provider.build_executive_brief(recommendation)

    def build_decision_package(
        self,
        recommendation: Recommendation,
        executive_brief: ExecutiveBrief,
    ) -> DecisionPackage:
        """Build a decision package through the provider abstraction."""
        return self._provider.build_decision_package(recommendation, executive_brief)

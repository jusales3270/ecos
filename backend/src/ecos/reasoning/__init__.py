"""Reasoning Engine architecture primitives for ECOS."""

from ecos.reasoning.ai_engine import AIReasoningEngine
from ecos.reasoning.models import (
    Alternative,
    Hypothesis,
    ReasoningContext,
    ReasoningEvidence,
    ReasoningResult,
    ReasoningType,
    Tradeoff,
)
from ecos.reasoning.provider import ReasoningProvider
from ecos.reasoning.service import ReasoningService

__all__ = [
    "AIReasoningEngine",
    "Alternative",
    "Hypothesis",
    "ReasoningContext",
    "ReasoningEvidence",
    "ReasoningProvider",
    "ReasoningResult",
    "ReasoningService",
    "ReasoningType",
    "Tradeoff",
]

"""Debate Engine architecture primitives for ECOS."""

from ecos.debate.ai_engine import AIDebateEngine
from ecos.debate.models import (
    Argument,
    Consensus,
    ConsensusLevel,
    CounterArgument,
    Debate,
    DebateResult,
    DebateStatus,
)
from ecos.debate.provider import DebateProvider
from ecos.debate.service import DebateService

__all__ = [
    "Argument",
    "AIDebateEngine",
    "Consensus",
    "ConsensusLevel",
    "CounterArgument",
    "Debate",
    "DebateProvider",
    "DebateResult",
    "DebateService",
    "DebateStatus",
]

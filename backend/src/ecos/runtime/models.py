"""Runtime models for the first executable ECOS cognitive pipeline."""

from pydantic import BaseModel, ConfigDict, Field

from ecos.context import ContextObject
from ecos.decision import Recommendation
from ecos.domain import CognitiveSession
from ecos.memory import MemoryObject
from ecos.planner import CognitivePlan
from ecos.reasoning import ReasoningResult
from ecos.session import ManagedSession
from ecos.simulation import SimulationReport


class ExecutionContext(BaseModel):
    """Runtime aggregate carrying artifacts produced by a cognitive execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    managed_session: ManagedSession = Field(description="Managed cognitive session.")
    cognitive_session: CognitiveSession = Field(description="Domain session.")
    plan: CognitivePlan | None = Field(default=None, description="Cognitive plan.")
    context: ContextObject | None = Field(default=None, description="Context object.")
    reasoning: ReasoningResult | None = Field(
        default=None,
        description="Reasoning output.",
    )
    simulation: SimulationReport | None = None
    recommendation: Recommendation | None = Field(
        default=None,
        description="Final recommendation.",
    )
    memory: MemoryObject | None = Field(default=None, description="Recorded memory.")


class RuntimeResult(BaseModel):
    """Public result returned by the runtime demo pipeline."""

    session_id: str = Field(description="Cognitive session identifier.")
    status: str = Field(description="Final execution status.")
    recommendation: str = Field(description="Generated deterministic recommendation.")
    confidence: float = Field(ge=0.0, le=1.0, description="Final confidence.")

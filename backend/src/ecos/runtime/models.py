"""Runtime models for the first executable ECOS cognitive pipeline."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ecos.context import ContextObject
from ecos.decision import Recommendation
from ecos.domain import CognitiveSession
from ecos.governance import ApprovalDecision
from ecos.memory import MemoryObject
from ecos.orchestrator import PipelineExecutionStatus
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


class StartExistingSessionCommand(BaseModel):
    """Explicit authenticated input for starting an existing cognitive session."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    session_id: UUID
    organization_id: UUID
    user_id: UUID
    correlation_id: UUID
    objective: str = Field(min_length=1, max_length=200)


class ResumeSessionCommand(StartExistingSessionCommand):
    """Explicit authenticated input and human decision for runtime resume."""

    approval_decision: ApprovalDecision


class AuthenticatedRuntimeResult(BaseModel):
    """Internal result from an authenticated start or resume operation."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    organization_id: UUID
    plan_id: UUID
    status: PipelineExecutionStatus
    checkpoint_version: int = Field(ge=1)

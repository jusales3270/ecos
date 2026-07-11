"""Pydantic models for the ECOS Cognitive Planner architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.domain import Objective
from ecos.specialists import SpecialistType

PlannerMetadataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ObjectiveClassification(StrEnum):
    """Canonical objective classifications used by the planner."""

    QUESTION = "question"
    ANALYSIS = "analysis"
    RECOMMENDATION = "recommendation"
    DECISION_SUPPORT = "decision_support"
    SIMULATION = "simulation"
    RESEARCH = "research"
    PLANNING = "planning"
    EXECUTION = "execution"
    MONITORING = "monitoring"
    OPTIMIZATION = "optimization"


class PlanningStrategy(StrEnum):
    """Supported planning strategies for cognitive execution."""

    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP_ANALYSIS = "DEEP_ANALYSIS"
    EXECUTIVE = "EXECUTIVE"
    CRISIS = "CRISIS"
    FAST_RESPONSE = "fast_response"
    DEEP = "deep_analysis"
    EXECUTIVE_ADVISORY = "executive_advisory"
    CRISIS_MODE = "crisis_mode"
    CONTINUOUS_MONITORING = "continuous_monitoring"


class ComplexityLevel(StrEnum):
    """Supported objective complexity levels."""

    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"
    LEVEL_5 = "LEVEL_5"


class RiskLevel(StrEnum):
    """Planner risk levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PlannerEngine(StrEnum):
    """Known cognitive engines that can appear in a plan."""

    CONTEXT = "context"
    REASONING = "reasoning"
    SPECIALISTS = "specialists"
    DEBATE = "debate"
    SIMULATION = "simulation"
    DECISION_SUPPORT = "decision_support"
    GOVERNANCE = "governance"
    EXECUTION = "execution"
    OBSERVATION = "observation"
    LEARNING = "learning"
    MEMORY = "memory"
    DECISION = "decision"


class StageStatus(StrEnum):
    """Initial and future stage statuses."""

    PENDING = "pending"
    BLOCKED = "blocked"


class PlannerModel(BaseModel):
    """Base planner model with identity and UTC creation timestamp."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=True,
    )

    id: UUID = Field(default_factory=uuid4, description="Unique model identifier.")
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for planner model creation.",
    )

    @model_validator(mode="after")
    def validate_created_at(self) -> Self:
        """Ensure created_at is timezone-aware UTC."""
        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() != UTC.utcoffset(self.created_at)
        ):
            msg = "created_at must be timezone-aware and in UTC"
            raise ValueError(msg)
        return self


class RetryPolicy(BaseModel):
    """Suggested retry policy metadata; not executed in this sprint."""

    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=1, ge=1)
    backoff_seconds: int = Field(default=0, ge=0)


class StageCondition(BaseModel):
    """Structured stage condition for a future orchestrator."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    type: str = Field(min_length=1, max_length=100)
    requirements: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("requirements", mode="before")
    @classmethod
    def tuple_requirements(cls, value: object) -> tuple[str, ...]:
        """Normalize condition requirements to immutable tuples."""
        return tuple(value or ())


class GovernanceRequirements(BaseModel):
    """Structured governance requirements for a plan."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    governance_required: bool = False
    approval_required: bool = False
    minimum_approval_level: str | None = None
    policy_checks: tuple[str, ...] = Field(default_factory=tuple)
    human_review_required: bool = False
    execution_blocked_until_approval: bool = False
    reasons: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("policy_checks", "reasons", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[str, ...]:
        """Normalize list-like values to immutable tuples."""
        return tuple(value or ())


class ApprovalRequirements(BaseModel):
    """Required approvals, without granting any approval."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    required: bool = False
    minimum_level: str | None = None
    roles: tuple[str, ...] = Field(default_factory=tuple)
    granted: bool = False
    reasons: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("roles", "reasons", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[str, ...]:
        """Normalize list-like values to immutable tuples."""
        return tuple(value or ())


class PlannerInput(BaseModel):
    """Immutable typed input consumed by the real Cognitive Planner."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    session_id: UUID
    organization_id: UUID
    objective: Objective
    user_id: UUID | None = None
    description: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    declared_category: ObjectiveClassification | None = None
    desired_outcome: str | None = None
    constraints: tuple[str, ...] = Field(default_factory=tuple)
    policies: tuple[str, ...] = Field(default_factory=tuple)
    resources_available: tuple[str, ...] = Field(default_factory=tuple)
    urgency: str | None = None
    declared_risk: RiskLevel | None = None
    domains: tuple[str, ...] = Field(default_factory=tuple)
    context_available: bool = True
    context_gap_count: int = Field(default=0, ge=0)
    critical_context_gap_count: int = Field(default=0, ge=0)
    previous_session_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    execution_requested: bool = False
    stakeholders_count: int = Field(default=1, ge=0)
    temporal_horizon: str | None = None
    impact: str | None = None
    reversible: bool = True
    recurring: bool = False
    metadata: dict[str, PlannerMetadataValue] = Field(default_factory=dict)
    correlation_id: UUID | None = None

    @field_validator(
        "constraints",
        "policies",
        "resources_available",
        "domains",
        mode="before",
    )
    @classmethod
    def tuple_strings(cls, value: object) -> tuple[str, ...]:
        """Normalize string lists to immutable tuples."""
        return tuple(item.strip() for item in (value or ()) if str(item).strip())

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, PlannerMetadataValue],
    ) -> dict[str, PlannerMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return dict(value)


class ExecutionStrategy(PlannerModel):
    """Execution strategy selected for a cognitive plan."""

    strategy: PlanningStrategy = Field(description="Selected planning strategy.")
    rationale: str = Field(min_length=1, max_length=3000)
    constraints: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("constraints", "reason_codes", mode="before")
    @classmethod
    def tuple_constraints(cls, value: object) -> tuple[str, ...]:
        """Normalize string lists and reject blanks."""
        normalized = tuple(item.strip() for item in (value or ()))
        if any(item == "" for item in normalized):
            msg = "constraints cannot contain blank values"
            raise ValueError(msg)
        return normalized


class EngineSelection(PlannerModel):
    """Engine selected for a cognitive plan."""

    engine: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    required: bool = True
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("reason_codes", mode="before")
    @classmethod
    def tuple_reason_codes(cls, value: object) -> tuple[str, ...]:
        """Normalize reason codes."""
        return tuple(value or ())


class SpecialistSelection(PlannerModel):
    """Specialist selected for a cognitive plan."""

    specialist_type: SpecialistType = Field(description="Selected specialist type.")
    specialist_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    required: bool = True
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("reason_codes", mode="before")
    @classmethod
    def tuple_reason_codes(cls, value: object) -> tuple[str, ...]:
        """Normalize reason codes."""
        return tuple(value or ())


class PipelineStep(PlannerModel):
    """Single execution step in a cognitive pipeline."""

    stage_id: UUID | None = None
    order: int = Field(ge=1)
    engine: str = Field(min_length=1, max_length=100)
    required: bool = True
    conditional: bool = False
    condition: StageCondition | None = None
    depends_on: tuple[UUID, ...] = Field(default_factory=tuple)
    dependencies: tuple[UUID, ...] = Field(default_factory=tuple)
    optional: bool = False
    timeout_seconds: int = Field(default=60, ge=0)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    expected_output: str = Field(default="stage output", min_length=1)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    status: StageStatus = StageStatus.PENDING

    @field_validator("depends_on", "dependencies", "reason_codes", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[object, ...]:
        """Normalize list-like values to immutable tuples."""
        return tuple(value or ())

    @model_validator(mode="after")
    def normalize_stage(self) -> Self:
        """Mirror legacy depends_on and new dependencies fields."""
        stage_id = self.stage_id or self.id
        dependencies = self.dependencies or self.depends_on
        optional = self.optional or not self.required
        object.__setattr__(self, "stage_id", stage_id)
        object.__setattr__(self, "depends_on", dependencies)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "optional", optional)
        return self


class Pipeline(PlannerModel):
    """Ordered cognitive execution pipeline."""

    steps: tuple[PipelineStep, ...] = Field(default_factory=tuple)
    metadata: dict[str, PlannerMetadataValue] = Field(default_factory=dict)

    @field_validator("steps", mode="before")
    @classmethod
    def tuple_steps(cls, value: object) -> tuple[PipelineStep, ...]:
        """Normalize pipeline steps to an immutable tuple."""
        return tuple(value or ())

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, PlannerMetadataValue],
    ) -> dict[str, PlannerMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return dict(value)

    @model_validator(mode="after")
    def validate_steps(self) -> Self:
        """Ensure pipeline step order and identifiers are unique."""
        orders = [step.order for step in self.steps]
        if len(orders) != len(set(orders)):
            msg = "pipeline step order values must be unique"
            raise ValueError(msg)
        ids = [step.stage_id for step in self.steps]
        if len(ids) != len(set(ids)):
            msg = "pipeline step identifiers must be unique"
            raise ValueError(msg)
        return self


class CognitivePlan(PlannerModel):
    """Plan for executing an ECOS cognitive session."""

    plan_id: UUID | None = None
    session_id: UUID
    organization_id: UUID | None = None
    objective: Objective
    objective_classification: ObjectiveClassification = ObjectiveClassification.ANALYSIS
    complexity_level: int = Field(default=3, ge=1, le=5)
    complexity: ComplexityLevel = ComplexityLevel.LEVEL_3
    complexity_score: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    strategy: ExecutionStrategy
    stages: tuple[PipelineStep, ...] = Field(default_factory=tuple)
    selected_engines: tuple[EngineSelection, ...] = Field(default_factory=tuple)
    selected_specialists: tuple[SpecialistSelection, ...] = Field(default_factory=tuple)
    governance_requirements: GovernanceRequirements = Field(
        default_factory=GovernanceRequirements
    )
    approval_requirements: ApprovalRequirements = Field(
        default_factory=ApprovalRequirements
    )
    pipeline: Pipeline | None = None
    estimated_duration_seconds: int = Field(default=0, ge=0)
    estimated_duration: int = Field(default=0, ge=0)
    estimated_token_budget: int = Field(default=0, ge=0)
    estimated_cost_units: float = Field(default=0.0, ge=0.0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    cognitive_depth: int = Field(default=1, ge=1, le=5)
    expected_engine_invocations: int = Field(default=0, ge=0)
    expected_specialist_count: int = Field(default=0, ge=0)
    confidence_target: float = Field(default=0.0, ge=0.0, le=1.0)
    version: str = Field(default="16g.1", min_length=1, max_length=50)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    assumptions: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, PlannerMetadataValue] = Field(default_factory=dict)

    @field_validator(
        "stages",
        "selected_engines",
        "selected_specialists",
        "reason_codes",
        "assumptions",
        "warnings",
        mode="before",
    )
    @classmethod
    def tuple_values(cls, value: object) -> tuple[object, ...]:
        """Normalize list-like values to immutable tuples."""
        return tuple(value or ())

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, PlannerMetadataValue],
    ) -> dict[str, PlannerMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return dict(value)

    @model_validator(mode="after")
    def normalize_plan(self) -> Self:
        """Mirror legacy fields and derive missing compatibility values."""
        plan_id = self.plan_id or self.id
        organization_id = self.organization_id or self.objective.organization_id
        stages = self.stages or tuple(self.pipeline.steps if self.pipeline else ())
        pipeline = self.pipeline or Pipeline(steps=stages, metadata={"source": "plan"})
        estimated_duration = self.estimated_duration or self.estimated_duration_seconds
        estimated_duration_seconds = (
            self.estimated_duration_seconds or self.estimated_duration
        )
        estimated_cost = self.estimated_cost or self.estimated_cost_units
        estimated_cost_units = self.estimated_cost_units or self.estimated_cost
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "organization_id", organization_id)
        object.__setattr__(self, "stages", tuple(stages))
        object.__setattr__(self, "pipeline", pipeline)
        object.__setattr__(self, "estimated_duration", estimated_duration)
        object.__setattr__(
            self,
            "estimated_duration_seconds",
            estimated_duration_seconds,
        )
        object.__setattr__(self, "estimated_cost", estimated_cost)
        object.__setattr__(self, "estimated_cost_units", estimated_cost_units)
        object.__setattr__(
            self,
            "expected_engine_invocations",
            self.expected_engine_invocations or len(stages),
        )
        object.__setattr__(
            self,
            "expected_specialist_count",
            self.expected_specialist_count or len(self.selected_specialists),
        )
        return self

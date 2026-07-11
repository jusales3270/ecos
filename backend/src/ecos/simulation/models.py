"""Public contracts for exploratory strategic simulation."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ecos.debate import DebateResult
from ecos.reasoning import ReasoningResult


class ScenarioType(StrEnum):
    BEST_CASE = "best_case"
    EXPECTED_CASE = "expected_case"
    WORST_CASE = "worst_case"
    BLACK_SWAN = "black_swan"
    COMPETITIVE = "competitive"
    INTERNAL = "internal"


class SimulationModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class SimulationRisk(SimulationModel):
    description: str
    probability: float = Field(ge=0.0, le=1.0)
    impact: str
    severity: str
    mitigation: str
    early_warning_signal: str
    owner_role: str | None = None


class Scenario(SimulationModel):
    scenario_id: str
    scenario_type: ScenarioType
    name: str
    description: str
    assumptions: list[str]
    trigger_conditions: list[str]
    probability: float = Field(ge=0.0, le=1.0)
    early_warning_signals: list[str]
    impacts: dict[str, str]
    risks: list[SimulationRisk]
    opportunities: list[str]
    second_order_effects: list[str]
    failure_modes: list[str]
    success_factors: list[str]
    mitigation_actions: list[str]
    recovery_options: list[str]


class Contingency(SimulationModel):
    primary_plan: str
    fallback_plan: str
    emergency_plan: str
    recovery_plan: str
    exit_strategy: str
    activation_conditions: list[str]


class SimulationContext(SimulationModel):
    session_id: UUID
    objective: dict[str, object]
    unified_context: dict[str, object]
    organizational_constraints: list[str] = Field(default_factory=list)
    relevant_policies: list[str] = Field(default_factory=list)
    memory: list[dict[str, object]] = Field(default_factory=list)
    reasoning_report: ReasoningResult
    debate_report: DebateResult
    external_signals: list[dict[str, object]] = Field(default_factory=list)
    correlation_id: UUID | None = None


class SimulationReport(SimulationModel):
    session_id: UUID
    objective: str
    critical_assumptions: list[str]
    scenarios: list[Scenario]
    cross_scenario_risks: list[SimulationRisk]
    cross_scenario_opportunities: list[str]
    second_order_effects: list[str]
    failure_modes: list[str]
    success_factors: list[str]
    contingencies: list[Contingency]
    resilience_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    executive_assessment: str
    metadata: dict[str, str | int | float] = Field(default_factory=dict)

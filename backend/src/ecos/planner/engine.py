"""Deterministic Cognitive Planner implementation for ECOS."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from ecos.core.exceptions import (
    PlannerDependencyUnavailableError,
    PlannerInvalidObjectiveError,
    PlannerMissingOrganizationError,
    PlannerValidationError,
)
from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.planner.models import (
    ApprovalRequirements,
    CognitivePlan,
    ComplexityLevel,
    EngineSelection,
    ExecutionStrategy,
    GovernanceRequirements,
    ObjectiveClassification,
    Pipeline,
    PipelineStep,
    PlannerEngine,
    PlannerInput,
    PlanningStrategy,
    RetryPolicy,
    RiskLevel,
    SpecialistSelection,
    StageCondition,
    StageStatus,
)
from ecos.specialists import SpecialistRegistry, SpecialistType

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]

COMPLEXITY_WEIGHTS: dict[str, float] = {
    "domains": 0.12,
    "constraints": 0.08,
    "policies": 0.10,
    "priority": 0.10,
    "urgency": 0.08,
    "risk": 0.12,
    "temporal_horizon": 0.06,
    "stakeholders": 0.08,
    "context_gaps": 0.10,
    "execution": 0.08,
    "multiple_perspectives": 0.04,
    "simulation": 0.02,
    "impact": 0.02,
}
ENGINE_COST_WEIGHTS: dict[PlannerEngine, float] = {
    PlannerEngine.CONTEXT: 1.0,
    PlannerEngine.REASONING: 2.0,
    PlannerEngine.SPECIALISTS: 1.5,
    PlannerEngine.DEBATE: 2.0,
    PlannerEngine.SIMULATION: 2.5,
    PlannerEngine.DECISION_SUPPORT: 1.8,
    PlannerEngine.GOVERNANCE: 1.0,
    PlannerEngine.EXECUTION: 2.0,
    PlannerEngine.OBSERVATION: 1.0,
    PlannerEngine.LEARNING: 1.0,
}
ENGINE_ORDER: tuple[PlannerEngine, ...] = (
    PlannerEngine.CONTEXT,
    PlannerEngine.REASONING,
    PlannerEngine.SPECIALISTS,
    PlannerEngine.DEBATE,
    PlannerEngine.SIMULATION,
    PlannerEngine.DECISION_SUPPORT,
    PlannerEngine.GOVERNANCE,
    PlannerEngine.EXECUTION,
    PlannerEngine.OBSERVATION,
    PlannerEngine.LEARNING,
)


class CognitivePlanner:
    """Real deterministic planner that plans cognition, not problem answers."""

    def __init__(
        self,
        *,
        specialist_registry: SpecialistRegistry,
        event_service: EventService | None = None,
        clock: Clock,
        id_generator: IdGenerator = uuid4,
    ) -> None:
        self._specialist_registry = specialist_registry
        self._event_service = event_service
        self._clock = clock
        self._id_generator = id_generator

    def create_plan(self, planner_input: PlannerInput) -> CognitivePlan:
        """Create and validate a deterministic cognitive plan."""
        self._validate_input(planner_input)
        self._publish(
            EventType.PLANNING_STARTED,
            planner_input,
            {"status": "started"},
        )

        classification, classification_codes = self._classify(planner_input)
        self._publish(
            EventType.OBJECTIVE_CLASSIFIED,
            planner_input,
            {"classification": classification.value},
        )

        risk_level, risk_codes = self._risk(planner_input, classification)
        complexity_score, complexity_level, complexity_codes = self._complexity(
            planner_input,
            classification,
            risk_level,
        )
        self._publish(
            EventType.COMPLEXITY_CALCULATED,
            planner_input,
            {
                "complexity_level": complexity_level,
                "complexity_score": round(complexity_score, 4),
                "risk_level": risk_level.value,
            },
        )

        strategy, strategy_codes = self._strategy(
            planner_input,
            classification,
            complexity_level,
            risk_level,
        )
        engines, engine_codes = self._select_engines(
            planner_input,
            classification,
            complexity_level,
            risk_level,
        )
        stages = self._build_stages(engines)
        self._publish(
            EventType.PIPELINE_GENERATED,
            planner_input,
            {"engine_count": len(engines)},
        )

        specialists, specialist_codes = self._select_specialists(
            planner_input,
            complexity_level,
            risk_level,
        )
        self._publish(
            EventType.SPECIALISTS_SELECTED,
            planner_input,
            {"specialist_count": len(specialists)},
        )

        governance = self._governance(
            planner_input,
            classification,
            complexity_level,
            risk_level,
        )
        approvals = ApprovalRequirements(
            required=governance.approval_required,
            minimum_level=governance.minimum_approval_level,
            roles=("governance_reviewer",) if governance.approval_required else (),
            granted=False,
            reasons=governance.reasons,
        )
        estimates = self._estimates(complexity_level, engines, specialists)
        confidence_target = self._confidence_target(
            classification,
            complexity_level,
            risk_level,
        )
        reason_codes = (
            *classification_codes,
            *risk_codes,
            *complexity_codes,
            *strategy_codes,
            *engine_codes,
            *specialist_codes,
        )
        created_at = self._clock()
        plan = CognitivePlan(
            id=self._id_generator(),
            plan_id=self._id_generator(),
            session_id=planner_input.session_id,
            organization_id=planner_input.organization_id,
            objective=planner_input.objective,
            objective_classification=classification,
            complexity_level=complexity_level,
            complexity=self._complexity_enum(complexity_level),
            complexity_score=complexity_score,
            risk_level=risk_level,
            strategy=strategy,
            stages=stages,
            selected_engines=engines,
            selected_specialists=specialists,
            governance_requirements=governance,
            approval_requirements=approvals,
            pipeline=Pipeline(
                id=self._id_generator(),
                steps=stages,
                metadata={"generated_by": "cognitive_planner"},
                created_at=created_at,
            ),
            confidence_target=confidence_target,
            version="16g.1",
            reason_codes=reason_codes,
            assumptions=self._assumptions(planner_input),
            warnings=self._warnings(planner_input, governance),
            metadata={"planner": "deterministic", "cost_units": "relative"},
            created_at=created_at,
            **estimates,
        )
        self._validate_plan(plan)
        self._publish(
            EventType.PLANNING_COMPLETED,
            planner_input,
            {
                "classification": classification.value,
                "complexity_level": complexity_level,
                "complexity_score": round(complexity_score, 4),
                "risk_level": risk_level.value,
                "strategy": strategy.strategy.value,
                "engine_count": len(engines),
                "specialist_count": len(specialists),
                "estimated_duration_seconds": plan.estimated_duration_seconds,
                "estimated_cost_units": plan.estimated_cost_units,
                "confidence_target": plan.confidence_target,
            },
        )
        return plan

    def _validate_input(self, planner_input: PlannerInput) -> None:
        if planner_input.organization_id is None:
            raise PlannerMissingOrganizationError()
        if (
            planner_input.objective is None
            or planner_input.objective.title.strip() == ""
        ):
            raise PlannerInvalidObjectiveError()

    def _classify(
        self,
        planner_input: PlannerInput,
    ) -> tuple[ObjectiveClassification, tuple[str, ...]]:
        if planner_input.declared_category is not None:
            return planner_input.declared_category, ("CLASS_DECLARED_CATEGORY",)
        text = self._text(planner_input)
        rules: tuple[tuple[ObjectiveClassification, str, tuple[str, ...]], ...] = (
            (
                ObjectiveClassification.EXECUTION,
                "CLASS_EXECUTION_REQUEST",
                ("execute", "implement", "run", "deploy"),
            ),
            (
                ObjectiveClassification.SIMULATION,
                "CLASS_SIMULATION_KEYWORD",
                ("simulate", "scenario", "war game", "stress test"),
            ),
            (
                ObjectiveClassification.DECISION_SUPPORT,
                "CLASS_DECISION_SUPPORT_KEYWORD",
                ("decide", "decision", "choose", "approve"),
            ),
            (
                ObjectiveClassification.RECOMMENDATION,
                "CLASS_RECOMMENDATION_KEYWORD",
                ("recommend", "recommendation", "advise", "suggest"),
            ),
            (
                ObjectiveClassification.PLANNING,
                "CLASS_PLANNING_KEYWORD",
                ("plan", "roadmap", "strategy", "prepare"),
            ),
            (
                ObjectiveClassification.MONITORING,
                "CLASS_MONITORING_KEYWORD",
                ("monitor", "track", "alert", "watch"),
            ),
            (
                ObjectiveClassification.OPTIMIZATION,
                "CLASS_OPTIMIZATION_KEYWORD",
                ("optimize", "improve", "reduce", "increase"),
            ),
            (
                ObjectiveClassification.RESEARCH,
                "CLASS_RESEARCH_KEYWORD",
                ("research", "investigate", "benchmark", "explore"),
            ),
            (
                ObjectiveClassification.ANALYSIS,
                "CLASS_ANALYSIS_KEYWORD",
                ("analyze", "analysis", "assess", "evaluate"),
            ),
            (
                ObjectiveClassification.QUESTION,
                "CLASS_QUESTION_MARKER",
                ("?", "what", "why", "how", "when"),
            ),
        )
        if planner_input.execution_requested:
            return ObjectiveClassification.EXECUTION, ("CLASS_EXECUTION_FLAG",)
        for classification, code, keywords in rules:
            if any(keyword in text for keyword in keywords):
                return classification, (code,)
        return ObjectiveClassification.ANALYSIS, ("CLASS_DEFAULT_ANALYSIS",)

    def _risk(
        self,
        planner_input: PlannerInput,
        classification: ObjectiveClassification,
    ) -> tuple[RiskLevel, tuple[str, ...]]:
        if planner_input.declared_risk is not None:
            return planner_input.declared_risk, ("RISK_DECLARED",)
        score = 0.0
        codes: list[str] = []
        impact = (planner_input.impact or "").lower()
        if impact in {"high", "strategic", "executive", "critical"}:
            score += 0.30
            codes.append("RISK_HIGH_IMPACT")
        if (
            planner_input.execution_requested
            or classification is ObjectiveClassification.EXECUTION
        ):
            score += 0.25
            codes.append("RISK_EXECUTION_REQUESTED")
        if planner_input.policies:
            score += min(0.20, len(planner_input.policies) * 0.05)
            codes.append("RISK_POLICY_SCOPE")
        if len(planner_input.domains) >= 3:
            score += 0.15
            codes.append("RISK_MULTI_DOMAIN")
        if not planner_input.reversible:
            score += 0.15
            codes.append("RISK_LOW_REVERSIBILITY")
        if planner_input.critical_context_gap_count > 0:
            score += 0.20
            codes.append("RISK_CRITICAL_CONTEXT_GAPS")
        if planner_input.priority >= 5:
            score += 0.10
            codes.append("RISK_CRITICAL_PRIORITY")
        if classification in {
            ObjectiveClassification.DECISION_SUPPORT,
            ObjectiveClassification.EXECUTION,
        }:
            score += 0.10
            codes.append("RISK_DECISION_OR_EXECUTION")
        if score >= 0.70:
            return RiskLevel.CRITICAL, tuple(codes or ["RISK_SCORE_CRITICAL"])
        if score >= 0.45:
            return RiskLevel.HIGH, tuple(codes or ["RISK_SCORE_HIGH"])
        if score >= 0.20:
            return RiskLevel.MEDIUM, tuple(codes or ["RISK_SCORE_MEDIUM"])
        return RiskLevel.LOW, tuple(codes or ["RISK_DEFAULT_LOW"])

    def _complexity(
        self,
        planner_input: PlannerInput,
        classification: ObjectiveClassification,
        risk_level: RiskLevel,
    ) -> tuple[float, int, tuple[str, ...]]:
        score = 0.0
        codes: list[str] = []
        score += min(len(planner_input.domains) / 5, 1) * COMPLEXITY_WEIGHTS["domains"]
        score += (
            min(len(planner_input.constraints) / 5, 1)
            * COMPLEXITY_WEIGHTS["constraints"]
        )
        score += (
            min(len(planner_input.policies) / 5, 1) * COMPLEXITY_WEIGHTS["policies"]
        )
        score += ((planner_input.priority - 1) / 4) * COMPLEXITY_WEIGHTS["priority"]
        if planner_input.urgency in {"high", "critical", "immediate"}:
            score += COMPLEXITY_WEIGHTS["urgency"]
            codes.append("COMPLEXITY_URGENCY")
        risk_scores = {
            RiskLevel.LOW: 0.0,
            RiskLevel.MEDIUM: 0.4,
            RiskLevel.HIGH: 0.7,
            RiskLevel.CRITICAL: 1.0,
        }
        score += risk_scores[risk_level] * COMPLEXITY_WEIGHTS["risk"]
        if planner_input.temporal_horizon in {
            "quarter",
            "year",
            "multi_year",
            "strategic",
        }:
            score += COMPLEXITY_WEIGHTS["temporal_horizon"]
            codes.append("COMPLEXITY_TEMPORAL_HORIZON")
        score += (
            min(planner_input.stakeholders_count / 10, 1)
            * COMPLEXITY_WEIGHTS["stakeholders"]
        )
        score += (
            min(
                (
                    planner_input.context_gap_count
                    + planner_input.critical_context_gap_count * 2
                )
                / 10,
                1,
            )
            * COMPLEXITY_WEIGHTS["context_gaps"]
        )
        if planner_input.execution_requested:
            score += COMPLEXITY_WEIGHTS["execution"]
            codes.append("COMPLEXITY_EXECUTION_DEPENDENCY")
        if len(planner_input.domains) >= 2 or planner_input.stakeholders_count >= 3:
            score += COMPLEXITY_WEIGHTS["multiple_perspectives"]
            codes.append("COMPLEXITY_MULTIPLE_PERSPECTIVES")
        if classification is ObjectiveClassification.SIMULATION:
            score += COMPLEXITY_WEIGHTS["simulation"]
            codes.append("COMPLEXITY_SIMULATION_NEED")
        if planner_input.impact in {"high", "strategic", "executive", "critical"}:
            score += COMPLEXITY_WEIGHTS["impact"]
            codes.append("COMPLEXITY_ORGANIZATIONAL_IMPACT")
        score = min(round(score, 4), 1.0)
        level = 1
        if score >= 0.80:
            level = 5
        elif score >= 0.60:
            level = 4
        elif score >= 0.35:
            level = 3
        elif score >= 0.15:
            level = 2
        if risk_level is RiskLevel.CRITICAL:
            level = max(level, 4)
            codes.append("COMPLEXITY_CRITICAL_RISK_MINIMUM")
        if classification in {
            ObjectiveClassification.DECISION_SUPPORT,
            ObjectiveClassification.EXECUTION,
        } and planner_input.impact in {"strategic", "executive"}:
            level = max(level, 4)
            codes.append("COMPLEXITY_STRATEGIC_DECISION_MINIMUM")
        return score, level, tuple(codes or ["COMPLEXITY_SCORE_WEIGHTED"])

    def _strategy(
        self,
        planner_input: PlannerInput,
        classification: ObjectiveClassification,
        complexity_level: int,
        risk_level: RiskLevel,
    ) -> tuple[ExecutionStrategy, tuple[str, ...]]:
        if (
            planner_input.recurring
            or classification is ObjectiveClassification.MONITORING
        ):
            strategy = PlanningStrategy.CONTINUOUS_MONITORING
            codes = ("STRATEGY_CONTINUOUS_MONITORING",)
        elif planner_input.priority >= 5 and risk_level in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }:
            strategy = PlanningStrategy.CRISIS_MODE
            codes = ("STRATEGY_CRISIS_MODE",)
        elif complexity_level >= 4:
            strategy = PlanningStrategy.EXECUTIVE_ADVISORY
            codes = ("STRATEGY_EXECUTIVE_ADVISORY",)
        elif complexity_level >= 3:
            strategy = PlanningStrategy.DEEP
            codes = ("STRATEGY_DEEP_ANALYSIS",)
        elif complexity_level == 2:
            strategy = PlanningStrategy.BALANCED
            codes = ("STRATEGY_BALANCED",)
        else:
            strategy = PlanningStrategy.FAST_RESPONSE
            codes = ("STRATEGY_FAST_RESPONSE",)
        return (
            ExecutionStrategy(
                id=self._id_generator(),
                strategy=strategy,
                rationale=(
                    "Deterministic planning rule selected this cognitive strategy."
                ),
                constraints=planner_input.constraints,
                reason_codes=codes,
                created_at=self._clock(),
            ),
            codes,
        )

    def _select_engines(
        self,
        planner_input: PlannerInput,
        classification: ObjectiveClassification,
        complexity_level: int,
        risk_level: RiskLevel,
    ) -> tuple[tuple[EngineSelection, ...], tuple[str, ...]]:
        selected: list[tuple[PlannerEngine, str]] = [
            (PlannerEngine.CONTEXT, "ENGINE_CONTEXT_BASELINE")
        ]
        if classification in {
            ObjectiveClassification.ANALYSIS,
            ObjectiveClassification.RECOMMENDATION,
            ObjectiveClassification.PLANNING,
            ObjectiveClassification.OPTIMIZATION,
            ObjectiveClassification.DECISION_SUPPORT,
            ObjectiveClassification.EXECUTION,
            ObjectiveClassification.RESEARCH,
        }:
            selected.append((PlannerEngine.REASONING, "ENGINE_REASONING_REQUIRED"))
        if (
            complexity_level >= 3
            or risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            or len(planner_input.domains) > 1
            or planner_input.stakeholders_count >= 3
        ):
            selected.extend(
                [
                    (PlannerEngine.SPECIALISTS, "ENGINE_SPECIALISTS_PERSPECTIVES"),
                    (PlannerEngine.DEBATE, "ENGINE_DEBATE_REQUIRED"),
                ]
            )
        if (
            classification is ObjectiveClassification.SIMULATION
            or (complexity_level >= 3 and planner_input.temporal_horizon is not None)
            or risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            or planner_input.impact in {"strategic", "executive"}
        ):
            selected.append((PlannerEngine.SIMULATION, "ENGINE_SIMULATION_REQUIRED"))
        if (
            classification
            in {
                ObjectiveClassification.RECOMMENDATION,
                ObjectiveClassification.DECISION_SUPPORT,
                ObjectiveClassification.PLANNING,
                ObjectiveClassification.OPTIMIZATION,
                ObjectiveClassification.EXECUTION,
            }
            or complexity_level >= 4
        ):
            selected.append(
                (PlannerEngine.DECISION_SUPPORT, "ENGINE_DECISION_SUPPORT_REQUIRED")
            )
        if (
            planner_input.execution_requested
            or risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            or planner_input.policies
            or planner_input.impact in {"medium", "high", "strategic", "executive"}
        ):
            selected.append((PlannerEngine.GOVERNANCE, "ENGINE_GOVERNANCE_REQUIRED"))
        if planner_input.execution_requested:
            selected.extend(
                [
                    (PlannerEngine.EXECUTION, "ENGINE_EXECUTION_CONDITIONAL"),
                    (PlannerEngine.OBSERVATION, "ENGINE_OBSERVATION_AFTER_EXECUTION"),
                    (PlannerEngine.LEARNING, "ENGINE_LEARNING_AFTER_EXECUTION"),
                ]
            )
        deduped: dict[PlannerEngine, str] = {}
        for engine, code in selected:
            deduped.setdefault(engine, code)
        ordered = [
            (engine, deduped[engine]) for engine in ENGINE_ORDER if engine in deduped
        ]
        return tuple(
            EngineSelection(
                id=self._id_generator(),
                engine=engine.value,
                reason=f"Selected by deterministic rule {code}.",
                required=engine is not PlannerEngine.EXECUTION,
                reason_codes=(code,),
                created_at=self._clock(),
            )
            for engine, code in ordered
        ), tuple(code for _, code in ordered)

    def _build_stages(
        self,
        engines_and_codes: tuple[EngineSelection, ...] | tuple[EngineSelection, ...],
    ) -> tuple[PipelineStep, ...]:
        stages: list[PipelineStep] = []
        previous_id: UUID | None = None
        for order, selection in enumerate(engines_and_codes, start=1):
            engine = selection.engine
            dependencies = (previous_id,) if previous_id is not None else ()
            conditional = engine == PlannerEngine.EXECUTION.value
            stage_id = self._id_generator()
            stages.append(
                PipelineStep(
                    id=stage_id,
                    stage_id=stage_id,
                    order=order,
                    engine=engine,
                    required=not conditional,
                    conditional=conditional,
                    condition=StageCondition(
                        type="governance_approval",
                        requirements=("governance_completed", "human_approval_granted"),
                    )
                    if conditional
                    else None,
                    depends_on=dependencies,
                    dependencies=dependencies,
                    optional=conditional,
                    timeout_seconds=60 + order * 30,
                    retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=0),
                    expected_output=f"{engine} artifact",
                    reason_codes=selection.reason_codes,
                    status=StageStatus.BLOCKED if conditional else StageStatus.PENDING,
                    created_at=self._clock(),
                )
            )
            previous_id = stage_id
        return tuple(stages)

    def _select_specialists(
        self,
        planner_input: PlannerInput,
        complexity_level: int,
        risk_level: RiskLevel,
    ) -> tuple[tuple[SpecialistSelection, ...], tuple[str, ...]]:
        if complexity_level == 1 and risk_level is RiskLevel.LOW:
            return (), ()
        domain_text = " ".join(planner_input.domains).lower()
        selected: list[tuple[SpecialistType, str]] = []
        mapping = (
            (
                SpecialistType.FINANCE,
                "SPECIALIST_FINANCE_DOMAIN",
                ("finance", "cost", "budget"),
            ),
            (
                SpecialistType.LEGAL,
                "SPECIALIST_LEGAL_POLICY",
                ("legal", "contract", "regulation", "compliance"),
            ),
            (SpecialistType.RISK, "SPECIALIST_RISK_HIGH", ("risk",)),
            (
                SpecialistType.TECHNOLOGY,
                "SPECIALIST_TECHNOLOGY_DOMAIN",
                ("technology", "software", "platform", "data"),
            ),
            (
                SpecialistType.OPERATIONS,
                "SPECIALIST_OPERATIONS_DOMAIN",
                ("operations", "process", "supply"),
            ),
            (
                SpecialistType.STRATEGY,
                "SPECIALIST_STRATEGY_DOMAIN",
                ("strategy", "market", "executive"),
            ),
            (
                SpecialistType.HR,
                "SPECIALIST_HR_DOMAIN",
                ("people", "hr", "hiring", "workforce"),
            ),
        )
        for specialist_type, code, keywords in mapping:
            if any(keyword in domain_text for keyword in keywords):
                selected.append((specialist_type, code))
        if planner_input.policies:
            selected.append((SpecialistType.LEGAL, "SPECIALIST_POLICY_REVIEW"))
        if risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            selected.append((SpecialistType.RISK, "SPECIALIST_RISK_HIGH"))
        if complexity_level >= 3:
            selected.append((SpecialistType.STRATEGY, "SPECIALIST_COMPLEXITY_STRATEGY"))
        deduped: dict[SpecialistType, str] = {}
        for specialist_type, code in selected:
            deduped.setdefault(specialist_type, code)
        selections: list[SpecialistSelection] = []
        for specialist_type in sorted(deduped, key=lambda item: item.value):
            specialists = sorted(
                (
                    specialist
                    for specialist in self._specialist_registry.find_by_type(
                        specialist_type
                    )
                    if specialist.enabled
                ),
                key=lambda item: item.name,
            )
            if not specialists:
                raise PlannerValidationError(
                    "selected specialist is not registered.",
                    "PLANNER_SPECIALIST_NOT_FOUND",
                    {"specialist_type": specialist_type.value},
                )
            specialist = specialists[0]
            selections.append(
                SpecialistSelection(
                    id=self._id_generator(),
                    specialist_id=specialist.id,
                    specialist_type=specialist.type,
                    reason=(
                        f"Selected by deterministic rule {deduped[specialist_type]}."
                    ),
                    reason_codes=(deduped[specialist_type],),
                    created_at=self._clock(),
                )
            )
        return tuple(selections), tuple(deduped.values())

    def _governance(
        self,
        planner_input: PlannerInput,
        classification: ObjectiveClassification,
        complexity_level: int,
        risk_level: RiskLevel,
    ) -> GovernanceRequirements:
        required = (
            planner_input.execution_requested
            or risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            or bool(planner_input.policies)
            or planner_input.impact in {"medium", "high", "strategic", "executive"}
        )
        human = (
            planner_input.execution_requested
            or risk_level is RiskLevel.CRITICAL
            or complexity_level >= 4
            or classification is ObjectiveClassification.EXECUTION
        )
        reasons: list[str] = []
        if planner_input.execution_requested:
            reasons.append("GOVERNANCE_EXECUTION_REQUESTED")
        if risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            reasons.append("GOVERNANCE_HIGH_RISK")
        if planner_input.policies:
            reasons.append("GOVERNANCE_POLICY_CHECKS")
        if complexity_level >= 4:
            reasons.append("GOVERNANCE_STRATEGIC_REVIEW")
        return GovernanceRequirements(
            governance_required=required,
            approval_required=human,
            minimum_approval_level="executive" if complexity_level >= 4 else "manager",
            policy_checks=tuple(
                f"policy_{index}"
                for index, _ in enumerate(planner_input.policies, start=1)
            ),
            human_review_required=human,
            execution_blocked_until_approval=planner_input.execution_requested,
            reasons=tuple(reasons or ["GOVERNANCE_NOT_REQUIRED"]),
        )

    def _estimates(
        self,
        complexity_level: int,
        engines: tuple[EngineSelection, ...],
        specialists: tuple[SpecialistSelection, ...],
    ) -> dict[str, int | float]:
        engine_units = sum(
            ENGINE_COST_WEIGHTS.get(PlannerEngine(selection.engine), 1.0)
            for selection in engines
        )
        duration = int(
            30 + complexity_level * 45 + len(engines) * 20 + len(specialists) * 15
        )
        token_budget = int(500 + complexity_level * 750 + engine_units * 250)
        cost_units = round(
            complexity_level * 1.5 + engine_units + len(specialists) * 0.5, 2
        )
        return {
            "estimated_duration_seconds": duration,
            "estimated_token_budget": token_budget,
            "estimated_cost_units": cost_units,
            "cognitive_depth": complexity_level,
            "expected_engine_invocations": len(engines),
            "expected_specialist_count": len(specialists),
        }

    def _confidence_target(
        self,
        classification: ObjectiveClassification,
        complexity_level: int,
        risk_level: RiskLevel,
    ) -> float:
        target = 0.60 + complexity_level * 0.04
        if classification in {
            ObjectiveClassification.DECISION_SUPPORT,
            ObjectiveClassification.EXECUTION,
            ObjectiveClassification.RECOMMENDATION,
        }:
            target += 0.08
        if risk_level is RiskLevel.HIGH:
            target += 0.08
        if risk_level is RiskLevel.CRITICAL:
            target += 0.12
        return min(round(target, 2), 0.95)

    def _validate_plan(self, plan: CognitivePlan) -> None:
        if not plan.stages:
            raise PlannerValidationError(
                "plan pipeline cannot be empty.", "PLANNER_PIPELINE_EMPTY"
            )
        stage_ids = [stage.stage_id for stage in plan.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise PlannerValidationError(
                "stage identifiers must be unique.", "PLANNER_DUPLICATE_STAGE_ID"
            )
        stage_by_id = {stage.stage_id: stage for stage in plan.stages}
        for stage in plan.stages:
            if stage.engine not in {engine.value for engine in PlannerEngine}:
                raise PlannerValidationError(
                    "unknown engine selected.", "PLANNER_ENGINE_NOT_FOUND"
                )
            for dependency in stage.dependencies:
                if dependency not in stage_by_id:
                    raise PlannerValidationError(
                        "stage dependency is invalid.", "PLANNER_INVALID_DEPENDENCY"
                    )
                if stage_by_id[dependency].order >= stage.order:
                    raise PlannerValidationError(
                        "stage dependency order is invalid.",
                        "PLANNER_INVALID_DEPENDENCY_ORDER",
                    )
        self._validate_acyclic(plan.stages)
        engines = [selection.engine for selection in plan.selected_engines]
        if len(engines) != len(set(engines)):
            raise PlannerValidationError(
                "selected engines must be unique.", "PLANNER_DUPLICATE_ENGINE"
            )
        if PlannerEngine.EXECUTION.value in engines:
            if PlannerEngine.GOVERNANCE.value not in engines:
                raise PlannerValidationError(
                    "execution requires governance.",
                    "PLANNER_EXECUTION_WITHOUT_GOVERNANCE",
                )
            if not plan.governance_requirements.execution_blocked_until_approval:
                raise PlannerValidationError(
                    "execution must be blocked until approval.",
                    "PLANNER_EXECUTION_NOT_BLOCKED",
                )
            if plan.approval_requirements.granted:
                raise PlannerValidationError(
                    "planner cannot grant approval.", "PLANNER_APPROVAL_GRANTED"
                )

    def _validate_acyclic(self, stages: tuple[PipelineStep, ...]) -> None:
        visiting: set[UUID] = set()
        visited: set[UUID] = set()
        graph = {stage.stage_id: set(stage.dependencies) for stage in stages}

        def visit(stage_id: UUID) -> None:
            if stage_id in visited:
                return
            if stage_id in visiting:
                raise PlannerValidationError(
                    "pipeline contains a cycle.", "PLANNER_CYCLE_DETECTED"
                )
            visiting.add(stage_id)
            for dependency in graph[stage_id]:
                visit(dependency)
            visiting.remove(stage_id)
            visited.add(stage_id)

        for stage_id in graph:
            visit(stage_id)

    def _publish(
        self,
        event_type: EventType,
        planner_input: PlannerInput,
        payload: dict[str, str | int | float | bool | None],
    ) -> None:
        if self._event_service is None:
            return
        try:
            envelope = self._event_service.publish(
                Event(
                    event_type=event_type,
                    source="planner",
                    session_id=planner_input.session_id,
                    payload=payload,
                    metadata=EventMetadata(
                        correlation_id=planner_input.correlation_id,
                        attributes={
                            "organization_id": str(planner_input.organization_id)
                        },
                    ),
                    priority=EventPriority.NORMAL,
                    created_at=self._clock(),
                )
            )
            self._event_service.dispatch(envelope)
        except Exception as error:
            raise PlannerDependencyUnavailableError("event_service") from error

    def _assumptions(self, planner_input: PlannerInput) -> tuple[str, ...]:
        assumptions = ["Planner uses deterministic rules only."]
        if not planner_input.context_available:
            assumptions.append("Context is marked unavailable at planning time.")
        return tuple(assumptions)

    def _warnings(
        self,
        planner_input: PlannerInput,
        governance: GovernanceRequirements,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if (
            planner_input.execution_requested
            and governance.execution_blocked_until_approval
        ):
            warnings.append("Execution is planned only as conditional and blocked.")
        if planner_input.critical_context_gap_count:
            warnings.append("Critical context gaps require downstream handling.")
        return tuple(warnings)

    def _text(self, planner_input: PlannerInput) -> str:
        return " ".join(
            item
            for item in (
                planner_input.objective.title,
                planner_input.objective.description or "",
                planner_input.description or "",
                planner_input.desired_outcome or "",
            )
            if item
        ).lower()

    def _complexity_enum(self, level: int) -> ComplexityLevel:
        return ComplexityLevel(f"LEVEL_{level}")

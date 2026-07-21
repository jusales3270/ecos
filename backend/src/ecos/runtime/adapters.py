"""Runtime engine executor adapters for the real Orchestrator."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ecos.context import ContextBuildRequest, ContextService
from ecos.debate import Debate, DebateService
from ecos.decision import DecisionContext, DecisionPackage, DecisionService
from ecos.execution import (
    ExecutionAuthorization,
    ExecutionEngine,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionType,
    ResourceRequirement,
)
from ecos.execution import (
    ExecutionPlan as OperationalExecutionPlan,
)
from ecos.execution import (
    ExecutionStep as OperationalExecutionStep,
)
from ecos.governance import (
    AuthorizationDecisionValue,
    GovernanceActionType,
    GovernanceEngine,
    GovernanceRequest,
    GovernanceResult,
    GovernanceResultStatus,
    ImpactLevel,
)
from ecos.learning import LearningRequest, LearningService
from ecos.observation import (
    ComparisonOperator,
    ExpectedOutcome,
    Measurement,
    MeasurementSource,
    MeasurementValueType,
    ObservationEngine,
    ObservationRequest,
    ObservationSourceType,
    ObservationWindow,
)
from ecos.orchestrator import (
    EngineExecutor,
    EngineInvocationContext,
    EngineStageResult,
    StageExecutionStatus,
)
from ecos.planner import RiskLevel
from ecos.reasoning import ReasoningContext, ReasoningService, ReasoningType
from ecos.simulation import SimulationContext, SimulationService
from ecos.specialists import SpecialistService


class RuntimeEngineExecutor(EngineExecutor):
    """Base adapter that wraps a runtime service as a generic executor."""

    def __init__(self, engine_type: str) -> None:
        self._engine_type = engine_type

    @property
    def engine_type(self) -> str:
        return self._engine_type

    @property
    def available(self) -> bool:
        return True

    def execute(self, context: EngineInvocationContext) -> EngineStageResult:
        started_at = _now()
        output = self._execute(context)
        completed_at = _now()
        return EngineStageResult(
            stage_id=context.stage.stage_id,
            engine=self.engine_type,
            status=StageExecutionStatus.COMPLETED,
            output=output,
            started_at=started_at,
            completed_at=completed_at,
            duration=max((completed_at - started_at).total_seconds(), 0.0),
            attempt=context.attempt,
            safe_metadata={"adapter": type(self).__name__},
        )

    def _execute(self, context: EngineInvocationContext) -> Any:
        raise NotImplementedError


class ContextExecutor(RuntimeEngineExecutor):
    """Build Unified Context through ContextService."""

    def __init__(self, service: ContextService) -> None:
        super().__init__("context")
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> Any:
        objective = context.session.session.objective
        request = ContextBuildRequest(
            session_id=context.session.session.id,
            organization_id=context.session.session.organization_id,
            objective=objective,
            user_information=[objective.description or ""]
            if objective.description
            else [],
            constraints=list(context.plan.strategy.constraints),
            policies=list(context.plan.governance_requirements.policy_checks),
            resources=[step.engine for step in context.plan.pipeline.steps],
            external_signals=[],
            relevant_entities=[objective.title],
            required_context_fields=["objective", "memory"],
            correlation_id=context.correlation_id,
        )
        output = self._service.build(request)
        if not self._service.validate(output):
            raise RuntimeError("context validation failed")
        return output


class ReasoningExecutor(RuntimeEngineExecutor):
    """Run Reasoning through ReasoningService."""

    def __init__(self, service: ReasoningService) -> None:
        super().__init__("reasoning")
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> Any:
        context_object = _require(context.accumulated_context, "context")
        reasoning_context = ReasoningContext(
            session_id=context.session.session.id,
            context=context_object,
            reasoning_type=ReasoningType.STRATEGIC,
            constraints=list(context_object.constraints),
            memory=[
                str(reference.memory_id)
                for reference in context_object.memory_references
            ],
        )
        return self._service.analyze(reasoning_context)


class SpecialistsExecutor(RuntimeEngineExecutor):
    """Collect specialist contributions through SpecialistService."""

    def __init__(self, service: SpecialistService) -> None:
        super().__init__("specialists")
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> Any:
        reasoning = _require(context.accumulated_context, "reasoning")
        planned_types = {
            selection.specialist_type for selection in context.plan.selected_specialists
        }
        specialists = [
            specialist
            for specialist in self._service.load()
            if not planned_types or specialist.type in planned_types
        ]
        contributions = [
            self._service.contribute(
                specialist.id,
                {
                    "objective": context.session.session.objective.title,
                    "reasoning": reasoning.summary,
                },
            )
            for specialist in specialists
        ]
        return {"specialists": specialists, "contributions": contributions}


class DebateExecutor(RuntimeEngineExecutor):
    """Run Debate through DebateService."""

    def __init__(self, service: DebateService) -> None:
        super().__init__("debate")
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> Any:
        context_object = _require(context.accumulated_context, "context")
        reasoning = _require(context.accumulated_context, "reasoning")
        specialist_output = context.accumulated_context.get(
            "specialists",
            {"specialists": [], "contributions": []},
        )
        debate = Debate(
            session_id=context.session.session.id,
            specialists=specialist_output["specialists"],
            objective=context.session.session.objective.title,
            unified_context=context_object.model_dump(mode="json"),
            organizational_constraints=list(context_object.constraints),
            reasoning_result=reasoning,
            contributions=specialist_output["contributions"],
        )
        debate = self._service.start(debate)
        arguments = self._service.collect_arguments(debate)
        debate = debate.model_copy(update={"arguments": arguments})
        return self._service.finalize(debate)


class SimulationExecutor(RuntimeEngineExecutor):
    """Run exploratory simulation through SimulationService."""

    def __init__(self, service: SimulationService) -> None:
        super().__init__("simulation")
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> Any:
        context_object = _require(context.accumulated_context, "context")
        reasoning = _require(context.accumulated_context, "reasoning")
        debate = _require(context.accumulated_context, "debate")
        simulation_context = SimulationContext(
            session_id=context.session.session.id,
            objective=context.session.session.objective.model_dump(mode="json"),
            unified_context=context_object.model_dump(mode="json"),
            organizational_constraints=list(context_object.constraints),
            relevant_policies=[
                element.content
                for element in context_object.elements
                if element.source_type.value == "POLICY"
            ],
            memory=[
                item.model_dump(mode="json")
                for item in context_object.memory_references
            ],
            reasoning_report=reasoning,
            debate_report=debate,
            external_signals=[
                element.model_dump(mode="json")
                for element in context_object.elements
                if element.source_type.value == "EXTERNAL"
            ],
            correlation_id=context.correlation_id,
        )
        return self._service.simulate(simulation_context)


class DecisionExecutor(RuntimeEngineExecutor):
    """Build decision support package through DecisionService."""

    def __init__(self, service: DecisionService, engine_type: str = "decision") -> None:
        super().__init__(engine_type)
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> DecisionPackage:
        context_object = _require(context.accumulated_context, "context")
        reasoning = _require(context.accumulated_context, "reasoning")
        debate = _require(context.accumulated_context, "debate")
        simulation = _require(context.accumulated_context, "simulation")
        decision_context = DecisionContext(
            session_id=context.session.session.id,
            objective=context.session.session.objective.model_dump(mode="json"),
            unified_context=context_object,
            constraints=list(context_object.constraints),
            relevant_policies=[
                element.content
                for element in context_object.elements
                if element.source_type.value == "POLICY"
            ],
            memory=[
                item.model_dump(mode="json")
                for item in context_object.memory_references
            ],
            reasoning_report=reasoning,
            debate_report=debate,
            simulation_report=simulation,
            correlation_id=context.correlation_id,
        )
        recommendation = self._service.build_recommendation(
            reasoning,
            debate,
            decision_context,
        )
        brief = self._service.build_executive_brief(recommendation)
        return self._service.build_decision_package(recommendation, brief)


class LearningExecutor(RuntimeEngineExecutor):
    """Run LearningService without allowing the Orchestrator to create candidates."""

    def __init__(self, service: LearningService, engine_type: str = "learning") -> None:
        super().__init__(engine_type)
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> Any:
        observation = _require(context.accumulated_context, "observation")
        decision_package = context.accumulated_context.get("decision") or (
            context.accumulated_context.get("decision_support")
        )
        return self._service.process(
            LearningRequest(
                learning_request_id=context.stage.stage_id,
                organization_id=context.session.session.organization_id,
                session_id=context.session.session.id,
                plan_id=context.plan.plan_id,
                correlation_id=context.correlation_id,
                execution_id=observation.execution_id,
                observation_id=observation.observation_id,
                observation_result=observation,
                decision_package=decision_package,
                recommendation=getattr(decision_package, "recommendation", None),
                execution_result=context.accumulated_context.get("execution"),
                simulation_result=context.accumulated_context.get("simulation"),
                debate_report=context.accumulated_context.get("debate"),
                user_feedback=tuple(observation.feedback),
                applicable_policies=tuple(
                    context.plan.governance_requirements.policy_checks
                ),
                human_review_state=(
                    "enabled"
                    if context.safe_metadata.get("authenticated") is True
                    else None
                ),
                safe_metadata={
                    "adapter": type(self).__name__,
                    "objective": context.session.session.objective.title,
                },
            )
        )


class ObservationExecutor(RuntimeEngineExecutor):
    """Run the real ObservationEngine from accumulated stage outputs."""

    def __init__(self, engine: ObservationEngine) -> None:
        super().__init__("observation")
        self._engine = engine

    def _execute(self, context: EngineInvocationContext) -> Any:
        decision_package = context.accumulated_context.get("decision") or (
            context.accumulated_context.get("decision_support")
        )
        execution_result = context.accumulated_context.get("execution")
        recommendation = getattr(decision_package, "recommendation", None)
        confidence = float(getattr(recommendation, "confidence", 0.0))
        execution = (
            execution_result if isinstance(execution_result, ExecutionResult) else None
        )
        source_type = (
            ObservationSourceType.EXECUTION_RESULT
            if execution is not None
            else ObservationSourceType.DECISION_OUTCOME
        )
        source_id = (
            f"execution:{execution.execution_id}"
            if execution is not None
            else f"decision:{context.stage.stage_id}"
        )
        source = MeasurementSource(
            source_type=source_type,
            source_id=source_id,
            reliability=1.0,
            verified=True,
        )
        measurements: list[Measurement] = []
        expected_outcomes: list[ExpectedOutcome] = []
        if execution is not None:
            evidence = [
                f"execution_result:{execution.execution_id}:{execution.fingerprint}"
            ]
            evidence.extend(
                f"execution_failure:{failure.failure_id}"
                for failure in execution.failures
            )
            evidence.extend(
                f"execution_artifact:{artifact.artifact_id}"
                for artifact in execution.artifacts
                if not artifact.sensitive
            )
            observed_at = _now()
            measurements.extend(
                (
                    Measurement(
                        measurement_id=(
                            f"measurement:{context.stage.stage_id}:execution_status"
                        ),
                        metric_key="execution_status",
                        value=execution.status.value,
                        value_type=MeasurementValueType.STATUS,
                        source=source,
                        observed_at=observed_at,
                        evidence_references=tuple(evidence),
                        confidence=1.0,
                        verified=True,
                        reason_codes=("canonical_execution_result",),
                    ),
                    Measurement(
                        measurement_id=(
                            f"measurement:{context.stage.stage_id}:execution_duration"
                        ),
                        metric_key="execution_duration",
                        value=execution.duration,
                        value_type=MeasurementValueType.DURATION,
                        unit="seconds",
                        source=source,
                        observed_at=observed_at,
                        evidence_references=tuple(evidence[:1]),
                        confidence=1.0,
                        verified=True,
                        reason_codes=("canonical_execution_metric",),
                    ),
                    Measurement(
                        measurement_id=(
                            f"measurement:{context.stage.stage_id}:failure_count"
                        ),
                        metric_key="execution_failure_count",
                        value=len(execution.failures),
                        value_type=MeasurementValueType.COUNT,
                        source=source,
                        observed_at=observed_at,
                        evidence_references=tuple(evidence),
                        confidence=1.0,
                        verified=True,
                        reason_codes=("canonical_execution_failures",),
                    ),
                    Measurement(
                        measurement_id=(
                            f"measurement:{context.stage.stage_id}:rollback_count"
                        ),
                        metric_key="execution_rollback_count",
                        value=len(execution.rollback_results),
                        value_type=MeasurementValueType.COUNT,
                        source=source,
                        observed_at=observed_at,
                        evidence_references=tuple(evidence[:1]),
                        confidence=1.0,
                        verified=True,
                        reason_codes=("canonical_execution_rollbacks",),
                    ),
                )
            )
            measurements.extend(
                Measurement(
                    measurement_id=(
                        f"measurement:{context.stage.stage_id}:metric:{index}"
                    ),
                    metric_key=f"execution_metric:{metric.name}",
                    value=metric.value,
                    value_type=MeasurementValueType.NUMERIC,
                    unit=metric.unit,
                    source=source,
                    observed_at=observed_at,
                    evidence_references=tuple(evidence[:1]),
                    confidence=1.0,
                    verified=True,
                    reason_codes=("canonical_execution_metric",),
                )
                for index, metric in enumerate(execution.metrics, 1)
            )
            expected_outcomes.append(
                ExpectedOutcome(
                    expected_outcome_id=(
                        f"expected:{context.stage.stage_id}:execution_status"
                    ),
                    name="Execution completes successfully",
                    description="Compares the canonical execution status with success.",
                    metric_key="execution_status",
                    expected_status=ExecutionStatus.COMPLETED.value,
                    comparison_operator=ComparisonOperator.EQUALS,
                    weight=1.0,
                    required=True,
                    source_reference=f"plan:{context.plan.plan_id}",
                    reason_codes=("execution_completion_required",),
                )
            )
        else:
            measurements.append(
                Measurement(
                    measurement_id=(f"measurement:{context.stage.stage_id}:confidence"),
                    metric_key="recommendation_confidence",
                    value=confidence,
                    value_type=MeasurementValueType.SCORE,
                    source=source,
                    observed_at=_now(),
                    evidence_references=(f"decision:{context.stage.stage_id}",),
                    confidence=confidence,
                    verified=True,
                    reason_codes=("runtime_decision_output",),
                )
            )
            expected_outcomes.append(
                ExpectedOutcome(
                    expected_outcome_id=(
                        f"expected:{context.stage.stage_id}:confidence"
                    ),
                    name="Recommendation confidence meets plan target",
                    description=(
                        "Compares declared plan target with observed recommendation "
                        "confidence."
                    ),
                    metric_key="recommendation_confidence",
                    expected_value=context.plan.confidence_target,
                    comparison_operator=ComparisonOperator.GREATER_THAN_OR_EQUAL,
                    tolerance=0.0,
                    weight=1.0,
                    required=True,
                    source_reference=f"plan:{context.plan.plan_id}",
                    reason_codes=("plan_confidence_target",),
                )
            )
        return self._engine.observe(
            ObservationRequest(
                observation_request_id=context.stage.stage_id,
                organization_id=context.session.session.organization_id,
                session_id=context.session.session.id,
                plan_id=context.plan.plan_id,
                correlation_id=context.correlation_id,
                execution_id=None if execution is None else execution.execution_id,
                source_event_id=None
                if execution is None
                else execution.terminal_event_id,
                source_type=source_type,
                source_id=source_id,
                execution_result=execution_result,
                decision_package=decision_package,
                recommendation=recommendation,
                expected_outcomes=tuple(expected_outcomes),
                observed_measurements=tuple(measurements),
                observation_window=ObservationWindow(
                    started_at=context.session.state.updated_at,
                    ended_at=_now(),
                ),
                affected_domains=tuple(context.safe_metadata.keys()),
                policy_references=tuple(
                    context.plan.governance_requirements.policy_checks
                ),
                safe_metadata={"adapter": type(self).__name__},
            )
        )


class GovernanceExecutor(RuntimeEngineExecutor):
    """Run the real GovernanceEngine without performing cognition."""

    def __init__(self, engine: GovernanceEngine) -> None:
        super().__init__("governance")
        self._engine = engine

    def _execute(self, context: EngineInvocationContext) -> GovernanceResult:
        decision_package = context.accumulated_context.get(
            "decision"
        ) or context.accumulated_context.get("decision_support")
        if decision_package is None:
            raise RuntimeError("decision output is required before governance")
        execution_requested = any(
            step.engine == "execution" for step in context.plan.pipeline.steps
        )
        action_type = (
            GovernanceActionType.EXECUTION
            if execution_requested
            else GovernanceActionType.CONTINUATION
        )
        request = GovernanceRequest(
            governance_id=context.stage.stage_id,
            session_id=context.session.session.id,
            organization_id=context.session.session.organization_id,
            plan_id=context.plan.plan_id,
            correlation_id=context.correlation_id,
            user_id=_metadata_uuid(context.safe_metadata, "user_id"),
            actor_id=_metadata_uuid(context.safe_metadata, "user_id"),
            cognitive_plan=context.plan,
            current_stage=context.stage.engine,
            requested_action="runtime_execution"
            if execution_requested
            else "runtime_continuation",
            action_type=action_type,
            decision_package=decision_package,
            execution_requested=execution_requested,
            risk_level=(
                context.plan.risk_level if execution_requested else RiskLevel.LOW
            ),
            impact_level=_impact_from_decision(decision_package)
            if execution_requested
            else ImpactLevel.LOW,
            affected_domains=(),
            applicable_policy_ids=tuple(
                context.plan.governance_requirements.policy_checks
            ),
            policy_context={
                "runtime": bool(context.safe_metadata.get("runtime")),
                "confidence_target": context.plan.confidence_target,
            },
            resources=tuple(step.engine for step in context.plan.pipeline.steps),
            reversibility=True,
            rollback_available=True,
            metadata={"adapter": type(self).__name__},
        )
        return self._engine.evaluate(request)


class ExecutionExecutor(RuntimeEngineExecutor):
    """Adapter that delegates approved action execution to ExecutionEngine."""

    def __init__(self, engine: ExecutionEngine) -> None:
        RuntimeEngineExecutor.__init__(self, "execution")
        self._engine = engine

    async def execute(self, context: EngineInvocationContext) -> EngineStageResult:
        started_at = _now()
        output = await self._engine.execute_async(self._request(context))
        completed_at = _now()
        return EngineStageResult(
            stage_id=context.stage.stage_id,
            engine=self.engine_type,
            status=StageExecutionStatus.COMPLETED,
            output=output,
            started_at=started_at,
            completed_at=completed_at,
            duration=max((completed_at - started_at).total_seconds(), 0.0),
            attempt=context.attempt,
            safe_metadata={"adapter": type(self).__name__},
        )

    def _execute(self, context: EngineInvocationContext) -> Any:
        return self._engine.execute(self._request(context))

    def _request(self, context: EngineInvocationContext) -> ExecutionRequest:
        governance = context.accumulated_context.get("governance")
        if not isinstance(governance, GovernanceResult):
            raise RuntimeError("execution requires a GovernanceResult")
        authorization = governance.authorization_decision
        if authorization is None:
            raise RuntimeError("execution requires authorization")
        if authorization.organization_id != context.session.session.organization_id:
            raise RuntimeError("authorization organization mismatch")
        if authorization.session_id != context.session.session.id:
            raise RuntimeError("authorization session mismatch")
        if authorization.plan_id != context.plan.plan_id:
            raise RuntimeError("authorization plan mismatch")
        now = _now()
        if authorization.valid_until <= now:
            raise RuntimeError("authorization is expired")
        if authorization.decision is not AuthorizationDecisionValue.AUTHORIZED:
            raise RuntimeError("authorization is not granted")
        if governance.status is not GovernanceResultStatus.AUTHORIZED:
            raise RuntimeError("governance is not authorized")
        if not governance.execution_authorized:
            raise RuntimeError("execution is not authorized")
        execution_type = ExecutionType.SYSTEM
        execution_plan = OperationalExecutionPlan(
            execution_plan_id=context.stage.stage_id,
            organization_id=context.session.session.organization_id,
            session_id=context.session.session.id,
            cognitive_plan_id=context.plan.plan_id,
            authorization_id=authorization.authorization_id,
            action_scope=authorization.action_scope,
            execution_type=execution_type,
            steps=(
                OperationalExecutionStep(
                    step_id=context.stage.stage_id,
                    order=1,
                    name="Approved dry-run execution",
                    execution_type=execution_type,
                    connector_id="memory.dry_run",
                    required_capability="dry_run",
                    action=authorization.action_scope,
                    parameters={
                        "cognitive_stage": context.stage.engine,
                    },
                    timeout_seconds=context.deadline_remaining_seconds,
                    idempotency_scope="runtime_execution_stage",
                    reason_codes=("runtime_adapter",),
                ),
            ),
            resources=(
                ResourceRequirement(
                    resource_type="connector",
                    identifier="memory.dry_run",
                ),
            ),
            maximum_duration_seconds=context.deadline_remaining_seconds,
            created_at=_now(),
            reason_codes=("runtime_adapter",),
            safe_metadata={"adapter": type(self).__name__},
        )
        execution_authorization = ExecutionAuthorization(
            authorization_id=authorization.authorization_id,
            governance_id=authorization.governance_id,
            organization_id=authorization.organization_id,
            session_id=authorization.session_id,
            plan_id=authorization.plan_id,
            execution_plan_id=execution_plan.execution_plan_id,
            action_scope=authorization.action_scope,
            approved_action=authorization.action_scope,
            allowed_execution_types=(execution_type,),
            allowed_connector_ids=("memory.dry_run",),
            allowed_capabilities=("dry_run",),
            policy_references=authorization.policy_references,
            approval_evidence=tuple(
                str(item.approval_decision_id)
                for item in (
                    governance.approval_state.decisions
                    if governance.approval_state is not None
                    else ()
                )
            ),
            valid_from=authorization.valid_from,
            valid_until=authorization.valid_until,
            execution_authorized=authorization.execution_authorized,
            live_authorized=False,
            rollback_authorized=False,
            issued_at=authorization.valid_from,
        )
        request = ExecutionRequest(
            execution_request_id=context.stage.stage_id,
            execution_id=_metadata_uuid(context.safe_metadata, "runtime_execution_id"),
            organization_id=context.session.session.organization_id,
            session_id=context.session.session.id,
            plan_id=context.plan.plan_id,
            correlation_id=context.correlation_id,
            approved_action=authorization.action_scope,
            action_scope=authorization.action_scope,
            execution_type=execution_type,
            execution_plan=execution_plan,
            authorization=execution_authorization,
            approval_evidence=execution_authorization.approval_evidence,
            policy_references=authorization.policy_references,
            required_resources=execution_plan.resources,
            dry_run=True,
            idempotency_key=(
                f"runtime:{context.session.session.id}:"
                f"{context.plan.plan_id}:{context.stage.stage_id}"
            ),
            safe_metadata={"adapter": type(self).__name__},
        )
        return request


class NoopExecutionExecutor(RuntimeEngineExecutor):
    """Explicit test double preserving the former safe no-op behavior."""

    def __init__(self) -> None:
        RuntimeEngineExecutor.__init__(self, "execution")

    def _execute(self, context: EngineInvocationContext) -> Any:
        governance = context.accumulated_context.get("governance")
        if not isinstance(governance, GovernanceResult):
            raise RuntimeError("execution requires a GovernanceResult")
        authorization = governance.authorization_decision
        if authorization is None:
            raise RuntimeError("execution requires authorization")
        return {
            "engine": self.engine_type,
            "session_id": str(context.session.session.id),
            "plan_id": str(context.plan.plan_id),
            "status": "completed",
            "authorization_id": str(authorization.authorization_id),
        }


class NoopExecutor(RuntimeEngineExecutor):
    """Executor for non-cognitive placeholder stages without external effects."""

    def __init__(self, engine_type: str) -> None:
        super().__init__(engine_type)

    def _execute(self, context: EngineInvocationContext) -> Any:
        return {
            "engine": self.engine_type,
            "session_id": str(context.session.session.id),
            "plan_id": str(context.plan.plan_id),
            "status": "completed",
        }


def _require(values: dict[str, Any], key: str) -> Any:
    value = values.get(key)
    if value is None:
        raise RuntimeError(f"{key} output is required")
    return value


def _metadata_uuid(values: dict[str, Any], key: str) -> UUID | None:
    value = values.get(key)
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError as error:
        raise RuntimeError(f"invalid {key} runtime metadata") from error


def _now() -> datetime:
    return datetime.now(UTC)


def _impact_from_decision(decision_package: DecisionPackage) -> ImpactLevel:
    value = decision_package.recommendation.expected_impact.value.lower()
    if value == "medium":
        return ImpactLevel.MODERATE
    if value == "critical":
        return ImpactLevel.CRITICAL
    if value == "high":
        return ImpactLevel.HIGH
    return ImpactLevel.LOW

"""Runtime engine executor adapters for the real Orchestrator."""

from datetime import UTC, datetime
from typing import Any

from ecos.context import ContextBuildRequest, ContextService
from ecos.debate import Debate, DebateService
from ecos.decision import DecisionContext, DecisionPackage, DecisionService
from ecos.execution import (
    ExecutionAuthorization,
    ExecutionEngine,
    ExecutionRequest,
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
from ecos.learning import LearningObject, LearningService
from ecos.memory import MemoryType
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
    """Run LearningService without allowing the Orchestrator to write memory."""

    def __init__(self, service: LearningService, engine_type: str = "memory") -> None:
        super().__init__(engine_type)
        self._service = service

    def _execute(self, context: EngineInvocationContext) -> Any:
        decision_package = context.accumulated_context.get(
            "decision"
        ) or context.accumulated_context.get("decision_support")
        if decision_package is None:
            raise RuntimeError("decision output is required before learning")
        reasoning = _require(context.accumulated_context, "reasoning")
        debate = _require(context.accumulated_context, "debate")
        recommendation = decision_package.recommendation
        return self._service.learn(
            LearningObject(
                session_id=context.session.session.id,
                memory_type=MemoryType.EPISODIC,
                title="Runtime cognitive pipeline completed",
                description=recommendation.summary,
                evidence=[reasoning.summary, *debate.recommendations],
                tags=["runtime", "demo", "cognitive-pipeline"],
                confidence=recommendation.confidence,
                origin="runtime",
                organization_id=context.session.session.organization_id,
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

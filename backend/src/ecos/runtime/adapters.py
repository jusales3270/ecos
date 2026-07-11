"""Runtime engine executor adapters for the real Orchestrator."""

from datetime import UTC, datetime
from typing import Any

from ecos.context import ContextBuildRequest, ContextService
from ecos.debate import Debate, DebateService
from ecos.decision import DecisionContext, DecisionPackage, DecisionService
from ecos.learning import LearningObject, LearningService
from ecos.memory import MemoryType
from ecos.orchestrator import (
    EngineExecutor,
    EngineInvocationContext,
    EngineStageResult,
    StageExecutionStatus,
)
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

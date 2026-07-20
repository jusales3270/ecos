"""Real deterministic ECOS Orchestrator implementation."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from ecos.domain import SessionStage
from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.governance import (
    AuthorizationDecisionValue,
    GovernanceResult,
    GovernanceResultStatus,
)
from ecos.orchestrator.exceptions import (
    ApprovalMissingError,
    AuthorizationExpiredError,
    CycleDetectedError,
    DuplicateExecutorError,
    EngineNotRegisteredError,
    ExecutorIncompatibleError,
    GovernanceMissingError,
    IncompatibleApprovalError,
    IncompatiblePlanError,
    IncompatibleSessionError,
    InvalidConditionError,
    InvalidDependencyError,
    InvalidResultError,
    InvalidRetryError,
    InvalidTimeoutError,
    OperatorNotAllowedError,
    PipelineInconsistentError,
    RequiredOutputMissingError,
    RequiredStageFailedError,
)
from ecos.orchestrator.executor import EngineExecutor
from ecos.orchestrator.models import (
    ApprovalState,
    ApprovalStatus,
    EngineInvocationContext,
    EngineStageResult,
    FailureClassification,
    FailureReport,
    GovernanceState,
    OrchestrationConfig,
    OrchestrationInput,
    OrchestrationMode,
    OrchestrationResult,
    PipelineExecutionStatus,
    ResumableOrchestrationState,
    StageExecutionStatus,
    TimelineEntry,
    TimelineEntryType,
)
from ecos.planner import CognitivePlan, PipelineStep
from ecos.session import (
    ManagedSession,
    SessionLifecycleStatus,
    SessionService,
    SessionState,
)

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]
Sleeper = Callable[[float], Awaitable[None]]
FailureClassifier = Callable[[BaseException], FailureClassification]


class Orchestrator:
    """Coordinate a valid CognitivePlan without performing cognition."""

    def __init__(
        self,
        *,
        executors: dict[str, EngineExecutor],
        event_service: EventService,
        session_service: SessionService,
        clock: Clock,
        id_generator: IdGenerator,
        sleeper: Sleeper,
        config: OrchestrationConfig,
        failure_classifier: FailureClassifier | None = None,
    ) -> None:
        """Initialize the Orchestrator with injected contracts only."""
        self._executors = self._validate_executor_registry(executors)
        self._event_service = event_service
        self._session_service = session_service
        self._clock = clock
        self._id_generator = id_generator
        self._sleeper = sleeper
        self._config = config
        self._failure_classifier = failure_classifier or self._classify_failure

    def execute(self, orchestration_input: OrchestrationInput) -> OrchestrationResult:
        """Execute orchestration synchronously for current runtime callers."""
        return asyncio.run(self.execute_async(orchestration_input))

    def resume(
        self,
        orchestration_input: OrchestrationInput,
        resumable_state: ResumableOrchestrationState,
    ) -> OrchestrationResult:
        """Resume orchestration synchronously from a validated durable checkpoint."""
        return asyncio.run(self.resume_async(orchestration_input, resumable_state))

    async def execute_async(
        self,
        orchestration_input: OrchestrationInput,
    ) -> OrchestrationResult:
        """Execute a CognitivePlan through injected engine executors."""
        execution_id = self._id_generator()
        started_at = self._now()
        state = _RuntimeState(
            execution_id=execution_id,
            orchestration_input=orchestration_input,
            started_at=started_at,
        )
        self._timeline(state, TimelineEntryType.PIPELINE, "validating")
        self._publish(orchestration_input, EventType.PIPELINE_VALIDATION_STARTED)
        try:
            stages = self._validate_input(orchestration_input)
            self._timeline(state, TimelineEntryType.PIPELINE, "running")
            self._publish(orchestration_input, EventType.PIPELINE_STARTED)
            self._sync_session(
                orchestration_input.active_session,
                SessionLifecycleStatus.EXECUTING,
                self._session_stage(stages[0].engine),
                stages[0].engine,
                0.0,
            )
            result = await self._run_ready_stages(state, stages)
            return result
        except Exception as error:
            if isinstance(error, (ApprovalMissingError, GovernanceMissingError)):
                return self._waiting_approval_result(state, error)
            failure = self._failure_report(
                state,
                error,
                classification=self._failure_classifier(error),
                pipeline_status=PipelineExecutionStatus.FAILED,
            )
            self._timeline(state, TimelineEntryType.FAILURE, "failed")
            self._publish(orchestration_input, EventType.PIPELINE_FAILED)
            self._sync_session(
                orchestration_input.active_session,
                SessionLifecycleStatus.FAILED,
                SessionStage.CONTEXT,
                None,
                1.0,
                last_error=failure.safe_message,
            )
            completed_at = self._now()
            return self._build_result(
                state,
                PipelineExecutionStatus.FAILED,
                completed_at,
                failure_report=failure,
            )

    async def resume_async(
        self,
        orchestration_input: OrchestrationInput,
        resumable_state: ResumableOrchestrationState,
    ) -> OrchestrationResult:
        """Resume orchestration from returned state after explicit approval."""
        self._validate_resume(orchestration_input, resumable_state)
        state = _RuntimeState(
            execution_id=resumable_state.execution_id,
            orchestration_input=orchestration_input,
            started_at=resumable_state.created_at,
            timeline=list(resumable_state.timeline),
            stage_results={
                item.stage_id: item for item in resumable_state.stage_results
            },
            attempts=dict(resumable_state.attempts),
            emitted_events={
                (item.status, item.stage_id) for item in resumable_state.timeline
            },
        )
        self._publish(orchestration_input, EventType.PIPELINE_RESUMED)
        stages = self._validate_input(orchestration_input)
        return await self._run_ready_stages(state, stages)

    async def _run_ready_stages(
        self,
        state: "_RuntimeState",
        stages: tuple[PipelineStep, ...],
    ) -> OrchestrationResult:
        pending = {self._stage_id(stage) for stage in stages}
        pending.difference_update(state.stage_results)
        blocked: set[UUID] = set()
        stage_by_id = {self._stage_id(stage): stage for stage in stages}
        completed_at: datetime | None = None
        while pending:
            ready = [
                stage
                for stage in stages
                if self._stage_id(stage) in pending
                and self._dependencies(stage).issubset(state.stage_results)
                and self._stage_id(stage) not in blocked
            ]
            if not ready:
                raise PipelineInconsistentError("pipeline has no ready stage")
            if self._config.mode is OrchestrationMode.PARALLEL:
                batch = ready[: self._config.concurrency_limit]
                batch_results = await asyncio.gather(
                    *(self._execute_stage(state, stage) for stage in batch),
                    return_exceptions=True,
                )
                for item in batch_results:
                    if isinstance(item, BaseException):
                        raise item
            else:
                await self._execute_stage(state, ready[0])
            for stage_id, result in tuple(state.stage_results.items()):
                if stage_id not in pending:
                    continue
                pending.remove(stage_id)
                if result.status in {
                    StageExecutionStatus.FAILED,
                    StageExecutionStatus.TIMED_OUT,
                    StageExecutionStatus.BLOCKED,
                }:
                    stage = stage_by_id[stage_id]
                    if stage.required:
                        dependents = self._dependents(stage_id, stages)
                        blocked.update(dependents)
                        raise RequiredStageFailedError(
                            f"required stage {stage.engine} failed"
                        )
            completed_at = self._now()
        self._validate_success(state, stages)
        self._timeline(state, TimelineEntryType.COMPLETION, "completed")
        self._publish(state.orchestration_input, EventType.PIPELINE_COMPLETED)
        self._sync_session(
            state.orchestration_input.active_session,
            SessionLifecycleStatus.COMPLETED,
            self._session_stage(stages[-1].engine),
            None,
            1.0,
        )
        return self._build_result(
            state,
            PipelineExecutionStatus.COMPLETED,
            completed_at or self._now(),
        )

    async def _execute_stage(
        self,
        state: "_RuntimeState",
        stage: PipelineStep,
    ) -> None:
        stage_id = self._stage_id(stage)
        if stage_id in state.stage_results:
            return
        self._validate_governance_for_stage(state, stage)
        if stage.conditional and stage.condition is not None:
            if not self._evaluate_condition(state, stage):
                if stage.required:
                    raise InvalidConditionError(
                        "required stage condition evaluated false"
                    )
                result = self._skipped_result(stage, state, "condition_false")
                state.stage_results[stage_id] = result
                self._timeline(
                    state,
                    TimelineEntryType.STAGE,
                    "skipped",
                    stage=stage,
                    reason_code="condition_false",
                )
                self._publish(state.orchestration_input, EventType.STAGE_SKIPPED, stage)
                return
        self._timeline(state, TimelineEntryType.STAGE, "ready", stage=stage)
        self._publish(state.orchestration_input, EventType.STAGE_READY, stage)
        self._sync_session(
            state.orchestration_input.active_session,
            SessionLifecycleStatus.EXECUTING,
            self._session_stage(stage.engine),
            stage.engine,
            self._progress(state, stage),
        )
        executor = self._executors[stage.engine]
        max_attempts = stage.retry_policy.max_attempts
        if max_attempts < 1:
            raise InvalidRetryError("max_attempts must be at least one")
        last_error: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            state.attempts[stage_id] = attempt
            started_at = self._now()
            self._timeline(
                state,
                TimelineEntryType.ATTEMPT,
                "running",
                stage=stage,
                attempt=attempt,
            )
            self._publish(
                state.orchestration_input,
                EventType.ENGINE_INVOKED,
                stage,
                attempt,
            )
            try:
                timeout = self._timeout(stage)
                invocation = self._invocation_context(state, stage, attempt, timeout)
                result = await asyncio.wait_for(
                    self._call_executor(executor, invocation),
                    timeout=timeout,
                )
                self._validate_result(stage, result)
                state.stage_results[stage_id] = result
                self._timeline(
                    state,
                    TimelineEntryType.COMPLETION,
                    "completed",
                    stage=stage,
                    attempt=attempt,
                )
                self._publish(
                    state.orchestration_input,
                    EventType.ENGINE_COMPLETED,
                    stage,
                    attempt,
                )
                return
            except TimeoutError as error:
                last_error = error
                timeout_at = self._now()
                result = EngineStageResult(
                    stage_id=stage_id,
                    engine=stage.engine,
                    status=StageExecutionStatus.TIMED_OUT,
                    output=None,
                    started_at=started_at,
                    completed_at=timeout_at,
                    duration=max((timeout_at - started_at).total_seconds(), 0.0),
                    attempt=attempt,
                    warnings=("stage timed out",),
                    safe_metadata={
                        "classification": FailureClassification.TIMEOUT.value
                    },
                )
                state.stage_results[stage_id] = result
                self._publish(
                    state.orchestration_input,
                    EventType.ENGINE_TIMED_OUT,
                    stage,
                    attempt,
                )
                break
            except Exception as error:
                last_error = error
                classification = self._failure_classifier(error)
                self._publish(
                    state.orchestration_input,
                    EventType.ENGINE_FAILED,
                    stage,
                    attempt,
                )
                if not self._should_retry(stage, attempt, classification):
                    break
                self._timeline(
                    state,
                    TimelineEntryType.ATTEMPT,
                    "retrying",
                    stage=stage,
                    attempt=attempt,
                )
                self._publish(
                    state.orchestration_input,
                    EventType.ENGINE_RETRYING,
                    stage,
                    attempt,
                )
                await self._sleeper(float(stage.retry_policy.backoff_seconds))
        if stage.optional and stage.engine != "execution":
            skipped = self._skipped_result(stage, state, "optional_stage_failed")
            state.stage_results[stage_id] = skipped
            self._publish(state.orchestration_input, EventType.STAGE_SKIPPED, stage)
            return
        if last_error is not None:
            raise RequiredStageFailedError(
                f"required stage {stage.engine} failed: {last_error}"
            ) from last_error
        raise RequiredStageFailedError(f"required stage {stage.engine} failed")

    async def _call_executor(
        self,
        executor: EngineExecutor,
        context: EngineInvocationContext,
    ) -> EngineStageResult:
        result = executor.execute(context)
        if inspect.isawaitable(result):
            return await result
        return result

    def _validate_executor_registry(
        self,
        executors: dict[str, EngineExecutor],
    ) -> dict[str, EngineExecutor]:
        registry: dict[str, EngineExecutor] = {}
        for name, executor in executors.items():
            engine_type = executor.engine_type.strip()
            if name != engine_type:
                raise ExecutorIncompatibleError("executor key and engine_type differ")
            if engine_type in registry:
                raise DuplicateExecutorError(f"duplicate executor for {engine_type}")
            registry[engine_type] = executor
        return registry

    def _validate_input(
        self,
        orchestration_input: OrchestrationInput,
    ) -> tuple[PipelineStep, ...]:
        plan = orchestration_input.cognitive_plan
        session = orchestration_input.active_session
        if plan.plan_id is None:
            raise IncompatiblePlanError("plan_id is required")
        if plan.session_id != orchestration_input.session_id:
            raise IncompatiblePlanError("plan session_id mismatch")
        if plan.organization_id != orchestration_input.organization_id:
            raise IncompatiblePlanError("plan organization_id mismatch")
        if session.session.id != orchestration_input.session_id:
            raise IncompatibleSessionError("active session_id mismatch")
        if session.session.organization_id != orchestration_input.organization_id:
            raise IncompatibleSessionError("active session organization mismatch")
        stages = tuple(plan.pipeline.steps if plan.pipeline else plan.stages)
        if not stages:
            raise IncompatiblePlanError("plan pipeline cannot be empty")
        ids = [self._stage_id(stage) for stage in stages]
        if len(ids) != len(set(ids)):
            raise InvalidDependencyError("duplicate stage identifier")
        engines = [stage.engine for stage in stages]
        if len(engines) != len(set(zip(ids, engines, strict=False))):
            raise InvalidDependencyError("duplicate stage")
        for stage in stages:
            if stage.engine not in self._executors:
                raise EngineNotRegisteredError(f"engine not registered: {stage.engine}")
            if not self._executors[stage.engine].available:
                raise EngineNotRegisteredError(f"engine unavailable: {stage.engine}")
            self._timeout(stage)
            if stage.retry_policy.max_attempts < 1:
                raise InvalidRetryError("max_attempts must be at least one")
            for dependency in self._dependencies(stage):
                if dependency not in ids:
                    raise InvalidDependencyError("stage depends on unknown stage")
                if dependency == self._stage_id(stage):
                    raise InvalidDependencyError("stage cannot depend on itself")
        self._validate_dag(stages)
        self._validate_required_order(stages)
        return tuple(
            sorted(
                stages,
                key=lambda item: (item.order, str(self._stage_id(item))),
            )
        )

    def _validate_dag(self, stages: tuple[PipelineStep, ...]) -> None:
        visiting: set[UUID] = set()
        visited: set[UUID] = set()
        stage_by_id = {self._stage_id(stage): stage for stage in stages}

        def visit(stage_id: UUID) -> None:
            if stage_id in visited:
                return
            if stage_id in visiting:
                raise CycleDetectedError("stage dependency cycle detected")
            visiting.add(stage_id)
            for dependency in self._dependencies(stage_by_id[stage_id]):
                visit(dependency)
            visiting.remove(stage_id)
            visited.add(stage_id)

        for stage in stages:
            visit(self._stage_id(stage))

    def _validate_required_order(self, stages: tuple[PipelineStep, ...]) -> None:
        order = {stage.engine: stage.order for stage in stages}
        required_pairs = (
            ("context", "reasoning"),
            ("reasoning", "debate"),
            ("debate", "simulation"),
            ("simulation", "decision_support"),
            ("governance", "execution"),
            ("execution", "observation"),
            ("observation", "learning"),
        )
        aliases = {"decision": "decision_support", "memory": "learning"}
        normalized = {
            aliases.get(engine, engine): value for engine, value in order.items()
        }
        for before, after in required_pairs:
            if (
                before in normalized
                and after in normalized
                and normalized[before] > normalized[after]
            ):
                raise InvalidDependencyError(f"{before} must precede {after}")

    def _validate_governance_for_stage(
        self,
        state: "_RuntimeState",
        stage: PipelineStep,
    ) -> None:
        if stage.engine != "execution":
            return
        orchestration_input = state.orchestration_input
        plan = orchestration_input.cognitive_plan
        governance_result = self._governance_result_from_outputs(state)
        if governance_result is not None:
            self._validate_governance_result_for_execution(
                governance_result,
                plan,
                self._now(),
            )
            return
        governance_required = plan.governance_requirements.governance_required
        approval_required = (
            plan.approval_requirements.required
            or plan.governance_requirements.approval_required
            or plan.governance_requirements.execution_blocked_until_approval
        )
        if governance_required and not self._governance_satisfied(
            orchestration_input.governance_state,
            plan,
        ):
            self._timeline(
                state,
                TimelineEntryType.BLOCK,
                "governance_missing",
                stage=stage,
            )
            self._publish(orchestration_input, EventType.PIPELINE_BLOCKED, stage)
            raise GovernanceMissingError("execution requires completed governance")
        if approval_required:
            self._validate_approval(
                orchestration_input.approval_state,
                plan,
                self._now(),
            )

    def _governance_result_from_outputs(
        self,
        state: "_RuntimeState",
    ) -> GovernanceResult | None:
        initial = state.orchestration_input.initial_inputs.get("governance")
        if isinstance(initial, GovernanceResult):
            return initial
        for result in state.stage_results.values():
            if result.engine == "governance" and isinstance(
                result.output,
                GovernanceResult,
            ):
                return result.output
        return None

    def _validate_governance_result_for_execution(
        self,
        governance: GovernanceResult,
        plan: CognitivePlan,
        now: datetime,
    ) -> None:
        authorization = governance.authorization_decision
        if authorization is None:
            raise GovernanceMissingError("execution requires authorization")
        if (
            governance.organization_id != plan.organization_id
            or governance.session_id != plan.session_id
            or governance.plan_id != plan.plan_id
        ):
            raise GovernanceMissingError("governance result scope is incompatible")
        if (
            authorization.organization_id != plan.organization_id
            or authorization.session_id != plan.session_id
            or authorization.plan_id != plan.plan_id
        ):
            raise IncompatibleApprovalError("authorization scope is incompatible")
        if authorization.valid_until <= now:
            raise AuthorizationExpiredError("authorization is expired")
        if governance.status is GovernanceResultStatus.AWAITING_APPROVAL:
            raise ApprovalMissingError("governance is awaiting approval")
        if governance.status is GovernanceResultStatus.REVIEW_REQUIRED:
            raise ApprovalMissingError("governance requires human review")
        if governance.status is GovernanceResultStatus.DENIED:
            raise GovernanceMissingError("governance denied execution")
        if authorization.decision is not AuthorizationDecisionValue.AUTHORIZED:
            raise ApprovalMissingError("authorization is not granted")
        if not governance.execution_authorized:
            raise ApprovalMissingError("execution authorization is not granted")

    def _validate_approval(
        self,
        approval: ApprovalState,
        plan: CognitivePlan,
        now: datetime,
    ) -> None:
        if approval.status in {ApprovalStatus.UNKNOWN, ApprovalStatus.MISSING}:
            raise ApprovalMissingError("execution requires explicit human approval")
        if approval.status is ApprovalStatus.DENIED:
            raise ApprovalMissingError("execution approval was denied")
        if approval.status is ApprovalStatus.EXPIRED:
            raise AuthorizationExpiredError("execution approval is expired")
        if approval.status is not ApprovalStatus.APPROVED:
            raise ApprovalMissingError("execution approval is not granted")
        if (
            approval.organization_id != plan.organization_id
            or approval.session_id != plan.session_id
            or approval.plan_id != plan.plan_id
        ):
            raise IncompatibleApprovalError("approval identity is incompatible")
        if approval.expires_at is not None and approval.expires_at <= now:
            raise AuthorizationExpiredError("execution approval is expired")

    def _governance_satisfied(
        self,
        governance: GovernanceState | None,
        plan: CognitivePlan,
    ) -> bool:
        return (
            governance is not None
            and governance.satisfied
            and not governance.blocked
            and governance.organization_id == plan.organization_id
            and governance.session_id == plan.session_id
            and governance.plan_id == plan.plan_id
        )

    def _evaluate_condition(
        self,
        state: "_RuntimeState",
        stage: PipelineStep,
    ) -> bool:
        condition = stage.condition
        if condition is None:
            return True
        operator = condition.type
        requirements = condition.requirements
        if operator == "governance_approval":
            governance = self._governance_result_from_outputs(state)
            return (
                state.orchestration_input.approval_state.status
                is ApprovalStatus.APPROVED
                and governance is not None
                and governance.status is GovernanceResultStatus.AUTHORIZED
                and governance.execution_authorized
            )
        if operator not in _ALLOWED_OPERATORS:
            raise OperatorNotAllowedError(f"condition operator not allowed: {operator}")
        if operator in {"all", "any"}:
            values = [
                self._truthy(self._resolve_condition_value(state, item))
                for item in requirements
            ]
            return all(values) if operator == "all" else any(values)
        if operator == "not":
            if len(requirements) != 1:
                raise InvalidConditionError("not condition requires one operand")
            return not self._truthy(
                self._resolve_condition_value(state, requirements[0])
            )
        if operator in {"exists", "not_exists"}:
            if len(requirements) != 1:
                raise InvalidConditionError("exists condition requires one operand")
            exists = (
                self._resolve_condition_value(
                    state,
                    requirements[0],
                    missing=None,
                )
                is not None
            )
            return exists if operator == "exists" else not exists
        if len(requirements) != 2:
            raise InvalidConditionError("comparison conditions require two operands")
        left = self._resolve_condition_value(state, requirements[0])
        right = self._resolve_condition_value(state, requirements[1])
        if operator == "equals":
            return left == right
        if operator == "not_equals":
            return left != right
        if operator == "greater_than":
            return left > right
        if operator == "greater_than_or_equal":
            return left >= right
        if operator == "less_than":
            return left < right
        if operator == "less_than_or_equal":
            return left <= right
        if operator == "in":
            return left in right
        if operator == "not_in":
            return left not in right
        raise OperatorNotAllowedError(f"condition operator not allowed: {operator}")

    def _resolve_condition_value(
        self,
        state: "_RuntimeState",
        token: str,
        *,
        missing: object = ...,
    ) -> object:
        if token.startswith("literal:"):
            return token.removeprefix("literal:")
        if token.startswith("number:"):
            return float(token.removeprefix("number:"))
        if token == "approval_state.status":
            return state.orchestration_input.approval_state.status.value
        if token == "governance_state.satisfied":
            governance = state.orchestration_input.governance_state
            return False if governance is None else governance.satisfied
        if token.startswith("metadata."):
            key = token.removeprefix("metadata.")
            return state.orchestration_input.safe_metadata.get(key, missing)
        if token.startswith("status."):
            stage_id = UUID(token.removeprefix("status."))
            result = state.stage_results.get(stage_id)
            return missing if result is None else result.status.value
        if token.startswith("outputs."):
            _, raw_stage_id, *path = token.split(".")
            output = state.stage_results.get(UUID(raw_stage_id))
            value = None if output is None else output.output
            for part in path:
                if isinstance(value, dict):
                    value = value.get(part, missing)
                else:
                    value = getattr(value, part, missing)
                if value is missing:
                    break
            return value
        return token

    def _truthy(self, value: object) -> bool:
        return bool(value)

    def _timeout(self, stage: PipelineStep) -> float:
        timeout = float(stage.timeout_seconds or self._config.default_timeout_seconds)
        if timeout <= 0:
            raise InvalidTimeoutError("stage timeout must be positive")
        return timeout

    def _should_retry(
        self,
        stage: PipelineStep,
        attempt: int,
        classification: FailureClassification,
    ) -> bool:
        return (
            classification is FailureClassification.RECOVERABLE
            and attempt < stage.retry_policy.max_attempts
        )

    def _validate_result(self, stage: PipelineStep, result: EngineStageResult) -> None:
        if result.stage_id != self._stage_id(stage) or result.engine != stage.engine:
            raise ExecutorIncompatibleError("executor returned incompatible result")
        if result.status is not StageExecutionStatus.COMPLETED:
            raise InvalidResultError("executor did not complete the stage")
        if stage.required and result.output is None:
            raise RequiredOutputMissingError("required stage output is missing")
        if stage.engine == "execution":
            output_status = getattr(result.output, "status", None)
            output_status_value = getattr(output_status, "value", output_status)
            if output_status_value is not None and output_status_value != "completed":
                raise InvalidResultError("execution engine did not complete")

    def _validate_success(
        self,
        state: "_RuntimeState",
        stages: tuple[PipelineStep, ...],
    ) -> None:
        for stage in stages:
            result = state.stage_results.get(self._stage_id(stage))
            if result is None:
                raise PipelineInconsistentError("stage was not executed")
            if stage.required and result.status is not StageExecutionStatus.COMPLETED:
                raise PipelineInconsistentError("required stage is not completed")
            if not stage.required and result.status not in {
                StageExecutionStatus.COMPLETED,
                StageExecutionStatus.SKIPPED,
            }:
                raise PipelineInconsistentError("optional stage is inconsistent")
            if not self._dependencies(stage).issubset(state.stage_results):
                raise PipelineInconsistentError("stage dependencies are not satisfied")

    def _validate_resume(
        self,
        orchestration_input: OrchestrationInput,
        state: ResumableOrchestrationState,
    ) -> None:
        if state.pipeline_status is not PipelineExecutionStatus.WAITING_APPROVAL:
            raise IncompatiblePlanError("resume state is not waiting for approval")
        if state.plan_id != orchestration_input.cognitive_plan.plan_id:
            raise IncompatiblePlanError("resume plan mismatch")
        if state.session_id != orchestration_input.session_id:
            raise IncompatibleSessionError("resume session mismatch")
        if state.organization_id != orchestration_input.organization_id:
            raise IncompatibleSessionError("resume organization mismatch")
        if state.correlation_id != orchestration_input.correlation_id:
            raise IncompatibleSessionError("resume correlation mismatch")
        stage_results = {item.stage_id: item for item in state.stage_results}
        if len(stage_results) != len(state.stage_results):
            raise PipelineInconsistentError("resume state has duplicate stage results")
        if set(state.completed_stage_ids) != set(stage_results):
            raise PipelineInconsistentError("resume completed stages are inconsistent")
        stages = tuple(
            orchestration_input.cognitive_plan.pipeline.steps
            if orchestration_input.cognitive_plan.pipeline
            else orchestration_input.cognitive_plan.stages
        )
        execution_stage_ids = {
            self._stage_id(stage) for stage in stages if stage.engine == "execution"
        }
        if state.blocked_stage not in execution_stage_ids:
            raise PipelineInconsistentError("resume blocked stage is not execution")
        if state.blocked_stage in stage_results:
            raise PipelineInconsistentError(
                "blocked execution stage is already completed"
            )

    def _waiting_approval_result(
        self,
        state: "_RuntimeState",
        error: Exception,
    ) -> OrchestrationResult:
        orchestration_input = state.orchestration_input
        self._timeline(state, TimelineEntryType.BLOCK, "waiting_approval")
        self._publish(orchestration_input, EventType.PIPELINE_WAITING_APPROVAL)
        self._sync_session(
            orchestration_input.active_session,
            SessionLifecycleStatus.PAUSED,
            SessionStage.APPROVAL,
            None,
            0.0,
        )
        now = self._now()
        blocked_stage = next(
            (
                item.stage_id
                for item in reversed(state.timeline)
                if item.entry_type is TimelineEntryType.BLOCK
                and item.engine == "execution"
            ),
            next(
                (
                    self._stage_id(stage)
                    for stage in orchestration_input.cognitive_plan.pipeline.steps
                    if stage.engine == "execution"
                    and self._stage_id(stage) not in state.stage_results
                ),
                None,
            ),
        )
        resumable = ResumableOrchestrationState(
            execution_id=state.execution_id,
            plan_id=orchestration_input.cognitive_plan.plan_id,
            session_id=orchestration_input.session_id,
            organization_id=orchestration_input.organization_id,
            correlation_id=orchestration_input.correlation_id,
            pipeline_status=PipelineExecutionStatus.WAITING_APPROVAL,
            blocked_stage=blocked_stage,
            completed_stage_ids=tuple(state.stage_results),
            stage_results=tuple(state.stage_results.values()),
            attempts=state.attempts,
            timeline=tuple(state.timeline),
            approval_required=True,
            governance_required=orchestration_input.cognitive_plan.governance_requirements.governance_required,
            created_at=state.started_at,
            updated_at=now,
        )
        failure = self._failure_report(
            state,
            error,
            classification=FailureClassification.APPROVAL
            if isinstance(error, ApprovalMissingError)
            else FailureClassification.GOVERNANCE,
            pipeline_status=PipelineExecutionStatus.WAITING_APPROVAL,
            human_escalation_required=True,
        )
        return self._build_result(
            state,
            PipelineExecutionStatus.WAITING_APPROVAL,
            now,
            failure_report=failure,
            resumable_state=resumable,
        )

    def _build_result(
        self,
        state: "_RuntimeState",
        status: PipelineExecutionStatus,
        completed_at: datetime,
        *,
        failure_report: FailureReport | None = None,
        resumable_state: ResumableOrchestrationState | None = None,
    ) -> OrchestrationResult:
        orchestration_input = state.orchestration_input
        ordered = tuple(
            sorted(
                state.stage_results.values(),
                key=lambda item: self._stage_order(
                    orchestration_input.cognitive_plan,
                    item.stage_id,
                ),
            )
        )
        return OrchestrationResult(
            execution_id=state.execution_id,
            plan_id=orchestration_input.cognitive_plan.plan_id,
            session_id=orchestration_input.session_id,
            organization_id=orchestration_input.organization_id,
            correlation_id=orchestration_input.correlation_id,
            status=status,
            started_at=state.started_at,
            completed_at=completed_at,
            duration=max((completed_at - state.started_at).total_seconds(), 0.0),
            stage_results=ordered,
            outputs_by_stage={item.stage_id: item.output for item in ordered},
            outputs_by_engine={item.engine: item.output for item in ordered},
            timeline=tuple(state.timeline),
            warnings=tuple(warning for item in ordered for warning in item.warnings),
            failure_report=failure_report,
            blocked_stage=resumable_state.blocked_stage if resumable_state else None,
            approval_required=orchestration_input.cognitive_plan.approval_requirements.required,
            governance_required=orchestration_input.cognitive_plan.governance_requirements.governance_required,
            resumable_state=resumable_state,
            safe_metadata=orchestration_input.safe_metadata,
        )

    def _failure_report(
        self,
        state: "_RuntimeState",
        error: BaseException,
        *,
        classification: FailureClassification,
        pipeline_status: PipelineExecutionStatus,
        human_escalation_required: bool = False,
    ) -> FailureReport:
        return FailureReport(
            failure_id=self._id_generator(),
            session_id=state.orchestration_input.session_id,
            plan_id=state.orchestration_input.cognitive_plan.plan_id,
            classification=classification,
            recoverable=classification is FailureClassification.RECOVERABLE,
            occurred_at=self._now(),
            safe_message=str(error)[:500] or classification.value,
            cause_type=type(error).__name__,
            reason_codes=(classification.value,),
            affected_dependents=tuple(),
            pipeline_status=pipeline_status,
            human_escalation_required=human_escalation_required,
        )

    def _skipped_result(
        self,
        stage: PipelineStep,
        state: "_RuntimeState",
        reason_code: str,
    ) -> EngineStageResult:
        now = self._now()
        return EngineStageResult(
            stage_id=self._stage_id(stage),
            engine=stage.engine,
            status=StageExecutionStatus.SKIPPED,
            output=None,
            started_at=now,
            completed_at=now,
            duration=0.0,
            attempt=max(state.attempts.get(self._stage_id(stage), 1), 1),
            warnings=(reason_code,),
            safe_metadata={"reason_code": reason_code},
        )

    def _invocation_context(
        self,
        state: "_RuntimeState",
        stage: PipelineStep,
        attempt: int,
        timeout: float,
    ) -> EngineInvocationContext:
        dependencies = self._dependencies(stage)
        dependency_outputs = {
            stage_id: state.stage_results[stage_id].output for stage_id in dependencies
        }
        accumulated = {
            result.engine: result.output for result in state.stage_results.values()
        }
        accumulated.update(state.orchestration_input.initial_inputs)
        return EngineInvocationContext(
            session=state.orchestration_input.active_session,
            plan=state.orchestration_input.cognitive_plan,
            stage=stage,
            completed_dependencies=tuple(dependencies),
            dependency_outputs=dependency_outputs,
            accumulated_context=accumulated,
            correlation_id=state.orchestration_input.correlation_id,
            attempt=attempt,
            deadline_remaining_seconds=timeout,
            safe_metadata=state.orchestration_input.safe_metadata,
        )

    def _sync_session(
        self,
        session: ManagedSession,
        lifecycle_status: SessionLifecycleStatus,
        current_stage: SessionStage,
        active_engine: str | None,
        progress: float,
        *,
        last_error: str | None = None,
    ) -> None:
        state = SessionState(
            session_id=session.session.id,
            lifecycle_status=lifecycle_status,
            current_stage=current_stage,
            active_engine=active_engine,
            progress=max(0.0, min(progress, 1.0)),
            last_error=last_error,
            updated_at=self._now(),
        )
        self._session_service.update_state(state)

    def _publish(
        self,
        orchestration_input: OrchestrationInput,
        event_type: EventType,
        stage: PipelineStep | None = None,
        attempt: int | None = None,
    ) -> None:
        key = (event_type.value, self._stage_id(stage) if stage else None, attempt)
        if key in orchestration_input.safe_context.get("_emitted_events", ()):
            return
        payload = {
            "execution_id": str(orchestration_input.correlation_id),
            "plan_id": str(orchestration_input.cognitive_plan.plan_id),
            "organization_id": str(orchestration_input.organization_id),
        }
        if stage is not None:
            payload.update(
                {"stage_id": str(self._stage_id(stage)), "engine": stage.engine}
            )
        if attempt is not None:
            payload["attempt"] = attempt
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="orchestrator",
                session_id=orchestration_input.session_id,
                payload=payload,
                metadata=EventMetadata(
                    correlation_id=orchestration_input.correlation_id
                ),
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)

    def _timeline(
        self,
        state: "_RuntimeState",
        entry_type: TimelineEntryType,
        status: str,
        *,
        stage: PipelineStep | None = None,
        attempt: int | None = None,
        reason_code: str | None = None,
    ) -> None:
        state.timeline.append(
            TimelineEntry(
                sequence=len(state.timeline) + 1,
                entry_type=entry_type,
                status=status,
                occurred_at=self._now(),
                stage_id=self._stage_id(stage) if stage else None,
                engine=None if stage is None else stage.engine,
                attempt=attempt,
                reason_code=reason_code,
            )
        )

    def _classify_failure(self, error: BaseException) -> FailureClassification:
        if isinstance(error, TimeoutError):
            return FailureClassification.TIMEOUT
        if isinstance(error, (GovernanceMissingError,)):
            return FailureClassification.GOVERNANCE
        if isinstance(
            error,
            (
                ApprovalMissingError,
                IncompatibleApprovalError,
                AuthorizationExpiredError,
            ),
        ):
            return FailureClassification.APPROVAL
        if isinstance(error, (EngineNotRegisteredError,)):
            return FailureClassification.UNAVAILABLE
        if isinstance(
            error,
            (IncompatiblePlanError, IncompatibleSessionError, InvalidDependencyError),
        ):
            return FailureClassification.VALIDATION
        return FailureClassification.NON_RECOVERABLE

    def _stage_id(self, stage: PipelineStep | None) -> UUID | None:
        if stage is None:
            return None
        return stage.stage_id or stage.id

    def _dependencies(self, stage: PipelineStep) -> set[UUID]:
        return set(stage.dependencies or stage.depends_on)

    def _dependents(
        self,
        stage_id: UUID,
        stages: tuple[PipelineStep, ...],
    ) -> set[UUID]:
        return {
            self._stage_id(stage)
            for stage in stages
            if stage_id in self._dependencies(stage)
        }

    def _stage_order(self, plan: CognitivePlan, stage_id: UUID) -> tuple[int, str]:
        stages = tuple(plan.pipeline.steps if plan.pipeline else plan.stages)
        for stage in stages:
            if self._stage_id(stage) == stage_id:
                return (stage.order, str(stage_id))
        return (10_000, str(stage_id))

    def _session_stage(self, engine: str) -> SessionStage:
        return {
            "context": SessionStage.CONTEXT,
            "reasoning": SessionStage.REASONING,
            "specialists": SessionStage.REASONING,
            "debate": SessionStage.DEBATE,
            "simulation": SessionStage.SIMULATION,
            "decision": SessionStage.RECOMMENDATION,
            "decision_support": SessionStage.RECOMMENDATION,
            "governance": SessionStage.APPROVAL,
            "execution": SessionStage.EXECUTION,
            "observation": SessionStage.OBSERVATION,
            "learning": SessionStage.LEARNING,
            "memory": SessionStage.LEARNING,
        }.get(engine, SessionStage.CONTEXT)

    def _progress(self, state: "_RuntimeState", stage: PipelineStep) -> float:
        stages = tuple(
            state.orchestration_input.cognitive_plan.pipeline.steps
            if state.orchestration_input.cognitive_plan.pipeline
            else state.orchestration_input.cognitive_plan.stages
        )
        return max((stage.order - 1) / max(len(stages), 1), 0.0)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class _RuntimeState:
    def __init__(
        self,
        *,
        execution_id: UUID,
        orchestration_input: OrchestrationInput,
        started_at: datetime,
        timeline: list[TimelineEntry] | None = None,
        stage_results: dict[UUID, EngineStageResult] | None = None,
        attempts: dict[UUID, int] | None = None,
        emitted_events: set[tuple[str, UUID | None]] | None = None,
    ) -> None:
        self.execution_id = execution_id
        self.orchestration_input = orchestration_input
        self.started_at = started_at
        self.timeline = timeline or []
        self.stage_results = stage_results or {}
        self.attempts = attempts or {}
        self.emitted_events = emitted_events or set()


_ALLOWED_OPERATORS = {
    "equals",
    "not_equals",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
    "in",
    "not_in",
    "exists",
    "not_exists",
    "all",
    "any",
    "not",
}

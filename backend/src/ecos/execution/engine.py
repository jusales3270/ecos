"""Real deterministic ECOS Execution Engine."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.execution.exceptions import (
    ApprovalEvidenceMissingError,
    AuthorizationRejectedError,
    ConnectorIncompatibleError,
    ExecutionError,
    ExecutionTimeoutError,
    HumanTaskError,
    InvalidConditionError,
    InvalidExecutionPlanError,
    InvalidExecutionRequestError,
    OperatorNotAllowedError,
    RollbackUnauthorizedError,
    ValidationRuleFailedError,
)
from ecos.execution.models import (
    ConnectorInvocation,
    ConnectorResult,
    ExecutionArtifact,
    ExecutionAuthorization,
    ExecutionFailure,
    ExecutionLogEntry,
    ExecutionMetric,
    ExecutionMode,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionResult,
    ExecutionResumeState,
    ExecutionStatus,
    ExecutionStep,
    ExecutionStepResult,
    ExecutionStepStatus,
    ExecutionTimelineEntry,
    ExecutionType,
    FailureClassification,
    HumanTask,
    IdempotencyRecord,
    IdempotencyRecordStatus,
    RollbackAction,
    RollbackResult,
    StructuredCondition,
    TimelineEntryType,
)
from ecos.execution.provider import (
    HumanTaskProvider,
    IdempotencyProvider,
    deterministic_fingerprint,
)
from ecos.execution.registry import ConnectorRegistry
from ecos.execution.repository import (
    ExecutionResultConflictError,
    ExecutionResultRepository,
    InMemoryExecutionResultRepository,
)

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]
Sleeper = Callable[[float], Awaitable[None]]
FailureClassifier = Callable[[BaseException], FailureClassification]


class ExecutionEngine:
    """Execute approved operational plans through injected connectors only."""

    def __init__(
        self,
        *,
        connector_registry: ConnectorRegistry,
        idempotency_provider: IdempotencyProvider,
        human_task_provider: HumanTaskProvider,
        event_service: EventService,
        clock: Clock,
        id_generator: IdGenerator,
        sleeper: Sleeper,
        concurrency_limit: int = 1,
        default_timeout_seconds: float = 30.0,
        failure_classifier: FailureClassifier | None = None,
        result_repository: ExecutionResultRepository | None = None,
    ) -> None:
        if concurrency_limit < 1:
            raise ValueError("concurrency_limit must be at least one")
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        self._connector_registry = connector_registry
        self._idempotency = idempotency_provider
        self._human_tasks = human_task_provider
        self._event_service = event_service
        self._clock = clock
        self._id_generator = id_generator
        self._sleeper = sleeper
        self._concurrency_limit = concurrency_limit
        self._default_timeout_seconds = default_timeout_seconds
        self._failure_classifier = failure_classifier or self._classify_failure
        self._results = result_repository or InMemoryExecutionResultRepository()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute synchronously for current runtime callers."""
        return asyncio.run(self.execute_async(request))

    async def execute_async(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute an approved ExecutionRequest."""
        execution_id = request.execution_id or self._id_generator()
        canonical = self._results.get(request.organization_id, execution_id)
        if canonical is not None:
            self._validate_canonical_result(request, canonical)
            return canonical
        started_at = self._now()
        state = _ExecutionRuntimeState(
            execution_id=execution_id,
            request=request,
            started_at=started_at,
        )
        self._timeline(state, TimelineEntryType.EXECUTION, "planned")
        self._publish(state, EventType.EXECUTION_PLANNED)
        try:
            self._timeline(state, TimelineEntryType.EXECUTION, "validating")
            self._publish(state, EventType.EXECUTION_VALIDATION_STARTED)
            self._validate_request(request)
            root_record = self._reserve_idempotency(
                request.idempotency_key,
                request,
                execution_id,
                None,
            )
            if root_record.status is IdempotencyRecordStatus.COMPLETED and isinstance(
                root_record.result, ExecutionResult
            ):
                self._timeline(state, TimelineEntryType.EXECUTION, "idempotency_hit")
                self._publish(state, EventType.IDEMPOTENCY_HIT)
                return root_record.result
            waiting = self._waiting_for_window(request)
            if waiting is not None:
                return self._waiting_result(state, waiting)
            self._validate_authorization(request.authorization, request)
            self._publish(state, EventType.EXECUTION_AUTHORIZATION_VALIDATED)
            self._publish(state, EventType.PRIVILEGED_EXECUTION_REQUESTED)
            result = await self._run_plan(state)
            if result.status is ExecutionStatus.COMPLETED:
                self._idempotency.complete(request.idempotency_key, result, self._now())
            else:
                self._idempotency.fail(request.idempotency_key, self._now())
            return result
        except Exception as error:
            if self._idempotency.get(request.idempotency_key) is not None:
                self._idempotency.fail(request.idempotency_key, self._now())
            if isinstance(error, AuthorizationRejectedError):
                self._publish(state, EventType.EXECUTION_AUTHORIZATION_REJECTED)
            failure = self._failure(state, error)
            state.failures.append(failure)
            self._timeline(state, TimelineEntryType.FAILURE, "failed")
            result = self._build_result(state, ExecutionStatus.FAILED, self._now())
            event = self._terminal_event(state, EventType.EXECUTION_FAILED, result)
            canonical = self._results.save_terminal(result, event)
            if not self._results.supports_transactional_outbox:
                self._event_service.publish(event)
            return canonical

    async def resume_async(self, request: ExecutionRequest) -> ExecutionResult:
        """Resume from a returned ExecutionResumeState."""
        if request.resume_state is None:
            raise HumanTaskError("resume_state is required")
        state_value = request.resume_state
        if state_value.execution_plan_id != request.execution_plan.execution_plan_id:
            raise InvalidExecutionRequestError("resume execution plan mismatch")
        if state_value.organization_id != request.organization_id:
            raise InvalidExecutionRequestError("resume organization mismatch")
        if state_value.session_id != request.session_id:
            raise InvalidExecutionRequestError("resume session mismatch")
        if state_value.plan_id != request.plan_id:
            raise InvalidExecutionRequestError("resume plan mismatch")
        execution_id = state_value.execution_id
        canonical = self._results.get(request.organization_id, execution_id)
        if canonical is not None:
            self._validate_canonical_result(request, canonical)
            return canonical
        state = _ExecutionRuntimeState(
            execution_id=execution_id,
            request=request,
            started_at=state_value.created_at,
            timeline=list(state_value.timeline),
            artifacts=list(state_value.artifacts),
            human_tasks=list(state_value.human_tasks),
            outputs=dict(state_value.outputs),
            attempts=dict(state_value.attempts),
        )
        self._publish(state, EventType.EXECUTION_RESUMED)
        self._validate_request(request)
        return await self._run_plan(state)

    async def _run_plan(self, state: "_ExecutionRuntimeState") -> ExecutionResult:
        request = state.request
        steps = self._validate_plan(request.execution_plan)
        pending = {step.step_id for step in steps}
        pending.difference_update(state.outputs)
        paused = (
            set(state.request.resume_state.paused_steps)
            if state.request.resume_state
            else set()
        )
        step_by_id = {step.step_id: step for step in steps}
        while pending:
            ready = [
                step
                for step in steps
                if step.step_id in pending
                and set(step.dependencies).issubset(state.outputs)
                and step.step_id not in paused
            ]
            if not ready and paused:
                return self._paused_result(state, tuple(paused))
            if not ready:
                raise InvalidExecutionPlanError("execution plan has no ready step")
            batch = ready[: self._concurrency_limit]
            results = await asyncio.gather(
                *(self._execute_step(state, step) for step in batch),
                return_exceptions=True,
            )
            for item in results:
                if isinstance(item, BaseException):
                    await self._maybe_rollback(state, step_by_id, item)
                    raise item
            for step in batch:
                if step.step_id in pending and step.step_id in state.step_results:
                    result = state.step_results[step.step_id]
                    if result.status in {
                        ExecutionStepStatus.COMPLETED,
                        ExecutionStepStatus.SKIPPED,
                    }:
                        pending.remove(step.step_id)
                    elif result.status is ExecutionStepStatus.PAUSED:
                        paused.add(step.step_id)
        self._validate_success(state, steps)
        self._timeline(state, TimelineEntryType.EXECUTION, "completed")
        result = self._build_result(state, ExecutionStatus.COMPLETED, self._now())
        event = self._terminal_event(state, EventType.EXECUTION_COMPLETED, result)
        canonical = self._results.save_terminal(result, event)
        if not self._results.supports_transactional_outbox:
            self._event_service.publish(event)
        return canonical

    async def _execute_step(
        self,
        state: "_ExecutionRuntimeState",
        step: ExecutionStep,
    ) -> None:
        if step.step_id in state.outputs:
            return
        if not self._preconditions_pass(state, step):
            if step.required:
                raise InvalidConditionError("required precondition evaluated false")
            self._skip_step(state, step, "precondition_false")
            return
        if step.execution_type is ExecutionType.HUMAN:
            self._create_human_task(state, step)
            return
        connector = self._connector_registry.select(
            step,
            state.request.authorization,
            self._mode(state.request),
        )
        self._timeline(
            state,
            TimelineEntryType.CONNECTOR,
            "selected",
            step=step,
            connector_id=connector.safe_descriptor.connector_id,
        )
        self._publish(state, EventType.CONNECTOR_SELECTED, step)
        timeout = step.timeout_seconds or self._default_timeout_seconds
        last_error: BaseException | None = None
        candidates = (
            connector.safe_descriptor.connector_id,
            *step.fallback_connector_ids,
        )
        for connector_id in candidates:
            selected = self._connector_registry.select(
                step,
                state.request.authorization,
                self._mode(state.request),
                fallback_ids=(connector_id,),
            )
            for attempt in range(1, step.retry_policy.max_attempts + 1):
                state.attempts[step.step_id] = attempt
                started_at = self._now()
                self._timeline(
                    state,
                    TimelineEntryType.ATTEMPT,
                    "running",
                    step=step,
                    connector_id=selected.safe_descriptor.connector_id,
                    attempt=attempt,
                )
                invocation = self._invocation(
                    state, step, selected.safe_descriptor.connector_id, attempt
                )
                try:
                    step_key = self._step_key(state.request, step)
                    record = (
                        self._idempotency.get(step_key)
                        if step_key in state.reserved_idempotency_keys
                        else self._reserve_idempotency(
                            step_key,
                            invocation,
                            state.execution_id,
                            step.step_id,
                        )
                    )
                    if (
                        step_key not in state.reserved_idempotency_keys
                        and record is not None
                        and record.status is IdempotencyRecordStatus.COMPLETED
                        and isinstance(
                            record.result,
                            ExecutionStepResult,
                        )
                    ):
                        state.step_results[step.step_id] = record.result
                        state.outputs[step.step_id] = record.result.output
                        self._publish(state, EventType.IDEMPOTENCY_HIT, step)
                        return
                    state.reserved_idempotency_keys.add(step_key)
                    self._publish(state, EventType.CONNECTOR_INVOKED, step)
                    connector_result = await asyncio.wait_for(
                        selected.execute(invocation),
                        timeout=timeout,
                    )
                    result = self._step_result(
                        state,
                        step,
                        selected.safe_descriptor.connector_id,
                        connector_result,
                        started_at,
                        attempt,
                    )
                    self._validate_connector_result(state, step, result)
                    state.step_results[step.step_id] = result
                    state.outputs[step.step_id] = result.output
                    state.artifacts.extend(result.artifacts)
                    self._idempotency.complete(step_key, result, self._now())
                    self._timeline(
                        state, TimelineEntryType.STEP, "completed", step=step
                    )
                    self._publish(state, EventType.STEP_COMPLETED, step)
                    return
                except TimeoutError:
                    last_error = ExecutionTimeoutError("execution step timed out")
                    self._publish(state, EventType.STEP_TIMED_OUT, step)
                    if attempt >= step.retry_policy.max_attempts:
                        break
                    self._publish(state, EventType.STEP_RETRYING, step)
                    await self._sleeper(float(step.retry_policy.backoff_seconds))
                except Exception as error:
                    last_error = error
                    classification = self._failure_classifier(error)
                    self._publish(state, EventType.CONNECTOR_FAILED, step)
                    if classification is not FailureClassification.RECOVERABLE:
                        break
                    if attempt >= step.retry_policy.max_attempts:
                        break
                    self._publish(state, EventType.STEP_RETRYING, step)
                    await self._sleeper(float(step.retry_policy.backoff_seconds))
            if last_error is not None and self._can_fallback(
                last_error, step, connector_id
            ):
                self._publish(state, EventType.CONNECTOR_FALLBACK_SELECTED, step)
                continue
            break
        failure = self._failure(
            state, last_error or ExecutionError("step failed"), step
        )
        result = ExecutionStepResult(
            step_id=step.step_id,
            connector_id=connector.safe_descriptor.connector_id,
            status=ExecutionStepStatus.FAILED,
            started_at=self._now(),
            completed_at=self._now(),
            duration=0.0,
            attempts=state.attempts.get(step.step_id, 1),
            failure=failure,
        )
        state.step_results[step.step_id] = result
        state.failures.append(failure)
        self._publish(state, EventType.STEP_FAILED, step)
        if step.required:
            raise last_error or ExecutionError("required execution step failed")

    async def _maybe_rollback(
        self,
        state: "_ExecutionRuntimeState",
        step_by_id: dict[UUID, ExecutionStep],
        original_error: BaseException,
    ) -> None:
        if not state.request.rollback_required:
            return
        if not state.request.authorization.rollback_authorized:
            raise RollbackUnauthorizedError(
                "rollback is not authorized"
            ) from original_error
        self._publish(state, EventType.ROLLBACK_STARTED)
        completed = [
            step_by_id[step_id]
            for step_id, result in state.step_results.items()
            if result.status is ExecutionStepStatus.COMPLETED
        ]
        for step in sorted(
            completed, key=lambda item: (-item.order, str(item.step_id))
        ):
            if step.rollback_action is None:
                continue
            rollback = await self._rollback_step(state, step.rollback_action)
            state.rollback_results.append(rollback)
            if rollback.status is ExecutionStepStatus.ROLLED_BACK:
                self._publish(state, EventType.ROLLBACK_STEP_COMPLETED)
            else:
                self._publish(state, EventType.ROLLBACK_STEP_FAILED)
        if all(
            item.status is ExecutionStepStatus.ROLLED_BACK
            for item in state.rollback_results
        ):
            self._publish(state, EventType.EXECUTION_ROLLED_BACK)
        elif state.rollback_results:
            self._publish(state, EventType.ROLLBACK_FAILED)

    async def _rollback_step(
        self,
        state: "_ExecutionRuntimeState",
        action: RollbackAction,
    ) -> RollbackResult:
        started_at = self._now()
        connector = self._connector_registry.get(action.connector_id)
        invocation = ConnectorInvocation(
            invocation_id=self._id_generator(),
            execution_id=state.execution_id,
            execution_request_id=state.request.execution_request_id,
            organization_id=state.request.organization_id,
            session_id=state.request.session_id,
            plan_id=state.request.plan_id,
            execution_plan_id=state.request.execution_plan.execution_plan_id,
            step_id=action.original_step_id,
            connector_id=action.connector_id,
            execution_type=state.request.execution_type,
            action=action.action,
            parameters=action.parameters,
            mode=self._mode(state.request),
            idempotency_key=action.idempotency_key,
            attempt=1,
        )
        try:
            result = await asyncio.wait_for(
                connector.rollback(invocation),
                timeout=action.timeout_seconds,
            )
            status = result.status
            failure = None
        except Exception as error:
            status = ExecutionStepStatus.ROLLBACK_FAILED
            failure = self._failure(state, error)
        completed_at = self._now()
        return RollbackResult(
            rollback_action_id=action.rollback_action_id,
            original_step_id=action.original_step_id,
            connector_id=action.connector_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration=max((completed_at - started_at).total_seconds(), 0.0),
            attempts=1,
            failure=failure,
        )

    def _validate_request(self, request: ExecutionRequest) -> None:
        if request.rollback_required and not any(
            step.rollback_action is not None for step in request.execution_plan.steps
        ):
            raise InvalidExecutionRequestError("rollback is required but undefined")
        if request.authorization.approval_evidence and not request.approval_evidence:
            raise ApprovalEvidenceMissingError("approval evidence is required")
        if not request.required_resources and not request.execution_plan.resources:
            raise InvalidExecutionRequestError("declared resources are required")
        self._validate_plan(request.execution_plan)

    def _validate_authorization(
        self,
        authorization: ExecutionAuthorization,
        request: ExecutionRequest,
    ) -> None:
        now = self._now()
        if authorization.denied:
            raise AuthorizationRejectedError("authorization is denied")
        if authorization.revoked:
            raise AuthorizationRejectedError("authorization is revoked")
        if authorization.valid_from > now:
            raise AuthorizationRejectedError("authorization is not yet valid")
        if authorization.valid_until <= now:
            raise AuthorizationRejectedError("authorization is expired")
        if not authorization.execution_authorized:
            raise AuthorizationRejectedError("execution is not authorized")
        if request.execution_type not in authorization.allowed_execution_types:
            raise AuthorizationRejectedError("execution type is not authorized")
        if not request.dry_run and not authorization.live_authorized:
            raise AuthorizationRejectedError("live execution is not authorized")
        if authorization.execution_plan_id not in {
            None,
            request.execution_plan.execution_plan_id,
        }:
            raise AuthorizationRejectedError("execution plan is not authorized")

    def _validate_plan(self, plan: ExecutionPlan) -> tuple[ExecutionStep, ...]:
        if not plan.steps:
            raise InvalidExecutionPlanError("execution plan cannot be empty")
        steps = tuple(
            sorted(plan.steps, key=lambda item: (item.order, str(item.step_id)))
        )
        ids = [step.step_id for step in steps]
        if len(ids) != len(set(ids)):
            raise InvalidExecutionPlanError("duplicate execution step id")
        orders = [step.order for step in steps]
        if len(orders) != len(set(orders)):
            raise InvalidExecutionPlanError("duplicate execution step order")
        order_by_id = {step.step_id: step.order for step in steps}
        for step in steps:
            for dependency in step.dependencies:
                if dependency not in order_by_id:
                    raise InvalidExecutionPlanError("step depends on unknown step")
                if order_by_id[dependency] >= step.order:
                    raise InvalidExecutionPlanError("step depends on a future step")
        self._validate_dag(steps)
        return steps

    def _validate_dag(self, steps: tuple[ExecutionStep, ...]) -> None:
        visiting: set[UUID] = set()
        visited: set[UUID] = set()
        by_id = {step.step_id: step for step in steps}

        def visit(step_id: UUID) -> None:
            if step_id in visited:
                return
            if step_id in visiting:
                raise InvalidExecutionPlanError("execution step dependency cycle")
            visiting.add(step_id)
            for dependency in by_id[step_id].dependencies:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step in steps:
            visit(step.step_id)

    def _preconditions_pass(
        self,
        state: "_ExecutionRuntimeState",
        step: ExecutionStep,
    ) -> bool:
        return all(self._evaluate_condition(state, item) for item in step.preconditions)

    def _validate_connector_result(
        self,
        state: "_ExecutionRuntimeState",
        step: ExecutionStep,
        result: ExecutionStepResult,
    ) -> None:
        if result.status is not ExecutionStepStatus.COMPLETED:
            raise ConnectorIncompatibleError("connector result did not complete")
        if any(
            not self._evaluate_condition(state, item, connector_result=result)
            for item in step.validation_rules
        ):
            raise ValidationRuleFailedError("execution validation rule failed")
        if step.expected_output and step.required and result.output is None:
            raise ValidationRuleFailedError("required output is missing")
        for artifact in result.artifacts:
            if not artifact.content_reference:
                raise ValidationRuleFailedError("artifact must use a reference")
            self._publish(state, EventType.ARTIFACT_GENERATED, step)

    def _evaluate_condition(
        self,
        state: "_ExecutionRuntimeState",
        condition: StructuredCondition,
        *,
        connector_result: ExecutionStepResult | None = None,
    ) -> bool:
        operator = condition.operator
        if operator not in _ALLOWED_OPERATORS:
            raise OperatorNotAllowedError(f"operator not allowed: {operator}")
        if operator in {"all", "any"}:
            values = [
                self._evaluate_condition(state, item) for item in condition.conditions
            ]
            return all(values) if operator == "all" else any(values)
        if operator == "not":
            if len(condition.conditions) != 1:
                raise InvalidConditionError("not requires one condition")
            return not self._evaluate_condition(state, condition.conditions[0])
        current = self._resolve_field(state, condition.field, connector_result)
        if operator == "exists":
            return current is not None
        if operator == "not_exists":
            return current is None
        expected = condition.value
        if operator == "equals":
            return current == expected
        if operator == "not_equals":
            return current != expected
        if operator == "greater_than":
            return current > expected
        if operator == "greater_than_or_equal":
            return current >= expected
        if operator == "less_than":
            return current < expected
        if operator == "less_than_or_equal":
            return current <= expected
        if operator == "in":
            return current in expected
        if operator == "not_in":
            return current not in expected
        if operator == "contains":
            return expected in current
        if operator == "not_contains":
            return expected not in current
        raise OperatorNotAllowedError(f"operator not allowed: {operator}")

    def _resolve_field(
        self,
        state: "_ExecutionRuntimeState",
        field: str | None,
        connector_result: ExecutionStepResult | None,
    ) -> object:
        if field is None:
            return None
        if field.startswith("authorization."):
            return getattr(
                state.request.authorization,
                field.removeprefix("authorization."),
                None,
            )
        if field.startswith("metadata."):
            return state.request.safe_metadata.get(field.removeprefix("metadata."))
        if field.startswith("constraints."):
            name = field.removeprefix("constraints.")
            return next(
                (
                    constraint.value
                    for constraint in state.request.constraints
                    if constraint.name == name
                ),
                None,
            )
        if field.startswith("outputs."):
            _, raw_step_id, *path = field.split(".")
            value: object = state.outputs.get(UUID(raw_step_id))
            for part in path:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return None
            return value
        if field == "connector_result.status":
            return None if connector_result is None else connector_result.status.value
        if field.startswith("connector_result.output."):
            if connector_result is None:
                return None
            return connector_result.output.get(
                field.removeprefix("connector_result.output.")
            )
        raise InvalidConditionError("condition field is not allowed")

    def _create_human_task(
        self,
        state: "_ExecutionRuntimeState",
        step: ExecutionStep,
    ) -> None:
        assigned_to = str(step.safe_metadata.get("assigned_to") or "")
        if not assigned_to:
            raise HumanTaskError("human step requires assigned_to metadata")
        task = HumanTask(
            task_id=self._id_generator(),
            execution_id=state.execution_id,
            step_id=step.step_id,
            organization_id=state.request.organization_id,
            session_id=state.request.session_id,
            plan_id=state.request.plan_id,
            assigned_to=assigned_to,
            instructions=step.action,
            evidence_required=bool(step.safe_metadata.get("evidence_required")),
        )
        self._human_tasks.create(task)
        state.human_tasks.append(task)
        result = ExecutionStepResult(
            step_id=step.step_id,
            connector_id=None,
            status=ExecutionStepStatus.PAUSED,
            started_at=self._now(),
            completed_at=self._now(),
            duration=0.0,
            attempts=1,
            safe_metadata={"task_id": str(task.task_id)},
        )
        state.step_results[step.step_id] = result
        self._publish(state, EventType.HUMAN_TASK_CREATED, step)
        self._publish(state, EventType.EXECUTION_PAUSED)

    def _skip_step(
        self,
        state: "_ExecutionRuntimeState",
        step: ExecutionStep,
        reason: str,
    ) -> None:
        now = self._now()
        state.step_results[step.step_id] = ExecutionStepResult(
            step_id=step.step_id,
            connector_id=None,
            status=ExecutionStepStatus.SKIPPED,
            started_at=now,
            completed_at=now,
            duration=0.0,
            attempts=1,
            safe_metadata={"reason": reason},
        )
        self._timeline(state, TimelineEntryType.STEP, "skipped", step=step)
        self._publish(state, EventType.STEP_SKIPPED, step)

    def _step_result(
        self,
        state: "_ExecutionRuntimeState",
        step: ExecutionStep,
        connector_id: str,
        result: ConnectorResult,
        started_at: datetime,
        attempt: int,
    ) -> ExecutionStepResult:
        completed_at = self._now()
        metrics = tuple(
            ExecutionMetric(name=name, value=value, unit="relative")
            for name, value in sorted(result.metrics.items())
        )
        return ExecutionStepResult(
            step_id=step.step_id,
            connector_id=connector_id,
            status=result.status,
            started_at=started_at,
            completed_at=completed_at,
            duration=max((completed_at - started_at).total_seconds(), 0.0),
            attempts=attempt,
            output=result.output,
            artifacts=tuple(
                sorted(result.artifacts, key=lambda item: str(item.artifact_id))
            ),
            metrics=metrics,
            safe_metadata=result.safe_metadata,
        )

    def _invocation(
        self,
        state: "_ExecutionRuntimeState",
        step: ExecutionStep,
        connector_id: str,
        attempt: int,
    ) -> ConnectorInvocation:
        return ConnectorInvocation(
            invocation_id=self._id_generator(),
            execution_id=state.execution_id,
            execution_request_id=state.request.execution_request_id,
            organization_id=state.request.organization_id,
            session_id=state.request.session_id,
            plan_id=state.request.plan_id,
            execution_plan_id=state.request.execution_plan.execution_plan_id,
            step_id=step.step_id,
            connector_id=connector_id,
            execution_type=step.execution_type,
            action=step.action,
            parameters=dict(step.parameters),
            mode=self._mode(state.request),
            idempotency_key=self._step_key(state.request, step),
            attempt=attempt,
        )

    def _reserve_idempotency(
        self,
        key: str,
        payload: object,
        execution_id: UUID,
        step_id: UUID | None,
    ) -> IdempotencyRecord:
        request = payload if isinstance(payload, ExecutionRequest) else None
        base_request = request or None
        if base_request is None and hasattr(payload, "organization_id"):
            organization_id = payload.organization_id
            session_id = payload.session_id
            plan_id = payload.plan_id
            execution_plan_id = payload.execution_plan_id
        else:
            organization_id = self._request_for_key(payload).organization_id
            session_id = self._request_for_key(payload).session_id
            plan_id = self._request_for_key(payload).plan_id
            execution_plan_id = self._request_for_key(
                payload
            ).execution_plan.execution_plan_id
        now = self._now()
        data = (
            payload.model_dump(mode="json", exclude={"authorization"})
            if hasattr(payload, "model_dump")
            else {"payload": str(payload)}
        )
        record = IdempotencyRecord(
            key=key,
            fingerprint=deterministic_fingerprint(data),
            status=IdempotencyRecordStatus.IN_PROGRESS,
            organization_id=organization_id,
            session_id=session_id,
            plan_id=plan_id,
            execution_plan_id=execution_plan_id,
            step_id=step_id,
            created_at=now,
            updated_at=now,
        )
        return self._idempotency.reserve(record)

    def _request_for_key(self, payload: object) -> ExecutionRequest:
        if isinstance(payload, ExecutionRequest):
            return payload
        msg = "payload cannot provide request scope"
        raise InvalidExecutionRequestError(msg)

    def _waiting_for_window(self, request: ExecutionRequest) -> str | None:
        window = request.execution_window or request.execution_plan.execution_window
        if window is None:
            return None
        now = self._now()
        if now < window.starts_at:
            return "execution_window_not_started"
        if now > window.ends_at:
            raise InvalidExecutionRequestError("execution window expired")
        return None

    def _waiting_result(
        self,
        state: "_ExecutionRuntimeState",
        reason: str,
    ) -> ExecutionResult:
        self._timeline(
            state, TimelineEntryType.EXECUTION, "waiting", reason_code=reason
        )
        self._publish(state, EventType.EXECUTION_WAITING)
        return self._build_result(state, ExecutionStatus.WAITING, self._now())

    def _paused_result(
        self,
        state: "_ExecutionRuntimeState",
        paused_steps: tuple[UUID, ...],
    ) -> ExecutionResult:
        return self._build_result(
            state,
            ExecutionStatus.PAUSED,
            self._now(),
            paused_steps=paused_steps,
        )

    def _validate_success(
        self,
        state: "_ExecutionRuntimeState",
        steps: tuple[ExecutionStep, ...],
    ) -> None:
        for step in steps:
            result = state.step_results.get(step.step_id)
            if result is None:
                raise InvalidExecutionPlanError("step missing result")
            if step.required and result.status is not ExecutionStepStatus.COMPLETED:
                raise InvalidExecutionPlanError("required step did not complete")

    def _build_result(
        self,
        state: "_ExecutionRuntimeState",
        status: ExecutionStatus,
        completed_at: datetime,
        *,
        paused_steps: tuple[UUID, ...] = (),
    ) -> ExecutionResult:
        request = state.request
        step_results = tuple(
            sorted(
                state.step_results.values(),
                key=lambda item: self._step_order(
                    request.execution_plan,
                    item.step_id,
                ),
            )
        )
        artifacts = tuple(
            sorted(
                {item.artifact_id: item for item in state.artifacts}.values(),
                key=lambda item: str(item.artifact_id),
            )
        )
        metrics = self._metrics(step_results, artifacts, state.rollback_results)
        logs = tuple(state.logs)
        timeline = tuple(state.timeline)
        resume_state = None
        if status in {ExecutionStatus.PAUSED, ExecutionStatus.WAITING}:
            resume_state = ExecutionResumeState(
                execution_id=state.execution_id,
                execution_plan_id=request.execution_plan.execution_plan_id,
                organization_id=request.organization_id,
                session_id=request.session_id,
                plan_id=request.plan_id,
                correlation_id=request.correlation_id,
                status=status,
                current_step=paused_steps[0] if paused_steps else None,
                completed_steps=tuple(state.outputs),
                skipped_steps=tuple(
                    item.step_id
                    for item in step_results
                    if item.status is ExecutionStepStatus.SKIPPED
                ),
                paused_steps=paused_steps,
                attempts=state.attempts,
                outputs=state.outputs,
                artifacts=artifacts,
                timeline=timeline,
                idempotency_references=tuple(
                    self._step_key(request, step)
                    for step in request.execution_plan.steps
                ),
                human_tasks=tuple(state.human_tasks),
                authorization_id=request.authorization.authorization_id,
                created_at=state.started_at,
                updated_at=completed_at,
            )
        provisional = ExecutionResult(
            execution_id=state.execution_id,
            execution_request_id=request.execution_request_id,
            execution_plan_id=request.execution_plan.execution_plan_id,
            organization_id=request.organization_id,
            session_id=request.session_id,
            plan_id=request.plan_id,
            correlation_id=request.correlation_id,
            status=status,
            fingerprint="0" * 64,
            terminal_event_id=(
                self._id_generator()
                if status
                in {
                    ExecutionStatus.COMPLETED,
                    ExecutionStatus.FAILED,
                    ExecutionStatus.CANCELLED,
                    ExecutionStatus.ROLLED_BACK,
                    ExecutionStatus.ROLLBACK_FAILED,
                }
                else None
            ),
            mode=self._mode(request),
            started_at=state.started_at,
            completed_at=completed_at,
            duration=max((completed_at - state.started_at).total_seconds(), 0.0),
            step_results=step_results,
            outputs_by_step={item.step_id: item.output for item in step_results},
            outputs_by_connector={
                item.connector_id: item.output
                for item in step_results
                if item.connector_id is not None
            },
            artifacts=artifacts,
            metrics=metrics,
            logs=logs,
            timeline=timeline,
            failures=tuple(state.failures),
            rollback_results=tuple(state.rollback_results),
            human_tasks=tuple(state.human_tasks),
            resume_state=resume_state,
            idempotency_key=request.idempotency_key,
            authorization_id=request.authorization.authorization_id,
            policy_references=request.policy_references,
            reason_codes=request.execution_plan.reason_codes,
            safe_metadata=request.safe_metadata,
        )
        fingerprint = deterministic_fingerprint(
            provisional.model_dump(mode="json", exclude={"fingerprint"})
        )
        return provisional.model_copy(update={"fingerprint": fingerprint})

    @staticmethod
    def _validate_canonical_result(
        request: ExecutionRequest,
        result: ExecutionResult,
    ) -> None:
        expected_scope = (
            request.organization_id,
            request.session_id,
            request.plan_id,
            request.correlation_id,
        )
        actual_scope = (
            result.organization_id,
            result.session_id,
            result.plan_id,
            result.correlation_id,
        )
        if actual_scope != expected_scope:
            raise ExecutionResultConflictError(
                "persisted execution result scope does not match runtime request"
            )
        if result.execution_plan_id != request.execution_plan.execution_plan_id:
            raise ExecutionResultConflictError(
                "persisted execution result plan does not match runtime request"
            )

    def _metrics(
        self,
        step_results: tuple[ExecutionStepResult, ...],
        artifacts: tuple[ExecutionArtifact, ...],
        rollback_results: list[RollbackResult],
    ) -> tuple[ExecutionMetric, ...]:
        return (
            ExecutionMetric(
                name="steps_completed",
                value=float(
                    sum(
                        item.status is ExecutionStepStatus.COMPLETED
                        for item in step_results
                    )
                ),
                unit="count",
            ),
            ExecutionMetric(
                name="artifacts", value=float(len(artifacts)), unit="count"
            ),
            ExecutionMetric(
                name="rollback_steps",
                value=float(len(rollback_results)),
                unit="count",
            ),
        )

    def _failure(
        self,
        state: "_ExecutionRuntimeState",
        error: BaseException,
        step: ExecutionStep | None = None,
    ) -> ExecutionFailure:
        return ExecutionFailure(
            failure_id=self._id_generator(),
            execution_id=state.execution_id,
            execution_plan_id=state.request.execution_plan.execution_plan_id,
            step_id=None if step is None else step.step_id,
            connector_id=None if step is None else step.connector_id,
            classification=self._failure_classifier(error),
            recoverable=self._failure_classifier(error)
            is FailureClassification.RECOVERABLE,
            attempt=1 if step is None else state.attempts.get(step.step_id, 1),
            occurred_at=self._now(),
            safe_message=str(error)[:300],
            cause_type=type(error).__name__,
            rollback_required=state.request.rollback_required,
            human_escalation_required=state.request.rollback_required,
        )

    def _classify_failure(self, error: BaseException) -> FailureClassification:
        if isinstance(error, AuthorizationRejectedError):
            return FailureClassification.AUTHORIZATION
        if isinstance(error, ApprovalEvidenceMissingError):
            return FailureClassification.APPROVAL
        if isinstance(error, ExecutionTimeoutError):
            return FailureClassification.TIMEOUT
        if isinstance(error, ValidationRuleFailedError):
            return FailureClassification.OUTPUT_VALIDATION
        if isinstance(error, InvalidConditionError | InvalidExecutionPlanError):
            return FailureClassification.VALIDATION
        return FailureClassification.CONNECTOR

    def _can_fallback(
        self,
        error: BaseException,
        step: ExecutionStep,
        connector_id: str,
    ) -> bool:
        return (
            connector_id != step.fallback_connector_ids[-1]
            if step.fallback_connector_ids
            else False
        ) and self._failure_classifier(error) in {
            FailureClassification.RECOVERABLE,
            FailureClassification.UNAVAILABLE,
            FailureClassification.CONNECTOR,
        }

    def _step_key(self, request: ExecutionRequest, step: ExecutionStep) -> str:
        return (
            f"{request.idempotency_key}:"
            f"{request.organization_id}:{request.session_id}:{request.plan_id}:"
            f"{request.action_scope}:{request.execution_plan.execution_plan_id}:"
            f"{step.step_id}:{step.idempotency_scope}"
        )

    def _step_order(self, plan: ExecutionPlan, step_id: UUID) -> tuple[int, str]:
        for step in plan.steps:
            if step.step_id == step_id:
                return (step.order, str(step_id))
        return (999999, str(step_id))

    def _mode(self, request: ExecutionRequest) -> ExecutionMode:
        return ExecutionMode.DRY_RUN if request.dry_run else ExecutionMode.LIVE

    def _timeline(
        self,
        state: "_ExecutionRuntimeState",
        entry_type: TimelineEntryType,
        status: str,
        *,
        step: ExecutionStep | None = None,
        connector_id: str | None = None,
        attempt: int | None = None,
        reason_code: str | None = None,
    ) -> None:
        state.timeline.append(
            ExecutionTimelineEntry(
                sequence=len(state.timeline) + 1,
                entry_type=entry_type,
                status=status,
                occurred_at=self._now(),
                step_id=None if step is None else step.step_id,
                connector_id=connector_id,
                attempt=attempt,
                reason_code=reason_code,
            )
        )
        state.logs.append(
            ExecutionLogEntry(
                sequence=len(state.logs) + 1,
                occurred_at=self._now(),
                level="INFO",
                message=status,
                step_id=None if step is None else step.step_id,
                connector_id=connector_id,
            )
        )

    def _publish(
        self,
        state: "_ExecutionRuntimeState",
        event_type: EventType,
        step: ExecutionStep | None = None,
        *,
        result: ExecutionResult | None = None,
    ) -> None:
        terminal = event_type in {
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
        }
        if terminal and result is None:
            raise ValueError("terminal execution events require a persisted result")
        payload = {
            "organization_id": str(state.request.organization_id),
            "session_id": str(state.request.session_id),
            "plan_id": str(state.request.plan_id),
            "execution_id": str(state.execution_id),
            "correlation_id": str(state.request.correlation_id),
            "step_id": None if step is None else str(step.step_id),
            "status": event_type.value,
        }
        if result is not None:
            payload.update(
                {
                    "status": result.status.value,
                    "fingerprint": result.fingerprint,
                    "result_reference": (
                        f"execution_results:{result.organization_id}:"
                        f"{result.execution_id}"
                    ),
                }
            )
        self._event_service.publish(
            self._terminal_event(state, event_type, result)
            if result is not None
            else Event(
                id=result.terminal_event_id
                if result is not None and result.terminal_event_id is not None
                else self._id_generator(),
                event_type=event_type,
                source="execution",
                organization_id=state.request.organization_id,
                session_id=state.request.session_id,
                payload=payload,
                metadata=EventMetadata(correlation_id=state.request.correlation_id),
                priority=EventPriority.NORMAL,
            )
        )

    def _terminal_event(
        self,
        state: "_ExecutionRuntimeState",
        event_type: EventType,
        result: ExecutionResult,
    ) -> Event:
        return Event(
            id=result.terminal_event_id or self._id_generator(),
            event_type=event_type,
            source="execution",
            organization_id=state.request.organization_id,
            session_id=state.request.session_id,
            payload={
                "organization_id": str(state.request.organization_id),
                "session_id": str(state.request.session_id),
                "plan_id": str(state.request.plan_id),
                "execution_id": str(state.execution_id),
                "correlation_id": str(state.request.correlation_id),
                "step_id": None,
                "status": result.status.value,
                "fingerprint": result.fingerprint,
                "result_reference": (
                    f"execution_results:{result.organization_id}:{result.execution_id}"
                ),
            },
            metadata=EventMetadata(correlation_id=state.request.correlation_id),
            priority=EventPriority.NORMAL,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class _ExecutionRuntimeState:
    def __init__(
        self,
        *,
        execution_id: UUID,
        request: ExecutionRequest,
        started_at: datetime,
        timeline: list[ExecutionTimelineEntry] | None = None,
        artifacts: list[ExecutionArtifact] | None = None,
        human_tasks: list[HumanTask] | None = None,
        outputs: dict[UUID, dict[str, object]] | None = None,
        attempts: dict[UUID, int] | None = None,
    ) -> None:
        self.execution_id = execution_id
        self.request = request
        self.started_at = started_at
        self.timeline = timeline or []
        self.logs: list[ExecutionLogEntry] = []
        self.step_results: dict[UUID, ExecutionStepResult] = {}
        self.outputs = outputs or {}
        self.artifacts = artifacts or []
        self.failures: list[ExecutionFailure] = []
        self.rollback_results: list[RollbackResult] = []
        self.human_tasks = human_tasks or []
        self.attempts = attempts or {}
        self.reserved_idempotency_keys: set[str] = set()


_ALLOWED_OPERATORS = {
    "equals",
    "not_equals",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "exists",
    "not_exists",
    "all",
    "any",
    "not",
}

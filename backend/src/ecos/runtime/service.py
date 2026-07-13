"""Application service for authenticated, resumable cognitive runtime sessions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from ecos.domain import SessionStage
from ecos.governance import (
    ApprovalRequestStatus,
    GovernanceEngine,
    GovernanceResult,
    GovernanceResultStatus,
)
from ecos.orchestrator import (
    ApprovalState as OrchestratorApprovalState,
)
from ecos.orchestrator import (
    ApprovalStatus as OrchestratorApprovalStatus,
)
from ecos.orchestrator import (
    GovernanceState,
    OrchestrationInput,
    OrchestrationResult,
    OrchestratorService,
    PipelineExecutionStatus,
)
from ecos.planner import PlannerInput, PlannerService
from ecos.runtime.artifacts import RuntimeArtifactCodec
from ecos.runtime.models import (
    AuthenticatedRuntimeResult,
    ResumeSessionCommand,
    StartExistingSessionCommand,
)
from ecos.runtime.repository import (
    RuntimeCheckpoint,
    RuntimeCheckpointConflictError,
    RuntimeCheckpointNotFoundError,
    RuntimeCheckpointRepository,
    RuntimeCheckpointScopeError,
    RuntimeCheckpointStatus,
)
from ecos.session import (
    ManagedSession,
    SessionLifecycleStatus,
    SessionService,
    SessionSnapshot,
    SessionState,
    SessionTransition,
    TransitionType,
)

Clock = Callable[[], datetime]


class AuthenticatedRuntimeService:
    """Start and resume existing sessions through the governed runtime only."""

    def __init__(
        self,
        *,
        session_service: SessionService,
        planner_service: PlannerService,
        orchestrator_service: OrchestratorService,
        governance_engine: GovernanceEngine,
        checkpoint_repository: RuntimeCheckpointRepository,
        artifact_codec: RuntimeArtifactCodec,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._session_service = session_service
        self._planner_service = planner_service
        self._orchestrator_service = orchestrator_service
        self._governance_engine = governance_engine
        self._checkpoints = checkpoint_repository
        self._codec = artifact_codec
        self._clock = clock

    def start_existing_session(
        self, command: StartExistingSessionCommand
    ) -> AuthenticatedRuntimeResult:
        """Plan and execute an existing scoped session up to its governance gate."""
        session = self._scoped_session(command.organization_id, command.session_id)
        self._validate_objective(session, command.objective)
        if (
            self._checkpoints.get(command.organization_id, command.session_id)
            is not None
        ):
            raise RuntimeCheckpointConflictError(
                "runtime checkpoint already exists for session"
            )
        plan = self._planner_service.create_plan(
            PlannerInput(
                session_id=command.session_id,
                organization_id=command.organization_id,
                user_id=command.user_id,
                objective=session.session.objective,
                description=session.session.objective.description,
                priority=session.session.objective.priority,
                desired_outcome="Produce and execute a governed dry-run plan.",
                constraints=("Execution requires explicit human approval",),
                resources_available=("runtime", "memory.dry_run"),
                domains=("operations", "risk"),
                context_available=True,
                execution_requested=True,
                stakeholders_count=2,
                impact="high",
                reversible=True,
                metadata={
                    "runtime": True,
                    "authenticated": True,
                    "user_id": str(command.user_id),
                },
                correlation_id=command.correlation_id,
            )
        )
        self._begin_session(session)
        session = self._scoped_session(command.organization_id, command.session_id)
        result = self._orchestrator_service.execute(
            self._orchestration_input(command, session, plan)
        )
        checkpoint = self._checkpoint_from_result(command, plan, result, version=1)
        if result.status is PipelineExecutionStatus.WAITING_APPROVAL:
            self._record_pause(command.organization_id, command.session_id)
        try:
            stored = self._checkpoints.save(checkpoint, expected_version=None)
        except Exception:
            if result.status is PipelineExecutionStatus.WAITING_APPROVAL:
                try:
                    self._record_initial_checkpoint_failure(
                        command.organization_id,
                        command.session_id,
                    )
                except Exception:
                    pass
            raise
        return self._result(stored, result.status)

    def resume_session(
        self, command: ResumeSessionCommand
    ) -> AuthenticatedRuntimeResult:
        """Record a human decision and resume only after Governance grants quorum."""
        session = self._scoped_session(command.organization_id, command.session_id)
        self._validate_objective(session, command.objective)
        checkpoint = self._checkpoints.get(command.organization_id, command.session_id)
        if checkpoint is None:
            raise RuntimeCheckpointNotFoundError("runtime checkpoint does not exist")
        self._validate_resume_command(command, checkpoint)
        if checkpoint.status is RuntimeCheckpointStatus.EXECUTING:
            governance = self._governance(checkpoint)
            if self._decision_was_recorded(
                governance, command.approval_decision.approval_decision_id
            ):
                return self._result(checkpoint, PipelineExecutionStatus.RUNNING)
            raise RuntimeCheckpointConflictError(
                "executing runtime checkpoint rejects a different decision"
            )
        if checkpoint.status is RuntimeCheckpointStatus.COMPLETED:
            governance = self._governance(checkpoint)
            if self._decision_was_recorded(
                governance, command.approval_decision.approval_decision_id
            ):
                return self._result(checkpoint, PipelineExecutionStatus.COMPLETED)
            raise RuntimeCheckpointConflictError(
                "completed runtime checkpoint cannot be resumed"
            )
        if checkpoint.status is RuntimeCheckpointStatus.FAILED:
            raise RuntimeCheckpointConflictError(
                "failed runtime checkpoint cannot be resumed"
            )
        governance = self._governance(checkpoint)
        authorized = governance
        idempotent_resume_replay = False
        if governance.status is not GovernanceResultStatus.AUTHORIZED:
            approval_request = governance.approval_request
            if approval_request is None:
                raise RuntimeCheckpointConflictError(
                    "checkpoint has no human approval request"
                )
            updated_request, audits = self._governance_engine.record_decision(
                approval_request=approval_request,
                decision=command.approval_decision,
                audit_records=governance.audit_records,
            )
            if updated_request.status is not ApprovalRequestStatus.GRANTED:
                partial = governance.model_copy(
                    update={
                        "approval_request": updated_request,
                        "approval_state": governance.approval_state.model_copy(
                            update={
                                "approval_request": updated_request,
                                "decisions": (
                                    *updated_request.current_approvals,
                                    *updated_request.current_rejections,
                                ),
                                "status": updated_request.status,
                            }
                        )
                        if governance.approval_state is not None
                        else None,
                        "audit_records": audits,
                    }
                )
                waiting = self._replace_governance(checkpoint, partial)
                stored = self._checkpoints.save(
                    waiting,
                    expected_version=checkpoint.version,
                )
                return self._result(stored, PipelineExecutionStatus.WAITING_APPROVAL)
            authorized = self._governance_engine.authorize_after_quorum(
                result=governance,
                approval_request=updated_request,
                audit_records=audits,
            )
            checkpoint = self._checkpoints.save(
                self._replace_governance(checkpoint, authorized),
                expected_version=checkpoint.version,
            )
        else:
            idempotent_resume_replay = self._decision_was_recorded(
                governance, command.approval_decision.approval_decision_id
            )
            if not idempotent_resume_replay:
                raise RuntimeCheckpointConflictError(
                    "approval decision is not part of the authorized checkpoint"
                )
        resumable = checkpoint.resumable_state
        if resumable is None:
            raise RuntimeCheckpointConflictError("checkpoint is not resumable")
        restored = self._codec.deserialize_resume_state(resumable)
        should_resume = self._record_resume(
            command.organization_id,
            command.session_id,
            idempotent_replay=idempotent_resume_replay,
        )
        if not should_resume:
            latest = self._checkpoints.get(command.organization_id, command.session_id)
            if (
                latest is not None
                and latest.status is RuntimeCheckpointStatus.EXECUTING
            ):
                return self._result(latest, PipelineExecutionStatus.RUNNING)
            raise RuntimeCheckpointConflictError(
                "runtime session is executing without an executing checkpoint"
            )
        executing = checkpoint.model_copy(
            update={
                "status": RuntimeCheckpointStatus.EXECUTING,
                "version": checkpoint.version + 1,
                "updated_at": self._now(),
            }
        )
        try:
            checkpoint = self._checkpoints.save(
                executing,
                expected_version=checkpoint.version,
            )
        except Exception:
            self._restore_paused_after_failed_execution_claim(
                command.organization_id,
                command.session_id,
            )
            raise
        session = self._scoped_session(command.organization_id, command.session_id)
        input_ = self._orchestration_input(
            command,
            session,
            checkpoint.cognitive_plan,
            governance_result=authorized,
            approved_at=command.approval_decision.decided_at,
        )
        try:
            result = self._orchestrator_service.resume(input_, restored)
        except Exception:
            failed = checkpoint.model_copy(
                update={
                    "status": RuntimeCheckpointStatus.FAILED,
                    "version": checkpoint.version + 1,
                    "updated_at": self._now(),
                }
            )
            try:
                self._record_failure(command.organization_id, command.session_id)
            except Exception:
                pass
            else:
                try:
                    self._checkpoints.save(
                        failed,
                        expected_version=checkpoint.version,
                    )
                except Exception:
                    pass
            raise
        completed = self._checkpoint_from_result(
            command,
            checkpoint.cognitive_plan,
            result,
            version=checkpoint.version + 1,
            created_at=checkpoint.created_at,
        )
        stored = self._checkpoints.save(
            completed,
            expected_version=checkpoint.version,
        )
        if result.status is PipelineExecutionStatus.COMPLETED:
            latest = self._scoped_session(command.organization_id, command.session_id)
            self._session_service.save_snapshot(
                SessionSnapshot(
                    session_id=command.session_id,
                    state=latest.state,
                    context=latest.context,
                )
            )
        return self._result(stored, result.status)

    def get_checkpoint(
        self, organization_id: UUID, session_id: UUID
    ) -> RuntimeCheckpoint | None:
        """Return one checkpoint through its mandatory organization scope."""
        return self._checkpoints.get(organization_id, session_id)

    def _scoped_session(
        self, organization_id: UUID, session_id: UUID
    ) -> ManagedSession:
        session = self._session_service.get_session(session_id)
        if session is None:
            raise RuntimeCheckpointNotFoundError("cognitive session does not exist")
        if session.context.organization_id != organization_id:
            raise RuntimeCheckpointScopeError("cognitive session is not available")
        return session

    @staticmethod
    def _validate_objective(session: ManagedSession, objective: str) -> None:
        if session.session.objective.title != objective.strip():
            raise RuntimeCheckpointConflictError(
                "runtime objective does not match session"
            )

    @staticmethod
    def _validate_resume_command(
        command: ResumeSessionCommand, checkpoint: RuntimeCheckpoint
    ) -> None:
        decision = command.approval_decision
        if checkpoint.organization_id != command.organization_id:
            raise RuntimeCheckpointScopeError("runtime checkpoint is not available")
        if checkpoint.session_id != command.session_id:
            raise RuntimeCheckpointConflictError("runtime session mismatch")
        if decision.actor_id != command.user_id:
            raise RuntimeCheckpointScopeError("approval actor does not match user")
        if (
            decision.organization_id != command.organization_id
            or decision.session_id != command.session_id
            or decision.plan_id != checkpoint.cognitive_plan.plan_id
        ):
            raise RuntimeCheckpointScopeError("approval decision scope mismatch")

    def _begin_session(self, session: ManagedSession) -> None:
        self._session_service.record_transition(
            SessionTransition(
                session_id=session.session.id,
                transition_type=TransitionType.INITIALIZE,
                from_status=session.state.lifecycle_status,
                to_status=SessionLifecycleStatus.INITIALIZED,
                reason="Authenticated runtime session initialized.",
            )
        )
        self._session_service.record_transition(
            SessionTransition(
                session_id=session.session.id,
                transition_type=TransitionType.START_PLANNING,
                from_status=SessionLifecycleStatus.INITIALIZED,
                to_status=SessionLifecycleStatus.PLANNING,
                reason="Authenticated runtime planning started.",
            )
        )
        self._session_service.update_state(
            SessionState(
                session_id=session.session.id,
                lifecycle_status=SessionLifecycleStatus.PLANNING,
                current_stage=SessionStage.CONTEXT,
                active_engine="planner",
                progress=0.0,
                updated_at=self._now(),
            )
        )

    def _record_pause(self, organization_id: UUID, session_id: UUID) -> None:
        session = self._scoped_session(organization_id, session_id)
        if session.state.lifecycle_status is SessionLifecycleStatus.PAUSED:
            return
        if session.state.lifecycle_status is not SessionLifecycleStatus.EXECUTING:
            raise RuntimeCheckpointConflictError(
                "runtime session cannot pause from "
                f"{session.state.lifecycle_status.value}"
            )
        self._session_service.record_transition(
            SessionTransition(
                session_id=session.session.id,
                transition_type=TransitionType.PAUSE,
                from_status=session.state.lifecycle_status,
                to_status=SessionLifecycleStatus.PAUSED,
                reason="Runtime is waiting for explicit human approval.",
            )
        )
        self._session_service.update_state(
            session.state.model_copy(
                update={
                    "lifecycle_status": SessionLifecycleStatus.PAUSED,
                    "updated_at": self._now(),
                }
            )
        )

    def _record_resume(
        self,
        organization_id: UUID,
        session_id: UUID,
        *,
        idempotent_replay: bool = False,
    ) -> bool:
        session = self._scoped_session(organization_id, session_id)
        if session.state.lifecycle_status is SessionLifecycleStatus.EXECUTING:
            if idempotent_replay:
                return False
            raise RuntimeCheckpointConflictError(
                "runtime session is already executing without a proven replay"
            )
        if session.state.lifecycle_status is not SessionLifecycleStatus.PAUSED:
            raise RuntimeCheckpointConflictError(
                "runtime session cannot resume from "
                f"{session.state.lifecycle_status.value}"
            )
        self._session_service.record_transition(
            SessionTransition(
                session_id=session.session.id,
                transition_type=TransitionType.RESUME,
                from_status=session.state.lifecycle_status,
                to_status=SessionLifecycleStatus.EXECUTING,
                reason="Runtime resumed after validated human quorum.",
            )
        )
        self._session_service.update_state(
            session.state.model_copy(
                update={
                    "lifecycle_status": SessionLifecycleStatus.EXECUTING,
                    "updated_at": self._now(),
                }
            )
        )
        return True

    def _restore_paused_after_failed_execution_claim(
        self, organization_id: UUID, session_id: UUID
    ) -> None:
        latest = self._checkpoints.get(organization_id, session_id)
        if latest is not None and latest.status is RuntimeCheckpointStatus.EXECUTING:
            return
        session = self._scoped_session(organization_id, session_id)
        if session.state.lifecycle_status is SessionLifecycleStatus.EXECUTING:
            self._record_pause(organization_id, session_id)

    def _record_failure(self, organization_id: UUID, session_id: UUID) -> None:
        session = self._scoped_session(organization_id, session_id)
        if session.state.lifecycle_status is SessionLifecycleStatus.FAILED:
            return
        if session.state.lifecycle_status is not SessionLifecycleStatus.EXECUTING:
            raise RuntimeCheckpointConflictError(
                "runtime session cannot fail from "
                f"{session.state.lifecycle_status.value}"
            )
        self._session_service.record_transition(
            SessionTransition(
                session_id=session.session.id,
                transition_type=TransitionType.FAIL,
                from_status=SessionLifecycleStatus.EXECUTING,
                to_status=SessionLifecycleStatus.FAILED,
                reason="Authenticated runtime resume failed.",
            )
        )
        self._session_service.update_state(
            session.state.model_copy(
                update={
                    "lifecycle_status": SessionLifecycleStatus.FAILED,
                    "updated_at": self._now(),
                }
            )
        )

    def _record_initial_checkpoint_failure(
        self, organization_id: UUID, session_id: UUID
    ) -> None:
        session = self._scoped_session(organization_id, session_id)
        if session.state.lifecycle_status is SessionLifecycleStatus.FAILED:
            return
        if session.state.lifecycle_status is not SessionLifecycleStatus.PAUSED:
            raise RuntimeCheckpointConflictError(
                "runtime session cannot reconcile initial checkpoint failure from "
                f"{session.state.lifecycle_status.value}"
            )
        self._session_service.record_transition(
            SessionTransition(
                session_id=session.session.id,
                transition_type=TransitionType.FAIL,
                from_status=SessionLifecycleStatus.PAUSED,
                to_status=SessionLifecycleStatus.FAILED,
                reason="Initial runtime checkpoint persistence failed.",
            )
        )
        self._session_service.update_state(
            session.state.model_copy(
                update={
                    "lifecycle_status": SessionLifecycleStatus.FAILED,
                    "updated_at": self._now(),
                }
            )
        )

    def _orchestration_input(
        self,
        command: StartExistingSessionCommand,
        session: ManagedSession,
        plan,
        *,
        governance_result: GovernanceResult | None = None,
        approved_at: datetime | None = None,
    ) -> OrchestrationInput:
        approval = OrchestratorApprovalState()
        governance_state = GovernanceState(
            satisfied=False,
            organization_id=command.organization_id,
            session_id=command.session_id,
            plan_id=plan.plan_id,
        )
        initial_inputs = {}
        if governance_result is not None:
            authorization = governance_result.authorization_decision
            approval = OrchestratorApprovalState(
                status=OrchestratorApprovalStatus.APPROVED,
                organization_id=command.organization_id,
                session_id=command.session_id,
                plan_id=plan.plan_id,
                approved_at=approved_at,
                expires_at=authorization.valid_until if authorization else None,
                metadata={"source": "governance_human_quorum"},
            )
            governance_state = GovernanceState(
                satisfied=True,
                organization_id=command.organization_id,
                session_id=command.session_id,
                plan_id=plan.plan_id,
                metadata={"source": "governance_human_quorum"},
            )
            initial_inputs = {"governance": governance_result}
        return OrchestrationInput(
            cognitive_plan=plan,
            active_session=session,
            organization_id=command.organization_id,
            session_id=command.session_id,
            correlation_id=command.correlation_id,
            approval_state=approval,
            governance_state=governance_state,
            resources_available=("runtime", "memory.dry_run"),
            initial_inputs=initial_inputs,
            safe_metadata={
                "runtime": True,
                "authenticated": True,
                "user_id": str(command.user_id),
            },
        )

    def _checkpoint_from_result(
        self,
        command: StartExistingSessionCommand,
        plan,
        result: OrchestrationResult,
        *,
        version: int,
        created_at: datetime | None = None,
    ) -> RuntimeCheckpoint:
        governance = result.outputs_by_engine.get("governance")
        if governance is not None and not isinstance(governance, GovernanceResult):
            raise RuntimeCheckpointConflictError("invalid governance runtime output")
        status = {
            PipelineExecutionStatus.WAITING_APPROVAL: (
                RuntimeCheckpointStatus.WAITING_APPROVAL
            ),
            PipelineExecutionStatus.COMPLETED: RuntimeCheckpointStatus.COMPLETED,
        }.get(result.status, RuntimeCheckpointStatus.FAILED)
        now = self._now()
        return RuntimeCheckpoint(
            session_id=command.session_id,
            organization_id=command.organization_id,
            user_id=command.user_id,
            correlation_id=command.correlation_id,
            cognitive_plan=plan,
            resumable_state=self._codec.serialize_resume_state(result.resumable_state)
            if result.resumable_state is not None
            else None,
            stage_results=tuple(
                self._codec.serialize_stage_result(item)
                for item in result.stage_results
            ),
            governance_result=self._codec.encode("governance", governance)
            if governance is not None
            else None,
            version=version,
            status=status,
            created_at=created_at or now,
            updated_at=now,
        )

    def _replace_governance(
        self, checkpoint: RuntimeCheckpoint, governance: GovernanceResult
    ) -> RuntimeCheckpoint:
        governance_envelope = self._codec.encode("governance", governance)
        stage_results = tuple(
            item.model_copy(update={"output": governance_envelope})
            if item.engine == "governance"
            else item
            for item in checkpoint.stage_results
        )
        resumable = checkpoint.resumable_state
        if resumable is not None:
            resumable = resumable.model_copy(
                update={
                    "stage_results": tuple(
                        item.model_copy(update={"output": governance_envelope})
                        if item.engine == "governance"
                        else item
                        for item in resumable.stage_results
                    ),
                    "updated_at": self._now(),
                }
            )
        return checkpoint.model_copy(
            update={
                "governance_result": governance_envelope,
                "stage_results": stage_results,
                "resumable_state": resumable,
                "version": checkpoint.version + 1,
                "updated_at": self._now(),
            }
        )

    def _governance(self, checkpoint: RuntimeCheckpoint) -> GovernanceResult:
        if checkpoint.governance_result is None:
            raise RuntimeCheckpointConflictError("checkpoint has no governance result")
        value = self._codec.decode(checkpoint.governance_result)
        if not isinstance(value, GovernanceResult):
            raise RuntimeCheckpointConflictError("invalid governance checkpoint")
        return value

    @staticmethod
    def _decision_was_recorded(governance: GovernanceResult, decision_id: UUID) -> bool:
        request = governance.approval_request
        if request is None:
            return False
        return any(
            item.approval_decision_id == decision_id
            for item in (*request.current_approvals, *request.current_rejections)
        )

    @staticmethod
    def _result(
        checkpoint: RuntimeCheckpoint, status: PipelineExecutionStatus
    ) -> AuthenticatedRuntimeResult:
        return AuthenticatedRuntimeResult(
            session_id=checkpoint.session_id,
            organization_id=checkpoint.organization_id,
            plan_id=checkpoint.cognitive_plan.plan_id,
            status=status,
            checkpoint_version=checkpoint.version,
        )

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

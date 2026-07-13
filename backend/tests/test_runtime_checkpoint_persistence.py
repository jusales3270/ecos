"""Sprint 19D phase-one authenticated runtime checkpoint tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ecos.core import Container, Settings
from ecos.domain import CognitiveSession, Objective, SessionStage
from ecos.governance import (
    ApprovalDecision,
    GovernanceResult,
    GovernanceResultStatus,
    HumanDecision,
    UnauthorizedRoleError,
)
from ecos.main import app
from ecos.operational.service import DEMO_OPERATOR, DEMO_ORG_A
from ecos.orchestrator import EngineExecutor, PipelineExecutionStatus
from ecos.runtime import (
    ArtifactEnvelope,
    InvalidArtifactError,
    PostgresRuntimeCheckpointRepository,
    ResumeSessionCommand,
    RuntimeArtifactCodec,
    RuntimeCheckpoint,
    RuntimeCheckpointConflictError,
    RuntimeCheckpointNotFoundError,
    RuntimeCheckpointScopeError,
    RuntimeCheckpointStatus,
    StartExistingSessionCommand,
    UnknownArtifactTypeError,
    UnknownArtifactVersionError,
)
from ecos.security import Role
from ecos.session import (
    ManagedSession,
    SessionContext,
    SessionLifecycleStatus,
    SessionState,
    TransitionType,
)

TEST_DATABASE_URL = os.getenv("ECOS_TEST_DATABASE_URL")


class CountingExecutor(EngineExecutor):
    """Count invocations while preserving a real injected executor."""

    def __init__(self, delegate: EngineExecutor) -> None:
        self.delegate = delegate
        self.calls = 0

    @property
    def engine_type(self) -> str:
        return self.delegate.engine_type

    @property
    def available(self) -> bool:
        return self.delegate.available

    def execute(self, context):
        self.calls += 1
        return self.delegate.execute(context)


@pytest.fixture
def runtime_case() -> tuple[Container, ManagedSession, StartExistingSessionCommand]:
    container = Container(settings=Settings())
    session_id = uuid4()
    correlation_id = uuid4()
    objective = Objective(
        organization_id=DEMO_ORG_A,
        title="Execute a governed authenticated dry run",
    )
    managed = ManagedSession(
        session=CognitiveSession(
            id=session_id,
            organization_id=DEMO_ORG_A,
            objective=objective,
        ),
        state=SessionState(
            session_id=session_id,
            lifecycle_status=SessionLifecycleStatus.CREATED,
            current_stage=SessionStage.CONTEXT,
        ),
        context=SessionContext(
            organization_id=DEMO_ORG_A,
            objective=objective,
            metadata={"authenticated": True},
        ),
    )
    container.session_service.create_session(managed)
    command = StartExistingSessionCommand(
        session_id=session_id,
        organization_id=DEMO_ORG_A,
        user_id=DEMO_OPERATOR,
        correlation_id=correlation_id,
        objective=objective.title,
    )
    return container, managed, command


def test_start_uses_received_session_scope_and_persists_typed_checkpoint(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, managed, command = runtime_case

    result = container.runtime_engine.start_existing_session(command)
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )

    assert result.session_id == managed.session.id == command.session_id
    assert result.organization_id == command.organization_id
    assert result.status is PipelineExecutionStatus.WAITING_APPROVAL
    assert checkpoint is not None
    assert checkpoint.session_id == command.session_id
    assert checkpoint.organization_id == command.organization_id
    assert checkpoint.user_id == command.user_id
    assert checkpoint.correlation_id == command.correlation_id
    assert checkpoint.version == 1
    assert checkpoint.resumable_state is not None
    assert checkpoint.stage_results
    assert all(item.output.artifact_type != "Any" for item in checkpoint.stage_results)
    restored = checkpoint.model_validate(checkpoint.model_dump(mode="json"))
    assert restored == checkpoint


def test_initial_checkpoint_save_failure_marks_session_failed_with_audit(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    persistence_error = RuntimeError("initial checkpoint persistence failed")

    def fail_save(_checkpoint, *, expected_version):
        assert expected_version is None
        raise persistence_error

    monkeypatch.setattr(container.runtime_checkpoint_repository, "save", fail_save)

    with pytest.raises(RuntimeError) as raised:
        container.runtime_engine.start_existing_session(command)

    assert raised.value is persistence_error
    assert (
        container.authenticated_runtime_service.get_checkpoint(
            command.organization_id, command.session_id
        )
        is None
    )
    session = container.session_service.get_session(command.session_id)
    assert session is not None
    assert session.state.lifecycle_status is SessionLifecycleStatus.FAILED
    transitions = container.session_service.get_transitions(command.session_id)
    assert transitions[-1].transition_type is TransitionType.FAIL
    assert transitions[-1].from_status is SessionLifecycleStatus.PAUSED
    assert transitions[-1].to_status is SessionLifecycleStatus.FAILED


def test_initial_compensation_failure_does_not_hide_persistence_error(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    service = container.authenticated_runtime_service
    persistence_error = RuntimeError("original checkpoint failure")

    def fail_save(_checkpoint, *, expected_version):
        assert expected_version is None
        raise persistence_error

    def fail_compensation(_organization_id, _session_id):
        raise RuntimeCheckpointConflictError("compensation failed")

    monkeypatch.setattr(container.runtime_checkpoint_repository, "save", fail_save)
    monkeypatch.setattr(
        service,
        "_record_initial_checkpoint_failure",
        fail_compensation,
    )

    with pytest.raises(RuntimeError) as raised:
        container.runtime_engine.start_existing_session(command)

    assert raised.value is persistence_error


def test_organization_is_required_and_cross_tenant_access_is_blocked(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, _, command = runtime_case
    payload = command.model_dump()
    payload.pop("organization_id")
    with pytest.raises(ValidationError):
        StartExistingSessionCommand.model_validate(payload)

    container.runtime_engine.start_existing_session(command)
    with pytest.raises(RuntimeCheckpointScopeError):
        container.authenticated_runtime_service.get_checkpoint(
            uuid4(), command.session_id
        )
    foreign = command.model_copy(update={"organization_id": uuid4()})
    with pytest.raises(RuntimeCheckpointScopeError):
        container.authenticated_runtime_service.start_existing_session(foreign)


def test_artifact_codec_rejects_unknown_version_type_and_invalid_payload(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, _, command = runtime_case
    container.runtime_engine.start_existing_session(command)
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert checkpoint is not None
    assert checkpoint.governance_result is not None
    codec = RuntimeArtifactCodec()
    governance = codec.decode(checkpoint.governance_result)
    assert isinstance(governance, GovernanceResult)

    with pytest.raises(UnknownArtifactVersionError):
        codec.decode(
            checkpoint.governance_result.model_copy(update={"schema_version": 999})
        )
    with pytest.raises(UnknownArtifactTypeError):
        codec.decode(
            ArtifactEnvelope(
                engine="unknown",
                artifact_type="Unknown",
                schema_version=1,
                payload={},
            )
        )
    with pytest.raises(InvalidArtifactError):
        codec.decode(checkpoint.governance_result.model_copy(update={"payload": {}}))


def test_execute_receives_session_reloaded_after_begin_session(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    original_execute = container.orchestrator_service.execute
    received_statuses: list[SessionLifecycleStatus] = []

    def capture_execute(orchestration_input):
        received_statuses.append(
            orchestration_input.active_session.state.lifecycle_status
        )
        return original_execute(orchestration_input)

    monkeypatch.setattr(container.orchestrator_service, "execute", capture_execute)

    container.runtime_engine.start_existing_session(command)

    assert received_statuses == [SessionLifecycleStatus.PLANNING]


def test_resume_receives_reloaded_executing_session_and_never_paused(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    final_command = _prepare_final_resume(container, command)
    original_resume = container.orchestrator_service.resume
    original_save = container.runtime_checkpoint_repository.save
    received_statuses: list[SessionLifecycleStatus] = []
    save_calls: list[tuple[RuntimeCheckpointStatus, int, int | None]] = []

    def capture_save(checkpoint, *, expected_version):
        stored = original_save(checkpoint, expected_version=expected_version)
        save_calls.append((stored.status, stored.version, expected_version))
        return stored

    def capture_resume(orchestration_input, state):
        received_statuses.append(
            orchestration_input.active_session.state.lifecycle_status
        )
        executing = container.authenticated_runtime_service.get_checkpoint(
            command.organization_id, command.session_id
        )
        assert executing is not None
        assert executing.status is RuntimeCheckpointStatus.EXECUTING
        return original_resume(orchestration_input, state)

    monkeypatch.setattr(container.runtime_checkpoint_repository, "save", capture_save)
    monkeypatch.setattr(container.orchestrator_service, "resume", capture_resume)

    result = container.runtime_engine.resume_session(final_command)

    assert result.status is PipelineExecutionStatus.COMPLETED
    assert received_statuses == [SessionLifecycleStatus.EXECUTING]
    assert SessionLifecycleStatus.PAUSED not in received_statuses
    executing_save = next(
        item for item in save_calls if item[0] is RuntimeCheckpointStatus.EXECUTING
    )
    completed_save = next(
        item for item in save_calls if item[0] is RuntimeCheckpointStatus.COMPLETED
    )
    assert executing_save[2] == executing_save[1] - 1
    assert completed_save[2] == executing_save[1]
    assert completed_save[1] == executing_save[1] + 1
    completed = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert completed is not None
    assert completed.status is RuntimeCheckpointStatus.COMPLETED
    completed_session = container.session_service.get_session(command.session_id)
    assert completed_session is not None
    assert completed_session.state.lifecycle_status is SessionLifecycleStatus.COMPLETED


def test_resume_waits_for_quorum_does_not_repeat_stages_and_executes_once(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, _, start_command = runtime_case
    shared_service = container.orchestrator_service
    shared_orchestrator = container.orchestrator_service._orchestrator
    context_counter = CountingExecutor(container.orchestrator._executors["context"])
    execution_counter = CountingExecutor(container.orchestrator._executors["execution"])
    container.orchestrator._executors["context"] = context_counter
    container.orchestrator._executors["execution"] = execution_counter

    started = container.runtime_engine.start_existing_session(start_command)
    assert started.status is PipelineExecutionStatus.WAITING_APPROVAL
    assert execution_counter.calls == 0
    assert context_counter.calls == 1
    assert container.orchestrator_service is shared_service
    assert container.orchestrator_service._orchestrator is shared_orchestrator

    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        start_command.organization_id, start_command.session_id
    )
    assert checkpoint is not None
    governance = _governance(container, checkpoint.governance_result)
    request = governance.approval_request
    assert request is not None
    assert request.minimum_approvals == 3

    approvers = _create_board_approvers(container, request.minimum_approvals)
    final_command: ResumeSessionCommand | None = None
    for index, approver_id in enumerate(approvers, start=1):
        decision = ApprovalDecision(
            approval_decision_id=uuid4(),
            approval_request_id=request.approval_request_id,
            organization_id=start_command.organization_id,
            session_id=start_command.session_id,
            plan_id=checkpoint.cognitive_plan.plan_id,
            actor_id=approver_id,
            actor_role=Role.EXECUTIVE_BOARD.value,
            decision=HumanDecision.APPROVE,
            decided_at=datetime.now(UTC),
            identity_reference=f"local:{approver_id}",
        )
        resume_command = ResumeSessionCommand.model_validate(
            {
                **start_command.model_dump(),
                "user_id": approver_id,
                "correlation_id": uuid4(),
                "approval_decision": decision,
            }
        )
        resumed = container.runtime_engine.resume_session(resume_command)
        current = container.authenticated_runtime_service.get_checkpoint(
            start_command.organization_id, start_command.session_id
        )
        assert current is not None
        current_governance = _governance(container, current.governance_result)
        if index < request.minimum_approvals:
            assert resumed.status is PipelineExecutionStatus.WAITING_APPROVAL
            assert current_governance.status is not GovernanceResultStatus.AUTHORIZED
            assert execution_counter.calls == 0
        else:
            final_command = resume_command
            assert resumed.status is PipelineExecutionStatus.COMPLETED
            assert current_governance.status is GovernanceResultStatus.AUTHORIZED
            assert current_governance.execution_authorized is True

    assert context_counter.calls == 1
    assert execution_counter.calls == 1
    assert container.orchestrator_service is shared_service
    assert container.orchestrator_service._orchestrator is shared_orchestrator
    assert final_command is not None
    completed = container.authenticated_runtime_service.get_checkpoint(
        start_command.organization_id, start_command.session_id
    )
    assert completed is not None
    transitions_before = container.session_service.get_transitions(
        start_command.session_id
    )

    replay = container.runtime_engine.resume_session(final_command)

    replayed_checkpoint = container.authenticated_runtime_service.get_checkpoint(
        start_command.organization_id, start_command.session_id
    )
    assert replay.status is PipelineExecutionStatus.COMPLETED
    assert replay.checkpoint_version == completed.version
    assert replayed_checkpoint == completed
    assert execution_counter.calls == 1
    assert context_counter.calls == 1
    assert (
        container.session_service.get_transitions(start_command.session_id)
        == transitions_before
    )


@pytest.mark.parametrize(
    "terminal_status",
    [RuntimeCheckpointStatus.COMPLETED, RuntimeCheckpointStatus.FAILED],
)
def test_terminal_checkpoint_cannot_be_resumed_with_a_new_decision(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    terminal_status: RuntimeCheckpointStatus,
) -> None:
    container, _, command = runtime_case
    execution_counter = CountingExecutor(container.orchestrator._executors["execution"])
    container.orchestrator._executors["execution"] = execution_counter
    container.runtime_engine.start_existing_session(command)
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert checkpoint is not None
    governance = _governance(container, checkpoint.governance_result)
    request = governance.approval_request
    assert request is not None
    terminal = checkpoint.model_copy(
        update={
            "status": terminal_status,
            "version": checkpoint.version + 1,
            "updated_at": datetime.now(UTC),
        }
    )
    container.runtime_checkpoint_repository.save(
        terminal,
        expected_version=checkpoint.version,
    )
    approver_id = _create_board_approvers(container, 1)[0]
    resume_command = _resume_command(
        command,
        approver_id,
        _approval_decision(
            command, checkpoint, request.approval_request_id, approver_id
        ),
    )

    with pytest.raises(RuntimeCheckpointConflictError, match="cannot be resumed"):
        container.runtime_engine.resume_session(resume_command)

    assert execution_counter.calls == 0
    assert (
        container.authenticated_runtime_service.get_checkpoint(
            command.organization_id, command.session_id
        )
        == terminal
    )


def test_pause_is_idempotent_when_session_is_already_paused(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, _, command = runtime_case
    service = container.authenticated_runtime_service
    container.runtime_engine.start_existing_session(command)
    current = container.session_service.get_session(command.session_id)
    assert current is not None
    assert current.state.lifecycle_status is SessionLifecycleStatus.PAUSED
    initial_transitions = container.session_service.get_transitions(command.session_id)
    assert all(
        item.transition_type is not TransitionType.PAUSE for item in initial_transitions
    )

    service._record_pause(command.organization_id, command.session_id)
    assert container.session_service.get_transitions(command.session_id) == (
        initial_transitions
    )


@pytest.mark.parametrize(
    "lifecycle_status",
    [SessionLifecycleStatus.PLANNING, SessionLifecycleStatus.COMPLETED],
)
def test_pause_rejects_incompatible_current_session_state(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    lifecycle_status: SessionLifecycleStatus,
) -> None:
    container, managed, command = runtime_case
    container.session_service.update_state(
        managed.state.model_copy(update={"lifecycle_status": lifecycle_status})
    )

    with pytest.raises(RuntimeCheckpointConflictError, match="cannot pause"):
        container.authenticated_runtime_service._record_pause(
            command.organization_id, command.session_id
        )

    assert container.session_service.get_transitions(command.session_id) == []


@pytest.mark.parametrize(
    "lifecycle_status",
    [SessionLifecycleStatus.PLANNING, SessionLifecycleStatus.COMPLETED],
)
def test_resume_rejects_incompatible_current_session_state(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    lifecycle_status: SessionLifecycleStatus,
) -> None:
    container, managed, command = runtime_case
    container.session_service.update_state(
        managed.state.model_copy(update={"lifecycle_status": lifecycle_status})
    )

    with pytest.raises(RuntimeCheckpointConflictError, match="cannot resume"):
        container.authenticated_runtime_service._record_resume(
            command.organization_id, command.session_id
        )

    assert container.session_service.get_transitions(command.session_id) == []


def test_paused_session_records_resume_to_executing(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, managed, command = runtime_case
    container.session_service.update_state(
        managed.state.model_copy(
            update={"lifecycle_status": SessionLifecycleStatus.PAUSED}
        )
    )

    should_resume = container.authenticated_runtime_service._record_resume(
        command.organization_id, command.session_id
    )

    assert should_resume is True
    transitions = container.session_service.get_transitions(command.session_id)
    assert transitions[-1].transition_type is TransitionType.RESUME
    assert transitions[-1].from_status is SessionLifecycleStatus.PAUSED
    assert transitions[-1].to_status is SessionLifecycleStatus.EXECUTING


def test_executing_session_requires_proven_idempotent_resume_replay(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, managed, command = runtime_case
    service = container.authenticated_runtime_service
    container.session_service.update_state(
        managed.state.model_copy(
            update={"lifecycle_status": SessionLifecycleStatus.EXECUTING}
        )
    )

    with pytest.raises(RuntimeCheckpointConflictError, match="proven replay"):
        service._record_resume(command.organization_id, command.session_id)

    should_resume = service._record_resume(
        command.organization_id,
        command.session_id,
        idempotent_replay=True,
    )
    assert should_resume is False
    assert container.session_service.get_transitions(command.session_id) == []


def test_record_failure_transitions_executing_session_to_failed(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, managed, command = runtime_case
    container.session_service.update_state(
        managed.state.model_copy(
            update={"lifecycle_status": SessionLifecycleStatus.EXECUTING}
        )
    )

    container.authenticated_runtime_service._record_failure(
        command.organization_id, command.session_id
    )

    session = container.session_service.get_session(command.session_id)
    assert session is not None
    assert session.state.lifecycle_status is SessionLifecycleStatus.FAILED
    transitions = container.session_service.get_transitions(command.session_id)
    assert transitions[-1].transition_type is TransitionType.FAIL
    assert transitions[-1].from_status is SessionLifecycleStatus.EXECUTING
    assert transitions[-1].to_status is SessionLifecycleStatus.FAILED


def test_record_failure_is_idempotent_for_failed_session(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, managed, command = runtime_case
    container.session_service.update_state(
        managed.state.model_copy(
            update={"lifecycle_status": SessionLifecycleStatus.FAILED}
        )
    )

    container.authenticated_runtime_service._record_failure(
        command.organization_id, command.session_id
    )
    container.authenticated_runtime_service._record_failure(
        command.organization_id, command.session_id
    )

    assert container.session_service.get_transitions(command.session_id) == []


@pytest.mark.parametrize(
    "lifecycle_status",
    [
        SessionLifecycleStatus.PAUSED,
        SessionLifecycleStatus.PLANNING,
        SessionLifecycleStatus.COMPLETED,
    ],
)
def test_record_failure_rejects_incompatible_session_state(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    lifecycle_status: SessionLifecycleStatus,
) -> None:
    container, managed, command = runtime_case
    container.session_service.update_state(
        managed.state.model_copy(update={"lifecycle_status": lifecycle_status})
    )

    with pytest.raises(RuntimeCheckpointConflictError, match="cannot fail"):
        container.authenticated_runtime_service._record_failure(
            command.organization_id, command.session_id
        )

    assert container.session_service.get_transitions(command.session_id) == []


def test_idempotent_replay_in_executing_state_does_not_call_orchestrator(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    final_command = _prepare_final_resume(container, command)
    service = container.authenticated_runtime_service
    original_scoped_session = service._scoped_session
    scoped_session_calls = 0
    orchestrator_resume_calls = 0

    def fail_post_claim_reload(organization_id, session_id):
        nonlocal scoped_session_calls
        scoped_session_calls += 1
        if scoped_session_calls == 3:
            raise RuntimeCheckpointNotFoundError(
                "session unavailable after executing checkpoint"
            )
        return original_scoped_session(organization_id, session_id)

    def count_resume(*_args, **_kwargs):
        nonlocal orchestrator_resume_calls
        orchestrator_resume_calls += 1
        raise AssertionError("orchestrator resume must not be called")

    monkeypatch.setattr(service, "_scoped_session", fail_post_claim_reload)
    monkeypatch.setattr(container.orchestrator_service, "resume", count_resume)

    with pytest.raises(RuntimeCheckpointNotFoundError, match="unavailable"):
        container.runtime_engine.resume_session(final_command)

    executing = service.get_checkpoint(command.organization_id, command.session_id)
    assert executing is not None
    assert executing.status is RuntimeCheckpointStatus.EXECUTING
    current = container.session_service.get_session(command.session_id)
    assert current is not None
    assert current.state.lifecycle_status is SessionLifecycleStatus.EXECUTING

    monkeypatch.setattr(service, "_scoped_session", original_scoped_session)
    replay = container.runtime_engine.resume_session(final_command)

    assert replay.status is PipelineExecutionStatus.RUNNING
    assert replay.checkpoint_version == executing.version
    assert orchestrator_resume_calls == 0


def test_different_decision_in_executing_checkpoint_is_rejected(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    final_command = _prepare_final_resume(container, command)
    service = container.authenticated_runtime_service
    original_scoped_session = service._scoped_session
    scoped_session_calls = 0

    def fail_post_claim_reload(organization_id, session_id):
        nonlocal scoped_session_calls
        scoped_session_calls += 1
        if scoped_session_calls == 3:
            raise RuntimeCheckpointNotFoundError("stop after execution claim")
        return original_scoped_session(organization_id, session_id)

    monkeypatch.setattr(service, "_scoped_session", fail_post_claim_reload)
    with pytest.raises(RuntimeCheckpointNotFoundError, match="execution claim"):
        container.runtime_engine.resume_session(final_command)
    monkeypatch.setattr(service, "_scoped_session", original_scoped_session)
    different = final_command.model_copy(
        update={
            "approval_decision": final_command.approval_decision.model_copy(
                update={"approval_decision_id": uuid4()}
            )
        }
    )

    with pytest.raises(RuntimeCheckpointConflictError, match="different decision"):
        container.runtime_engine.resume_session(different)


def test_executing_checkpoint_persistence_failure_prevents_execution(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    final_command = _prepare_final_resume(container, command)
    repository = container.runtime_checkpoint_repository
    original_save = repository.save
    orchestrator_resume_calls = 0

    def reject_executing(checkpoint, *, expected_version):
        if checkpoint.status is RuntimeCheckpointStatus.EXECUTING:
            raise RuntimeCheckpointConflictError("execution claim conflict")
        return original_save(checkpoint, expected_version=expected_version)

    def count_resume(*_args, **_kwargs):
        nonlocal orchestrator_resume_calls
        orchestrator_resume_calls += 1
        raise AssertionError("orchestrator resume must not be called")

    monkeypatch.setattr(repository, "save", reject_executing)
    monkeypatch.setattr(container.orchestrator_service, "resume", count_resume)

    with pytest.raises(RuntimeCheckpointConflictError, match="claim conflict"):
        container.runtime_engine.resume_session(final_command)

    assert orchestrator_resume_calls == 0
    waiting = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert waiting is not None
    assert waiting.status is RuntimeCheckpointStatus.WAITING_APPROVAL
    session = container.session_service.get_session(command.session_id)
    assert session is not None
    assert session.state.lifecycle_status is SessionLifecycleStatus.PAUSED


def test_orchestrator_exception_persists_failed_checkpoint_and_session(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    final_command = _prepare_final_resume(container, command)

    def fail_resume(*_args, **_kwargs):
        executing = container.authenticated_runtime_service.get_checkpoint(
            command.organization_id, command.session_id
        )
        assert executing is not None
        assert executing.status is RuntimeCheckpointStatus.EXECUTING
        raise RuntimeError("orchestrator resume failed")

    monkeypatch.setattr(container.orchestrator_service, "resume", fail_resume)

    with pytest.raises(RuntimeError, match="orchestrator resume failed"):
        container.runtime_engine.resume_session(final_command)

    failed = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert failed is not None
    assert failed.status is RuntimeCheckpointStatus.FAILED
    session = container.session_service.get_session(command.session_id)
    assert session is not None
    assert session.state.lifecycle_status is SessionLifecycleStatus.FAILED


def test_final_checkpoint_save_failure_keeps_execution_lock_and_blocks_replay(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    final_command = _prepare_final_resume(container, command)
    repository = container.runtime_checkpoint_repository
    original_save = repository.save
    original_resume = container.orchestrator_service.resume
    persistence_error = RuntimeError("final checkpoint persistence failed")
    orchestrator_resume_calls = 0

    def fail_completed_save(checkpoint, *, expected_version):
        if checkpoint.status is RuntimeCheckpointStatus.COMPLETED:
            raise persistence_error
        return original_save(checkpoint, expected_version=expected_version)

    def count_resume(orchestration_input, state):
        nonlocal orchestrator_resume_calls
        orchestrator_resume_calls += 1
        return original_resume(orchestration_input, state)

    monkeypatch.setattr(repository, "save", fail_completed_save)
    monkeypatch.setattr(container.orchestrator_service, "resume", count_resume)

    with pytest.raises(RuntimeError) as raised:
        container.runtime_engine.resume_session(final_command)

    assert raised.value is persistence_error
    executing = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert executing is not None
    assert executing.status is RuntimeCheckpointStatus.EXECUTING
    session = container.session_service.get_session(command.session_id)
    assert session is not None
    assert session.state.lifecycle_status is SessionLifecycleStatus.COMPLETED

    replay = container.runtime_engine.resume_session(final_command)

    assert replay.status is PipelineExecutionStatus.RUNNING
    assert replay.checkpoint_version == executing.version
    assert orchestrator_resume_calls == 1


def test_reload_failure_after_resume_transition_prevents_orchestrator_call(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    final_command = _prepare_final_resume(container, command)
    service = container.authenticated_runtime_service
    original_scoped_session = service._scoped_session
    scoped_session_calls = 0
    orchestrator_resume_calls = 0

    def fail_post_transition_reload(organization_id, session_id):
        nonlocal scoped_session_calls
        scoped_session_calls += 1
        if scoped_session_calls == 3:
            raise RuntimeCheckpointNotFoundError(
                "session unavailable after resume transition"
            )
        return original_scoped_session(organization_id, session_id)

    def count_orchestrator_resume(*_args, **_kwargs):
        nonlocal orchestrator_resume_calls
        orchestrator_resume_calls += 1
        raise AssertionError("orchestrator resume must not be called")

    monkeypatch.setattr(service, "_scoped_session", fail_post_transition_reload)
    monkeypatch.setattr(
        container.orchestrator_service, "resume", count_orchestrator_resume
    )

    with pytest.raises(RuntimeCheckpointNotFoundError, match="unavailable"):
        container.runtime_engine.resume_session(final_command)

    assert orchestrator_resume_calls == 0


def test_transition_failure_prevents_orchestrator_resume(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, command = runtime_case
    container.runtime_engine.start_existing_session(command)
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert checkpoint is not None
    governance = _governance(container, checkpoint.governance_result)
    request = governance.approval_request
    assert request is not None
    approvers = _create_board_approvers(container, request.minimum_approvals)

    for approver_id in approvers[:-1]:
        container.runtime_engine.resume_session(
            _resume_command(
                command,
                approver_id,
                _approval_decision(
                    command,
                    checkpoint,
                    request.approval_request_id,
                    approver_id,
                ),
            )
        )

    orchestrator_resume_calls = 0

    def fail_transition(_transition) -> None:
        raise RuntimeCheckpointConflictError("session transition failed")

    def count_orchestrator_resume(*_args, **_kwargs):
        nonlocal orchestrator_resume_calls
        orchestrator_resume_calls += 1
        raise AssertionError("orchestrator resume must not be called")

    monkeypatch.setattr(container.session_service, "record_transition", fail_transition)
    monkeypatch.setattr(
        container.orchestrator_service, "resume", count_orchestrator_resume
    )
    final_approver = approvers[-1]
    final_command = _resume_command(
        command,
        final_approver,
        _approval_decision(
            command,
            checkpoint,
            request.approval_request_id,
            final_approver,
        ),
    )

    with pytest.raises(RuntimeCheckpointConflictError, match="transition failed"):
        container.runtime_engine.resume_session(final_command)

    assert orchestrator_resume_calls == 0


def test_pause_and_resume_read_the_latest_session_state(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, _, command = runtime_case
    service = container.authenticated_runtime_service
    container.runtime_engine.start_existing_session(command)
    current = container.session_service.get_session(command.session_id)
    assert current is not None

    service._record_resume(command.organization_id, command.session_id)
    resumed_transitions = container.session_service.get_transitions(command.session_id)
    assert resumed_transitions[-1].transition_type is TransitionType.RESUME
    assert resumed_transitions[-1].from_status is SessionLifecycleStatus.PAUSED
    assert resumed_transitions[-1].to_status is SessionLifecycleStatus.EXECUTING

    completed_state = current.state.model_copy(
        update={
            "lifecycle_status": SessionLifecycleStatus.COMPLETED,
            "updated_at": datetime.now(UTC),
        }
    )
    container.session_service.update_state(completed_state)
    with pytest.raises(RuntimeCheckpointConflictError, match="cannot pause"):
        service._record_pause(command.organization_id, command.session_id)
    with pytest.raises(RuntimeCheckpointConflictError, match="cannot resume"):
        service._record_resume(command.organization_id, command.session_id)
    assert (
        container.session_service.get_transitions(command.session_id)
        == resumed_transitions
    )


def test_requester_cannot_satisfy_own_approval(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
) -> None:
    container, _, command = runtime_case
    container.runtime_engine.start_existing_session(command)
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert checkpoint is not None
    governance = _governance(container, checkpoint.governance_result)
    request = governance.approval_request
    assert request is not None
    decision = ApprovalDecision(
        approval_decision_id=uuid4(),
        approval_request_id=request.approval_request_id,
        organization_id=command.organization_id,
        session_id=command.session_id,
        plan_id=checkpoint.cognitive_plan.plan_id,
        actor_id=command.user_id,
        actor_role=Role.OPERATOR.value,
        decision=HumanDecision.APPROVE,
        decided_at=datetime.now(UTC),
        identity_reference=f"local:{command.user_id}",
    )
    with pytest.raises(UnauthorizedRoleError, match="role|requester"):
        container.runtime_engine.resume_session(
            ResumeSessionCommand(
                **command.model_dump(),
                approval_decision=decision,
            )
        )


def test_runtime_demo_contract_is_unchanged() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/runtime/demo",
            json={"objective": "Improve organizational decision quality"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": response.json()["session_id"],
        "status": "completed",
        "recommendation": (
            "Proceed using ECOS context, reasoning, debate and governance."
        ),
        "confidence": 0.91,
    }
    UUID(response.json()["session_id"])


@pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)
def test_postgres_checkpoint_repository_round_trip(
    runtime_case: tuple[Container, ManagedSession, StartExistingSessionCommand],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert TEST_DATABASE_URL is not None
    container, _, start_command = runtime_case
    container.runtime_engine.start_existing_session(start_command)
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        start_command.organization_id, start_command.session_id
    )
    assert checkpoint is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", TEST_DATABASE_URL)
    config = Config("alembic.ini")
    alembic_command.upgrade(config, "head")
    repository = PostgresRuntimeCheckpointRepository(
        TEST_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    try:
        stored = repository.save(checkpoint, expected_version=None)
        assert (
            repository.get(checkpoint.organization_id, checkpoint.session_id) == stored
        )
        with pytest.raises(RuntimeCheckpointScopeError):
            repository.get(uuid4(), checkpoint.session_id)
    finally:
        alembic_command.downgrade(config, "base")


def _governance(
    container: Container, envelope: ArtifactEnvelope | None
) -> GovernanceResult:
    assert envelope is not None
    value = container.runtime_artifact_codec.decode(envelope)
    assert isinstance(value, GovernanceResult)
    return value


def _create_board_approvers(container: Container, count: int) -> tuple[UUID, ...]:
    values: list[UUID] = []
    for index in range(count):
        user_id = uuid4()
        container.security_service.create_local_user(
            email=f"board-{user_id}@example.test",
            display_name=f"Board approver {index}",
            password="board-test-password",
            organization_name="ECOS Demo Organization",
            roles=(Role.EXECUTIVE_BOARD,),
            user_id=user_id,
            organization_id=DEMO_ORG_A,
        )
        values.append(user_id)
    return tuple(values)


def _approval_decision(
    command: StartExistingSessionCommand,
    checkpoint: RuntimeCheckpoint,
    approval_request_id: UUID,
    approver_id: UUID,
) -> ApprovalDecision:
    return ApprovalDecision(
        approval_decision_id=uuid4(),
        approval_request_id=approval_request_id,
        organization_id=command.organization_id,
        session_id=command.session_id,
        plan_id=checkpoint.cognitive_plan.plan_id,
        actor_id=approver_id,
        actor_role=Role.EXECUTIVE_BOARD.value,
        decision=HumanDecision.APPROVE,
        decided_at=datetime.now(UTC),
        identity_reference=f"local:{approver_id}",
    )


def _resume_command(
    command: StartExistingSessionCommand,
    approver_id: UUID,
    decision: ApprovalDecision,
) -> ResumeSessionCommand:
    return ResumeSessionCommand.model_validate(
        {
            **command.model_dump(),
            "user_id": approver_id,
            "correlation_id": uuid4(),
            "approval_decision": decision,
        }
    )


def _prepare_final_resume(
    container: Container,
    command: StartExistingSessionCommand,
) -> ResumeSessionCommand:
    container.runtime_engine.start_existing_session(command)
    checkpoint = container.authenticated_runtime_service.get_checkpoint(
        command.organization_id, command.session_id
    )
    assert checkpoint is not None
    governance = _governance(container, checkpoint.governance_result)
    request = governance.approval_request
    assert request is not None
    approvers = _create_board_approvers(container, request.minimum_approvals)
    commands = tuple(
        _resume_command(
            command,
            approver_id,
            _approval_decision(
                command,
                checkpoint,
                request.approval_request_id,
                approver_id,
            ),
        )
        for approver_id in approvers
    )
    for resume_command in commands[:-1]:
        result = container.runtime_engine.resume_session(resume_command)
        assert result.status is PipelineExecutionStatus.WAITING_APPROVAL
    return commands[-1]

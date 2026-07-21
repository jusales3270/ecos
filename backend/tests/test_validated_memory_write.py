"""Validated Learning memory idempotency and crash-recovery tests."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from ecos.events import EventService, EventType
from ecos.execution import (
    ExecutionMode,
    ExecutionResult,
    ExecutionStatus,
    deterministic_fingerprint,
)
from ecos.execution.postgres_repository import PostgresExecutionResultRepository
from ecos.learning import (
    InMemoryLearningRepository,
    LearningConflictError,
    LearningRequest,
    LearningService,
    PostgresLearningRepository,
)
from ecos.memory import (
    MemoryService,
    MemoryType,
    PostgresMemoryRepository,
    ValidatedMemoryConflictError,
    ValidatedMemoryWrite,
    validated_memory_fingerprint,
)
from ecos.observation import (
    ObservationQuality,
    ObservationResult,
    ObservationSourceType,
    ObservedOutcome,
    ObservedOutcomeStatus,
    PostgresObservationRepository,
)
from ecos.outbox import OutboxService, PostgresOutboxRepository
from ecos.runtime import FakeEventBus, FakeMemoryRepository

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
DATABASE_URL = os.getenv("ECOS_TEST_DATABASE_URL")


class FailFirstCompleteRepository(InMemoryLearningRepository):
    """Simulate a crash after memory storage and before Learning completion."""

    def __init__(self) -> None:
        super().__init__(lease_duration=timedelta(0), clock=lambda: NOW)
        self.fail_complete = True

    def complete(self, **kwargs):
        if self.fail_complete:
            self.fail_complete = False
            raise RuntimeError("simulated crash before Learning completion")
        return super().complete(**kwargs)


class AllowCanonicalWrite:
    """Storage-only test authority; Learning authority is tested separately."""

    def validate_memory_write(self, write: ValidatedMemoryWrite) -> None:
        del write


class FailFirstPostgresCompleteRepository(PostgresLearningRepository):
    """PostgreSQL Learning repository with one injected post-memory crash."""

    def __init__(self, database_url: str) -> None:
        super().__init__(database_url, lease_duration=timedelta(0))
        self.fail_complete = True

    def complete(self, **kwargs):
        if self.fail_complete:
            self.fail_complete = False
            raise RuntimeError("simulated postgres crash before Learning completion")
        return super().complete(**kwargs)


def _request() -> LearningRequest:
    organization_id = uuid4()
    session_id = uuid4()
    plan_id = uuid4()
    correlation_id = uuid4()
    execution_id = uuid4()
    observation = ObservationResult(
        observation_id=uuid4(),
        observation_request_id=uuid4(),
        organization_id=organization_id,
        session_id=session_id,
        plan_id=plan_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        source_type=ObservationSourceType.EXECUTION_RESULT,
        source_id=f"execution:{execution_id}",
        status=ObservedOutcomeStatus.SUCCESSFUL,
        fingerprint="a" * 64,
        execution_result_fingerprint="b" * 64,
        observed_outcomes=(
            ObservedOutcome(
                outcome_id="outcome:success",
                status=ObservedOutcomeStatus.SUCCESSFUL,
                score=1.0,
                confidence=0.95,
                evidence_references=("evidence:verified",),
            ),
        ),
        comparisons=(),
        deviations=(),
        anomalies=(),
        measurements=(),
        evidence=(),
        feedback=(),
        quality=ObservationQuality(
            completeness_score=1.0,
            evidence_quality_score=1.0,
            source_reliability_score=1.0,
            timeliness_score=1.0,
            consistency_score=1.0,
            verified_measurement_ratio=1.0,
        ),
        outcome_score=1.0,
        confidence=0.95,
        started_at=NOW,
        completed_at=NOW,
        duration=0.0,
        timeline=(),
    )
    execution = ExecutionResult(
        execution_id=execution_id,
        execution_request_id=uuid4(),
        execution_plan_id=uuid4(),
        organization_id=organization_id,
        session_id=session_id,
        plan_id=plan_id,
        correlation_id=correlation_id,
        status=ExecutionStatus.COMPLETED,
        fingerprint="b" * 64,
        mode=ExecutionMode.DRY_RUN,
        started_at=NOW,
        completed_at=NOW,
        duration=0.0,
        idempotency_key=f"validated-memory:{execution_id}",
        authorization_id=uuid4(),
    )
    return LearningRequest(
        learning_request_id=uuid4(),
        organization_id=organization_id,
        session_id=session_id,
        plan_id=plan_id,
        execution_id=execution_id,
        observation_id=observation.observation_id,
        correlation_id=correlation_id,
        observation_result=observation,
        execution_result=execution,
    )


def test_crash_after_memory_store_reuses_memory_and_completes_learning() -> None:
    memory_repository = FakeMemoryRepository()
    learning_repository = FailFirstCompleteRepository()
    bus = FakeEventBus()
    service = LearningService(
        MemoryService(memory_repository),
        EventService(bus),
        repository=learning_repository,
        clock=lambda: NOW,
    )
    request = _request()

    with pytest.raises(RuntimeError, match="simulated crash"):
        service.process(request)
    first_memory = memory_repository.list()[0]
    service._candidates = lambda _: pytest.fail("candidate provider reran on replay")

    result = service.process(request)

    assert memory_repository.list() == [first_memory]
    assert result.stored_memory_references == (str(first_memory.id),)
    assert first_memory.organization_id == request.organization_id
    assert first_memory.execution_id == request.execution_id
    assert first_memory.observation_id == request.observation_id
    assert first_memory.learning_id == result.learning_id
    assert first_memory.correlation_id == request.correlation_id
    assert first_memory.proposal_id == result.memory_update_proposals[0].proposal_id
    assert first_memory.validation_status == "validated"
    assert first_memory.validated_write_fingerprint is not None
    assert (
        sum(
            envelope.event.event_type is EventType.MEMORY_UPDATED
            for envelope in bus.envelopes
        )
        == 1
    )


def test_forged_validated_write_is_rejected_by_canonical_authority() -> None:
    memory_repository = FakeMemoryRepository()
    learning_repository = InMemoryLearningRepository()
    memory_service = MemoryService(memory_repository, learning_repository)
    service = LearningService(
        memory_service,
        EventService(FakeEventBus()),
        repository=learning_repository,
        clock=lambda: NOW,
    )
    result = service.process(_request())
    memory = memory_repository.list()[0]
    forged = ValidatedMemoryWrite(
        organization_id=memory.organization_id,
        session_id=memory.session_id,
        execution_id=memory.execution_id,
        correlation_id=memory.correlation_id,
        observation_id=memory.observation_id,
        learning_id=memory.learning_id,
        candidate_id=memory.learning_candidate_id,
        proposal_id=memory.proposal_id,
        policy_version=memory.policy_version,
        validation_status="validated",
        memory_type=memory.type,
        content=result.memory_update_proposals[0].content,
        tags=tuple(memory.tags),
        confidence=memory.confidence,
        evidence_references=tuple(memory.evidence_references or ()),
        source_references=tuple(memory.source_references or ()),
        fingerprint="f" * 64,
    )

    with pytest.raises(LearningConflictError):
        memory_service.store_validated(forged)
    assert memory_repository.list() == [memory]


def test_inconclusive_candidate_does_not_create_memory() -> None:
    request = _request()
    inconclusive_outcome = request.observation_result.observed_outcomes[0].model_copy(
        update={"status": ObservedOutcomeStatus.INCONCLUSIVE}
    )
    observation = request.observation_result.model_copy(
        update={
            "status": ObservedOutcomeStatus.INCONCLUSIVE,
            "observed_outcomes": (inconclusive_outcome,),
        }
    )
    request = request.model_copy(update={"observation_result": observation})
    repository = FakeMemoryRepository()
    service = LearningService(
        MemoryService(repository), EventService(FakeEventBus()), clock=lambda: NOW
    )

    result = service.process(request)

    assert result.validated_candidates == ()
    assert result.stored_memory_references == ()
    assert repository.list() == []


def _validated_write(
    *, organization_id: UUID | None = None, proposal_id: UUID | None = None
) -> ValidatedMemoryWrite:
    values = {
        "organization_id": organization_id or uuid4(),
        "session_id": uuid4(),
        "execution_id": uuid4(),
        "correlation_id": uuid4(),
        "observation_id": uuid4(),
        "learning_id": uuid4(),
        "candidate_id": uuid4(),
        "proposal_id": proposal_id or uuid4(),
        "policy_version": "learning-config-v1",
        "validation_status": "validated",
        "memory_type": MemoryType.EPISODIC,
        "content": {"statement": {"type": "verified_outcome"}},
        "tags": ("learning", "validated", "v1"),
        "confidence": 0.91,
        "evidence_references": ("evidence:1",),
        "source_references": ("observation:1",),
    }
    return ValidatedMemoryWrite(
        **values, fingerprint=validated_memory_fingerprint(**values)
    )


@pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL is not configured")
def test_postgres_validated_write_concurrency_provenance_and_tenant_scope() -> None:
    assert DATABASE_URL is not None
    command.upgrade(Config("alembic.ini"), "head")
    url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    repository = PostgresMemoryRepository(url)
    concurrent_repository = PostgresMemoryRepository(url)
    service = MemoryService(repository, AllowCanonicalWrite())
    concurrent_service = MemoryService(concurrent_repository, AllowCanonicalWrite())
    write = _validated_write()
    other_tenant = _validated_write(
        organization_id=uuid4(), proposal_id=write.proposal_id
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (
                pool.submit(service.store_validated, write),
                pool.submit(concurrent_service.store_validated, write),
            )
            results = [future.result(timeout=10) for future in futures]
        assert {result.memory.id for result in results} == {results[0].memory.id}
        assert sum(result.created for result in results) == 1
        memory = results[0].memory
        assert memory.organization_id == write.organization_id
        assert memory.session_id == write.session_id
        assert memory.execution_id == write.execution_id
        assert memory.correlation_id == write.correlation_id
        assert memory.observation_id == write.observation_id
        assert memory.learning_id == write.learning_id
        assert memory.learning_candidate_id == write.candidate_id
        assert memory.proposal_id == write.proposal_id
        assert memory.evidence_references == list(write.evidence_references)
        assert memory.source_references == list(write.source_references)
        assert memory.validated_write_fingerprint == write.fingerprint
        assert repository.list(organization_id=uuid4()) == []

        other = service.store_validated(other_tenant)
        assert other.memory.id != memory.id
        assert repository.list(organization_id=write.organization_id) == [memory]
        assert repository.list(organization_id=other_tenant.organization_id) == [
            other.memory
        ]

        with pytest.raises(ValidatedMemoryConflictError):
            service.store_validated(write.model_copy(update={"fingerprint": "f" * 64}))
    finally:
        for memory in repository.list(organization_id=write.organization_id):
            repository.delete(memory.id)
        if "other" in locals():
            repository.delete(other.memory.id)
        asyncio.run(repository.engine.dispose())
        asyncio.run(concurrent_repository.engine.dispose())


@pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL is not configured")
def test_postgres_crash_replay_reuses_exact_memory_and_completes() -> None:
    assert DATABASE_URL is not None
    command.upgrade(Config("alembic.ini"), "head")
    url = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    request = _request()
    execution = request.execution_result
    assert isinstance(execution, ExecutionResult)
    execution = execution.model_copy(
        update={
            "fingerprint": deterministic_fingerprint(
                execution.model_dump(mode="json", exclude={"fingerprint"})
            )
        }
    )
    observation = request.observation_result.model_copy(
        update={"execution_result_fingerprint": execution.fingerprint}
    )
    request = request.model_copy(
        update={"execution_result": execution, "observation_result": observation}
    )

    execution_repository = PostgresExecutionResultRepository(url)
    observation_repository = PostgresObservationRepository(url)
    learning_repository = FailFirstPostgresCompleteRepository(url)
    memory_repository = PostgresMemoryRepository(url)

    async def seed() -> None:
        async with execution_repository.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO sessions "
                    "(id, managed_id, session_data, context_data, organization_id) "
                    "VALUES (:id, :managed_id, '{}'::jsonb, '{}'::jsonb, :org)"
                ),
                {
                    "id": execution.session_id,
                    "managed_id": uuid4(),
                    "org": execution.organization_id,
                },
            )

    asyncio.run(seed())
    execution_repository.save(execution)
    observation_repository.save(request.observation_result)
    bus = FakeEventBus()
    service = LearningService(
        MemoryService(memory_repository),
        EventService(bus),
        repository=learning_repository,
        observation_repository=observation_repository,
        clock=lambda: NOW,
    )
    try:
        with pytest.raises(RuntimeError, match="simulated postgres crash"):
            service.process(request)
        first = memory_repository.list(organization_id=request.organization_id)
        assert len(first) == 1
        service._candidates = lambda _: pytest.fail(
            "candidate provider reran on postgres replay"
        )

        result = service.process(request)

        replayed = memory_repository.list(organization_id=request.organization_id)
        assert replayed == first
        assert result.stored_memory_references == (str(first[0].id),)
        assert (
            sum(
                envelope.event.event_type is EventType.MEMORY_UPDATED
                and envelope.event.organization_id == request.organization_id
                and envelope.event.payload.get("memory_id") == str(first[0].id)
                for envelope in bus.envelopes
            )
            == 0
        )
        outbox_repository = PostgresOutboxRepository(url)
        dispatcher = OutboxService(
            outbox_repository,
            EventService(bus),
            max_attempts=3,
            batch_size=10,
        )
        assert dispatcher.process_once()["delivered"] >= 1
        assert (
            sum(
                envelope.event.event_type is EventType.MEMORY_UPDATED
                and envelope.event.organization_id == request.organization_id
                and envelope.event.payload.get("memory_id") == str(first[0].id)
                for envelope in bus.envelopes
            )
            == 1
        )
        asyncio.run(outbox_repository.engine.dispose())
    finally:
        for memory in memory_repository.list(organization_id=request.organization_id):
            memory_repository.delete(memory.id)
        asyncio.run(memory_repository.engine.dispose())
        asyncio.run(learning_repository.engine.dispose())
        asyncio.run(observation_repository.engine.dispose())
        asyncio.run(execution_repository.engine.dispose())

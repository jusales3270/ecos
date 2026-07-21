"""PostgreSQL integration tests for canonical Observation and Learning."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
    LearningClaimUnavailableError,
    LearningConflictError,
    LearningService,
    PostgresLearningRepository,
)
from ecos.memory import MemoryService
from ecos.observation import (
    ComparisonOperator,
    ExpectedOutcome,
    InMemoryFeedbackProvider,
    InMemoryMeasurementProvider,
    InMemoryObservationIdempotencyProvider,
    Measurement,
    MeasurementSource,
    MeasurementValueType,
    ObservationConfig,
    ObservationEngine,
    ObservationIdempotencyConflictError,
    ObservationRequest,
    ObservationSourceType,
    PostgresObservationRepository,
)
from ecos.outbox import OutboxService, PostgresOutboxRepository
from ecos.runtime import FakeEventBus, FakeMemoryRepository

database_url = os.getenv("ECOS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    database_url is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)


def _async_url(value: str) -> str:
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


def _execution() -> ExecutionResult:
    provisional = ExecutionResult(
        execution_id=uuid4(),
        execution_request_id=uuid4(),
        execution_plan_id=uuid4(),
        organization_id=uuid4(),
        session_id=uuid4(),
        plan_id=uuid4(),
        correlation_id=uuid4(),
        status=ExecutionStatus.COMPLETED,
        fingerprint="0" * 64,
        mode=ExecutionMode.DRY_RUN,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        duration=0.1,
        idempotency_key=f"test:{uuid4()}",
        authorization_id=uuid4(),
    )
    return provisional.model_copy(
        update={
            "fingerprint": deterministic_fingerprint(
                provisional.model_dump(mode="json", exclude={"fingerprint"})
            )
        }
    )


async def _seed_session(url: str, result: ExecutionResult) -> None:
    repository = PostgresExecutionResultRepository(url)
    try:
        async with repository.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO sessions "
                    "(id, managed_id, session_data, context_data, organization_id) "
                    "VALUES (:id, :managed_id, CAST(:session_data AS jsonb), "
                    "CAST(:context_data AS jsonb), :organization_id)"
                ),
                {
                    "id": result.session_id,
                    "managed_id": uuid4(),
                    "session_data": "{}",
                    "context_data": "{}",
                    "organization_id": result.organization_id,
                },
            )
        repository.save(result)
    finally:
        await repository.engine.dispose()


def _request(result: ExecutionResult) -> ObservationRequest:
    now = datetime.now(UTC)
    source = MeasurementSource(
        source_type=ObservationSourceType.EXECUTION_RESULT,
        source_id=f"execution:{result.execution_id}",
        reliability=1.0,
        verified=True,
    )
    return ObservationRequest(
        observation_request_id=uuid4(),
        organization_id=result.organization_id,
        session_id=result.session_id,
        plan_id=result.plan_id,
        correlation_id=result.correlation_id,
        execution_id=result.execution_id,
        source_event_id=result.terminal_event_id,
        source_type=ObservationSourceType.EXECUTION_RESULT,
        source_id=source.source_id,
        execution_result=result,
        expected_outcomes=(
            ExpectedOutcome(
                expected_outcome_id="execution:completed",
                name="Execution completed",
                metric_key="execution_status",
                expected_status=ExecutionStatus.COMPLETED.value,
                comparison_operator=ComparisonOperator.EQUALS,
                source_reference=f"plan:{result.plan_id}",
            ),
        ),
        observed_measurements=(
            Measurement(
                measurement_id=f"status:{result.execution_id}",
                metric_key="execution_status",
                value=result.status.value,
                value_type=MeasurementValueType.STATUS,
                source=source,
                observed_at=now,
                evidence_references=(f"execution:{result.fingerprint}",),
                confidence=1.0,
                verified=True,
            ),
        ),
    )


def _engine(
    repository: PostgresObservationRepository,
) -> tuple[ObservationEngine, FakeEventBus]:
    bus = FakeEventBus()
    return (
        ObservationEngine(
            measurement_provider=InMemoryMeasurementProvider(),
            feedback_provider=InMemoryFeedbackProvider(),
            idempotency_provider=InMemoryObservationIdempotencyProvider(),
            event_service=EventService(bus),
            clock=lambda: datetime.now(UTC),
            id_generator=uuid4,
            config=ObservationConfig(),
            repository=repository,
        ),
        bus,
    )


def test_postgres_observation_round_trip_replay_conflict_and_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert database_url is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    url = _async_url(database_url)
    execution = _execution()
    asyncio.run(_seed_session(url, execution))
    repository = PostgresObservationRepository(url)
    engine, bus = _engine(repository)
    concurrent_engine, concurrent_bus = _engine(repository)
    request = _request(execution)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda item: item.observe(request),
                    (engine, concurrent_engine),
                )
            )
        first = results[0]
        assert {item.observation_id for item in results} == {first.observation_id}
        assert (
            repository.get(execution.organization_id, execution.execution_id) == first
        )
        assert repository.get(uuid4(), execution.execution_id) is None
        terminal_count = sum(
            item.event.event_type is EventType.OBSERVATION_COMPLETED
            for item in (*bus.envelopes, *concurrent_bus.envelopes)
        )
        replay_engine, replay_bus = _engine(repository)
        replay_engine._id_generator = lambda: pytest.fail("engine reran on replay")
        assert replay_engine.observe(request) == first
        assert not replay_bus.envelopes
        assert terminal_count == 0
        dispatcher_bus = FakeEventBus()
        outbox_repository = PostgresOutboxRepository(url)
        dispatcher = OutboxService(
            outbox_repository,
            EventService(dispatcher_bus),
            max_attempts=3,
            batch_size=10,
        )
        assert dispatcher.process_once()["delivered"] == 1
        assert (
            sum(
                item.event.event_type is EventType.OBSERVATION_COMPLETED
                for item in dispatcher_bus.envelopes
            )
            == 1
        )
        asyncio.run(outbox_repository.engine.dispose())
        with pytest.raises(ObservationIdempotencyConflictError):
            engine.observe(
                request.model_copy(
                    update={
                        "execution_result": execution.model_copy(
                            update={"fingerprint": "f" * 64}
                        )
                    }
                )
            )
    finally:
        asyncio.run(repository.engine.dispose())


def test_postgres_learning_persists_children_replays_and_claims_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert database_url is not None
    monkeypatch.setenv("ECOS_DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    url = _async_url(database_url)
    execution = _execution()
    asyncio.run(_seed_session(url, execution))
    observation_repository = PostgresObservationRepository(url)
    observation_engine, _ = _engine(observation_repository)
    observation = observation_engine.observe(_request(execution))
    learning_repository = PostgresLearningRepository(url)
    memories = FakeMemoryRepository()
    from ecos.learning import LearningRequest

    request = LearningRequest(
        learning_request_id=uuid4(),
        organization_id=execution.organization_id,
        session_id=execution.session_id,
        plan_id=execution.plan_id,
        correlation_id=execution.correlation_id,
        execution_id=execution.execution_id,
        observation_id=observation.observation_id,
        observation_result=observation,
        execution_result=execution,
    )

    try:
        services = tuple(
            LearningService(
                MemoryService(memories),
                EventService(FakeEventBus()),
                repository=learning_repository,
                observation_repository=observation_repository,
            )
            for _ in range(2)
        )

        def process(service: LearningService):
            try:
                return service.process(request)
            except LearningClaimUnavailableError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_results = list(pool.map(process, services))
        completed = [item for item in concurrent_results if item is not None]
        assert completed
        first = completed[0]
        assert {item.learning_id for item in completed} == {first.learning_id}
        assert first.validations
        assert (
            learning_repository.get(
                execution.organization_id,
                observation.observation_id,
                first.policy_version,
            )
            == first
        )
        assert (
            learning_repository.get(
                uuid4(), observation.observation_id, first.policy_version
            )
            is None
        )
        with pytest.raises(LearningConflictError):
            services[0].process(
                request.model_copy(update={"safe_metadata": {"changed": True}})
            )
        replay = LearningService(
            MemoryService(memories),
            EventService(FakeEventBus()),
            repository=learning_repository,
            observation_repository=observation_repository,
        )
        replay._candidates = lambda _: pytest.fail("provider reran on replay")
        assert replay.process(request) == first
        assert len(memories.list(organization_id=execution.organization_id)) == len(
            first.stored_memory_references
        )

        async def counts() -> tuple[int, int, int]:
            async with learning_repository.engine.connect() as connection:
                values = []
                for table in (
                    "learning_runs",
                    "learning_candidates",
                    "learning_validations",
                ):
                    values.append(
                        int(
                            (
                                await connection.scalar(
                                    text(
                                        f"SELECT count(*) FROM {table} "
                                        "WHERE learning_id = :learning_id"
                                    ),
                                    {"learning_id": first.learning_id},
                                )
                            )
                            or 0
                        )
                    )
                return values[0], values[1], values[2]

        assert asyncio.run(counts()) == (
            1,
            len(first.candidates),
            len(first.validations),
        )

        policy = "claim-test-v1"
        fingerprint = "a" * 64
        now = datetime.now(UTC)
        clock = [now]
        claims = PostgresLearningRepository(
            url,
            lease_duration=timedelta(seconds=1),
            clock=lambda: clock[0],
        )
        values = {
            "learning_id": uuid4(),
            "organization_id": execution.organization_id,
            "session_id": execution.session_id,
            "execution_id": execution.execution_id,
            "observation_id": observation.observation_id,
            "correlation_id": execution.correlation_id,
            "policy_version": policy,
            "fingerprint": fingerprint,
        }
        original = claims.acquire(**values, owner="worker-1").claim
        assert original is not None
        with pytest.raises(LearningClaimUnavailableError):
            claims.acquire(**values, owner="worker-2")
        clock[0] += timedelta(seconds=2)
        recovered = claims.acquire(**values, owner="worker-2").claim
        assert recovered is not None and recovered.version == original.version + 1
        stale_result = first.model_copy(
            update={
                "learning_id": values["learning_id"],
                "policy_version": policy,
                "fingerprint": fingerprint,
                "candidates": (),
                "validations": (),
                "validated_candidates": (),
                "rejected_candidates": (),
                "human_review_candidates": (),
            }
        )
        with pytest.raises(LearningConflictError):
            claims.complete(claim=original, result=stale_result, validations=())
    finally:
        asyncio.run(observation_repository.engine.dispose())
        asyncio.run(learning_repository.engine.dispose())

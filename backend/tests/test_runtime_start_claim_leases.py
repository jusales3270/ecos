"""Lease recovery and lifecycle tests for authenticated runtime start claims."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from pydantic import ValidationError

from ecos.core import Settings
from ecos.runtime import (
    InMemoryRuntimeCheckpointRepository,
    PostgresRuntimeCheckpointRepository,
    RuntimeCheckpointConflictError,
    RuntimeCheckpointRepository,
    RuntimeStartAcquisition,
    RuntimeStartClaimStatus,
    RuntimeStartLeaseLostError,
)

TEST_DATABASE_URL = os.getenv("ECOS_TEST_DATABASE_URL")
ORGANIZATION_ID = UUID("10000000-0000-4000-8000-000000000001")
USER_ID = UUID("10000000-0000-4000-8000-000000000002")


class MutableClock:
    """Thread-safe deterministic UTC clock for lease tests."""

    def __init__(self, current: datetime) -> None:
        self._current = current
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._current

    def advance(self, duration: timedelta) -> None:
        with self._lock:
            self._current += duration


def _acquire(
    repository: RuntimeCheckpointRepository,
    session_id: UUID,
    *,
    objective: str = "Lease objective",
) -> RuntimeStartAcquisition:
    return repository.acquire_start_claim(
        organization_id=ORGANIZATION_ID,
        session_id=session_id,
        user_id=USER_ID,
        correlation_id=uuid4(),
        objective=objective,
    )


def test_runtime_start_claim_lease_configuration_is_explicit() -> None:
    settings = Settings(
        runtime_start_claim_lease_seconds=17,
        runtime_start_claim_heartbeat_seconds=4,
        runtime_start_claim_heartbeat_shutdown_timeout_seconds=2,
    )

    assert settings.runtime_start_claim_lease == timedelta(seconds=17)
    assert settings.runtime_start_claim_heartbeat == timedelta(seconds=4)
    assert settings.runtime_start_claim_heartbeat_shutdown_timeout == timedelta(
        seconds=2
    )

    with pytest.raises(ValidationError, match="heartbeat must be shorter"):
        Settings(
            runtime_start_claim_lease_seconds=5,
            runtime_start_claim_heartbeat_seconds=5,
        )
    with pytest.raises(ValidationError):
        Settings(runtime_start_claim_heartbeat_shutdown_timeout_seconds=0)


def test_in_memory_renew_requires_live_owned_initializing_claim() -> None:
    clock = MutableClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    repository = InMemoryRuntimeCheckpointRepository(
        lease_duration=timedelta(seconds=5),
        clock=clock,
    )
    session_id = uuid4()
    acquired = _acquire(repository, session_id)

    clock.advance(timedelta(seconds=2))
    first_renewal = repository.renew_start_claim(
        organization_id=ORGANIZATION_ID,
        session_id=session_id,
        expected_attempt=acquired.claim.attempt,
        expected_status=RuntimeStartClaimStatus.INITIALIZING,
    )
    clock.advance(timedelta(seconds=2))
    second_renewal = repository.renew_start_claim(
        organization_id=ORGANIZATION_ID,
        session_id=session_id,
        expected_attempt=acquired.claim.attempt,
        expected_status=RuntimeStartClaimStatus.INITIALIZING,
    )

    assert first_renewal.lease_expires_at > acquired.claim.lease_expires_at
    assert second_renewal.lease_expires_at > first_renewal.lease_expires_at

    clock.advance(timedelta(seconds=6))
    with pytest.raises(RuntimeStartLeaseLostError, match="lease expired"):
        repository.renew_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=session_id,
            expected_attempt=acquired.claim.attempt,
            expected_status=RuntimeStartClaimStatus.INITIALIZING,
        )
    recovered = _acquire(repository, session_id)
    with pytest.raises(RuntimeStartLeaseLostError, match="attempt conflict"):
        repository.renew_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=session_id,
            expected_attempt=acquired.claim.attempt,
            expected_status=RuntimeStartClaimStatus.INITIALIZING,
        )
    with pytest.raises(RuntimeStartLeaseLostError, match="attempt conflict"):
        repository.mark_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=session_id,
            expected_attempt=acquired.claim.attempt,
            expected_status=RuntimeStartClaimStatus.INITIALIZING,
            status=RuntimeStartClaimStatus.FAILED,
        )

    assert recovered.claim.attempt == 2


def test_in_memory_renew_rejects_non_initializing_status() -> None:
    repository = InMemoryRuntimeCheckpointRepository()
    acquired = _acquire(repository, uuid4())

    with pytest.raises(RuntimeCheckpointConflictError, match="only initializing"):
        repository.renew_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=acquired.claim.session_id,
            expected_attempt=acquired.claim.attempt,
            expected_status=RuntimeStartClaimStatus.STARTED,
        )


def test_in_memory_active_and_expired_initializing_claims() -> None:
    clock = MutableClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    repository = InMemoryRuntimeCheckpointRepository(
        lease_duration=timedelta(seconds=10),
        clock=clock,
    )
    session_id = uuid4()

    first = _acquire(repository, session_id)
    active = _acquire(repository, session_id)
    clock.advance(timedelta(seconds=11))
    with ThreadPoolExecutor(max_workers=2) as executor:
        recovered = tuple(
            executor.map(lambda _: _acquire(repository, session_id), range(2))
        )

    assert first.acquired is True
    assert first.claim.lease_expires_at.tzinfo is not None
    assert active.acquired is False
    assert active.claim.attempt == 1
    assert sum(item.acquired for item in recovered) == 1
    assert {item.claim.attempt for item in recovered} == {2}
    assert len({item.claim.lease_expires_at for item in recovered}) == 1


def test_in_memory_started_and_failed_claim_recovery_rules() -> None:
    clock = MutableClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    repository = InMemoryRuntimeCheckpointRepository(
        lease_duration=timedelta(seconds=5),
        clock=clock,
    )
    started_id = uuid4()
    started = _acquire(repository, started_id)
    repository.mark_start_claim(
        organization_id=ORGANIZATION_ID,
        session_id=started_id,
        expected_attempt=started.claim.attempt,
        expected_status=RuntimeStartClaimStatus.INITIALIZING,
        status=RuntimeStartClaimStatus.STARTED,
    )
    clock.advance(timedelta(seconds=10))

    assert _acquire(repository, started_id).acquired is False

    failed_id = uuid4()
    failed = _acquire(repository, failed_id)
    repository.mark_start_claim(
        organization_id=ORGANIZATION_ID,
        session_id=failed_id,
        expected_attempt=failed.claim.attempt,
        expected_status=RuntimeStartClaimStatus.INITIALIZING,
        status=RuntimeStartClaimStatus.FAILED,
    )
    retried = _acquire(repository, failed_id)

    assert retried.acquired is True
    assert retried.claim.attempt == 2
    assert retried.claim.status is RuntimeStartClaimStatus.INITIALIZING


def test_in_memory_rejects_stale_and_invalid_finalization() -> None:
    clock = MutableClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    repository = InMemoryRuntimeCheckpointRepository(
        lease_duration=timedelta(seconds=5),
        clock=clock,
    )
    session_id = uuid4()
    first = _acquire(repository, session_id)
    clock.advance(timedelta(seconds=6))
    recovered = _acquire(repository, session_id)

    with pytest.raises(RuntimeCheckpointConflictError, match="attempt conflict"):
        repository.mark_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=session_id,
            expected_attempt=first.claim.attempt,
            expected_status=RuntimeStartClaimStatus.INITIALIZING,
            status=RuntimeStartClaimStatus.FAILED,
        )

    repository.mark_start_claim(
        organization_id=ORGANIZATION_ID,
        session_id=session_id,
        expected_attempt=recovered.claim.attempt,
        expected_status=RuntimeStartClaimStatus.INITIALIZING,
        status=RuntimeStartClaimStatus.STARTED,
    )
    for target in (
        RuntimeStartClaimStatus.FAILED,
        RuntimeStartClaimStatus.INITIALIZING,
    ):
        with pytest.raises(RuntimeCheckpointConflictError, match="invalid.*transition"):
            repository.mark_start_claim(
                organization_id=ORGANIZATION_ID,
                session_id=session_id,
                expected_attempt=recovered.claim.attempt,
                expected_status=RuntimeStartClaimStatus.STARTED,
                status=target,
            )

    failed_id = uuid4()
    failed = _acquire(repository, failed_id)
    repository.mark_start_claim(
        organization_id=ORGANIZATION_ID,
        session_id=failed_id,
        expected_attempt=failed.claim.attempt,
        expected_status=RuntimeStartClaimStatus.INITIALIZING,
        status=RuntimeStartClaimStatus.FAILED,
    )
    with pytest.raises(RuntimeCheckpointConflictError, match="invalid.*transition"):
        repository.mark_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=failed_id,
            expected_attempt=failed.claim.attempt,
            expected_status=RuntimeStartClaimStatus.FAILED,
            status=RuntimeStartClaimStatus.STARTED,
        )


@pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="ECOS_TEST_DATABASE_URL is not configured",
)
def test_postgres_runtime_start_claim_lease_recovery_and_transitions() -> None:
    assert TEST_DATABASE_URL is not None
    config = Config("alembic.ini")
    alembic_command.upgrade(config, "head")
    clock = MutableClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    repository = PostgresRuntimeCheckpointRepository(
        TEST_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1),
        lease_duration=timedelta(seconds=5),
        clock=clock,
    )
    session_id = uuid4()

    try:
        first = _acquire(repository, session_id)
        clock.advance(timedelta(seconds=2))
        renewed = repository.renew_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=session_id,
            expected_attempt=first.claim.attempt,
            expected_status=RuntimeStartClaimStatus.INITIALIZING,
        )
        assert renewed.lease_expires_at > first.claim.lease_expires_at
        assert _acquire(repository, session_id).acquired is False
        clock.advance(timedelta(seconds=6))
        with pytest.raises(RuntimeStartLeaseLostError, match="lease expired"):
            repository.renew_start_claim(
                organization_id=ORGANIZATION_ID,
                session_id=session_id,
                expected_attempt=first.claim.attempt,
                expected_status=RuntimeStartClaimStatus.INITIALIZING,
            )
        with ThreadPoolExecutor(max_workers=2) as executor:
            recovered = tuple(
                executor.map(lambda _: _acquire(repository, session_id), range(2))
            )

        assert sum(item.acquired for item in recovered) == 1
        assert {item.claim.attempt for item in recovered} == {2}
        with pytest.raises(RuntimeStartLeaseLostError, match="attempt conflict"):
            repository.renew_start_claim(
                organization_id=ORGANIZATION_ID,
                session_id=session_id,
                expected_attempt=first.claim.attempt,
                expected_status=RuntimeStartClaimStatus.INITIALIZING,
            )
        with pytest.raises(RuntimeCheckpointConflictError, match="attempt conflict"):
            repository.mark_start_claim(
                organization_id=ORGANIZATION_ID,
                session_id=session_id,
                expected_attempt=first.claim.attempt,
                expected_status=RuntimeStartClaimStatus.INITIALIZING,
                status=RuntimeStartClaimStatus.FAILED,
            )

        repository.mark_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=session_id,
            expected_attempt=2,
            expected_status=RuntimeStartClaimStatus.INITIALIZING,
            status=RuntimeStartClaimStatus.STARTED,
        )
        clock.advance(timedelta(seconds=6))
        assert _acquire(repository, session_id).acquired is False
        with pytest.raises(RuntimeCheckpointConflictError, match="invalid.*transition"):
            repository.mark_start_claim(
                organization_id=ORGANIZATION_ID,
                session_id=session_id,
                expected_attempt=2,
                expected_status=RuntimeStartClaimStatus.STARTED,
                status=RuntimeStartClaimStatus.FAILED,
            )

        failed_id = uuid4()
        failed = _acquire(repository, failed_id)
        repository.mark_start_claim(
            organization_id=ORGANIZATION_ID,
            session_id=failed_id,
            expected_attempt=failed.claim.attempt,
            expected_status=RuntimeStartClaimStatus.INITIALIZING,
            status=RuntimeStartClaimStatus.FAILED,
        )
        retry = _acquire(repository, failed_id)
        assert retry.acquired is True
        assert retry.claim.attempt == 2
    finally:
        alembic_command.downgrade(config, "base")

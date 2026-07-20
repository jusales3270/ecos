"""PostgreSQL persistence for claimed canonical learning runs."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory

from .models import LearningResult, LearningValidation
from .repository import (
    LearningAcquisition,
    LearningClaim,
    LearningClaimUnavailableError,
    LearningConflictError,
    LearningRepository,
)


class Base(DeclarativeBase):
    pass


class LearningRunRecord(Base):
    __tablename__ = "learning_runs"
    learning_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    execution_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    observation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_owner: Mapped[str | None] = mapped_column(String(200))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningCandidateRecord(Base):
    __tablename__ = "learning_candidates"
    candidate_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    learning_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("learning_runs.learning_id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    assertion: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    validation_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class LearningValidationRecord(Base):
    __tablename__ = "learning_validations"
    candidate_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("learning_candidates.candidate_id", ondelete="CASCADE"),
        primary_key=True,
    )
    learning_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("learning_runs.learning_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class PostgresLearningRepository(LearningRepository):
    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        lease_duration: timedelta = timedelta(seconds=30),
        clock=lambda: datetime.now(UTC),
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_database_engine(database_url or "")
        self._session_factory = session_factory or create_session_factory(self.engine)
        self._lease_duration = lease_duration
        self._clock = clock
        self._sync_lock = RLock()

    def get(
        self, organization_id: UUID, observation_id: UUID, policy_version: str
    ) -> LearningResult | None:
        with self._sync_lock:
            return _run(self._get(organization_id, observation_id, policy_version))

    async def _get(
        self, organization_id: UUID, observation_id: UUID, policy_version: str
    ) -> LearningResult | None:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(LearningRunRecord).where(
                    LearningRunRecord.organization_id == organization_id,
                    LearningRunRecord.observation_id == observation_id,
                    LearningRunRecord.policy_version == policy_version,
                    LearningRunRecord.status == "completed",
                )
            )
            return None if record is None else self._model(record)

    def acquire(self, **kwargs: Any) -> LearningAcquisition:
        with self._sync_lock:
            return _run(self._acquire(**kwargs))

    async def _acquire(self, **values: Any) -> LearningAcquisition:
        now = self._clock()
        owner = str(values["owner"])
        async with self._session_factory() as database:
            inserted = await database.scalar(
                insert(LearningRunRecord)
                .values(
                    **{
                        k: values[k]
                        for k in (
                            "learning_id",
                            "organization_id",
                            "session_id",
                            "execution_id",
                            "observation_id",
                            "correlation_id",
                            "policy_version",
                            "fingerprint",
                        )
                    },
                    status="processing",
                    payload=None,
                    created_at=now,
                    updated_at=now,
                    version=1,
                    claim_owner=owner,
                    claim_expires_at=now + self._lease_duration,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        "organization_id",
                        "observation_id",
                        "policy_version",
                    ]
                )
                .returning(LearningRunRecord.learning_id)
            )
            await database.commit()
            record = await database.scalar(
                select(LearningRunRecord)
                .where(
                    LearningRunRecord.organization_id == values["organization_id"],
                    LearningRunRecord.observation_id == values["observation_id"],
                    LearningRunRecord.policy_version == values["policy_version"],
                )
                .with_for_update()
            )
            if record is None:
                raise LearningConflictError(
                    "learning run disappeared during acquisition"
                )
            self._validate_scope(record, values)
            if record.status == "completed":
                return LearningAcquisition(result=self._model(record))
            if inserted is None:
                if (
                    record.claim_expires_at is not None
                    and record.claim_expires_at > now
                    and record.claim_owner != owner
                ):
                    raise LearningClaimUnavailableError(
                        "learning claim is already owned"
                    )
                record.claim_owner = owner
                record.claim_expires_at = now + self._lease_duration
                record.version += 1
                record.updated_at = now
                await database.commit()
            return LearningAcquisition(claim=self._claim(record))

    def complete(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        with self._sync_lock:
            return _run(self._complete(claim, result, validations))

    async def _complete(
        self,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        now = self._clock()
        validation_by_id = {item.learning_candidate_id: item for item in validations}
        async with self._session_factory() as database:
            changed = await database.scalar(
                update(LearningRunRecord)
                .where(
                    LearningRunRecord.learning_id == claim.learning_id,
                    LearningRunRecord.organization_id == claim.organization_id,
                    LearningRunRecord.version == claim.version,
                    LearningRunRecord.claim_owner == claim.owner,
                    LearningRunRecord.status == "processing",
                )
                .values(
                    status="completed",
                    payload=result.model_dump(mode="json"),
                    updated_at=now,
                    version=claim.version + 1,
                    claim_owner=None,
                    claim_expires_at=None,
                )
                .returning(LearningRunRecord.learning_id)
            )
            if changed is None:
                raise LearningConflictError("stale or lost learning claim")
            for candidate in result.candidates:
                validation = validation_by_id[candidate.learning_candidate_id]
                reason = ",".join(validation.reason_codes)
                await database.execute(
                    insert(LearningCandidateRecord)
                    .values(
                        candidate_id=candidate.learning_candidate_id,
                        learning_id=result.learning_id,
                        candidate_type=candidate.category.value,
                        assertion=candidate.statement,
                        confidence=candidate.confidence,
                        validation_status=validation.outcome.value,
                        validation_reason=reason,
                        evidence=list(candidate.evidence_references),
                        requires_human_review=validation.human_review_required,
                        payload=candidate.model_dump(mode="json"),
                        created_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["learning_id", "candidate_id"]
                    )
                )
                await database.execute(
                    insert(LearningValidationRecord)
                    .values(
                        candidate_id=candidate.learning_candidate_id,
                        learning_id=result.learning_id,
                        status=validation.outcome.value,
                        reason=reason,
                        evidence=list(candidate.evidence_references),
                        requires_human_review=validation.human_review_required,
                        payload=validation.model_dump(mode="json"),
                        created_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["learning_id", "candidate_id"]
                    )
                )
            await database.commit()
            return result.model_copy(deep=True)

    @staticmethod
    def _validate_scope(record: LearningRunRecord, values: dict[str, Any]) -> None:
        if any(
            getattr(record, key) != values[key]
            for key in (
                "organization_id",
                "session_id",
                "execution_id",
                "observation_id",
                "correlation_id",
                "policy_version",
                "fingerprint",
            )
        ):
            raise LearningConflictError("learning scope or fingerprint conflict")

    @staticmethod
    def _claim(record: LearningRunRecord) -> LearningClaim:
        if record.claim_owner is None or record.claim_expires_at is None:
            raise LearningConflictError("learning run has no active claim")
        return LearningClaim(
            learning_id=record.learning_id,
            organization_id=record.organization_id,
            observation_id=record.observation_id,
            policy_version=record.policy_version,
            fingerprint=record.fingerprint,
            owner=record.claim_owner,
            expires_at=record.claim_expires_at,
            version=record.version,
        )

    @staticmethod
    def _model(record: LearningRunRecord) -> LearningResult:
        if record.payload is None:
            raise LearningConflictError("completed learning run has no payload")
        result = LearningResult.model_validate(record.payload)
        if any(
            (
                result.learning_id != record.learning_id,
                result.organization_id != record.organization_id,
                result.session_id != record.session_id,
                result.execution_id != record.execution_id,
                result.observation_id != record.observation_id,
                result.correlation_id != record.correlation_id,
                result.policy_version != record.policy_version,
                result.fingerprint != record.fingerprint,
            )
        ):
            raise LearningConflictError("stored learning columns do not match payload")
        return result

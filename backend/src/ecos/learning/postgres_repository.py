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
from ecos.events import Event
from ecos.memory import ValidatedMemoryWrite
from ecos.outbox import append_outbox_event

from .models import (
    LearningCandidateReview,
    LearningResult,
    LearningReviewStatus,
    LearningStatus,
    LearningValidation,
)
from .repository import (
    LearningAcquisition,
    LearningClaim,
    LearningClaimUnavailableError,
    LearningConflictError,
    LearningRepository,
    LearningReviewDecision,
    _validate_write_against_result,
    apply_learning_review,
    validate_learning_terminal_event,
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


class LearningCandidateReviewRecord(Base):
    __tablename__ = "learning_candidate_reviews"
    review_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    learning_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("learning_runs.learning_id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("learning_candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    justification: Mapped[str | None] = mapped_column(String(1000))
    actor_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
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
    supports_transactional_outbox = True

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
                    LearningRunRecord.status.in_(("completed", "failed")),
                )
            )
            return None if record is None else self._model(record)

    def list_by_session(
        self, organization_id: UUID, session_id: UUID
    ) -> list[LearningResult]:
        with self._sync_lock:
            return _run(self._list_by_session(organization_id, session_id))

    async def _list_by_session(
        self, organization_id: UUID, session_id: UUID
    ) -> list[LearningResult]:
        async with self._session_factory() as database:
            records = (
                await database.scalars(
                    select(LearningRunRecord)
                    .where(
                        LearningRunRecord.organization_id == organization_id,
                        LearningRunRecord.session_id == session_id,
                        LearningRunRecord.payload.is_not(None),
                    )
                    .order_by(LearningRunRecord.created_at)
                )
            ).all()
        return [self._model(record) for record in records]

    def list_reviews(
        self,
        organization_id: UUID,
        *,
        session_id: UUID | None = None,
        status: LearningReviewStatus | None = None,
    ) -> list[LearningCandidateReview]:
        with self._sync_lock:
            return _run(
                self._list_reviews(
                    organization_id, session_id=session_id, status=status
                )
            )

    async def _list_reviews(
        self,
        organization_id: UUID,
        *,
        session_id: UUID | None,
        status: LearningReviewStatus | None,
    ) -> list[LearningCandidateReview]:
        statement = select(LearningCandidateReviewRecord).where(
            LearningCandidateReviewRecord.organization_id == organization_id
        )
        if session_id is not None:
            statement = statement.where(
                LearningCandidateReviewRecord.session_id == session_id
            )
        if status is not None:
            statement = statement.where(
                LearningCandidateReviewRecord.status == status.value
            )
        statement = statement.order_by(LearningCandidateReviewRecord.created_at)
        async with self._session_factory() as database:
            records = (await database.scalars(statement)).all()
        return [self._review_model(record) for record in records]

    def decide_review(self, **kwargs: Any) -> LearningReviewDecision:
        with self._sync_lock:
            return _run(self._decide_review(**kwargs))

    async def _decide_review(self, **values: Any) -> LearningReviewDecision:
        status = values["status"]
        if status not in {LearningReviewStatus.APPROVED, LearningReviewStatus.REJECTED}:
            raise LearningConflictError("human review decision must be terminal")
        now = self._clock()
        async with self._session_factory() as database:
            review = await database.scalar(
                select(LearningCandidateReviewRecord)
                .where(
                    LearningCandidateReviewRecord.organization_id
                    == values["organization_id"],
                    LearningCandidateReviewRecord.candidate_id
                    == values["candidate_id"],
                )
                .with_for_update()
            )
            if review is None:
                raise LearningConflictError("learning review is not available")
            run = await database.scalar(
                select(LearningRunRecord)
                .where(
                    LearningRunRecord.organization_id == values["organization_id"],
                    LearningRunRecord.learning_id == review.learning_id,
                )
                .with_for_update()
            )
            if run is None or run.payload is None:
                raise LearningConflictError("canonical learning is not available")
            if review.status != LearningReviewStatus.PENDING.value:
                if (
                    review.idempotency_key == values["idempotency_key"]
                    and review.status == status.value
                    and review.justification == values["justification"]
                ):
                    return LearningReviewDecision(
                        review=self._review_model(review), result=self._model(run)
                    )
                raise LearningConflictError(
                    "learning review decision conflicts with persisted decision"
                )
            result = apply_learning_review(
                self._model(run),
                candidate_id=values["candidate_id"],
                approved=status is LearningReviewStatus.APPROVED,
            )
            review.status = status.value
            review.justification = values["justification"]
            review.actor_id = values["actor_id"]
            review.idempotency_key = values["idempotency_key"]
            review.decided_at = now
            review.updated_at = now
            review.version += 1
            run.status = result.status.value
            run.payload = result.model_dump(mode="json")
            run.updated_at = now
            run.version += 1
            await self._persist_children(
                database, result, result.validations, now, update_existing=True
            )
            await database.commit()
            return LearningReviewDecision(
                review=self._review_model(review), result=result
            )

    def finalize_review(
        self, *, result: LearningResult, event: Event
    ) -> LearningResult:
        validate_learning_terminal_event(result, event)
        with self._sync_lock:
            return _run(self._finalize_review(result, event))

    async def _finalize_review(
        self, result: LearningResult, event: Event
    ) -> LearningResult:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(LearningRunRecord)
                .where(
                    LearningRunRecord.organization_id == result.organization_id,
                    LearningRunRecord.learning_id == result.learning_id,
                )
                .with_for_update()
            )
            if record is None or record.payload is None:
                raise LearningConflictError("canonical learning is not available")
            if record.status == LearningStatus.COMPLETED.value:
                return self._model(record)
            if record.status != LearningStatus.VALIDATED.value:
                raise LearningConflictError("learning still has pending human reviews")
            record.status = result.status.value
            record.payload = result.model_dump(mode="json")
            record.updated_at = self._clock()
            record.version += 1
            record.claim_owner = None
            record.claim_expires_at = None
            await self._persist_children(
                database,
                result,
                result.validations,
                self._clock(),
                update_existing=True,
            )
            await append_outbox_event(
                database,
                event,
                aggregate_type="learning",
                aggregate_id=result.learning_id,
                execution_id=result.execution_id,
                observation_id=result.observation_id,
                learning_id=result.learning_id,
            )
            await database.commit()
        return result.model_copy(deep=True)

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
            if record.status in {"completed", "failed"}:
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
            staged = (
                self._model(record)
                if record.status in {"validated", "human_review_required"}
                else None
            )
            return LearningAcquisition(claim=self._claim(record), staged_result=staged)

    def stage_validated(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        with self._sync_lock:
            return _run(self._stage_validated(claim, result, validations))

    async def _stage_validated(
        self,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        now = self._clock()
        async with self._session_factory() as database:
            record = await database.scalar(
                select(LearningRunRecord)
                .where(
                    LearningRunRecord.learning_id == claim.learning_id,
                    LearningRunRecord.organization_id == claim.organization_id,
                )
                .with_for_update()
            )
            if (
                record is None
                or record.claim_owner != claim.owner
                or record.version != claim.version
            ):
                raise LearningConflictError("stale or lost learning claim")
            if record.status in {"validated", "human_review_required"}:
                existing = self._model(record)
                if existing.fingerprint != result.fingerprint:
                    raise LearningConflictError("learning fingerprint conflict")
                return existing
            if record.status != "processing":
                raise LearningConflictError("learning cannot be staged")
            record.status = result.status.value
            record.payload = result.model_dump(mode="json")
            record.updated_at = now
            await self._persist_children(database, result, validations, now)
            await database.commit()
        return result.model_copy(deep=True)

    def validate_memory_write(self, write: ValidatedMemoryWrite) -> None:
        with self._sync_lock:
            _run(self._validate_memory_write(write))

    async def _validate_memory_write(self, write: ValidatedMemoryWrite) -> None:
        async with self._session_factory() as database:
            record = await database.scalar(
                select(LearningRunRecord).where(
                    LearningRunRecord.learning_id == write.learning_id,
                    LearningRunRecord.organization_id == write.organization_id,
                    LearningRunRecord.status.in_(("validated", "completed")),
                )
            )
        if record is None:
            raise LearningConflictError("canonical validated learning not found")
        _validate_write_against_result(write, self._model(record))

    def complete(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
    ) -> LearningResult:
        with self._sync_lock:
            return _run(self._complete(claim, result, validations, event=None))

    def complete_terminal(
        self,
        *,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
        event: Event,
    ) -> LearningResult:
        validate_learning_terminal_event(result, event)
        if type(self).complete is not PostgresLearningRepository.complete:
            return self.complete(claim=claim, result=result, validations=validations)
        with self._sync_lock:
            return _run(self._complete(claim, result, validations, event=event))

    async def _complete(
        self,
        claim: LearningClaim,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
        *,
        event: Event | None,
    ) -> LearningResult:
        now = self._clock()
        if result.status not in {LearningStatus.COMPLETED, LearningStatus.FAILED}:
            raise LearningConflictError("learning completion requires terminal status")
        async with self._session_factory() as database:
            changed = await database.scalar(
                update(LearningRunRecord)
                .where(
                    LearningRunRecord.learning_id == claim.learning_id,
                    LearningRunRecord.organization_id == claim.organization_id,
                    LearningRunRecord.version == claim.version,
                    LearningRunRecord.claim_owner == claim.owner,
                    LearningRunRecord.status == "validated",
                )
                .values(
                    status=result.status.value,
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
            await self._persist_children(database, result, validations, now)
            if event is not None:
                await append_outbox_event(
                    database,
                    event,
                    aggregate_type="learning",
                    aggregate_id=result.learning_id,
                    execution_id=result.execution_id,
                    observation_id=result.observation_id,
                    learning_id=result.learning_id,
                )
            await database.commit()
            return result.model_copy(deep=True)

    @staticmethod
    async def _persist_children(
        database: AsyncSession,
        result: LearningResult,
        validations: tuple[LearningValidation, ...],
        now: datetime,
        update_existing: bool = False,
    ) -> None:
        validation_by_id = {item.learning_candidate_id: item for item in validations}
        for candidate in result.candidates:
            validation = validation_by_id[candidate.learning_candidate_id]
            reason = ",".join(validation.reason_codes)
            candidate_insert = insert(LearningCandidateRecord)
            candidate_statement = candidate_insert.values(
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
            if update_existing:
                candidate_statement = candidate_statement.on_conflict_do_update(
                    index_elements=["candidate_id"],
                    set_={
                        "validation_status": validation.outcome.value,
                        "validation_reason": reason,
                        "requires_human_review": validation.human_review_required,
                        "payload": candidate.model_dump(mode="json"),
                    },
                )
            else:
                candidate_statement = candidate_statement.on_conflict_do_nothing(
                    index_elements=["learning_id", "candidate_id"]
                )
            await database.execute(candidate_statement)
            validation_insert = insert(LearningValidationRecord)
            validation_statement = validation_insert.values(
                candidate_id=candidate.learning_candidate_id,
                learning_id=result.learning_id,
                status=validation.outcome.value,
                reason=reason,
                evidence=list(candidate.evidence_references),
                requires_human_review=validation.human_review_required,
                payload=validation.model_dump(mode="json"),
                created_at=now,
            )
            if update_existing:
                validation_statement = validation_statement.on_conflict_do_update(
                    index_elements=["candidate_id"],
                    set_={
                        "status": validation.outcome.value,
                        "reason": reason,
                        "requires_human_review": validation.human_review_required,
                        "payload": validation.model_dump(mode="json"),
                    },
                )
            else:
                validation_statement = validation_statement.on_conflict_do_nothing(
                    index_elements=["learning_id", "candidate_id"]
                )
            await database.execute(validation_statement)
            if (
                validation.human_review_required
                and result.status is LearningStatus.HUMAN_REVIEW_REQUIRED
            ):
                from uuid import NAMESPACE_URL, uuid5

                review_id = uuid5(
                    NAMESPACE_URL,
                    f"ecos:learning-review:{result.organization_id}:{candidate.learning_candidate_id}",
                )
                await database.execute(
                    insert(LearningCandidateReviewRecord)
                    .values(
                        review_id=review_id,
                        organization_id=result.organization_id,
                        session_id=result.session_id,
                        learning_id=result.learning_id,
                        candidate_id=candidate.learning_candidate_id,
                        status=LearningReviewStatus.PENDING.value,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["candidate_id"])
                )

    @staticmethod
    def _review_model(record: LearningCandidateReviewRecord) -> LearningCandidateReview:
        return LearningCandidateReview(
            review_id=record.review_id,
            organization_id=record.organization_id,
            session_id=record.session_id,
            learning_id=record.learning_id,
            learning_candidate_id=record.candidate_id,
            status=LearningReviewStatus(record.status),
            justification=record.justification,
            actor_id=record.actor_id,
            idempotency_key=record.idempotency_key,
            decided_at=record.decided_at,
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

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

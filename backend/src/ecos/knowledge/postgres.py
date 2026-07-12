"""PostgreSQL Knowledge Graph repository implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.knowledge.exceptions import KnowledgeRepositoryUnavailableError
from ecos.knowledge.models import (
    HealthStatus,
    KnowledgeClassification,
    KnowledgeEntity,
    KnowledgeEntityType,
    KnowledgeRelationship,
    KnowledgeRelationshipType,
    KnowledgeStatus,
    RelationshipDirection,
    RepositoryHealth,
)
from ecos.knowledge.repository import InMemoryKnowledgeGraphRepository
from ecos.session.orm import Base


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class KnowledgeEntityVersionRecord(Base):
    """Persisted immutable knowledge entity version."""

    __tablename__ = "knowledge_entity_versions"
    __table_args__ = (
        UniqueConstraint("entity_id", "version", name="uq_knowledge_entity_version"),
    )

    record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    entity_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(300), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_references: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_references: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    supersedes_entity_version: Mapped[int | None] = mapped_column(Integer)
    identity_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitive: Mapped[bool] = mapped_column(nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False
    )


class KnowledgeRelationshipVersionRecord(Base):
    """Persisted immutable knowledge relationship version."""

    __tablename__ = "knowledge_relationship_versions"
    __table_args__ = (
        UniqueConstraint(
            "relationship_id",
            "version",
            name="uq_knowledge_relationship_version",
        ),
    )

    record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    relationship_id: Mapped[str] = mapped_column(
        String(240), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    source_entity_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True
    )
    target_entity_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_references: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evidence_references: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    supersedes_relationship_version: Mapped[int | None] = mapped_column(Integer)
    relationship_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False
    )


class PostgresKnowledgeGraphRepository(InMemoryKnowledgeGraphRepository):
    """PostgreSQL-backed repository using existing SQLAlchemy infrastructure."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        super().__init__()
        self.engine = engine or create_database_engine(database_url or "")
        self._session_factory = session_factory or create_session_factory(self.engine)
        self._loaded = False

    def append_entity(self, entity: KnowledgeEntity) -> KnowledgeEntity:
        self._ensure_loaded()
        stored = super().append_entity(entity)
        _run(self._insert_entity(stored))
        return stored

    async def _insert_entity(self, entity: KnowledgeEntity) -> None:
        try:
            async with self._session_factory() as database:
                exists = await database.scalar(
                    select(KnowledgeEntityVersionRecord).where(
                        KnowledgeEntityVersionRecord.entity_id == entity.entity_id,
                        KnowledgeEntityVersionRecord.version == entity.version,
                    )
                )
                if exists is None:
                    database.add(_entity_record(entity))
                    await database.commit()
        except SQLAlchemyError as error:
            raise KnowledgeRepositoryUnavailableError(
                "failed to append entity"
            ) from error

    def append_relationship(
        self, relationship: KnowledgeRelationship
    ) -> KnowledgeRelationship:
        self._ensure_loaded()
        stored = super().append_relationship(relationship)
        _run(self._insert_relationship(stored))
        return stored

    async def _insert_relationship(self, relationship: KnowledgeRelationship) -> None:
        try:
            async with self._session_factory() as database:
                exists = await database.scalar(
                    select(KnowledgeRelationshipVersionRecord).where(
                        KnowledgeRelationshipVersionRecord.relationship_id
                        == relationship.relationship_id,
                        KnowledgeRelationshipVersionRecord.version
                        == relationship.version,
                    )
                )
                if exists is None:
                    database.add(_relationship_record(relationship))
                    await database.commit()
        except SQLAlchemyError as error:
            raise KnowledgeRepositoryUnavailableError(
                "failed to append relationship"
            ) from error

    def health(self) -> RepositoryHealth:
        try:
            self._ensure_loaded()
        except Exception as error:
            return RepositoryHealth(
                status=HealthStatus.UNHEALTHY,
                details={"mode": "postgres", "error": error.__class__.__name__},
            )
        return RepositoryHealth(
            status=HealthStatus.HEALTHY, details={"mode": "postgres"}
        )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        _run(self._load())
        self._loaded = True

    async def _load(self) -> None:
        try:
            async with self._session_factory() as database:
                entity_records = (
                    await database.scalars(
                        select(KnowledgeEntityVersionRecord).order_by(
                            KnowledgeEntityVersionRecord.entity_id,
                            KnowledgeEntityVersionRecord.version,
                        )
                    )
                ).all()
                relationship_records = (
                    await database.scalars(
                        select(KnowledgeRelationshipVersionRecord).order_by(
                            KnowledgeRelationshipVersionRecord.relationship_id,
                            KnowledgeRelationshipVersionRecord.version,
                        )
                    )
                ).all()
        except SQLAlchemyError as error:
            raise KnowledgeRepositoryUnavailableError("failed to load graph") from error
        for record in entity_records:
            super().append_entity(_entity_model(record))
        for record in relationship_records:
            super().append_relationship(_relationship_model(record))


def _entity_record(entity: KnowledgeEntity) -> KnowledgeEntityVersionRecord:
    return KnowledgeEntityVersionRecord(
        entity_id=entity.entity_id,
        organization_id=entity.organization_id,
        entity_type=entity.entity_type.value,
        name=entity.name,
        normalized_name=entity.normalized_name or "",
        description=entity.description,
        aliases=list(entity.aliases),
        attributes=entity.attributes,
        tags=list(entity.tags),
        confidence=entity.confidence,
        importance=entity.importance,
        status=entity.status.value,
        version=entity.version,
        valid_from=entity.valid_from,
        valid_until=entity.valid_until,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        source_references=list(entity.source_references),
        evidence_references=list(entity.evidence_references),
        supersedes_entity_version=entity.supersedes_entity_version,
        identity_fingerprint=entity.identity_fingerprint,
        classification=entity.classification.value,
        sensitive=entity.sensitive,
        reason_codes=list(entity.reason_codes),
        metadata_json=entity.safe_metadata,
    )


def _relationship_record(
    relationship: KnowledgeRelationship,
) -> KnowledgeRelationshipVersionRecord:
    return KnowledgeRelationshipVersionRecord(
        relationship_id=relationship.relationship_id,
        organization_id=relationship.organization_id,
        source_entity_id=relationship.source_entity_id,
        target_entity_id=relationship.target_entity_id,
        relationship_type=relationship.relationship_type.value,
        direction=relationship.direction.value,
        weight=relationship.weight,
        confidence=relationship.confidence,
        status=relationship.status.value,
        version=relationship.version,
        valid_from=relationship.valid_from,
        valid_until=relationship.valid_until,
        created_at=relationship.created_at,
        updated_at=relationship.updated_at,
        source_references=list(relationship.source_references),
        evidence_references=list(relationship.evidence_references),
        supersedes_relationship_version=relationship.supersedes_relationship_version,
        relationship_fingerprint=relationship.relationship_fingerprint,
        constraints=relationship.constraints,
        reason_codes=list(relationship.reason_codes),
        metadata_json=relationship.safe_metadata,
    )


def _entity_model(record: KnowledgeEntityVersionRecord) -> KnowledgeEntity:
    return KnowledgeEntity(
        entity_id=record.entity_id,
        organization_id=record.organization_id,
        entity_type=KnowledgeEntityType(record.entity_type),
        name=record.name,
        normalized_name=record.normalized_name,
        description=record.description,
        aliases=tuple(record.aliases),
        attributes=dict(record.attributes),
        tags=tuple(record.tags),
        confidence=record.confidence,
        importance=record.importance,
        status=KnowledgeStatus(record.status),
        version=record.version,
        valid_from=record.valid_from,
        valid_until=record.valid_until,
        created_at=record.created_at,
        updated_at=record.updated_at,
        source_references=tuple(record.source_references),
        evidence_references=tuple(record.evidence_references),
        supersedes_entity_version=record.supersedes_entity_version,
        classification=KnowledgeClassification(record.classification),
        sensitive=record.sensitive,
        reason_codes=tuple(record.reason_codes),
        safe_metadata=dict(record.metadata_json),
    )


def _relationship_model(
    record: KnowledgeRelationshipVersionRecord,
) -> KnowledgeRelationship:
    return KnowledgeRelationship(
        relationship_id=record.relationship_id,
        organization_id=record.organization_id,
        source_entity_id=record.source_entity_id,
        target_entity_id=record.target_entity_id,
        relationship_type=KnowledgeRelationshipType(record.relationship_type),
        direction=RelationshipDirection(record.direction),
        weight=record.weight,
        confidence=record.confidence,
        status=KnowledgeStatus(record.status),
        version=record.version,
        valid_from=record.valid_from,
        valid_until=record.valid_until,
        created_at=record.created_at,
        updated_at=record.updated_at,
        source_references=tuple(record.source_references),
        evidence_references=tuple(record.evidence_references),
        supersedes_relationship_version=record.supersedes_relationship_version,
        constraints=dict(record.constraints),
        reason_codes=tuple(record.reason_codes),
        safe_metadata=dict(record.metadata_json),
    )

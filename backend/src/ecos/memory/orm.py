"""SQLAlchemy models for PostgreSQL memory persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ecos.session.orm import Base


class MemoryRecord(Base):
    """Persisted organizational memory object."""

    __tablename__ = "memories"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(500), index=True, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    execution_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    correlation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    observation_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    learning_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    learning_candidate_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True)
    )
    proposal_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    policy_version: Mapped[str | None] = mapped_column(String(100))
    validation_status: Mapped[str | None] = mapped_column(String(40))
    evidence_references: Mapped[list[str] | None] = mapped_column(JSONB)
    source_references: Mapped[list[str] | None] = mapped_column(JSONB)
    validated_write_fingerprint: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

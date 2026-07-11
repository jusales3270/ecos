"""SQLAlchemy models for PostgreSQL session persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for ECOS database models."""


class SessionRecord(Base):
    """Persisted cognitive session and context aggregate data."""

    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    managed_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    session_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    context_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    state: Mapped["SessionStateRecord"] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )


class SessionStateRecord(Base):
    """Persisted current state for a cognitive session."""

    __tablename__ = "session_states"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    active_engine: Mapped[str | None] = mapped_column(String(100))
    progress: Mapped[float] = mapped_column(Float, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    session: Mapped[SessionRecord] = relationship(back_populates="state")


class SessionSnapshotRecord(Base):
    """Persisted immutable session snapshot."""

    __tablename__ = "session_snapshots"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    state_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    context_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SessionTransitionRecord(Base):
    """Persisted lifecycle transition."""

    __tablename__ = "session_transitions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    transition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

"""Create operational persistence and idempotency tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_01"
down_revision: str | None = "20260711_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persistent operational workflow tables."""
    op.create_table(
        "operational_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("objective", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("session_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_operational_sessions_version"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint(
            "organization_id",
            "session_id",
            name="uq_operational_sessions_org_session",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "approval_id",
            name="uq_operational_sessions_org_approval",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "execution_id",
            name="uq_operational_sessions_org_execution",
        ),
    )
    op.create_index(
        "ix_operational_sessions_organization_id",
        "operational_sessions",
        ["organization_id"],
    )
    op.create_index(
        "ix_operational_sessions_status", "operational_sessions", ["status"]
    )
    op.create_index(
        "ix_operational_sessions_correlation_id",
        "operational_sessions",
        ["correlation_id"],
    )
    op.create_index(
        "ix_operational_sessions_org_status",
        "operational_sessions",
        ["organization_id", "status"],
    )

    op.create_table(
        "operational_timeline_entries",
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("safe_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["operational_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.UniqueConstraint(
            "organization_id",
            "session_id",
            "sequence",
            name="uq_operational_timeline_org_session_sequence",
        ),
    )
    op.create_index(
        "ix_operational_timeline_organization_id",
        "operational_timeline_entries",
        ["organization_id"],
    )
    op.create_index(
        "ix_operational_timeline_session_id",
        "operational_timeline_entries",
        ["session_id"],
    )
    op.create_index(
        "ix_operational_timeline_correlation_id",
        "operational_timeline_entries",
        ["correlation_id"],
    )

    op.create_table(
        "operational_approval_decisions",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["operational_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint(
            "organization_id",
            "approval_id",
            name="uq_operational_approval_decisions_org_approval",
        ),
    )
    op.create_index(
        "ix_operational_approval_decisions_organization_id",
        "operational_approval_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_operational_approval_decisions_session_id",
        "operational_approval_decisions",
        ["session_id"],
    )
    op.create_index(
        "ix_operational_approval_decisions_status",
        "operational_approval_decisions",
        ["status"],
    )
    op.create_index(
        "ix_operational_approval_decisions_correlation_id",
        "operational_approval_decisions",
        ["correlation_id"],
    )

    op.create_table(
        "operational_execution_attempts",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["operational_sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "organization_id",
            "execution_id",
            "attempt_number",
            name="uq_operational_execution_attempts_org_execution_attempt",
        ),
    )
    op.create_index(
        "ix_operational_execution_attempts_organization_id",
        "operational_execution_attempts",
        ["organization_id"],
    )
    op.create_index(
        "ix_operational_execution_attempts_session_id",
        "operational_execution_attempts",
        ["session_id"],
    )
    op.create_index(
        "ix_operational_execution_attempts_status",
        "operational_execution_attempts",
        ["status"],
    )
    op.create_index(
        "ix_operational_execution_attempts_correlation_id",
        "operational_execution_attempts",
        ["correlation_id"],
    )

    op.create_table(
        "operational_idempotency_keys",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "user_id", "operation", "key"),
    )
    op.create_index(
        "ix_operational_idempotency_organization_id",
        "operational_idempotency_keys",
        ["organization_id"],
    )
    op.create_index(
        "ix_operational_idempotency_expires_at",
        "operational_idempotency_keys",
        ["expires_at"],
    )


def downgrade() -> None:
    """Drop operational workflow tables in dependency order."""
    op.drop_index(
        "ix_operational_idempotency_expires_at",
        table_name="operational_idempotency_keys",
    )
    op.drop_index(
        "ix_operational_idempotency_organization_id",
        table_name="operational_idempotency_keys",
    )
    op.drop_table("operational_idempotency_keys")
    op.drop_index(
        "ix_operational_execution_attempts_correlation_id",
        table_name="operational_execution_attempts",
    )
    op.drop_index(
        "ix_operational_execution_attempts_status",
        table_name="operational_execution_attempts",
    )
    op.drop_index(
        "ix_operational_execution_attempts_session_id",
        table_name="operational_execution_attempts",
    )
    op.drop_index(
        "ix_operational_execution_attempts_organization_id",
        table_name="operational_execution_attempts",
    )
    op.drop_table("operational_execution_attempts")
    op.drop_index(
        "ix_operational_approval_decisions_correlation_id",
        table_name="operational_approval_decisions",
    )
    op.drop_index(
        "ix_operational_approval_decisions_status",
        table_name="operational_approval_decisions",
    )
    op.drop_index(
        "ix_operational_approval_decisions_session_id",
        table_name="operational_approval_decisions",
    )
    op.drop_index(
        "ix_operational_approval_decisions_organization_id",
        table_name="operational_approval_decisions",
    )
    op.drop_table("operational_approval_decisions")
    op.drop_index(
        "ix_operational_timeline_correlation_id",
        table_name="operational_timeline_entries",
    )
    op.drop_index(
        "ix_operational_timeline_session_id", table_name="operational_timeline_entries"
    )
    op.drop_index(
        "ix_operational_timeline_organization_id",
        table_name="operational_timeline_entries",
    )
    op.drop_table("operational_timeline_entries")
    op.drop_index(
        "ix_operational_sessions_org_status", table_name="operational_sessions"
    )
    op.drop_index(
        "ix_operational_sessions_correlation_id", table_name="operational_sessions"
    )
    op.drop_index("ix_operational_sessions_status", table_name="operational_sessions")
    op.drop_index(
        "ix_operational_sessions_organization_id", table_name="operational_sessions"
    )
    op.drop_table("operational_sessions")

"""Create PostgreSQL session persistence tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create session aggregate, state, snapshot and transition tables."""
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("managed_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_data", postgresql.JSONB(), nullable=False),
        sa.Column("context_data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("managed_id"),
    )
    op.create_table(
        "session_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("current_stage", sa.String(length=32), nullable=False),
        sa.Column("active_engine", sa.String(length=100), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    for table, payload_columns in (
        (
            "session_snapshots",
            [
                sa.Column("state_data", postgresql.JSONB(), nullable=False),
                sa.Column("context_data", postgresql.JSONB(), nullable=False),
            ],
        ),
        (
            "session_transitions",
            [
                sa.Column("transition_type", sa.String(length=32), nullable=False),
                sa.Column("from_status", sa.String(length=32), nullable=False),
                sa.Column("to_status", sa.String(length=32), nullable=False),
                sa.Column("reason", sa.Text(), nullable=True),
            ],
        ),
    ):
        op.create_table(
            table,
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
            *payload_columns,
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["session_id"], ["sessions.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f(f"ix_{table}_session_id"), table, ["session_id"])


def downgrade() -> None:
    """Drop session persistence tables in dependency order."""
    for table in ("session_transitions", "session_snapshots"):
        op.drop_index(op.f(f"ix_{table}_session_id"), table_name=table)
        op.drop_table(table)
    op.drop_table("session_states")
    op.drop_table("sessions")

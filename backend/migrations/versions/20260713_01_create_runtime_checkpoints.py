"""Create durable authenticated runtime checkpoints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260713_01"
down_revision: str | None = "20260712_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the versioned, organization-scoped runtime checkpoint table."""
    op.create_table(
        "runtime_checkpoints",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cognitive_plan", postgresql.JSONB(), nullable=False),
        sa.Column("resumable_state", postgresql.JSONB(), nullable=True),
        sa.Column("stage_results", postgresql.JSONB(), nullable=False),
        sa.Column("governance_result", postgresql.JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_runtime_checkpoint_version"),
        sa.CheckConstraint(
            "status in ('waiting_approval','completed','failed')",
            name="ck_runtime_checkpoint_status",
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint(
            "organization_id",
            "session_id",
            name="uq_runtime_checkpoint_org_session",
        ),
    )
    op.create_index(
        "ix_runtime_checkpoint_organization_id",
        "runtime_checkpoints",
        ["organization_id"],
    )
    op.create_index("ix_runtime_checkpoint_user_id", "runtime_checkpoints", ["user_id"])
    op.create_index(
        "ix_runtime_checkpoint_correlation_id",
        "runtime_checkpoints",
        ["correlation_id"],
    )
    op.create_index("ix_runtime_checkpoint_status", "runtime_checkpoints", ["status"])
    op.create_index(
        "ix_runtime_checkpoint_org_status",
        "runtime_checkpoints",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    """Drop authenticated runtime checkpoint persistence."""
    op.drop_index("ix_runtime_checkpoint_org_status", table_name="runtime_checkpoints")
    op.drop_index("ix_runtime_checkpoint_status", table_name="runtime_checkpoints")
    op.drop_index(
        "ix_runtime_checkpoint_correlation_id", table_name="runtime_checkpoints"
    )
    op.drop_index("ix_runtime_checkpoint_user_id", table_name="runtime_checkpoints")
    op.drop_index(
        "ix_runtime_checkpoint_organization_id", table_name="runtime_checkpoints"
    )
    op.drop_table("runtime_checkpoints")

"""Create atomic authenticated runtime startup claims."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260713_02"
down_revision: str | None = "20260713_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow executing checkpoints and create persistent startup ownership."""
    op.drop_constraint(
        "ck_runtime_checkpoint_status",
        "runtime_checkpoints",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runtime_checkpoint_status",
        "runtime_checkpoints",
        "status in ('waiting_approval','executing','completed','failed')",
    )
    op.create_table(
        "runtime_start_claims",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("objective", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt > 0", name="ck_runtime_start_claim_attempt"),
        sa.CheckConstraint(
            "status in ('initializing','started','failed')",
            name="ck_runtime_start_claim_status",
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint(
            "organization_id",
            "session_id",
            name="uq_runtime_start_claim_org_session",
        ),
    )
    op.create_index(
        "ix_runtime_start_claim_organization_id",
        "runtime_start_claims",
        ["organization_id"],
    )
    op.create_index(
        "ix_runtime_start_claim_status",
        "runtime_start_claims",
        ["status"],
    )


def downgrade() -> None:
    """Drop startup claims and restore the original checkpoint constraint."""
    op.drop_index(
        "ix_runtime_start_claim_status",
        table_name="runtime_start_claims",
    )
    op.drop_index(
        "ix_runtime_start_claim_organization_id",
        table_name="runtime_start_claims",
    )
    op.drop_table("runtime_start_claims")
    op.drop_constraint(
        "ck_runtime_checkpoint_status",
        "runtime_checkpoints",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runtime_checkpoint_status",
        "runtime_checkpoints",
        "status in ('waiting_approval','completed','failed')",
    )

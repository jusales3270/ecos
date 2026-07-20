"""Create immutable canonical execution results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_01"
down_revision: str | None = "20260713_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create organization-scoped immutable execution result storage."""
    op.create_table(
        "execution_results",
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in "
            "('completed','failed','cancelled','rolled_back','rollback_failed')",
            name="ck_execution_result_terminal_status",
        ),
        sa.CheckConstraint(
            "char_length(fingerprint) = 64",
            name="ck_execution_result_fingerprint_length",
        ),
        sa.PrimaryKeyConstraint("execution_id"),
        sa.UniqueConstraint(
            "organization_id",
            "execution_id",
            name="uq_execution_result_org_execution",
        ),
    )
    op.create_index(
        "ix_execution_results_organization_id",
        "execution_results",
        ["organization_id"],
    )
    op.create_index(
        "ix_execution_results_session_id",
        "execution_results",
        ["session_id"],
    )
    op.create_index(
        "ix_execution_results_plan_id",
        "execution_results",
        ["plan_id"],
    )
    op.create_index(
        "ix_execution_results_correlation_id",
        "execution_results",
        ["correlation_id"],
    )
    op.create_index(
        "ix_execution_results_status",
        "execution_results",
        ["status"],
    )


def downgrade() -> None:
    """Drop canonical execution result storage."""
    op.drop_index("ix_execution_results_status", table_name="execution_results")
    op.drop_index("ix_execution_results_correlation_id", table_name="execution_results")
    op.drop_index("ix_execution_results_plan_id", table_name="execution_results")
    op.drop_index("ix_execution_results_session_id", table_name="execution_results")
    op.drop_index(
        "ix_execution_results_organization_id", table_name="execution_results"
    )
    op.drop_table("execution_results")

"""Add indexed organization scope to persisted sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_07"
down_revision: str | None = "20260711_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add explicit organization_id to sessions for tenant-scoped queries."""
    op.add_column(
        "sessions",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE sessions SET organization_id = "
        "(context_data ->> 'organization_id')::uuid "
        "WHERE organization_id IS NULL"
    )
    op.alter_column("sessions", "organization_id", nullable=False)
    op.create_index(
        "ix_sessions_organization_id",
        "sessions",
        ["organization_id"],
    )


def downgrade() -> None:
    """Remove explicit organization_id from sessions."""
    op.drop_index("ix_sessions_organization_id", table_name="sessions")
    op.drop_column("sessions", "organization_id")

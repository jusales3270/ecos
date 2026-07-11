"""Add organization scope to persisted memories."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_03"
down_revision: str | None = "20260711_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an indexed organization scope column to memories."""
    op.add_column(
        "memories",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_memories_organization_id"), "memories", ["organization_id"]
    )


def downgrade() -> None:
    """Remove the organization scope column from memories."""
    op.drop_index(op.f("ix_memories_organization_id"), table_name="memories")
    op.drop_column("memories", "organization_id")

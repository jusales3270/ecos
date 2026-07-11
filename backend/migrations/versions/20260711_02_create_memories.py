"""Create PostgreSQL memory persistence table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_02"
down_revision: str | None = "20260711_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the memory table and lookup indexes."""
    op.create_table(
        "memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0", name="ck_memories_confidence"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memories_type"), "memories", ["type"])
    op.create_index(op.f("ix_memories_source"), "memories", ["source"])
    op.create_index(
        "ix_memories_tags_gin", "memories", ["tags"], postgresql_using="gin"
    )


def downgrade() -> None:
    """Drop the memory table and its indexes."""
    op.drop_index("ix_memories_tags_gin", table_name="memories")
    op.drop_index(op.f("ix_memories_source"), table_name="memories")
    op.drop_index(op.f("ix_memories_type"), table_name="memories")
    op.drop_table("memories")

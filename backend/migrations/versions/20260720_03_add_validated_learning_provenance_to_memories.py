"""Add idempotent validated Learning provenance to memories."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_03"
down_revision: str | None = "20260720_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable legacy-compatible provenance and strict validated-write rules."""
    uuid_columns = (
        "session_id",
        "execution_id",
        "correlation_id",
        "observation_id",
        "learning_id",
        "learning_candidate_id",
        "proposal_id",
    )
    for name in uuid_columns:
        op.add_column(
            "memories",
            sa.Column(name, postgresql.UUID(as_uuid=True), nullable=True),
        )
    op.add_column("memories", sa.Column("policy_version", sa.String(100)))
    op.add_column("memories", sa.Column("validation_status", sa.String(40)))
    op.add_column("memories", sa.Column("evidence_references", postgresql.JSONB()))
    op.add_column("memories", sa.Column("source_references", postgresql.JSONB()))
    op.add_column("memories", sa.Column("validated_write_fingerprint", sa.String(64)))
    op.add_column(
        "memories",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_memories_org_execution", "memories", ["organization_id", "execution_id"]
    )
    op.create_index(
        "ix_memories_org_learning", "memories", ["organization_id", "learning_id"]
    )
    op.create_index(
        "uq_memories_org_proposal_validated",
        "memories",
        ["organization_id", "proposal_id"],
        unique=True,
        postgresql_where=sa.text("proposal_id IS NOT NULL"),
    )
    required = (
        "organization_id",
        "session_id",
        "execution_id",
        "correlation_id",
        "observation_id",
        "learning_id",
        "learning_candidate_id",
        "policy_version",
        "validation_status",
        "evidence_references",
        "source_references",
        "validated_write_fingerprint",
    )
    op.create_check_constraint(
        "ck_memories_validated_provenance_complete",
        "memories",
        "proposal_id IS NULL OR ("
        + " AND ".join(f"{column} IS NOT NULL" for column in required)
        + ")",
    )
    op.create_check_constraint(
        "ck_memories_validated_status",
        "memories",
        "proposal_id IS NULL OR validation_status = 'validated'",
    )
    op.create_check_constraint(
        "ck_memories_validated_fingerprint_length",
        "memories",
        "proposal_id IS NULL OR char_length(validated_write_fingerprint) = 64",
    )
    op.drop_constraint("ck_learning_run_status", "learning_runs", type_="check")
    op.create_check_constraint(
        "ck_learning_run_status",
        "learning_runs",
        "status in ('processing','validated','completed','failed')",
    )


def downgrade() -> None:
    """Remove validated Learning memory provenance."""
    op.drop_constraint("ck_learning_run_status", "learning_runs", type_="check")
    op.create_check_constraint(
        "ck_learning_run_status",
        "learning_runs",
        "status in ('processing','completed','failed')",
    )
    for name in (
        "ck_memories_validated_fingerprint_length",
        "ck_memories_validated_status",
        "ck_memories_validated_provenance_complete",
    ):
        op.drop_constraint(name, "memories", type_="check")
    op.drop_index("uq_memories_org_proposal_validated", table_name="memories")
    op.drop_index("ix_memories_org_learning", table_name="memories")
    op.drop_index("ix_memories_org_execution", table_name="memories")
    for name in reversed(
        (
            "session_id",
            "execution_id",
            "correlation_id",
            "observation_id",
            "learning_id",
            "learning_candidate_id",
            "proposal_id",
            "policy_version",
            "validation_status",
            "evidence_references",
            "source_references",
            "validated_write_fingerprint",
            "version",
        )
    ):
        op.drop_column("memories", name)

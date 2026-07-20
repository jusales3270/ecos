"""Create canonical observation and claimed learning persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_02"
down_revision: str | None = "20260720_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenant-scoped observation and learning result tables."""
    op.create_table(
        "observation_results",
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("execution_result_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            [
                "execution_results.organization_id",
                "execution_results.execution_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("observation_id"),
        sa.UniqueConstraint(
            "organization_id",
            "observation_id",
            name="uq_observation_org_observation",
        ),
        sa.UniqueConstraint(
            "organization_id", "execution_id", name="uq_observation_org_execution"
        ),
        sa.CheckConstraint(
            "char_length(fingerprint) = 64", name="ck_observation_fingerprint_length"
        ),
        sa.CheckConstraint(
            "char_length(execution_result_fingerprint) = 64",
            name="ck_observation_execution_fingerprint_length",
        ),
    )
    for column in (
        "organization_id",
        "session_id",
        "execution_id",
        "correlation_id",
        "source_event_id",
    ):
        op.create_index(
            f"ix_observation_results_{column}", "observation_results", [column]
        )

    op.create_table(
        "learning_runs",
        sa.Column("learning_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("claim_owner", sa.String(length=200), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id", "observation_id"],
            [
                "observation_results.organization_id",
                "observation_results.observation_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("learning_id"),
        sa.UniqueConstraint(
            "organization_id",
            "observation_id",
            "policy_version",
            name="uq_learning_org_observation_policy",
        ),
        sa.CheckConstraint(
            "status in ('processing','completed','failed')",
            name="ck_learning_run_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_learning_run_version"),
        sa.CheckConstraint(
            "char_length(fingerprint) = 64", name="ck_learning_fingerprint_length"
        ),
    )
    for column in (
        "organization_id",
        "session_id",
        "execution_id",
        "observation_id",
        "correlation_id",
        "status",
        "claim_expires_at",
    ):
        op.create_index(f"ix_learning_runs_{column}", "learning_runs", [column])

    op.create_table(
        "learning_candidates",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learning_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_type", sa.String(length=50), nullable=False),
        sa.Column("assertion", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("validation_status", sa.String(length=40), nullable=False),
        sa.Column("validation_reason", sa.String(length=500), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["learning_id"], ["learning_runs.learning_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint(
            "learning_id", "candidate_id", name="uq_learning_candidate_run_id"
        ),
    )
    op.create_index(
        "ix_learning_candidates_learning_id", "learning_candidates", ["learning_id"]
    )

    op.create_table(
        "learning_validations",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learning_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["learning_candidates.candidate_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["learning_id"], ["learning_runs.learning_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint(
            "learning_id", "candidate_id", name="uq_learning_validation_run_candidate"
        ),
    )
    op.create_index(
        "ix_learning_validations_learning_id", "learning_validations", ["learning_id"]
    )


def downgrade() -> None:
    """Drop learning and observation persistence in dependency order."""
    op.drop_index(
        "ix_learning_validations_learning_id", table_name="learning_validations"
    )
    op.drop_table("learning_validations")
    op.drop_index(
        "ix_learning_candidates_learning_id", table_name="learning_candidates"
    )
    op.drop_table("learning_candidates")
    for column in reversed(
        (
            "organization_id",
            "session_id",
            "execution_id",
            "observation_id",
            "correlation_id",
            "status",
            "claim_expires_at",
        )
    ):
        op.drop_index(f"ix_learning_runs_{column}", table_name="learning_runs")
    op.drop_table("learning_runs")
    for column in reversed(
        (
            "organization_id",
            "session_id",
            "execution_id",
            "correlation_id",
            "source_event_id",
        )
    ):
        op.drop_index(
            f"ix_observation_results_{column}", table_name="observation_results"
        )
    op.drop_table("observation_results")

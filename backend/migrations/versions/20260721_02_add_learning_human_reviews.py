"""Persist governed human review of canonical learning candidates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260721_02"
down_revision: str | None = "20260721_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_learning_run_status", "learning_runs", type_="check")
    op.create_check_constraint(
        "ck_learning_run_status",
        "learning_runs",
        "status in ('processing','validated','human_review_required',"
        "'completed','failed')",
    )
    op.drop_constraint(
        "ck_runtime_checkpoint_status", "runtime_checkpoints", type_="check"
    )
    op.create_check_constraint(
        "ck_runtime_checkpoint_status",
        "runtime_checkpoints",
        "status in ('waiting_approval','executing','waiting_human_review',"
        "'completed','failed')",
    )
    op.create_table(
        "learning_candidate_reviews",
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("learning_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("justification", sa.String(length=1000), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending','approved','rejected')",
            name="ck_learning_candidate_review_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_learning_candidate_review_version"),
        sa.ForeignKeyConstraint(
            ["learning_id"], ["learning_runs.learning_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["learning_candidates.candidate_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("review_id"),
        sa.UniqueConstraint(
            "candidate_id", name="uq_learning_candidate_review_candidate"
        ),
    )
    op.create_index(
        "ix_learning_candidate_review_org_status",
        "learning_candidate_reviews",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_learning_candidate_review_org_session",
        "learning_candidate_reviews",
        ["organization_id", "session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_candidate_review_org_session",
        table_name="learning_candidate_reviews",
    )
    op.drop_index(
        "ix_learning_candidate_review_org_status",
        table_name="learning_candidate_reviews",
    )
    op.drop_table("learning_candidate_reviews")
    op.drop_constraint(
        "ck_runtime_checkpoint_status", "runtime_checkpoints", type_="check"
    )
    op.create_check_constraint(
        "ck_runtime_checkpoint_status",
        "runtime_checkpoints",
        "status in ('waiting_approval','executing','completed','failed')",
    )
    op.drop_constraint("ck_learning_run_status", "learning_runs", type_="check")
    op.create_check_constraint(
        "ck_learning_run_status",
        "learning_runs",
        "status in ('processing','validated','completed','failed')",
    )

"""Add release-candidate reliability and security control tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_02"
down_revision: str | None = "20260712_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create outbox, login throttle and API rate limit tables."""
    op.create_table(
        "transactional_outbox",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("event_json", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_non_negative"),
        sa.CheckConstraint(
            "status in ('pending','processing','delivered','failed')",
            name="ck_outbox_status",
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
    )
    op.create_index(
        "ix_outbox_organization_id", "transactional_outbox", ["organization_id"]
    )
    op.create_index(
        "ix_outbox_correlation_id", "transactional_outbox", ["correlation_id"]
    )
    op.create_index("ix_outbox_event_type", "transactional_outbox", ["event_type"])
    op.create_index("ix_outbox_status", "transactional_outbox", ["status"])
    op.create_index(
        "ix_outbox_next_attempt_at", "transactional_outbox", ["next_attempt_at"]
    )
    op.create_index(
        "ix_outbox_claim",
        "transactional_outbox",
        ["status", "next_attempt_at", "created_at"],
    )

    op.create_table(
        "security_login_throttle",
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("failures >= 0", name="ck_login_throttle_failures"),
        sa.PrimaryKeyConstraint("scope_hash"),
    )
    op.create_index(
        "ix_login_throttle_organization_id",
        "security_login_throttle",
        ["organization_id"],
    )
    op.create_index(
        "ix_login_throttle_blocked_until",
        "security_login_throttle",
        ["blocked_until"],
    )

    op.create_table(
        "api_rate_limit_windows",
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("route_group", sa.String(length=80), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("count >= 0", name="ck_rate_limit_count"),
        sa.PrimaryKeyConstraint("scope_hash"),
    )
    op.create_index(
        "ix_rate_limit_route_group", "api_rate_limit_windows", ["route_group"]
    )
    op.create_index(
        "ix_rate_limit_expires_at", "api_rate_limit_windows", ["expires_at"]
    )


def downgrade() -> None:
    """Drop release-candidate control tables."""
    op.drop_index("ix_rate_limit_expires_at", table_name="api_rate_limit_windows")
    op.drop_index("ix_rate_limit_route_group", table_name="api_rate_limit_windows")
    op.drop_table("api_rate_limit_windows")
    op.drop_index(
        "ix_login_throttle_blocked_until", table_name="security_login_throttle"
    )
    op.drop_index(
        "ix_login_throttle_organization_id", table_name="security_login_throttle"
    )
    op.drop_table("security_login_throttle")
    op.drop_index("ix_outbox_claim", table_name="transactional_outbox")
    op.drop_index("ix_outbox_next_attempt_at", table_name="transactional_outbox")
    op.drop_index("ix_outbox_status", table_name="transactional_outbox")
    op.drop_index("ix_outbox_event_type", table_name="transactional_outbox")
    op.drop_index("ix_outbox_correlation_id", table_name="transactional_outbox")
    op.drop_index("ix_outbox_organization_id", table_name="transactional_outbox")
    op.drop_table("transactional_outbox")

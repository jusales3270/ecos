"""Extend the existing transactional outbox for cognitive terminal events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260721_01"
down_revision: str | None = "20260720_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add stable event identity, typed aggregate references, and claim leases."""
    op.add_column(
        "transactional_outbox",
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "transactional_outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "transactional_outbox", sa.Column("schema_version", sa.Integer(), nullable=True)
    )
    for name in (
        "session_id",
        "execution_id",
        "observation_id",
        "learning_id",
        "memory_id",
        "causation_id",
    ):
        op.add_column(
            "transactional_outbox",
            sa.Column(name, postgresql.UUID(as_uuid=True), nullable=True),
        )
    op.add_column(
        "transactional_outbox", sa.Column("claim_owner", sa.String(200), nullable=True)
    )
    op.add_column(
        "transactional_outbox",
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactional_outbox",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "transactional_outbox",
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transactional_outbox",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE transactional_outbox
        SET outbox_id = message_id,
            event_id = (event_json ->> 'id')::uuid,
            schema_version = COALESCE((event_json ->> 'schema_version')::integer, 1),
            session_id = NULLIF(event_json ->> 'session_id', '')::uuid,
            causation_id = NULLIF(
                event_json -> 'metadata' ->> 'causation_id', ''
            )::uuid,
            available_at = next_attempt_at,
            published_at = delivered_at
        """
    )
    op.alter_column("transactional_outbox", "event_id", nullable=False)
    op.alter_column("transactional_outbox", "outbox_id", nullable=False)
    op.alter_column("transactional_outbox", "schema_version", nullable=False)
    op.alter_column("transactional_outbox", "available_at", nullable=False)
    op.create_unique_constraint(
        "uq_outbox_outbox_id", "transactional_outbox", ["outbox_id"]
    )
    op.create_unique_constraint(
        "uq_outbox_event_id", "transactional_outbox", ["event_id"]
    )
    op.create_check_constraint(
        "ck_outbox_schema_version_positive",
        "transactional_outbox",
        "schema_version > 0",
    )
    op.create_check_constraint(
        "ck_outbox_version_positive", "transactional_outbox", "version > 0"
    )
    op.create_index(
        "ix_outbox_status_available",
        "transactional_outbox",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_outbox_claim_expires_at", "transactional_outbox", ["claim_expires_at"]
    )
    op.create_index(
        "uq_outbox_cognitive_terminal",
        "transactional_outbox",
        ["aggregate_type", "aggregate_id", "event_type"],
        unique=True,
        postgresql_where=sa.text(
            "aggregate_type IN ('execution', 'observation', 'learning', 'memory')"
        ),
    )


def downgrade() -> None:
    """Remove cognitive outbox extensions while preserving the legacy table."""
    op.drop_index("uq_outbox_cognitive_terminal", table_name="transactional_outbox")
    op.drop_index("ix_outbox_claim_expires_at", table_name="transactional_outbox")
    op.drop_index("ix_outbox_status_available", table_name="transactional_outbox")
    op.drop_constraint(
        "ck_outbox_version_positive", "transactional_outbox", type_="check"
    )
    op.drop_constraint(
        "ck_outbox_schema_version_positive", "transactional_outbox", type_="check"
    )
    op.drop_constraint("uq_outbox_event_id", "transactional_outbox", type_="unique")
    op.drop_constraint("uq_outbox_outbox_id", "transactional_outbox", type_="unique")
    for name in (
        "version",
        "published_at",
        "available_at",
        "claim_expires_at",
        "claim_owner",
        "causation_id",
        "memory_id",
        "learning_id",
        "observation_id",
        "execution_id",
        "session_id",
        "schema_version",
        "event_id",
        "outbox_id",
    ):
        op.drop_column("transactional_outbox", name)

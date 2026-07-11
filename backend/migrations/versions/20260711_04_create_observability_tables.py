"""Create observability event, audit, metric, trace, log and alert tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_04"
down_revision: str | None = "20260711_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create append-only observability tables and lookup indexes."""
    op.create_table(
        "event_records",
        sa.Column("stored_sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_component", sa.String(length=200), nullable=False),
        sa.Column("source_version", sa.String(length=50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("classification", sa.String(length=50), nullable=False),
        sa.Column("security_level", sa.String(length=50), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("retention_class", sa.String(length=50), nullable=False),
        sa.Column("integrity_status", sa.String(length=50), nullable=False),
        sa.Column("event_json", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("event_version > 0", name="ck_event_records_event_version"),
        sa.CheckConstraint(
            "schema_version > 0", name="ck_event_records_schema_version"
        ),
        sa.PrimaryKeyConstraint("stored_sequence"),
        sa.UniqueConstraint("event_id", name="uq_event_records_event_id"),
    )
    op.create_index("ix_event_records_fingerprint", "event_records", ["fingerprint"])
    op.create_index(
        "ix_event_records_organization_sequence",
        "event_records",
        ["organization_id", "stored_sequence"],
    )
    op.create_index(
        "ix_event_records_session_sequence",
        "event_records",
        ["session_id", "stored_sequence"],
    )
    op.create_index(
        "ix_event_records_correlation_sequence",
        "event_records",
        ["correlation_id", "stored_sequence"],
    )
    op.create_index(
        "ix_event_records_type_occurred",
        "event_records",
        ["event_type", "occurred_at"],
    )
    op.create_index(
        "ix_event_records_category_occurred",
        "event_records",
        ["category", "occurred_at"],
    )
    op.create_index(
        "ix_event_records_source_occurred",
        "event_records",
        ["source_component", "occurred_at"],
    )
    op.create_index(
        "ix_event_records_organization_occurred",
        "event_records",
        ["organization_id", "occurred_at"],
    )

    op.create_table(
        "audit_records",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("component", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_audit_records_source_event_id", "audit_records", ["source_event_id"]
    )
    op.create_index(
        "ix_audit_records_organization_id", "audit_records", ["organization_id"]
    )
    op.create_index("ix_audit_records_session_id", "audit_records", ["session_id"])
    op.create_index("ix_audit_records_plan_id", "audit_records", ["plan_id"])
    op.create_index(
        "ix_audit_records_correlation_id", "audit_records", ["correlation_id"]
    )
    op.create_index("ix_audit_records_action", "audit_records", ["action"])

    op.create_table(
        "metric_records",
        sa.Column("metric_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("metric_id"),
    )
    op.create_index(
        "ix_metric_records_organization_id", "metric_records", ["organization_id"]
    )
    op.create_index(
        "ix_metric_records_source_event_id", "metric_records", ["source_event_id"]
    )
    op.create_index("ix_metric_records_metric_name", "metric_records", ["metric_name"])

    op.create_table(
        "trace_records",
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("trace_id"),
    )
    op.create_index(
        "ix_trace_records_organization_id", "trace_records", ["organization_id"]
    )
    op.create_index(
        "ix_trace_records_correlation_id", "trace_records", ["correlation_id"]
    )
    op.create_index("ix_trace_records_session_id", "trace_records", ["session_id"])

    op.create_table(
        "trace_spans",
        sa.Column("span_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component", sa.String(length=200), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("span_id"),
    )
    op.create_index("ix_trace_spans_trace_id", "trace_spans", ["trace_id"])

    op.create_table(
        "structured_log_records",
        sa.Column("log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("component", sa.String(length=200), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index(
        "ix_structured_log_records_organization_id",
        "structured_log_records",
        ["organization_id"],
    )
    op.create_index(
        "ix_structured_log_records_severity", "structured_log_records", ["severity"]
    )
    op.create_index(
        "ix_structured_log_records_component", "structured_log_records", ["component"]
    )

    op.create_table(
        "alert_records",
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index("ix_alert_records_rule_id", "alert_records", ["rule_id"])
    op.create_index(
        "ix_alert_records_organization_id", "alert_records", ["organization_id"]
    )
    op.create_index(
        "ix_alert_records_source_event_id", "alert_records", ["source_event_id"]
    )
    op.create_index("ix_alert_records_status", "alert_records", ["status"])

    op.create_table(
        "health_snapshot_records",
        sa.Column("health_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component", sa.String(length=200), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("health_id"),
    )
    op.create_index(
        "ix_health_snapshot_records_component",
        "health_snapshot_records",
        ["component"],
    )
    op.create_index(
        "ix_health_snapshot_records_status",
        "health_snapshot_records",
        ["status"],
    )


def downgrade() -> None:
    """Drop observability tables and indexes."""
    op.drop_index(
        "ix_health_snapshot_records_status", table_name="health_snapshot_records"
    )
    op.drop_index(
        "ix_health_snapshot_records_component", table_name="health_snapshot_records"
    )
    op.drop_table("health_snapshot_records")
    op.drop_index("ix_alert_records_status", table_name="alert_records")
    op.drop_index("ix_alert_records_source_event_id", table_name="alert_records")
    op.drop_index("ix_alert_records_organization_id", table_name="alert_records")
    op.drop_index("ix_alert_records_rule_id", table_name="alert_records")
    op.drop_table("alert_records")
    op.drop_index(
        "ix_structured_log_records_component", table_name="structured_log_records"
    )
    op.drop_index(
        "ix_structured_log_records_severity", table_name="structured_log_records"
    )
    op.drop_index(
        "ix_structured_log_records_organization_id",
        table_name="structured_log_records",
    )
    op.drop_table("structured_log_records")
    op.drop_index("ix_trace_spans_trace_id", table_name="trace_spans")
    op.drop_table("trace_spans")
    op.drop_index("ix_trace_records_session_id", table_name="trace_records")
    op.drop_index("ix_trace_records_correlation_id", table_name="trace_records")
    op.drop_index("ix_trace_records_organization_id", table_name="trace_records")
    op.drop_table("trace_records")
    op.drop_index("ix_metric_records_metric_name", table_name="metric_records")
    op.drop_index("ix_metric_records_source_event_id", table_name="metric_records")
    op.drop_index("ix_metric_records_organization_id", table_name="metric_records")
    op.drop_table("metric_records")
    op.drop_index("ix_audit_records_action", table_name="audit_records")
    op.drop_index("ix_audit_records_correlation_id", table_name="audit_records")
    op.drop_index("ix_audit_records_plan_id", table_name="audit_records")
    op.drop_index("ix_audit_records_session_id", table_name="audit_records")
    op.drop_index("ix_audit_records_organization_id", table_name="audit_records")
    op.drop_index("ix_audit_records_source_event_id", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_index("ix_event_records_organization_occurred", table_name="event_records")
    op.drop_index("ix_event_records_source_occurred", table_name="event_records")
    op.drop_index("ix_event_records_category_occurred", table_name="event_records")
    op.drop_index("ix_event_records_type_occurred", table_name="event_records")
    op.drop_index("ix_event_records_correlation_sequence", table_name="event_records")
    op.drop_index("ix_event_records_session_sequence", table_name="event_records")
    op.drop_index("ix_event_records_organization_sequence", table_name="event_records")
    op.drop_index("ix_event_records_fingerprint", table_name="event_records")
    op.drop_table("event_records")

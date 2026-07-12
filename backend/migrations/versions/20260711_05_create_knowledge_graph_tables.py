"""Create Knowledge Graph entity and relationship version tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_05"
down_revision: str | None = "20260711_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create append-only Knowledge Graph tables and lookup indexes."""
    op.create_table(
        "knowledge_entity_versions",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", sa.String(length=200), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aliases", postgresql.JSONB(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_references", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_references", postgresql.JSONB(), nullable=False),
        sa.Column("supersedes_entity_version", sa.Integer(), nullable=True),
        sa.Column("identity_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_knowledge_entity_confidence",
        ),
        sa.CheckConstraint(
            "importance >= 0.0 AND importance <= 1.0",
            name="ck_knowledge_entity_importance",
        ),
        sa.CheckConstraint("version > 0", name="ck_knowledge_entity_version_positive"),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint("entity_id", "version", name="uq_knowledge_entity_version"),
    )
    op.create_index(
        "ix_knowledge_entities_org_type",
        "knowledge_entity_versions",
        ["organization_id", "entity_type"],
    )
    op.create_index(
        "ix_knowledge_entities_org_normalized_name",
        "knowledge_entity_versions",
        ["organization_id", "normalized_name"],
    )
    op.create_index(
        "ix_knowledge_entities_org_status",
        "knowledge_entity_versions",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_knowledge_entities_identity_fingerprint",
        "knowledge_entity_versions",
        ["identity_fingerprint"],
    )
    op.create_index(
        "ix_knowledge_entities_valid_from",
        "knowledge_entity_versions",
        ["valid_from"],
    )
    op.create_index(
        "ix_knowledge_entities_tags_gin",
        "knowledge_entity_versions",
        ["tags"],
        postgresql_using="gin",
    )

    op.create_table(
        "knowledge_relationship_versions",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_id", sa.String(length=240), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", sa.String(length=200), nullable=False),
        sa.Column("target_entity_id", sa.String(length=200), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_references", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_references", postgresql.JSONB(), nullable=False),
        sa.Column("supersedes_relationship_version", sa.Integer(), nullable=True),
        sa.Column("relationship_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("constraints", postgresql.JSONB(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "weight >= 0.0 AND weight <= 1.0",
            name="ck_knowledge_relationship_weight",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_knowledge_relationship_confidence",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_knowledge_relationship_version_positive"
        ),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint(
            "relationship_id",
            "version",
            name="uq_knowledge_relationship_version",
        ),
    )
    op.create_index(
        "ix_knowledge_relationships_org_source",
        "knowledge_relationship_versions",
        ["organization_id", "source_entity_id"],
    )
    op.create_index(
        "ix_knowledge_relationships_org_target",
        "knowledge_relationship_versions",
        ["organization_id", "target_entity_id"],
    )
    op.create_index(
        "ix_knowledge_relationships_org_type",
        "knowledge_relationship_versions",
        ["organization_id", "relationship_type"],
    )
    op.create_index(
        "ix_knowledge_relationships_source_target",
        "knowledge_relationship_versions",
        ["source_entity_id", "target_entity_id"],
    )
    op.create_index(
        "ix_knowledge_relationships_fingerprint",
        "knowledge_relationship_versions",
        ["relationship_fingerprint"],
    )
    op.create_index(
        "ix_knowledge_relationships_valid_from",
        "knowledge_relationship_versions",
        ["valid_from"],
    )


def downgrade() -> None:
    """Drop Knowledge Graph tables and indexes."""
    op.drop_index(
        "ix_knowledge_relationships_valid_from",
        table_name="knowledge_relationship_versions",
    )
    op.drop_index(
        "ix_knowledge_relationships_fingerprint",
        table_name="knowledge_relationship_versions",
    )
    op.drop_index(
        "ix_knowledge_relationships_source_target",
        table_name="knowledge_relationship_versions",
    )
    op.drop_index(
        "ix_knowledge_relationships_org_type",
        table_name="knowledge_relationship_versions",
    )
    op.drop_index(
        "ix_knowledge_relationships_org_target",
        table_name="knowledge_relationship_versions",
    )
    op.drop_index(
        "ix_knowledge_relationships_org_source",
        table_name="knowledge_relationship_versions",
    )
    op.drop_table("knowledge_relationship_versions")
    op.drop_index(
        "ix_knowledge_entities_tags_gin", table_name="knowledge_entity_versions"
    )
    op.drop_index(
        "ix_knowledge_entities_valid_from", table_name="knowledge_entity_versions"
    )
    op.drop_index(
        "ix_knowledge_entities_identity_fingerprint",
        table_name="knowledge_entity_versions",
    )
    op.drop_index(
        "ix_knowledge_entities_org_status", table_name="knowledge_entity_versions"
    )
    op.drop_index(
        "ix_knowledge_entities_org_normalized_name",
        table_name="knowledge_entity_versions",
    )
    op.drop_index(
        "ix_knowledge_entities_org_type", table_name="knowledge_entity_versions"
    )
    op.drop_table("knowledge_entity_versions")

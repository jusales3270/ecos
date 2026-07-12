"""Create local security identity and authentication tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_06"
down_revision: str | None = "20260711_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create append-only compatible local identity/authentication tables."""
    op.create_table(
        "security_users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email", name="uq_security_users_email"),
    )
    op.create_table(
        "security_organizations",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    op.create_table(
        "security_memberships",
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("roles", postgresql.JSONB(), nullable=False),
        sa.Column("permissions", postgresql.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.UniqueConstraint(
            "user_id",
            "organization_id",
            name="uq_security_memberships_user_org",
        ),
    )
    op.create_index(
        "ix_security_memberships_user_id", "security_memberships", ["user_id"]
    )
    op.create_index(
        "ix_security_memberships_organization_id",
        "security_memberships",
        ["organization_id"],
    )
    op.create_index(
        "ix_security_memberships_roles_gin",
        "security_memberships",
        ["roles"],
        postgresql_using="gin",
    )
    op.create_table(
        "security_password_credentials",
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("credential_id"),
        sa.UniqueConstraint("user_id", name="uq_security_password_credentials_user"),
    )
    op.create_table(
        "security_auth_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authentication_method", sa.String(length=50), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > issued_at", name="ck_auth_session_expiry"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("token_id", name="uq_security_auth_sessions_token_id"),
    )
    op.create_index(
        "ix_security_auth_sessions_user_id",
        "security_auth_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_security_auth_sessions_organization_id",
        "security_auth_sessions",
        ["organization_id"],
    )
    op.create_index(
        "ix_security_auth_sessions_org_expires",
        "security_auth_sessions",
        ["organization_id", "expires_at"],
    )


def downgrade() -> None:
    """Drop local security tables."""
    op.drop_index(
        "ix_security_auth_sessions_org_expires",
        table_name="security_auth_sessions",
    )
    op.drop_index(
        "ix_security_auth_sessions_organization_id",
        table_name="security_auth_sessions",
    )
    op.drop_index(
        "ix_security_auth_sessions_user_id",
        table_name="security_auth_sessions",
    )
    op.drop_table("security_auth_sessions")
    op.drop_table("security_password_credentials")
    op.drop_index(
        "ix_security_memberships_roles_gin",
        table_name="security_memberships",
    )
    op.drop_index(
        "ix_security_memberships_organization_id",
        table_name="security_memberships",
    )
    op.drop_index("ix_security_memberships_user_id", table_name="security_memberships")
    op.drop_table("security_memberships")
    op.drop_table("security_organizations")
    op.drop_table("security_users")

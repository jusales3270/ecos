"""Immutable identity, authentication and authorization models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class AuthenticationMethod(StrEnum):
    """Supported local authentication methods."""

    PASSWORD = "password"
    BEARER_TOKEN = "bearer_token"
    DEMO = "demo"


class Role(StrEnum):
    """Built-in organization-scoped roles."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    MANAGER = "manager"
    EXECUTIVE = "executive"
    EXECUTIVE_BOARD = "executive_board"
    AUDITOR = "auditor"
    ADMIN = "admin"
    GLOBAL_ADMIN = "global_admin"


class Permission(StrEnum):
    """Explicit permissions enforced by services and API dependencies."""

    READ_ORG_SETTINGS = "org_settings:read"
    WRITE_ORG_SETTINGS = "org_settings:write"
    READ_SESSIONS = "sessions:read"
    WRITE_SESSIONS = "sessions:write"
    READ_MEMORY = "memory:read"
    WRITE_MEMORY = "memory:write"
    READ_KNOWLEDGE_GRAPH = "knowledge_graph:read"
    WRITE_KNOWLEDGE_GRAPH = "knowledge_graph:write"
    READ_EVENTS = "events:read"
    READ_AUDIT = "audit:read"
    CREATE_DECISION = "decisions:create"
    APPROVE_DECISION = "decisions:approve"
    GOVERNANCE_ACTION = "governance:action"
    EXECUTE_ACTION = "execution:execute"
    READ_OBSERVATION = "observation:read"
    READ_LEARNING = "learning:read"
    ADMINISTER_ORGANIZATION = "organization:admin"
    ADMINISTER_GLOBAL = "global:admin"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(
        {
            Permission.READ_SESSIONS,
            Permission.READ_MEMORY,
            Permission.READ_KNOWLEDGE_GRAPH,
            Permission.READ_OBSERVATION,
            Permission.READ_LEARNING,
        }
    ),
    Role.OPERATOR: frozenset(
        {
            Permission.READ_SESSIONS,
            Permission.WRITE_SESSIONS,
            Permission.READ_MEMORY,
            Permission.WRITE_MEMORY,
            Permission.READ_KNOWLEDGE_GRAPH,
            Permission.CREATE_DECISION,
            Permission.EXECUTE_ACTION,
            Permission.READ_OBSERVATION,
            Permission.READ_LEARNING,
        }
    ),
    Role.MANAGER: frozenset(
        {
            Permission.READ_ORG_SETTINGS,
            Permission.READ_SESSIONS,
            Permission.WRITE_SESSIONS,
            Permission.READ_MEMORY,
            Permission.WRITE_MEMORY,
            Permission.READ_KNOWLEDGE_GRAPH,
            Permission.WRITE_KNOWLEDGE_GRAPH,
            Permission.READ_EVENTS,
            Permission.CREATE_DECISION,
            Permission.APPROVE_DECISION,
            Permission.GOVERNANCE_ACTION,
            Permission.EXECUTE_ACTION,
            Permission.READ_OBSERVATION,
            Permission.READ_LEARNING,
        }
    ),
    Role.EXECUTIVE: frozenset(
        {
            Permission.READ_ORG_SETTINGS,
            Permission.WRITE_ORG_SETTINGS,
            Permission.READ_SESSIONS,
            Permission.READ_MEMORY,
            Permission.READ_KNOWLEDGE_GRAPH,
            Permission.READ_EVENTS,
            Permission.READ_AUDIT,
            Permission.CREATE_DECISION,
            Permission.APPROVE_DECISION,
            Permission.GOVERNANCE_ACTION,
            Permission.EXECUTE_ACTION,
            Permission.READ_OBSERVATION,
            Permission.READ_LEARNING,
        }
    ),
    Role.EXECUTIVE_BOARD: frozenset(
        {
            Permission.READ_ORG_SETTINGS,
            Permission.WRITE_ORG_SETTINGS,
            Permission.READ_SESSIONS,
            Permission.READ_MEMORY,
            Permission.READ_KNOWLEDGE_GRAPH,
            Permission.READ_EVENTS,
            Permission.READ_AUDIT,
            Permission.CREATE_DECISION,
            Permission.APPROVE_DECISION,
            Permission.GOVERNANCE_ACTION,
            Permission.EXECUTE_ACTION,
            Permission.READ_OBSERVATION,
            Permission.READ_LEARNING,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Permission.READ_ORG_SETTINGS,
            Permission.READ_SESSIONS,
            Permission.READ_MEMORY,
            Permission.READ_KNOWLEDGE_GRAPH,
            Permission.READ_EVENTS,
            Permission.READ_AUDIT,
            Permission.READ_OBSERVATION,
            Permission.READ_LEARNING,
        }
    ),
    Role.ADMIN: frozenset(
        {
            Permission.READ_ORG_SETTINGS,
            Permission.WRITE_ORG_SETTINGS,
            Permission.READ_SESSIONS,
            Permission.WRITE_SESSIONS,
            Permission.READ_MEMORY,
            Permission.WRITE_MEMORY,
            Permission.READ_KNOWLEDGE_GRAPH,
            Permission.WRITE_KNOWLEDGE_GRAPH,
            Permission.READ_EVENTS,
            Permission.READ_AUDIT,
            Permission.CREATE_DECISION,
            Permission.APPROVE_DECISION,
            Permission.GOVERNANCE_ACTION,
            Permission.EXECUTE_ACTION,
            Permission.READ_OBSERVATION,
            Permission.READ_LEARNING,
            Permission.ADMINISTER_ORGANIZATION,
        }
    ),
    Role.GLOBAL_ADMIN: frozenset({Permission.ADMINISTER_GLOBAL}),
}


class SecurityModel(BaseModel):
    """Base immutable model for security contracts."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


class UserIdentity(SecurityModel):
    """Local immutable user identity."""

    user_id: UUID = Field(default_factory=uuid4)
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class OrganizationIdentity(SecurityModel):
    """Organization identity used for tenant isolation."""

    organization_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class UserOrganizationMembership(SecurityModel):
    """Immutable user-to-organization binding."""

    membership_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    organization_id: UUID
    roles: tuple[Role, ...]
    permissions: tuple[Permission, ...] = Field(default_factory=tuple)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("roles", "permissions", mode="before")
    @classmethod
    def tuple_values(cls, value: object) -> tuple[object, ...]:
        return tuple(value or ())

    @model_validator(mode="after")
    def validate_roles(self) -> Self:
        if not self.roles:
            raise ValueError("membership requires at least one role")
        return self

    @property
    def effective_permissions(self) -> tuple[Permission, ...]:
        """Return role-derived plus explicit permissions."""
        permissions: set[Permission] = set(self.permissions)
        for role in self.roles:
            permissions.update(ROLE_PERMISSIONS[role])
        return tuple(sorted(permissions, key=lambda item: item.value))


class PasswordCredential(SecurityModel):
    """Password verifier owned by one user."""

    credential_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    password_hash: str = Field(min_length=1)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class AuthSession(SecurityModel):
    """Local authentication session/token record."""

    session_id: UUID = Field(default_factory=uuid4)
    token_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    organization_id: UUID
    authentication_method: AuthenticationMethod
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self

    @property
    def active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utc_now()


class AuthenticatedPrincipal(SecurityModel):
    """Principal reconstructed from a validated credential or token."""

    user_id: UUID
    organization_id: UUID
    roles: tuple[Role, ...]
    permissions: tuple[Permission, ...]
    authentication_method: AuthenticationMethod
    session_id: UUID | None
    token_id: UUID | None
    issued_at: datetime
    expires_at: datetime
    correlation_id: UUID

    @field_validator("roles", "permissions", mode="before")
    @classmethod
    def tuple_principal_values(cls, value: object) -> tuple[object, ...]:
        return tuple(value or ())

    def has_permission(self, permission: Permission) -> bool:
        """Return whether this principal has one permission."""
        return permission in self.permissions

    def require_permission(self, permission: Permission) -> None:
        """Raise when the permission is absent."""
        if not self.has_permission(permission):
            from ecos.security.exceptions import AuthorizationError

            raise AuthorizationError(f"missing permission: {permission.value}")


class SecurityContext(SecurityModel):
    """Per-request security context propagated to services."""

    principal: AuthenticatedPrincipal
    correlation_id: UUID

    @property
    def user_id(self) -> UUID:
        return self.principal.user_id

    @property
    def organization_id(self) -> UUID:
        return self.principal.organization_id

    @property
    def roles(self) -> tuple[Role, ...]:
        return self.principal.roles

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return self.principal.permissions

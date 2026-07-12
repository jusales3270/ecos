"""Security, authentication, authorization and tenant isolation contracts."""

from ecos.security.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CrossTenantAccessError,
)
from ecos.security.models import (
    AuthenticatedPrincipal,
    AuthenticationMethod,
    AuthSession,
    OrganizationIdentity,
    PasswordCredential,
    Permission,
    Role,
    SecurityContext,
    UserIdentity,
    UserOrganizationMembership,
)
from ecos.security.repository import InMemorySecurityRepository, SecurityRepository
from ecos.security.scoped import TenantScopedMemoryService, TenantScopedSessionService
from ecos.security.service import SecurityIdentityPort, SecurityService

__all__ = [
    "AuthSession",
    "AuthenticatedPrincipal",
    "AuthenticationError",
    "AuthenticationMethod",
    "AuthorizationError",
    "CrossTenantAccessError",
    "InMemorySecurityRepository",
    "OrganizationIdentity",
    "PasswordCredential",
    "Permission",
    "Role",
    "SecurityContext",
    "SecurityIdentityPort",
    "SecurityRepository",
    "SecurityService",
    "TenantScopedMemoryService",
    "TenantScopedSessionService",
    "UserIdentity",
    "UserOrganizationMembership",
]

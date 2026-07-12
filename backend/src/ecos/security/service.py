"""Local deterministic authentication, authorization and tenant scoping."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from ecos.events import (
    Event,
    EventCategory,
    EventClassification,
    EventMetadata,
    EventPriority,
    EventSecurityLevel,
    EventService,
    EventType,
)
from ecos.governance.models import ValidatedIdentity
from ecos.governance.provider import IdentityPort
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
    utc_now,
)
from ecos.security.repository import SecurityRepository

Clock = Callable[[], datetime]


class SecurityService:
    """Authenticate local users and enforce organization-scoped permissions."""

    def __init__(
        self,
        repository: SecurityRepository,
        *,
        token_secret: str,
        issuer: str,
        audience: str,
        token_ttl: timedelta,
        token_key_ring: dict[str, str] | None = None,
        active_key_id: str = "local-dev",
        clock_skew_seconds: int = 30,
        event_service: EventService | None = None,
        clock: Clock | None = None,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        if len(token_secret) < 32:
            raise ValueError("token_secret must contain at least 32 characters")
        self._repository = repository
        self._token_secret = token_secret
        self._active_key_id = active_key_id
        self._token_key_ring = token_key_ring or {active_key_id: token_secret}
        if active_key_id not in self._token_key_ring:
            raise ValueError("active_key_id must exist in token_key_ring")
        for key_id, secret in self._token_key_ring.items():
            if not key_id or len(secret) < 32:
                raise ValueError(
                    "all JWT key ring secrets must contain at least 32 characters"
                )
        self._issuer = issuer
        self._audience = audience
        self._token_ttl = token_ttl
        self._clock_skew_seconds = clock_skew_seconds
        self._event_service = event_service
        self._clock = clock or utc_now
        self._password_hasher = password_hasher or PasswordHasher()

    def create_local_user(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        organization_name: str,
        roles: tuple[Role, ...],
        permissions: tuple[Permission, ...] = (),
        user_id: UUID | None = None,
        organization_id: UUID | None = None,
    ) -> tuple[UserIdentity, OrganizationIdentity, UserOrganizationMembership]:
        """Create a user, organization membership and password hash."""
        user = self._repository.add_user(
            UserIdentity(
                user_id=user_id or uuid4(),
                email=email,
                display_name=display_name,
            )
        )
        organization = self._repository.add_organization(
            OrganizationIdentity(
                organization_id=organization_id or uuid4(),
                name=organization_name,
            )
        )
        membership = self._repository.add_membership(
            UserOrganizationMembership(
                user_id=user.user_id,
                organization_id=organization.organization_id,
                roles=roles,
                permissions=permissions,
            )
        )
        self._repository.set_password_credential(
            PasswordCredential(
                user_id=user.user_id,
                password_hash=self.hash_password(password),
            )
        )
        self._publish_security_event(
            EventType.SECURITY_ROLE_CHANGED,
            organization.organization_id,
            actor_id=user.user_id,
            payload={"roles": ",".join(role.value for role in roles)},
        )
        return user, organization, membership

    def hash_password(self, password: str) -> str:
        """Hash a password with Argon2id via argon2-cffi."""
        if not password:
            raise ValueError("password cannot be empty")
        return self._password_hasher.hash(password)

    def login(
        self,
        *,
        email: str,
        password: str,
        organization_id: UUID,
        correlation_id: UUID,
    ) -> tuple[str, AuthenticatedPrincipal]:
        """Validate password credentials and issue a signed bearer token."""
        user = self._repository.get_user_by_email(email)
        if user is None or not user.active:
            self._publish_security_event(
                EventType.AUTHENTICATION_FAILED,
                organization_id,
                correlation_id=correlation_id,
                payload={"reason": "unknown_user"},
            )
            raise AuthenticationError("invalid credentials")
        credential = self._repository.get_password_credential(user.user_id)
        if credential is None or not credential.active:
            self._publish_security_event(
                EventType.AUTHENTICATION_FAILED,
                organization_id,
                actor_id=user.user_id,
                correlation_id=correlation_id,
                payload={"reason": "missing_credential"},
            )
            raise AuthenticationError("invalid credentials")
        try:
            verified = self._password_hasher.verify(
                credential.password_hash,
                password,
            )
        except VerifyMismatchError:
            verified = False
        if not verified:
            self._publish_security_event(
                EventType.AUTHENTICATION_FAILED,
                organization_id,
                actor_id=user.user_id,
                correlation_id=correlation_id,
                payload={"reason": "bad_password"},
            )
            raise AuthenticationError("invalid credentials")
        principal = self._principal_for_user(
            user.user_id,
            organization_id,
            AuthenticationMethod.PASSWORD,
            correlation_id=correlation_id,
        )
        session = AuthSession(
            session_id=principal.session_id or uuid4(),
            token_id=principal.token_id or uuid4(),
            user_id=user.user_id,
            organization_id=organization_id,
            authentication_method=AuthenticationMethod.PASSWORD,
            issued_at=principal.issued_at,
            expires_at=principal.expires_at,
        )
        self._repository.create_auth_session(session)
        principal = principal.model_copy(
            update={"session_id": session.session_id, "token_id": session.token_id}
        )
        token = self._encode_token(principal)
        self._publish_security_event(
            EventType.AUTHENTICATION_SUCCEEDED,
            organization_id,
            actor_id=user.user_id,
            correlation_id=correlation_id,
            payload={"authentication_method": AuthenticationMethod.PASSWORD.value},
        )
        self._publish_security_event(
            EventType.AUTH_SESSION_CREATED,
            organization_id,
            actor_id=user.user_id,
            correlation_id=correlation_id,
            payload={"session_id": str(session.session_id)},
        )
        return token, principal

    def authenticate_bearer_token(
        self, token: str, *, correlation_id: UUID
    ) -> AuthenticatedPrincipal:
        """Decode, verify and resolve a bearer token."""
        try:
            header = jwt.get_unverified_header(token)
            key_id = str(header.get("kid", ""))
            if key_id not in self._token_key_ring:
                raise AuthenticationError("unknown token key")
            payload = jwt.decode(
                token,
                self._token_key_ring[key_id],
                algorithms=["HS256"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
            )
            token_id = UUID(str(payload["jti"]))
            session = self._repository.get_auth_session_by_token_id(token_id)
            if session is None or session.revoked_at is not None:
                raise AuthenticationError("token is not active")
            if session.expires_at <= self._now():
                raise AuthenticationError("token expired")
            principal = self._principal_for_user(
                UUID(str(payload["sub"])),
                UUID(str(payload["org"])),
                AuthenticationMethod.BEARER_TOKEN,
                session_id=session.session_id,
                token_id=token_id,
                issued_at=session.issued_at,
                expires_at=session.expires_at,
                correlation_id=correlation_id,
            )
            return principal
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError("token expired") from error
        except (jwt.InvalidTokenError, ValueError, KeyError) as error:
            raise AuthenticationError("invalid token") from error

    def demo_principal(self, *, correlation_id: UUID) -> AuthenticatedPrincipal:
        """Return an explicit bounded demo identity."""
        user_id = UUID("00000000-0000-4000-8000-000000000017")
        organization_id = UUID("00000000-0000-4000-8000-0000000000ec")
        if self._repository.get_organization(organization_id) is None:
            self._repository.add_organization(
                OrganizationIdentity(
                    organization_id=organization_id,
                    name="ECOS Demo Organization",
                )
            )
        if self._repository.get_user(user_id) is None:
            self._repository.add_user(
                UserIdentity(
                    user_id=user_id,
                    email="demo@ecos.local",
                    display_name="ECOS Demo User",
                )
            )
        if self._repository.get_membership(user_id, organization_id) is None:
            self._repository.add_membership(
                UserOrganizationMembership(
                    user_id=user_id,
                    organization_id=organization_id,
                    roles=(Role.ADMIN,),
                    permissions=(),
                )
            )
        now = self._now()
        return self._principal_for_user(
            user_id,
            organization_id,
            AuthenticationMethod.DEMO,
            session_id=UUID("00000000-0000-4000-8000-0000000000de"),
            token_id=None,
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            correlation_id=correlation_id,
        )

    def context_for_principal(
        self, principal: AuthenticatedPrincipal
    ) -> SecurityContext:
        """Build a request context for a validated principal."""
        return SecurityContext(
            principal=principal,
            correlation_id=principal.correlation_id,
        )

    def authorize(
        self,
        principal: AuthenticatedPrincipal,
        permission: Permission,
        *,
        organization_id: UUID | None = None,
    ) -> None:
        """Enforce one permission and optional tenant boundary."""
        if organization_id is not None and organization_id != principal.organization_id:
            self._publish_security_event(
                EventType.CROSS_TENANT_ACCESS_ATTEMPTED,
                principal.organization_id,
                actor_id=principal.user_id,
                correlation_id=principal.correlation_id,
                payload={"target_organization_id": str(organization_id)},
            )
            raise CrossTenantAccessError()
        if permission not in principal.permissions:
            self._publish_security_event(
                EventType.ACCESS_DENIED,
                principal.organization_id,
                actor_id=principal.user_id,
                correlation_id=principal.correlation_id,
                payload={"permission": permission.value},
            )
            raise AuthorizationError(f"missing permission: {permission.value}")

    def require_same_organization(
        self,
        principal: AuthenticatedPrincipal,
        resource_organization_id: UUID,
    ) -> None:
        """Fail closed when a resource belongs to another organization."""
        self.authorize(
            principal,
            Permission.READ_SESSIONS,
            organization_id=resource_organization_id,
        )

    def revoke_token(self, token_id: UUID, *, correlation_id: UUID) -> None:
        """Revoke a local auth session."""
        session = self._repository.revoke_auth_session(token_id)
        if session is None:
            return
        self._publish_security_event(
            EventType.AUTH_SESSION_REVOKED,
            session.organization_id,
            actor_id=session.user_id,
            correlation_id=correlation_id,
            payload={"session_id": str(session.session_id)},
        )

    def _principal_for_user(
        self,
        user_id: UUID,
        organization_id: UUID,
        method: AuthenticationMethod,
        *,
        correlation_id: UUID,
        session_id: UUID | None = None,
        token_id: UUID | None = None,
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> AuthenticatedPrincipal:
        organization = self._repository.get_organization(organization_id)
        membership = self._repository.get_membership(user_id, organization_id)
        user = self._repository.get_user(user_id)
        if (
            user is None
            or organization is None
            or membership is None
            or not user.active
            or not organization.active
            or not membership.active
        ):
            raise AuthenticationError("identity is not active in organization")
        now = issued_at or self._now()
        expires = expires_at or now + self._token_ttl
        return AuthenticatedPrincipal(
            user_id=user_id,
            organization_id=organization_id,
            roles=membership.roles,
            permissions=membership.effective_permissions,
            authentication_method=method,
            session_id=session_id or uuid4(),
            token_id=token_id or uuid4(),
            issued_at=now,
            expires_at=expires,
            correlation_id=correlation_id,
        )

    def _encode_token(self, principal: AuthenticatedPrincipal) -> str:
        if principal.token_id is None:
            raise AuthenticationError("token_id is required")
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(principal.user_id),
            "org": str(principal.organization_id),
            "sid": None if principal.session_id is None else str(principal.session_id),
            "jti": str(principal.token_id),
            "iat": int(principal.issued_at.timestamp()),
            "exp": int(principal.expires_at.timestamp()),
            "amr": principal.authentication_method.value,
        }
        return jwt.encode(
            payload,
            self._token_key_ring[self._active_key_id],
            algorithm="HS256",
            headers={"kid": self._active_key_id},
        )

    def _publish_security_event(
        self,
        event_type: EventType,
        organization_id: UUID,
        *,
        actor_id: UUID | None = None,
        correlation_id: UUID | None = None,
        payload: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        if self._event_service is None:
            return
        self._event_service.publish(
            Event(
                event_type=event_type,
                category=EventCategory.SECURITY,
                source="security",
                organization_id=organization_id,
                actor_reference=None if actor_id is None else str(actor_id),
                payload={
                    "organization_id": str(organization_id),
                    "actor_id": None if actor_id is None else str(actor_id),
                    **(payload or {}),
                },
                metadata=EventMetadata(correlation_id=correlation_id),
                priority=EventPriority.NORMAL,
                classification=EventClassification.CONFIDENTIAL,
                security_level=EventSecurityLevel.HIGH,
            )
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class SecurityIdentityPort(IdentityPort):
    """Governance identity adapter backed by the SecurityRepository."""

    def __init__(self, repository: SecurityRepository) -> None:
        self._repository = repository

    def validate_identity(
        self,
        *,
        actor_id: UUID,
        organization_id: UUID,
    ) -> ValidatedIdentity | None:
        membership = self._repository.get_membership(actor_id, organization_id)
        user = self._repository.get_user(actor_id)
        if user is None or membership is None:
            return None
        return ValidatedIdentity(
            actor_id=actor_id,
            organization_id=organization_id,
            roles=tuple(role.value for role in membership.roles),
            active=user.active and membership.active,
            verified=True,
            identity_reference=f"local:{actor_id}",
        )

"""Repository ports and in-memory identity/auth storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock
from uuid import UUID

from ecos.security.models import (
    AuthSession,
    OrganizationIdentity,
    PasswordCredential,
    UserIdentity,
    UserOrganizationMembership,
)


class SecurityRepository(ABC):
    """Persistence port for local identity and authentication state."""

    @abstractmethod
    def add_user(self, user: UserIdentity) -> UserIdentity:
        raise NotImplementedError

    @abstractmethod
    def get_user(self, user_id: UUID) -> UserIdentity | None:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_email(self, email: str) -> UserIdentity | None:
        raise NotImplementedError

    @abstractmethod
    def add_organization(
        self, organization: OrganizationIdentity
    ) -> OrganizationIdentity:
        raise NotImplementedError

    @abstractmethod
    def get_organization(self, organization_id: UUID) -> OrganizationIdentity | None:
        raise NotImplementedError

    @abstractmethod
    def add_membership(
        self, membership: UserOrganizationMembership
    ) -> UserOrganizationMembership:
        raise NotImplementedError

    @abstractmethod
    def get_membership(
        self, user_id: UUID, organization_id: UUID
    ) -> UserOrganizationMembership | None:
        raise NotImplementedError

    @abstractmethod
    def set_password_credential(
        self, credential: PasswordCredential
    ) -> PasswordCredential:
        raise NotImplementedError

    @abstractmethod
    def get_password_credential(self, user_id: UUID) -> PasswordCredential | None:
        raise NotImplementedError

    @abstractmethod
    def create_auth_session(self, session: AuthSession) -> AuthSession:
        raise NotImplementedError

    @abstractmethod
    def get_auth_session_by_token_id(self, token_id: UUID) -> AuthSession | None:
        raise NotImplementedError

    @abstractmethod
    def revoke_auth_session(self, token_id: UUID) -> AuthSession | None:
        raise NotImplementedError


class InMemorySecurityRepository(SecurityRepository):
    """Thread-safe in-memory repository for tests and development."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._users: dict[UUID, UserIdentity] = {}
        self._users_by_email: dict[str, UUID] = {}
        self._organizations: dict[UUID, OrganizationIdentity] = {}
        self._memberships: dict[tuple[UUID, UUID], UserOrganizationMembership] = {}
        self._credentials: dict[UUID, PasswordCredential] = {}
        self._sessions_by_token_id: dict[UUID, AuthSession] = {}

    def add_user(self, user: UserIdentity) -> UserIdentity:
        with self._lock:
            existing = self._users_by_email.get(user.email)
            if existing is not None and existing != user.user_id:
                raise ValueError("user email already exists")
            self._users[user.user_id] = user
            self._users_by_email[user.email] = user.user_id
            return user

    def get_user(self, user_id: UUID) -> UserIdentity | None:
        with self._lock:
            return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> UserIdentity | None:
        with self._lock:
            user_id = self._users_by_email.get(email.strip().lower())
            return None if user_id is None else self._users.get(user_id)

    def add_organization(
        self, organization: OrganizationIdentity
    ) -> OrganizationIdentity:
        with self._lock:
            self._organizations[organization.organization_id] = organization
            return organization

    def get_organization(self, organization_id: UUID) -> OrganizationIdentity | None:
        with self._lock:
            return self._organizations.get(organization_id)

    def add_membership(
        self, membership: UserOrganizationMembership
    ) -> UserOrganizationMembership:
        with self._lock:
            self._memberships[(membership.user_id, membership.organization_id)] = (
                membership
            )
            return membership

    def get_membership(
        self, user_id: UUID, organization_id: UUID
    ) -> UserOrganizationMembership | None:
        with self._lock:
            return self._memberships.get((user_id, organization_id))

    def set_password_credential(
        self, credential: PasswordCredential
    ) -> PasswordCredential:
        with self._lock:
            self._credentials[credential.user_id] = credential
            return credential

    def get_password_credential(self, user_id: UUID) -> PasswordCredential | None:
        with self._lock:
            return self._credentials.get(user_id)

    def create_auth_session(self, session: AuthSession) -> AuthSession:
        with self._lock:
            self._sessions_by_token_id[session.token_id] = session
            return session

    def get_auth_session_by_token_id(self, token_id: UUID) -> AuthSession | None:
        with self._lock:
            return self._sessions_by_token_id.get(token_id)

    def revoke_auth_session(self, token_id: UUID) -> AuthSession | None:
        from ecos.security.models import utc_now

        with self._lock:
            session = self._sessions_by_token_id.get(token_id)
            if session is None:
                return None
            revoked = session.model_copy(update={"revoked_at": utc_now()})
            self._sessions_by_token_id[token_id] = revoked
            return revoked

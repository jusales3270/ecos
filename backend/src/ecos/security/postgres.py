"""PostgreSQL adapters for local identity and authentication."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ecos.database import create_database_engine, create_session_factory
from ecos.security.models import (
    AuthSession,
    OrganizationIdentity,
    PasswordCredential,
    UserIdentity,
    UserOrganizationMembership,
)
from ecos.security.repository import SecurityRepository
from ecos.session.orm import Base


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class SecurityUserRecord(Base):
    """Persisted local user identity."""

    __tablename__ = "security_users"

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityOrganizationRecord(Base):
    """Persisted organization identity."""

    __tablename__ = "security_organizations"

    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityMembershipRecord(Base):
    """Persisted user-to-organization binding."""

    __tablename__ = "security_memberships"

    membership_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityCredentialRecord(Base):
    """Persisted local password verifier."""

    __tablename__ = "security_password_credentials"

    credential_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityAuthSessionRecord(Base):
    """Persisted local auth session/token metadata."""

    __tablename__ = "security_auth_sessions"

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    token_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    authentication_method: Mapped[str] = mapped_column(String(50), nullable=False)
    issued_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class PostgresSecurityRepository(SecurityRepository):
    """SecurityRepository backed by PostgreSQL and SQLAlchemy."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_database_engine(database_url or "")
        self._session_factory = session_factory or create_session_factory(self.engine)

    def add_user(self, user: UserIdentity) -> UserIdentity:
        return _run(self._upsert(SecurityUserRecord, user.user_id, _user_row(user)))

    def get_user(self, user_id: UUID) -> UserIdentity | None:
        return _run(self._get_user(user_id))

    async def _get_user(self, user_id: UUID) -> UserIdentity | None:
        async with self._session_factory() as database:
            row = await database.get(SecurityUserRecord, user_id)
            return None if row is None else _user_model(row)

    def get_user_by_email(self, email: str) -> UserIdentity | None:
        return _run(self._get_user_by_email(email))

    async def _get_user_by_email(self, email: str) -> UserIdentity | None:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(SecurityUserRecord).where(
                    SecurityUserRecord.email == email.strip().lower()
                )
            )
            return None if row is None else _user_model(row)

    def add_organization(
        self, organization: OrganizationIdentity
    ) -> OrganizationIdentity:
        return _run(
            self._upsert(
                SecurityOrganizationRecord,
                organization.organization_id,
                _organization_row(organization),
            )
        )

    def get_organization(self, organization_id: UUID) -> OrganizationIdentity | None:
        return _run(self._get_organization(organization_id))

    async def _get_organization(
        self, organization_id: UUID
    ) -> OrganizationIdentity | None:
        async with self._session_factory() as database:
            row = await database.get(SecurityOrganizationRecord, organization_id)
            return None if row is None else _organization_model(row)

    def add_membership(
        self, membership: UserOrganizationMembership
    ) -> UserOrganizationMembership:
        return _run(
            self._upsert(
                SecurityMembershipRecord,
                membership.membership_id,
                _membership_row(membership),
            )
        )

    def get_membership(
        self, user_id: UUID, organization_id: UUID
    ) -> UserOrganizationMembership | None:
        return _run(self._get_membership(user_id, organization_id))

    async def _get_membership(
        self, user_id: UUID, organization_id: UUID
    ) -> UserOrganizationMembership | None:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(SecurityMembershipRecord).where(
                    SecurityMembershipRecord.user_id == user_id,
                    SecurityMembershipRecord.organization_id == organization_id,
                )
            )
            return None if row is None else _membership_model(row)

    def set_password_credential(
        self, credential: PasswordCredential
    ) -> PasswordCredential:
        return _run(
            self._upsert(
                SecurityCredentialRecord,
                credential.credential_id,
                _credential_row(credential),
            )
        )

    def get_password_credential(self, user_id: UUID) -> PasswordCredential | None:
        return _run(self._get_password_credential(user_id))

    async def _get_password_credential(
        self, user_id: UUID
    ) -> PasswordCredential | None:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(SecurityCredentialRecord).where(
                    SecurityCredentialRecord.user_id == user_id
                )
            )
            return None if row is None else _credential_model(row)

    def create_auth_session(self, session: AuthSession) -> AuthSession:
        return _run(
            self._upsert(
                SecurityAuthSessionRecord,
                session.session_id,
                _auth_session_row(session),
            )
        )

    def get_auth_session_by_token_id(self, token_id: UUID) -> AuthSession | None:
        return _run(self._get_auth_session_by_token_id(token_id))

    async def _get_auth_session_by_token_id(self, token_id: UUID) -> AuthSession | None:
        async with self._session_factory() as database:
            row = await database.scalar(
                select(SecurityAuthSessionRecord).where(
                    SecurityAuthSessionRecord.token_id == token_id
                )
            )
            return None if row is None else _auth_session_model(row)

    def revoke_auth_session(self, token_id: UUID) -> AuthSession | None:
        return _run(self._revoke_auth_session(token_id))

    async def _revoke_auth_session(self, token_id: UUID) -> AuthSession | None:
        from ecos.security.models import utc_now

        async with self._session_factory() as database:
            row = await database.scalar(
                select(SecurityAuthSessionRecord).where(
                    SecurityAuthSessionRecord.token_id == token_id
                )
            )
            if row is None:
                return None
            row.revoked_at = utc_now()
            await database.commit()
            return _auth_session_model(row)

    async def _upsert(
        self,
        row_type: type[Base],
        record_id: UUID,
        payload: dict[str, Any],
    ):
        async with self._session_factory() as database:
            if await database.get(row_type, record_id):
                return _model_from_row_type(row_type, payload)
            try:
                database.add(row_type(**payload))
                await database.commit()
            except IntegrityError as error:
                await database.rollback()
                raise ValueError("security record conflicts") from error
            return _model_from_row_type(row_type, payload)


def _user_row(user: UserIdentity) -> dict[str, Any]:
    return user.model_dump(mode="python")


def _organization_row(organization: OrganizationIdentity) -> dict[str, Any]:
    return organization.model_dump(mode="python")


def _membership_row(membership: UserOrganizationMembership) -> dict[str, Any]:
    payload = membership.model_dump(mode="python", exclude={"roles", "permissions"})
    payload["roles"] = [role.value for role in membership.roles]
    payload["permissions"] = [permission.value for permission in membership.permissions]
    return payload


def _credential_row(credential: PasswordCredential) -> dict[str, Any]:
    return credential.model_dump(mode="python")


def _auth_session_row(session: AuthSession) -> dict[str, Any]:
    payload = session.model_dump(mode="python", exclude={"authentication_method"})
    payload["authentication_method"] = session.authentication_method.value
    return payload


def _user_model(row: SecurityUserRecord) -> UserIdentity:
    return UserIdentity.model_validate(row.__dict__)


def _organization_model(row: SecurityOrganizationRecord) -> OrganizationIdentity:
    return OrganizationIdentity.model_validate(row.__dict__)


def _membership_model(row: SecurityMembershipRecord) -> UserOrganizationMembership:
    return UserOrganizationMembership.model_validate(row.__dict__)


def _credential_model(row: SecurityCredentialRecord) -> PasswordCredential:
    return PasswordCredential.model_validate(row.__dict__)


def _auth_session_model(row: SecurityAuthSessionRecord) -> AuthSession:
    return AuthSession.model_validate(row.__dict__)


def _model_from_row_type(row_type: type[Base], payload: dict[str, Any]):
    if row_type is SecurityUserRecord:
        return UserIdentity.model_validate(payload)
    if row_type is SecurityOrganizationRecord:
        return OrganizationIdentity.model_validate(payload)
    if row_type is SecurityMembershipRecord:
        return UserOrganizationMembership.model_validate(payload)
    if row_type is SecurityCredentialRecord:
        return PasswordCredential.model_validate(payload)
    return AuthSession.model_validate(payload)

"""Organization-scoped service wrappers for tenant isolation."""

from __future__ import annotations

from uuid import UUID

from ecos.memory import MemoryObject, MemoryService, MemoryType
from ecos.security.exceptions import CrossTenantAccessError
from ecos.security.models import AuthenticatedPrincipal, Permission
from ecos.security.service import SecurityService
from ecos.session import ManagedSession, SessionService


class TenantScopedMemoryService:
    """Memory access that derives organization scope from the principal."""

    def __init__(
        self,
        memory_service: MemoryService,
        security_service: SecurityService,
    ) -> None:
        self._memory_service = memory_service
        self._security_service = security_service

    def store(
        self,
        principal: AuthenticatedPrincipal,
        memory: MemoryObject,
    ) -> MemoryObject:
        self._security_service.authorize(principal, Permission.WRITE_MEMORY)
        scoped = memory.model_copy(
            update={"organization_id": principal.organization_id}
        )
        return self._memory_service.store(scoped)

    def get(
        self,
        principal: AuthenticatedPrincipal,
        memory_id: UUID,
    ) -> MemoryObject | None:
        self._security_service.authorize(principal, Permission.READ_MEMORY)
        memory = self._memory_service.get(memory_id)
        if memory is None:
            return None
        if memory.organization_id != principal.organization_id:
            raise CrossTenantAccessError()
        return memory

    def search(
        self,
        principal: AuthenticatedPrincipal,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        self._security_service.authorize(principal, Permission.READ_MEMORY)
        return self._memory_service.search(
            query,
            organization_id=principal.organization_id,
            memory_type=memory_type,
            tags=tags,
            limit=limit,
        )

    def list(
        self,
        principal: AuthenticatedPrincipal,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        self._security_service.authorize(principal, Permission.READ_MEMORY)
        return self._memory_service.list(
            organization_id=principal.organization_id,
            memory_type=memory_type,
            tags=tags,
            limit=limit,
        )


class TenantScopedSessionService:
    """Session access that rejects cross-organization IDs."""

    def __init__(
        self,
        session_service: SessionService,
        security_service: SecurityService,
    ) -> None:
        self._session_service = session_service
        self._security_service = security_service

    def create_session(
        self,
        principal: AuthenticatedPrincipal,
        session: ManagedSession,
    ) -> ManagedSession:
        self._security_service.authorize(principal, Permission.WRITE_SESSIONS)
        if session.context.organization_id != principal.organization_id:
            raise CrossTenantAccessError()
        return self._session_service.create_session(session)

    def get_session(
        self,
        principal: AuthenticatedPrincipal,
        session_id: UUID,
    ) -> ManagedSession | None:
        self._security_service.authorize(principal, Permission.READ_SESSIONS)
        session = self._session_service.get_session(session_id)
        if session is None:
            return None
        if session.context.organization_id != principal.organization_id:
            raise CrossTenantAccessError()
        return session

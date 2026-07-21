"""Application service for the ECOS Memory Engine architecture."""

from typing import Protocol
from uuid import UUID

from ecos.memory.models import (
    MemoryObject,
    MemoryType,
    ValidatedMemoryStoreResult,
    ValidatedMemoryWrite,
)
from ecos.memory.repository import MemoryRepository


class ValidatedMemoryAuthority(Protocol):
    """Canonical authority consulted before a Learning memory write."""

    def validate_memory_write(self, write: ValidatedMemoryWrite) -> None: ...


class MemoryService:
    """Coordinates memory operations through a repository abstraction only."""

    def __init__(
        self,
        repository: MemoryRepository,
        validated_authority: ValidatedMemoryAuthority | None = None,
    ) -> None:
        """Initialize the service with a memory repository abstraction."""
        self._repository = repository
        self._validated_authority = validated_authority

    def configure_validated_authority(
        self, authority: ValidatedMemoryAuthority
    ) -> None:
        """Bind the canonical Learning authority used by validated writes."""
        self._validated_authority = authority

    def store(self, memory: MemoryObject) -> MemoryObject:
        """Store a memory object through the repository abstraction."""
        return self._repository.store(memory)

    def store_validated(
        self, write: ValidatedMemoryWrite
    ) -> ValidatedMemoryStoreResult:
        """Validate canonically, then atomically create or reuse Learning memory."""
        if self._validated_authority is None:
            raise RuntimeError("validated memory authority is required")
        self._validated_authority.validate_memory_write(write)
        return self._repository.store_validated(write)

    @property
    def supports_transactional_outbox(self) -> bool:
        """Report whether validated writes enqueue MEMORY_UPDATED atomically."""
        return self._repository.supports_transactional_outbox

    def get(self, memory_id: UUID) -> MemoryObject | None:
        """Get a memory object through the repository abstraction."""
        return self._repository.get(memory_id)

    def search(
        self,
        query: str,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        """Search memory objects through the repository abstraction."""
        return self._repository.search(
            query,
            organization_id=organization_id,
            memory_type=memory_type,
            tags=tags,
            limit=limit,
        )

    def update(self, memory: MemoryObject) -> MemoryObject:
        """Update a memory object through the repository abstraction."""
        return self._repository.update(memory)

    def delete(self, memory_id: UUID) -> None:
        """Delete a memory object through the repository abstraction."""
        self._repository.delete(memory_id)

    def list(
        self,
        *,
        organization_id: UUID | None = None,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryObject]:
        """List memory objects through the repository abstraction."""
        return self._repository.list(
            organization_id=organization_id,
            memory_type=memory_type,
            tags=tags,
            limit=limit,
        )

"""Application service for the ECOS Memory Engine architecture."""

from uuid import UUID

from ecos.memory.models import MemoryObject, MemoryType
from ecos.memory.repository import MemoryRepository


class MemoryService:
    """Coordinates memory operations through a repository abstraction only."""

    def __init__(self, repository: MemoryRepository) -> None:
        """Initialize the service with a memory repository abstraction."""
        self._repository = repository

    def store(self, memory: MemoryObject) -> MemoryObject:
        """Store a memory object through the repository abstraction."""
        return self._repository.store(memory)

    def get(self, memory_id: UUID) -> MemoryObject | None:
        """Get a memory object through the repository abstraction."""
        return self._repository.get(memory_id)

    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """Search memory objects through the repository abstraction."""
        return self._repository.search(query, memory_type=memory_type, tags=tags)

    def update(self, memory: MemoryObject) -> MemoryObject:
        """Update a memory object through the repository abstraction."""
        return self._repository.update(memory)

    def delete(self, memory_id: UUID) -> None:
        """Delete a memory object through the repository abstraction."""
        self._repository.delete(memory_id)

    def list(
        self,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """List memory objects through the repository abstraction."""
        return self._repository.list(memory_type=memory_type, tags=tags)

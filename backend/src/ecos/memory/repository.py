"""Repository interface for the ECOS Memory Engine."""

from abc import ABC, abstractmethod
from uuid import UUID

from ecos.memory.models import MemoryObject, MemoryType


class MemoryRepository(ABC):
    """Abstract persistence interface for memory objects."""

    @abstractmethod
    def store(self, memory: MemoryObject) -> MemoryObject:
        """Store a memory object."""
        raise NotImplementedError

    @abstractmethod
    def get(self, memory_id: UUID) -> MemoryObject | None:
        """Get a memory object by identifier."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """Search memory objects using repository-specific criteria."""
        raise NotImplementedError

    @abstractmethod
    def update(self, memory: MemoryObject) -> MemoryObject:
        """Update a memory object."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, memory_id: UUID) -> None:
        """Delete a memory object by identifier."""
        raise NotImplementedError

    @abstractmethod
    def list(
        self,
        *,
        memory_type: MemoryType | None = None,
        tags: list[str] | None = None,
    ) -> list[MemoryObject]:
        """List memory objects using repository-specific filters."""
        raise NotImplementedError

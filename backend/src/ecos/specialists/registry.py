"""Registry for ECOS cognitive specialists."""

from __future__ import annotations

from uuid import UUID

from ecos.specialists.models import Specialist, SpecialistType


class SpecialistRegistry:
    """In-memory registry for specialist definitions."""

    def __init__(self) -> None:
        """Initialize an empty specialist registry."""
        self._specialists: dict[UUID, Specialist] = {}

    def register(self, specialist: Specialist) -> Specialist:
        """Register a specialist definition."""
        self._specialists[specialist.id] = specialist
        return specialist

    def unregister(self, specialist_id: UUID) -> None:
        """Remove a specialist definition from the registry."""
        self._specialists.pop(specialist_id, None)

    def get(self, specialist_id: UUID) -> Specialist | None:
        """Get a specialist by identifier."""
        return self._specialists.get(specialist_id)

    def list(self) -> list[Specialist]:
        """List all registered specialists."""
        return list(self._specialists.values())

    def find_by_type(self, specialist_type: SpecialistType) -> list[Specialist]:
        """Find registered specialists by specialist type."""
        return [
            specialist
            for specialist in self._specialists.values()
            if specialist.type == specialist_type
        ]

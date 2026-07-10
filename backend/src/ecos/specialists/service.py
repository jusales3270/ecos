"""Service layer for the ECOS Specialist Framework architecture."""

from uuid import UUID

from ecos.specialists.models import Contribution, Specialist, SpecialistType
from ecos.specialists.provider import SpecialistProvider
from ecos.specialists.registry import SpecialistRegistry


class SpecialistService:
    """Coordinates specialists through provider and registry abstractions only."""

    def __init__(
        self,
        provider: SpecialistProvider,
        registry: SpecialistRegistry,
    ) -> None:
        """Initialize the service with provider and registry abstractions."""
        self._provider = provider
        self._registry = registry

    def load(self) -> list[Specialist]:
        """Load specialists through the provider and register them."""
        specialists = self._provider.load()
        for specialist in specialists:
            self._registry.register(specialist)
        return specialists

    def register(self, specialist: Specialist) -> Specialist:
        """Register a specialist in the registry."""
        return self._registry.register(specialist)

    def unregister(self, specialist_id: UUID) -> None:
        """Unregister a specialist from the registry."""
        self._registry.unregister(specialist_id)

    def get(self, specialist_id: UUID) -> Specialist | None:
        """Get a specialist from the registry."""
        return self._registry.get(specialist_id)

    def list(self) -> list[Specialist]:
        """List specialists from the registry."""
        return self._registry.list()

    def find_by_type(self, specialist_type: SpecialistType) -> list[Specialist]:
        """Find specialists by type through the registry."""
        return self._registry.find_by_type(specialist_type)

    def analyze(
        self,
        specialist_id: UUID,
        input_data: dict[str, object],
    ) -> list[Contribution]:
        """Analyze input data with a registered specialist via the provider."""
        specialist = self._require_specialist(specialist_id)
        return self._provider.analyze(specialist, input_data)

    def contribute(
        self,
        specialist_id: UUID,
        input_data: dict[str, object],
    ) -> Contribution:
        """Produce a contribution with a registered specialist via the provider."""
        specialist = self._require_specialist(specialist_id)
        return self._provider.contribute(specialist, input_data)

    def _require_specialist(self, specialist_id: UUID) -> Specialist:
        """Return a registered specialist or raise a lookup error."""
        specialist = self._registry.get(specialist_id)
        if specialist is None:
            msg = f"specialist not registered: {specialist_id}"
            raise LookupError(msg)
        return specialist

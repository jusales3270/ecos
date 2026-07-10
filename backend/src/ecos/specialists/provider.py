"""Provider interface for ECOS cognitive specialists."""

from abc import ABC, abstractmethod

from ecos.specialists.models import Contribution, Specialist


class SpecialistProvider(ABC):
    """Abstract provider interface for specialist operations."""

    @abstractmethod
    def load(self) -> list[Specialist]:
        """Load available specialists."""
        raise NotImplementedError

    @abstractmethod
    def analyze(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> list[Contribution]:
        """Analyze input data with a specialist."""
        raise NotImplementedError

    @abstractmethod
    def contribute(
        self,
        specialist: Specialist,
        input_data: dict[str, object],
    ) -> Contribution:
        """Produce a specialist contribution for input data."""
        raise NotImplementedError

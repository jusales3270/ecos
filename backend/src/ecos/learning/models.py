"""Models for deterministic organizational learning validation."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from ecos.memory import MemoryType


class LearningValidationStatus(StrEnum):
    """Possible outcomes of learning validation."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LearningObject(BaseModel):
    """Candidate knowledge that must be validated before persistence."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    organization_id: UUID | None = None
    memory_type: MemoryType
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(min_length=1)
    origin: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    status: LearningValidationStatus = LearningValidationStatus.PENDING
    validation_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

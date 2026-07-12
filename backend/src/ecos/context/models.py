"""Pydantic models for the ECOS Context Engine architecture."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.domain import Objective

ContextMetadataValue = str | int | float | bool | None
ContextDataValue = str | int | float | bool | None


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ContextSourceType(StrEnum):
    """Supported source categories for context elements."""

    MEMORY = "MEMORY"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    USER = "USER"
    DOCUMENT = "DOCUMENT"
    POLICY = "POLICY"
    EXTERNAL = "EXTERNAL"
    SESSION = "SESSION"


class ContextPriority(StrEnum):
    """Priority levels used when assembling context."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MissingContextSeverity(StrEnum):
    """Severity levels for explicit missing-context reports."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ContextModel(BaseModel):
    """Base context model with identity and UTC creation timestamp."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique context model identifier.",
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        description="Timezone-aware UTC timestamp for context model creation.",
    )

    @model_validator(mode="after")
    def validate_created_at(self) -> Self:
        """Ensure created_at is timezone-aware UTC."""
        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() != UTC.utcoffset(self.created_at)
        ):
            msg = "created_at must be timezone-aware and in UTC"
            raise ValueError(msg)
        return self


class ContextSource(ContextModel):
    """Describes the origin of a context element."""

    source_type: ContextSourceType = Field(description="Source category.")
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Human-readable source name.",
    )
    reference: str | None = Field(
        default=None,
        max_length=500,
        description="Optional source reference or URI.",
    )

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        """Reject blank references when provided."""
        if value == "":
            msg = "reference cannot be empty when provided"
            raise ValueError(msg)
        return value


class ContextElement(ContextModel):
    """A single item considered while assembling ECOS context."""

    source_type: ContextSourceType = Field(description="Element source category.")
    priority: ContextPriority = Field(description="Element assembly priority.")
    title: str = Field(
        min_length=1,
        max_length=200,
        description="Short element title.",
    )
    content: str = Field(
        min_length=1,
        max_length=10000,
        description="Context content supplied by the element.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0.",
    )
    metadata: dict[str, ContextMetadataValue] = Field(
        default_factory=dict,
        description="Structured metadata associated with the element.",
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, ContextMetadataValue],
    ) -> dict[str, ContextMetadataValue]:
        """Reject blank metadata keys."""
        if any(key.strip() == "" for key in value):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return value


class ContextMemoryReference(ContextModel):
    """Safe reference to a selected memory object."""

    memory_id: UUID = Field(description="Referenced memory object identifier.")
    organization_id: UUID = Field(description="Organization that owns the memory.")
    title: str = Field(min_length=1, max_length=200, description="Memory title.")
    memory_type: str = Field(min_length=1, max_length=64, description="Memory type.")
    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Deterministic relevance score from 0.0 to 1.0.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Referenced memory confidence from 0.0 to 1.0.",
    )
    created_at: datetime = Field(description="Original memory creation timestamp.")

    @model_validator(mode="after")
    def validate_reference_created_at(self) -> Self:
        """Ensure referenced memory timestamps are timezone-aware UTC."""
        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() != UTC.utcoffset(self.created_at)
        ):
            msg = "created_at must be timezone-aware and in UTC"
            raise ValueError(msg)
        return self


class ContextKnowledgeReference(ContextModel):
    """Safe reference to a selected Knowledge Graph entity."""

    entity_id: str = Field(min_length=1, max_length=200)
    organization_id: UUID = Field(description="Organization that owns the entity.")
    entity_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    evidence_references: list[str] = Field(default_factory=list)


class ContextGraph(ContextModel):
    """Safe graph context references assembled for Context Engine use."""

    organization_id: UUID
    session_id: UUID
    seed_entities: list[str] = Field(default_factory=list)
    selected_entities: list[str] = Field(default_factory=list)
    selected_relationships: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    expansion_depth: int = Field(default=0, ge=0)
    entity_count: int = Field(default=0, ge=0)
    relationship_count: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    completeness_signal: str = Field(default="empty", max_length=64)
    truncated: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    safe_metadata: dict[str, ContextMetadataValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.entity_count != len(self.selected_entities):
            msg = "entity_count must match selected_entities"
            raise ValueError(msg)
        if self.relationship_count != len(self.selected_relationships):
            msg = "relationship_count must match selected_relationships"
            raise ValueError(msg)
        return self


class MissingContextItem(ContextModel):
    """Explicit report of unavailable or insufficient context."""

    field: str = Field(min_length=1, max_length=200, description="Missing field.")
    category: str = Field(
        min_length=1,
        max_length=100,
        description="Missing context category.",
    )
    description: str = Field(
        min_length=1,
        max_length=1000,
        description="Human-readable gap description.",
    )
    severity: MissingContextSeverity = Field(description="Gap severity.")
    reason: str = Field(min_length=1, max_length=1000, description="Gap reason.")
    cognitive_impact: str = Field(
        min_length=1,
        max_length=1000,
        description="Impact on downstream cognitive engines.",
    )
    suggested_action: str = Field(
        min_length=1,
        max_length=1000,
        description="Suggested action to obtain the missing information.",
    )


class ContextBuildRequest(BaseModel):
    """Typed input used by a real context provider to assemble context."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    session_id: UUID = Field(description="Cognitive session identifier.")
    organization_id: UUID = Field(description="Organization scope.")
    objective: Objective = Field(description="Primary objective.")
    user_id: UUID | None = Field(default=None, description="Optional user identifier.")
    objective_category: str | None = Field(
        default=None,
        max_length=100,
        description="Optional objective category.",
    )
    user_information: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    external_signals: list[str] = Field(default_factory=list)
    relevant_entities: list[str] = Field(default_factory=list)
    previous_session_ids: list[UUID] = Field(default_factory=list)
    required_context_fields: list[str] = Field(default_factory=list)
    correlation_id: UUID | None = Field(default=None)
    memory_limit: int = Field(default=8, ge=1, le=50)

    @field_validator(
        "user_information",
        "constraints",
        "policies",
        "resources",
        "external_signals",
        "relevant_entities",
        "required_context_fields",
    )
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        """Normalize list values and reject blank entries."""
        normalized = [item.strip() for item in value]
        if any(item == "" for item in normalized):
            msg = "context request lists cannot contain blank values"
            raise ValueError(msg)
        return list(normalized)


class ContextObject(ContextModel):
    """Context assembled for a cognitive session and objective."""

    session_id: UUID = Field(description="Cognitive session identifier.")
    organization_id: UUID | None = Field(
        default=None,
        description="Organization scope for the assembled context.",
    )
    objective: Objective = Field(description="Objective associated with this context.")
    summary: str | None = Field(
        default=None,
        max_length=2000,
        description="Deterministic summary of available context.",
    )
    elements: list[ContextElement] = Field(
        default_factory=list,
        description="Context elements selected for the session.",
    )
    organizational_context: list[str] = Field(default_factory=list)
    strategic_context: list[str] = Field(default_factory=list)
    operational_context: list[str] = Field(default_factory=list)
    historical_context: list[str] = Field(default_factory=list)
    external_context: list[str] = Field(default_factory=list)
    session_context: dict[str, ContextDataValue] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    relevant_entities: list[str] = Field(default_factory=list)
    memory_references: list[ContextMemoryReference] = Field(default_factory=list)
    knowledge_references: list[ContextKnowledgeReference] = Field(default_factory=list)
    context_graph: ContextGraph | None = None
    evidence: list[str] = Field(default_factory=list)
    previous_decisions: list[str] = Field(default_factory=list)
    missing_context: list[MissingContextItem] = Field(default_factory=list)
    completeness: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Context completeness score from 0.0 to 1.0.",
    )
    version: int = Field(default=1, ge=1, description="Context generation version.")
    generated_at: datetime | None = Field(
        default=None,
        description="Timezone-aware UTC generation timestamp.",
    )
    metadata: dict[str, ContextMetadataValue] = Field(
        default_factory=dict,
        description="Safe structured context metadata.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall assembled context confidence from 0.0 to 1.0.",
    )

    @model_validator(mode="after")
    def validate_context_object(self) -> Self:
        """Ensure generated_at is UTC and metadata keys are non-blank."""
        if self.generated_at is not None and (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset() != UTC.utcoffset(self.generated_at)
        ):
            msg = "generated_at must be timezone-aware and in UTC"
            raise ValueError(msg)
        if any(key.strip() == "" for key in self.metadata):
            msg = "metadata keys cannot be blank"
            raise ValueError(msg)
        return self

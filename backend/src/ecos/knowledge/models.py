"""Immutable Knowledge Graph contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ecos.knowledge.exceptions import (
    InvalidGraphPathError,
    InvalidKnowledgeLimitError,
    InvalidKnowledgeQueryError,
    InvalidSemanticQueryError,
    SensitiveMetadataError,
)

SAFE_VALUE = str | int | float | bool | None
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
}
MAX_SAFE_STRING = 5000


class KnowledgeEntityType(StrEnum):
    """Canonical organization entity types."""

    ORGANIZATION = "organization"
    BUSINESS_UNIT = "business_unit"
    DEPARTMENT = "department"
    TEAM = "team"
    PERSON = "person"
    ROLE = "role"
    PROJECT = "project"
    OBJECTIVE = "objective"
    DECISION = "decision"
    MEETING = "meeting"
    POLICY = "policy"
    PROCEDURE = "procedure"
    RISK = "risk"
    OPPORTUNITY = "opportunity"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    PRODUCT = "product"
    SERVICE = "service"
    DOCUMENT_REFERENCE = "document_reference"
    MEMORY = "memory"
    SESSION = "session"
    SPECIALIST = "specialist"
    RECOMMENDATION = "recommendation"
    EXECUTION = "execution"
    OBSERVATION = "observation"
    LEARNING = "learning"
    METRIC = "metric"
    SYSTEM = "system"
    RESOURCE = "resource"
    ARTIFACT = "artifact"
    EXTERNAL_EVENT = "external_event"


class KnowledgeStatus(StrEnum):
    """Version status for entities and relationships."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"
    MERGED = "merged"
    DISPUTED = "disputed"
    INVALIDATED = "invalidated"


class KnowledgeClassification(StrEnum):
    """Safe information classification."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RelationshipDirection(StrEnum):
    """Stored relationship direction."""

    DIRECTED = "directed"


class KnowledgeRelationshipType(StrEnum):
    """Canonical directed relationship vocabulary."""

    OWNS = "owns"
    BELONGS_TO = "belongs_to"
    CREATED_BY = "created_by"
    DEPENDS_ON = "depends_on"
    RELATES_TO = "relates_to"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    AFFECTS = "affects"
    GENERATED = "generated"
    APPROVED_BY = "approved_by"
    EXECUTED_BY = "executed_by"
    LEARNED_FROM = "learned_from"
    REFERENCES = "references"
    REPLACES = "replaces"
    EXTENDS = "extends"
    GOVERNED_BY = "governed_by"
    RESULTED_IN = "resulted_in"
    OBSERVED_BY = "observed_by"
    MEASURED_BY = "measured_by"
    ASSOCIATED_WITH = "associated_with"
    OCCURRED_AFTER = "occurred_after"
    CORRELATED_WITH = "correlated_with"
    PART_OF = "part_of"
    ASSIGNED_TO = "assigned_to"
    USES = "uses"
    PRODUCES = "produces"
    MITIGATES = "mitigates"
    EXPOSES = "exposes"
    REQUIRES = "requires"


ACYCLIC_RELATIONSHIP_TYPES = {
    KnowledgeRelationshipType.DEPENDS_ON,
    KnowledgeRelationshipType.REPLACES,
}
DEPENDENCY_RELATIONSHIP_TYPES = {
    KnowledgeRelationshipType.DEPENDS_ON,
    KnowledgeRelationshipType.REQUIRES,
    KnowledgeRelationshipType.PART_OF,
    KnowledgeRelationshipType.USES,
    KnowledgeRelationshipType.GOVERNED_BY,
}
IMPACT_RELATIONSHIP_TYPES = {
    KnowledgeRelationshipType.AFFECTS,
    KnowledgeRelationshipType.RESULTED_IN,
    KnowledgeRelationshipType.PRODUCES,
    KnowledgeRelationshipType.EXPOSES,
    KnowledgeRelationshipType.MITIGATES,
    KnowledgeRelationshipType.DEPENDS_ON,
}


class HealthStatus(StrEnum):
    """Repository health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class GraphIntegrityStatus(StrEnum):
    """Integrity report status."""

    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"
    INCOMPLETE = "incomplete"


class IntegritySeverity(StrEnum):
    """Integrity violation severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class KnowledgeLimits(BaseModel):
    """Immutable limits used by graph services."""

    model_config = ConfigDict(frozen=True)

    max_query_length: int = Field(default=500, gt=0, le=5000)
    max_aliases: int = Field(default=20, gt=0, le=200)
    max_tags: int = Field(default=50, gt=0, le=500)
    max_attributes: int = Field(default=100, gt=0, le=1000)
    max_relationships_per_entity: int = Field(default=500, gt=0, le=10000)
    max_traversal_depth: int = Field(default=5, gt=0, le=25)
    max_nodes_per_traversal: int = Field(default=200, gt=0, le=10000)
    max_paths: int = Field(default=50, gt=0, le=1000)
    max_semantic_results: int = Field(default=50, gt=0, le=500)
    max_context_entities: int = Field(default=50, gt=0, le=500)
    max_context_relationships: int = Field(default=100, gt=0, le=1000)


class KnowledgeModel(BaseModel):
    """Base immutable graph model."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class KnowledgeEntity(KnowledgeModel):
    """Versioned organizational entity stored by reference and safe metadata."""

    entity_id: str = Field(min_length=1, max_length=200)
    organization_id: UUID
    entity_type: KnowledgeEntityType
    name: str = Field(min_length=1, max_length=300)
    normalized_name: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    version: int = Field(default=1, ge=1)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_references: tuple[str, ...] = Field(default_factory=tuple)
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    supersedes_entity_version: int | None = Field(default=None, ge=1)
    classification: KnowledgeClassification = KnowledgeClassification.INTERNAL
    sensitive: bool = False
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("normalized_name", mode="before")
    @classmethod
    def normalize_name_value(cls, value: str | None) -> str | None:
        return normalize_text(value) if value else value

    @field_validator(
        "aliases", "tags", "source_references", "evidence_references", mode="before"
    )
    @classmethod
    def tuple_sorted_text(cls, value: object) -> tuple[str, ...]:
        values = [str(item).strip() for item in value or ()]
        filtered = [item for item in values if item]
        return tuple(sorted(dict.fromkeys(filtered), key=str.lower))

    @field_validator("reason_codes", mode="before")
    @classmethod
    def tuple_reason_codes(cls, value: object) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(item).strip() for item in value or () if str(item).strip()
            )
        )

    @model_validator(mode="after")
    def validate_entity(self) -> Self:
        if not self.entity_id.strip():
            from ecos.knowledge.exceptions import MissingEntityIdError

            raise MissingEntityIdError("entity_id is required")
        if self.normalized_name is None:
            object.__setattr__(self, "normalized_name", normalize_text(self.name))
        _validate_time("valid_from", self.valid_from)
        _validate_time("created_at", self.created_at)
        _validate_time("updated_at", self.updated_at)
        if self.valid_until is not None:
            _validate_time("valid_until", self.valid_until)
            if self.valid_until <= self.valid_from:
                raise ValueError("valid_until must be greater than valid_from")
        _validate_safe_payload(self.attributes, "attributes")
        _validate_safe_payload(self.safe_metadata, "safe_metadata")
        if len(self.aliases) > KnowledgeLimits().max_aliases:
            raise InvalidKnowledgeLimitError("too many aliases")
        if len(self.tags) > KnowledgeLimits().max_tags:
            raise InvalidKnowledgeLimitError("too many tags")
        if len(self.attributes) > KnowledgeLimits().max_attributes:
            raise InvalidKnowledgeLimitError("too many attributes")
        return self

    @property
    def identity_fingerprint(self) -> str:
        """Deterministic identity fingerprint from safe identity fields."""
        external_id = self.attributes.get("external_id")
        namespace = self.attributes.get("namespace")
        identity_safe = {
            key: self.attributes[key]
            for key in sorted(self.attributes)
            if key.startswith("identity_")
        }
        return stable_fingerprint(
            {
                "organization_id": str(self.organization_id),
                "entity_type": self.entity_type.value,
                "normalized_name": self.normalized_name,
                "external_id": external_id,
                "namespace": namespace,
                "identity_safe": identity_safe,
            }
        )


class KnowledgeRelationship(KnowledgeModel):
    """Versioned directed relationship between two logical entity IDs."""

    relationship_id: str = Field(min_length=1, max_length=240)
    organization_id: UUID
    source_entity_id: str = Field(min_length=1, max_length=200)
    target_entity_id: str = Field(min_length=1, max_length=200)
    relationship_type: KnowledgeRelationshipType
    direction: RelationshipDirection = RelationshipDirection.DIRECTED
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    version: int = Field(default=1, ge=1)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_references: tuple[str, ...] = Field(default_factory=tuple)
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    supersedes_relationship_version: int | None = Field(default=None, ge=1)
    constraints: dict[str, Any] = Field(default_factory=dict)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_references", "evidence_references", mode="before")
    @classmethod
    def tuple_sorted_text(cls, value: object) -> tuple[str, ...]:
        values = [str(item).strip() for item in value or ()]
        filtered = [item for item in values if item]
        return tuple(sorted(dict.fromkeys(filtered), key=str.lower))

    @field_validator("reason_codes", mode="before")
    @classmethod
    def tuple_reason_codes(cls, value: object) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(item).strip() for item in value or () if str(item).strip()
            )
        )

    @model_validator(mode="after")
    def validate_relationship(self) -> Self:
        _validate_time("valid_from", self.valid_from)
        _validate_time("created_at", self.created_at)
        _validate_time("updated_at", self.updated_at)
        if self.valid_until is not None:
            _validate_time("valid_until", self.valid_until)
            if self.valid_until <= self.valid_from:
                raise ValueError("valid_until must be greater than valid_from")
        if (
            self.source_entity_id == self.target_entity_id
            and self.relationship_type is not KnowledgeRelationshipType.RELATES_TO
        ):
            from ecos.knowledge.exceptions import SelfRelationshipForbiddenError

            raise SelfRelationshipForbiddenError("self relationship is forbidden")
        _validate_safe_payload(self.constraints, "constraints")
        _validate_safe_payload(self.safe_metadata, "safe_metadata")
        return self

    @property
    def relationship_fingerprint(self) -> str:
        """Deterministic relationship fingerprint."""
        return stable_fingerprint(
            {
                "organization_id": str(self.organization_id),
                "source_entity_id": self.source_entity_id,
                "target_entity_id": self.target_entity_id,
                "relationship_type": self.relationship_type.value,
                "scope": self.constraints.get("scope"),
                "logical_version": self.constraints.get("logical_version", 1),
            }
        )


class GraphPath(KnowledgeModel):
    """A deterministic connected path through the graph."""

    path_id: str = Field(min_length=1)
    organization_id: UUID
    start_entity_id: str = Field(min_length=1)
    end_entity_id: str = Field(min_length=1)
    entities: tuple[str, ...]
    relationships: tuple[str, ...]
    depth: int = Field(ge=0)
    total_weight: float = Field(ge=0.0)
    minimum_confidence: float = Field(ge=0.0, le=1.0)
    path_score: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if not math.isfinite(self.total_weight):
            raise InvalidGraphPathError("total_weight must be finite")
        if self.depth != max(len(self.entities) - 1, 0):
            raise InvalidGraphPathError("depth must match entity path length")
        if self.relationships and len(self.relationships) != self.depth:
            raise InvalidGraphPathError("relationships must match path depth")
        if self.entities and (
            self.entities[0] != self.start_entity_id
            or self.entities[-1] != self.end_entity_id
        ):
            raise InvalidGraphPathError("entities must match start/end")
        _validate_safe_payload(self.safe_metadata, "safe_metadata")
        return self


class SemanticQuery(KnowledgeModel):
    """Structured deterministic semantic search query."""

    query_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    text: str | None = Field(default=None, max_length=500)
    normalized_terms: tuple[str, ...] = Field(default_factory=tuple)
    entity_types: tuple[KnowledgeEntityType, ...] = Field(default_factory=tuple)
    relationship_types: tuple[KnowledgeRelationshipType, ...] = Field(
        default_factory=tuple
    )
    tags: tuple[str, ...] = Field(default_factory=tuple)
    domains: tuple[str, ...] = Field(default_factory=tuple)
    source_entity_ids: tuple[str, ...] = Field(default_factory=tuple)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    max_results: int = Field(default=10, gt=0, le=100)
    max_depth: int = Field(default=2, gt=0, le=10)
    as_of: datetime | None = None
    include_archived: bool = False
    safe_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("normalized_terms", mode="before")
    @classmethod
    def normalize_terms_value(cls, value: object) -> tuple[str, ...]:
        terms: list[str] = []
        for item in value or ():
            terms.extend(tokenize(str(item)))
        return tuple(sorted(dict.fromkeys(terms)))

    @field_validator("tags", "domains", "source_entity_ids", mode="before")
    @classmethod
    def tuple_text(cls, value: object) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(item).strip() for item in value or () if str(item).strip()
            )
        )

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        if self.as_of is not None:
            _validate_time("as_of", self.as_of)
        if not (
            (self.text and self.text.strip())
            or self.normalized_terms
            or self.entity_types
            or self.tags
            or self.source_entity_ids
        ):
            raise InvalidSemanticQueryError("text or structured filters are required")
        if self.text and len(self.text) > KnowledgeLimits().max_query_length:
            raise InvalidKnowledgeQueryError("query text is too long")
        if not self.normalized_terms and self.text:
            object.__setattr__(
                self, "normalized_terms", tuple(sorted(tokenize(self.text)))
            )
        _validate_safe_payload(self.safe_metadata, "safe_metadata")
        return self


class SemanticResult(KnowledgeModel):
    """Deterministic semantic result with objective score components."""

    entity: KnowledgeEntity
    semantic_score: float = Field(ge=0.0, le=1.0)
    lexical_score: float = Field(ge=0.0, le=1.0)
    graph_proximity_score: float = Field(ge=0.0, le=1.0)
    relationship_score: float = Field(ge=0.0, le=1.0)
    importance_score: float = Field(ge=0.0, le=1.0)
    recency_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    organizational_relevance_score: float = Field(ge=0.0, le=1.0)
    matched_terms: tuple[str, ...] = Field(default_factory=tuple)
    matched_tags: tuple[str, ...] = Field(default_factory=tuple)
    matched_relationships: tuple[str, ...] = Field(default_factory=tuple)
    path_reference: str | None = None
    evidence_references: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class KnowledgeContextExpansionRequest(KnowledgeModel):
    """Input for deterministic graph-backed context expansion."""

    organization_id: UUID
    session_id: UUID
    objective_reference: str
    seed_entity_ids: tuple[str, ...] = Field(default_factory=tuple)
    semantic_query: SemanticQuery | None = None
    relevant_memory_references: tuple[str, ...] = Field(default_factory=tuple)
    allowed_relationship_types: tuple[KnowledgeRelationshipType, ...] = Field(
        default_factory=tuple
    )
    max_depth: int = Field(default=2, gt=0, le=10)
    max_entities: int = Field(default=25, gt=0, le=200)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    context_budget: int = Field(default=50, gt=0, le=500)
    as_of: datetime | None = None
    correlation_id: UUID | None = None

    @model_validator(mode="after")
    def validate_expansion(self) -> Self:
        if (
            self.semantic_query is not None
            and self.semantic_query.organization_id != self.organization_id
        ):
            raise InvalidKnowledgeQueryError("semantic query organization mismatch")
        if self.as_of is not None:
            _validate_time("as_of", self.as_of)
        return self


class KnowledgeContextExpansion(KnowledgeModel):
    """Candidate graph context produced for Context Engine consumption."""

    selected_entities: tuple[KnowledgeEntity, ...]
    selected_relationships: tuple[KnowledgeRelationship, ...]
    graph_paths: tuple[GraphPath, ...]
    semantic_results: tuple[SemanticResult, ...]
    expanded_entity_ids: tuple[str, ...]
    excluded_entities: tuple[str, ...]
    truncation_applied: bool
    completeness_signal: str
    graph_confidence: float = Field(ge=0.0, le=1.0)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeQueryResult(KnowledgeModel):
    """Typed structural query result."""

    entities: tuple[KnowledgeEntity, ...]
    relationships: tuple[KnowledgeRelationship, ...]
    paths: tuple[GraphPath, ...]
    scores: dict[str, float] = Field(default_factory=dict)
    references: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class IntegrityViolation(KnowledgeModel):
    """Safe integrity violation."""

    violation_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    violation_type: str = Field(min_length=1)
    severity: IntegritySeverity
    entity_ids: tuple[str, ...] = Field(default_factory=tuple)
    relationship_ids: tuple[str, ...] = Field(default_factory=tuple)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    blocking: bool = False
    safe_message: str = Field(min_length=1, max_length=1000)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class GraphIntegrityReport(KnowledgeModel):
    """Graph integrity validation report."""

    report_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    status: GraphIntegrityStatus
    checked_entities: int = Field(ge=0)
    checked_relationships: int = Field(ge=0)
    violations: tuple[IntegrityViolation, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    orphan_entities: tuple[str, ...] = Field(default_factory=tuple)
    duplicate_entities: tuple[str, ...] = Field(default_factory=tuple)
    broken_relationships: tuple[str, ...] = Field(default_factory=tuple)
    cyclic_dependencies: tuple[GraphPath, ...] = Field(default_factory=tuple)
    version_conflicts: tuple[str, ...] = Field(default_factory=tuple)
    started_at: datetime
    completed_at: datetime
    duration: float = Field(ge=0.0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


class RepositoryHealth(KnowledgeModel):
    """Repository health response."""

    status: HealthStatus
    details: dict[str, SAFE_VALUE] = Field(default_factory=dict)


def normalize_text(value: str) -> str:
    """Normalize text deterministically using only the standard library."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    lowered = ascii_text.lower()
    cleaned = re.sub(r"[^\w\s.-]", " ", lowered)
    return " ".join(cleaned.split())


STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "de",
    "do",
    "da",
    "e",
    "for",
    "of",
    "or",
    "the",
    "to",
}


def tokenize(value: str) -> set[str]:
    """Tokenize normalized text without external language models."""
    return {
        token
        for token in normalize_text(value).replace("-", " ").split()
        if token and token not in STOPWORDS
    }


def stable_fingerprint(payload: dict[str, Any]) -> str:
    """Return a SHA-256 fingerprint from JSON-serializable safe payload."""
    _validate_safe_payload(payload, "fingerprint")
    try:
        encoded = json.dumps(
            payload, sort_keys=True, default=str, separators=(",", ":")
        )
    except TypeError as error:
        from ecos.knowledge.exceptions import NonSerializablePayloadError

        raise NonSerializablePayloadError("payload is not serializable") from error
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_time(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _validate_safe_payload(value: Any, field_name: str) -> None:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError(f"{field_name} contains non-finite number")
    if isinstance(value, bytes | bytearray | memoryview):
        raise ValueError(f"{field_name} cannot contain binary data")
    if isinstance(value, str) and len(value) > MAX_SAFE_STRING:
        raise ValueError(f"{field_name} string is too large")
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(sensitive in key_text for sensitive in SENSITIVE_KEYS):
                raise SensitiveMetadataError(f"{field_name} contains sensitive key")
            _validate_safe_payload(item, field_name)
    elif isinstance(value, list | tuple | set):
        for item in value:
            _validate_safe_payload(item, field_name)
    else:
        try:
            json.dumps(value, default=str)
        except TypeError as error:
            from ecos.knowledge.exceptions import NonSerializablePayloadError

            raise NonSerializablePayloadError(
                f"{field_name} is not serializable"
            ) from error


def relationship_id_for(relationship: KnowledgeRelationship) -> str:
    """Return a deterministic ID for a relationship signature."""
    return f"rel:{relationship.relationship_fingerprint[:32]}"

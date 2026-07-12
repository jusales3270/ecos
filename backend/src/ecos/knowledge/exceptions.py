"""Knowledge Graph domain exceptions."""


class KnowledgeGraphError(Exception):
    """Base error for Knowledge Graph operations."""


class InvalidKnowledgeEntityError(KnowledgeGraphError):
    """Raised when an entity violates the Knowledge Graph contract."""


class MissingEntityIdError(InvalidKnowledgeEntityError):
    """Raised when entity_id is missing."""


class MissingOrganizationError(InvalidKnowledgeEntityError):
    """Raised when organization_id is missing."""


class InvalidEntityTypeError(InvalidKnowledgeEntityError):
    """Raised when entity_type is unknown."""


class InvalidVersionError(KnowledgeGraphError):
    """Raised when a version is invalid."""


class AmbiguousVersionError(KnowledgeGraphError):
    """Raised when a current/as_of lookup is ambiguous."""


class ConflictingVersionError(KnowledgeGraphError):
    """Raised when an immutable version conflicts with stored history."""


class FingerprintConflictError(KnowledgeGraphError):
    """Raised when a deterministic fingerprint maps to conflicting content."""


class InvalidKnowledgeRelationshipError(KnowledgeGraphError):
    """Raised when a relationship violates the Knowledge Graph contract."""


class InvalidRelationshipTypeError(InvalidKnowledgeRelationshipError):
    """Raised when relationship_type is unknown."""


class SourceEntityNotFoundError(InvalidKnowledgeRelationshipError):
    """Raised when a relationship source does not exist."""


class TargetEntityNotFoundError(InvalidKnowledgeRelationshipError):
    """Raised when a relationship target does not exist."""


class OrganizationMismatchError(KnowledgeGraphError):
    """Raised when graph objects cross organization boundaries."""


class SelfRelationshipForbiddenError(InvalidKnowledgeRelationshipError):
    """Raised when a relationship cannot point to itself."""


class DuplicateRelationshipError(InvalidKnowledgeRelationshipError):
    """Raised when an active relationship signature already exists."""


class DependencyCycleError(KnowledgeGraphError):
    """Raised when an acyclic relationship type would create a cycle."""


class ReplacementCycleError(KnowledgeGraphError):
    """Raised when a replacement chain would create a cycle."""


class InvalidKnowledgeQueryError(KnowledgeGraphError):
    """Raised when a query is invalid."""


class InvalidKnowledgeLimitError(InvalidKnowledgeQueryError):
    """Raised when a query limit is invalid."""


class InvalidTraversalError(InvalidKnowledgeQueryError):
    """Raised when traversal parameters are invalid."""


class InvalidGraphPathError(KnowledgeGraphError):
    """Raised when a path does not describe connected graph objects."""


class InvalidSemanticQueryError(InvalidKnowledgeQueryError):
    """Raised when a semantic query is invalid."""


class InvalidSemanticScoreError(KnowledgeGraphError):
    """Raised when a semantic score is not finite or outside bounds."""


class SemanticProviderUnavailableError(KnowledgeGraphError):
    """Raised when semantic search provider is unavailable."""


class KnowledgeRepositoryUnavailableError(KnowledgeGraphError):
    """Raised when the repository cannot complete an operation."""


class IncompatibleContextError(KnowledgeGraphError):
    """Raised when context expansion input is incompatible with the graph."""


class InvalidProjectionError(KnowledgeGraphError):
    """Raised when an event cannot be projected to knowledge."""


class ConflictingProjectionError(KnowledgeGraphError):
    """Raised when replay idempotency detects a projection conflict."""


class InvalidGraphIntegrityError(KnowledgeGraphError):
    """Raised when graph integrity validation cannot run."""


class NonSerializablePayloadError(KnowledgeGraphError):
    """Raised when structured data cannot be serialized safely."""


class SensitiveMetadataError(KnowledgeGraphError):
    """Raised when safe metadata contains sensitive keys."""


class DependencyUnavailableError(KnowledgeGraphError):
    """Raised when an injected dependency is unavailable."""

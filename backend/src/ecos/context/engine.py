"""Deterministic real Context Engine implementation for ECOS."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from ecos.context.models import (
    ContextBuildRequest,
    ContextElement,
    ContextMemoryReference,
    ContextObject,
    ContextPriority,
    ContextSourceType,
    MissingContextItem,
    MissingContextSeverity,
)
from ecos.context.provider import ContextProvider
from ecos.core.exceptions import (
    CrossOrganizationMemoryError,
    ImpossibleContextError,
    InvalidObjectiveError,
    MemoryRetrievalError,
    MissingOrganizationError,
)
from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.memory import MemoryObject, MemoryRepository, MemoryType

Clock = Callable[[], datetime]
IdGenerator = Callable[[], UUID]


def utc_clock() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ContextEngine(ContextProvider):
    """Build a deterministic unified context from session input and memory."""

    def __init__(
        self,
        memory_repository: MemoryRepository,
        *,
        event_service: EventService | None = None,
        clock: Clock = utc_clock,
        id_generator: IdGenerator = uuid4,
    ) -> None:
        self._memory_repository = memory_repository
        self._event_service = event_service
        self._clock = clock
        self._id_generator = id_generator
        self._version = 0

    def build(self, request: ContextBuildRequest | None = None) -> ContextObject:
        """Build a unified context from an explicit typed request."""
        if request is None:
            raise ImpossibleContextError("ContextBuildRequest is required.")
        started_at = perf_counter()
        self._validate_request(request)
        self._publish(
            EventType.CONTEXT_REQUESTED,
            request,
            {
                "memory_limit": request.memory_limit,
                "policy_count": len(request.policies),
                "constraint_count": len(request.constraints),
            },
        )
        try:
            candidates = self._retrieve_memory(request)
        except Exception as error:
            raise MemoryRetrievalError() from error

        self._validate_memory_scope(request, candidates)
        selected = self._select_memories(request, candidates)
        missing_context = self._detect_missing_context(request, selected)
        confidence = self._calculate_confidence(request, selected, missing_context)
        completeness = self._calculate_completeness(request, selected, missing_context)
        if missing_context:
            self._publish(
                EventType.CONTEXT_MISSING,
                request,
                {
                    "missing_count": len(missing_context),
                    "critical_missing_count": sum(
                        item.severity is MissingContextSeverity.CRITICAL
                        for item in missing_context
                    ),
                    "confidence": confidence,
                    "completeness": completeness,
                },
            )

        context = self._assemble_context(
            request,
            selected,
            missing_context,
            confidence,
            completeness,
        )
        if not self.validate(context):
            raise ImpossibleContextError("assembled context failed validation")
        duration_ms = int((perf_counter() - started_at) * 1000)
        self._publish(
            EventType.CONTEXT_CREATED,
            request,
            {
                "memories_evaluated": len(candidates),
                "memories_selected": len(selected),
                "policy_count": len(request.policies),
                "constraint_count": len(request.constraints),
                "missing_count": len(missing_context),
                "confidence": confidence,
                "completeness": completeness,
                "version": context.version,
                "duration_ms": duration_ms,
            },
        )
        return context

    def expand(self, context: ContextObject) -> ContextObject:
        """Return a new context version without adding inferred information."""
        return context.model_copy(update={"version": context.version + 1}, deep=True)

    def compress(self, context: ContextObject) -> ContextObject:
        """Return context unchanged because LLM compression is out of scope."""
        return context

    def validate(self, context: ContextObject) -> bool:
        """Validate minimum invariants of a generated unified context."""
        return (
            context.organization_id is not None
            and context.objective.organization_id == context.organization_id
            and context.version >= 1
            and 0.0 <= context.confidence <= 1.0
            and 0.0 <= context.completeness <= 1.0
        )

    def _validate_request(self, request: ContextBuildRequest) -> None:
        if request.organization_id is None:
            raise MissingOrganizationError()
        if request.objective.organization_id != request.organization_id:
            raise MissingOrganizationError()
        if request.objective.title.strip() == "":
            raise InvalidObjectiveError()

    def _retrieve_memory(self, request: ContextBuildRequest) -> list[MemoryObject]:
        terms = self._query_terms(request)
        memories: OrderedDict[UUID, MemoryObject] = OrderedDict()
        per_query_limit = max(request.memory_limit * 4, 10)
        for term in terms:
            for memory in self._memory_repository.search(
                term,
                organization_id=request.organization_id,
                limit=per_query_limit,
            ):
                memories.setdefault(memory.id, memory)
        if not memories:
            for memory in self._memory_repository.list(
                organization_id=request.organization_id,
                limit=per_query_limit,
            ):
                memories.setdefault(memory.id, memory)
        return list(memories.values())

    def _query_terms(self, request: ContextBuildRequest) -> list[str]:
        values = [
            request.objective.title,
            request.objective.description or "",
            *request.relevant_entities,
            *request.constraints,
            *request.policies,
        ]
        terms: OrderedDict[str, None] = OrderedDict()
        for value in values:
            for token in self._tokens(value):
                if len(token) >= 3:
                    terms[token] = None
        return list(terms) or [request.objective.title]

    def _validate_memory_scope(
        self, request: ContextBuildRequest, memories: list[MemoryObject]
    ) -> None:
        for memory in memories:
            if memory.organization_id != request.organization_id:
                raise CrossOrganizationMemoryError()

    def _select_memories(
        self, request: ContextBuildRequest, memories: list[MemoryObject]
    ) -> list[tuple[MemoryObject, float]]:
        scored = [
            (memory, self._score_memory(request, memory))
            for memory in memories
            if self._score_memory(request, memory) > 0.0
        ]
        scored.sort(
            key=lambda item: (
                -item[1],
                -item[0].confidence,
                item[0].created_at,
                str(item[0].id),
            )
        )
        return scored[: request.memory_limit]

    def _score_memory(
        self, request: ContextBuildRequest, memory: MemoryObject
    ) -> float:
        memory_tokens = self._tokens(
            " ".join([memory.title, memory.description, " ".join(memory.tags)])
        )
        objective_score = self._overlap(
            memory_tokens, self._tokens(request.objective.title)
        )
        entity_score = self._overlap(
            memory_tokens, self._tokens(" ".join(request.relevant_entities))
        )
        policy_score = self._overlap(
            memory_tokens,
            self._tokens(" ".join([*request.policies, *request.constraints])),
        )
        if objective_score == 0.0 and entity_score == 0.0 and policy_score == 0.0:
            return 0.0
        importance = self._importance(memory)
        recency = self._recency(memory)
        category = (
            1.0
            if memory.type in {MemoryType.STRATEGIC, MemoryType.ORGANIZATIONAL}
            else 0.6
        )
        score = (
            objective_score * 0.28
            + entity_score * 0.18
            + policy_score * 0.14
            + importance * 0.16
            + memory.confidence * 0.14
            + recency * 0.06
            + category * 0.04
        )
        return round(max(0.0, min(score, 1.0)), 4)

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token
            for token in "".join(
                character.lower() if character.isalnum() else " " for character in value
            ).split()
            if token
        }

    @staticmethod
    def _overlap(memory_tokens: set[str], query_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        return len(memory_tokens.intersection(query_tokens)) / len(query_tokens)

    @staticmethod
    def _importance(memory: MemoryObject) -> float:
        type_weight = {
            MemoryType.STRATEGIC: 1.0,
            MemoryType.ORGANIZATIONAL: 0.9,
            MemoryType.SEMANTIC: 0.75,
            MemoryType.EPISODIC: 0.6,
            MemoryType.WORKING: 0.5,
        }[memory.type]
        tags = {tag.lower() for tag in memory.tags}
        tag_boost = 0.15 if {"critical", "important", "policy"} & tags else 0.0
        return min(type_weight + tag_boost, 1.0)

    def _recency(self, memory: MemoryObject) -> float:
        age_days = max((self._clock() - memory.updated_at).days, 0)
        if age_days <= 30:
            return 1.0
        if age_days <= 365:
            return 0.7
        return 0.35

    def _assemble_context(
        self,
        request: ContextBuildRequest,
        selected: list[tuple[MemoryObject, float]],
        missing_context: list[MissingContextItem],
        confidence: float,
        completeness: float,
    ) -> ContextObject:
        now = self._clock()
        self._version += 1
        elements = self._elements(request, selected, now)
        memory_references = [
            ContextMemoryReference(
                memory_id=memory.id,
                organization_id=request.organization_id,
                title=memory.title,
                memory_type=memory.type.value,
                relevance_score=score,
                confidence=memory.confidence,
                created_at=memory.created_at,
            )
            for memory, score in selected
        ]
        evidence = [
            f"memory:{memory.id}"
            for memory, _score in selected
            if memory.confidence >= 0.5
        ]
        summary = self._summary(request, selected, missing_context)
        return ContextObject(
            id=self._id_generator(),
            session_id=request.session_id,
            organization_id=request.organization_id,
            objective=request.objective.model_copy(deep=True),
            summary=summary,
            elements=elements,
            organizational_context=[
                memory.title
                for memory, _score in selected
                if memory.type is MemoryType.ORGANIZATIONAL
            ],
            strategic_context=[
                memory.title
                for memory, _score in selected
                if memory.type is MemoryType.STRATEGIC
            ],
            operational_context=list(request.resources),
            historical_context=[
                memory.title
                for memory, _score in selected
                if memory.type is MemoryType.EPISODIC
            ],
            external_context=list(request.external_signals),
            session_context={
                "user_id": None if request.user_id is None else str(request.user_id),
                "objective_category": request.objective_category,
                "correlation_id": None
                if request.correlation_id is None
                else str(request.correlation_id),
            },
            constraints=list(request.constraints),
            policies=list(request.policies),
            resources=list(request.resources),
            relevant_entities=list(request.relevant_entities),
            memory_references=memory_references,
            evidence=evidence,
            previous_decisions=[str(item) for item in request.previous_session_ids],
            missing_context=missing_context,
            confidence=confidence,
            completeness=completeness,
            version=self._version,
            generated_at=now,
            metadata={
                "engine": "ContextEngine",
                "memory_evaluated_count": len(selected),
                "policy_count": len(request.policies),
                "constraint_count": len(request.constraints),
            },
        )

    def _elements(
        self,
        request: ContextBuildRequest,
        selected: list[tuple[MemoryObject, float]],
        now: datetime,
    ) -> list[ContextElement]:
        elements = [
            ContextElement(
                source_type=ContextSourceType.USER,
                priority=ContextPriority.HIGH,
                title="Objective",
                content=request.objective.title,
                confidence=1.0,
                created_at=now,
                metadata={"category": "objective"},
            )
        ]
        for value in request.policies:
            elements.append(
                ContextElement(
                    source_type=ContextSourceType.POLICY,
                    priority=ContextPriority.CRITICAL,
                    title="Policy",
                    content=value,
                    confidence=1.0,
                    created_at=now,
                )
            )
        for value in request.external_signals:
            elements.append(
                ContextElement(
                    source_type=ContextSourceType.EXTERNAL,
                    priority=ContextPriority.MEDIUM,
                    title="External signal",
                    content=value,
                    confidence=0.7,
                    created_at=now,
                )
            )
        for memory, score in selected:
            elements.append(
                ContextElement(
                    source_type=ContextSourceType.MEMORY,
                    priority=self._priority(score),
                    title=memory.title,
                    content=memory.description,
                    confidence=memory.confidence,
                    created_at=now,
                    metadata={
                        "memory_id": str(memory.id),
                        "memory_type": memory.type.value,
                        "relevance_score": score,
                    },
                )
            )
        return elements

    @staticmethod
    def _priority(score: float) -> ContextPriority:
        if score >= 0.8:
            return ContextPriority.CRITICAL
        if score >= 0.55:
            return ContextPriority.HIGH
        if score >= 0.3:
            return ContextPriority.MEDIUM
        return ContextPriority.LOW

    def _detect_missing_context(
        self,
        request: ContextBuildRequest,
        selected: list[tuple[MemoryObject, float]],
    ) -> list[MissingContextItem]:
        gaps: list[MissingContextItem] = []
        if len(request.objective.title.strip()) < 8:
            gaps.append(
                self._gap("objective", "objective", MissingContextSeverity.HIGH)
            )
        if not selected:
            gaps.append(
                self._gap("memory", "historical_context", MissingContextSeverity.HIGH)
            )
        if not any(memory.confidence >= 0.5 for memory, _score in selected):
            gaps.append(
                self._gap("evidence", "evidence", MissingContextSeverity.MEDIUM)
            )
        if not request.policies:
            gaps.append(self._gap("policies", "policy", MissingContextSeverity.MEDIUM))
        if not request.constraints:
            gaps.append(
                self._gap("constraints", "constraint", MissingContextSeverity.MEDIUM)
            )
        if any(memory.confidence < 0.5 for memory, _score in selected):
            gaps.append(
                self._gap("memory_confidence", "quality", MissingContextSeverity.MEDIUM)
            )
        if any(
            (self._clock() - memory.updated_at).days > 730
            for memory, _score in selected
        ):
            gaps.append(
                self._gap("memory_recency", "freshness", MissingContextSeverity.LOW)
            )
        available = {
            "objective",
            "constraints",
            "policies",
            "resources",
            "external_signals",
            "relevant_entities",
            "memory",
            "evidence",
        }
        for field in request.required_context_fields:
            if field not in available or not self._has_field(request, selected, field):
                gaps.append(self._gap(field, "required", MissingContextSeverity.HIGH))
        return gaps

    @staticmethod
    def _has_field(
        request: ContextBuildRequest,
        selected: list[tuple[MemoryObject, float]],
        field: str,
    ) -> bool:
        return {
            "objective": bool(request.objective.title),
            "constraints": bool(request.constraints),
            "policies": bool(request.policies),
            "resources": bool(request.resources),
            "external_signals": bool(request.external_signals),
            "relevant_entities": bool(request.relevant_entities),
            "memory": bool(selected),
            "evidence": any(memory.confidence >= 0.5 for memory, _score in selected),
        }.get(field, False)

    @staticmethod
    def _gap(
        field: str, category: str, severity: MissingContextSeverity
    ) -> MissingContextItem:
        return MissingContextItem(
            field=field,
            category=category,
            description=f"Missing or insufficient context for {field}.",
            severity=severity,
            reason=f"No reliable {field} was available in the request or memory.",
            cognitive_impact="Downstream reasoning must treat this area as uncertain.",
            suggested_action=f"Provide verified {field} before relying on conclusions.",
        )

    @staticmethod
    def _calculate_confidence(
        request: ContextBuildRequest,
        selected: list[tuple[MemoryObject, float]],
        gaps: list[MissingContextItem],
    ) -> float:
        del request
        memory_quality = (
            sum(memory.confidence for memory, _score in selected) / len(selected)
            if selected
            else 0.0
        )
        critical_penalty = 0.25 * sum(
            item.severity is MissingContextSeverity.CRITICAL for item in gaps
        )
        high_penalty = 0.12 * sum(
            item.severity is MissingContextSeverity.HIGH for item in gaps
        )
        score = 0.45 + memory_quality * 0.45 - critical_penalty - high_penalty
        return round(max(0.0, min(score, 1.0)), 4)

    @staticmethod
    def _calculate_completeness(
        request: ContextBuildRequest,
        selected: list[tuple[MemoryObject, float]],
        gaps: list[MissingContextItem],
    ) -> float:
        required = 4 + len(request.required_context_fields)
        present = 1
        present += int(bool(selected))
        present += int(bool(request.policies))
        present += int(bool(request.constraints))
        present += sum(
            1
            for field in request.required_context_fields
            if ContextEngine._has_field(request, selected, field)
        )
        penalty = 0.15 * sum(
            item.severity is MissingContextSeverity.CRITICAL for item in gaps
        )
        return round(max(0.0, min((present / required) - penalty, 1.0)), 4)

    @staticmethod
    def _summary(
        request: ContextBuildRequest,
        selected: list[tuple[MemoryObject, float]],
        gaps: list[MissingContextItem],
    ) -> str:
        return (
            f"Context for '{request.objective.title}' includes {len(selected)} "
            f"memory references, {len(request.policies)} policies, "
            f"{len(request.constraints)} constraints, and {len(gaps)} gaps."
        )

    def _publish(
        self,
        event_type: EventType,
        request: ContextBuildRequest,
        payload: dict[str, str | int | float | bool | None],
    ) -> None:
        if self._event_service is None:
            return
        envelope = self._event_service.publish(
            Event(
                event_type=event_type,
                source="context",
                session_id=request.session_id,
                payload={"organization_id": str(request.organization_id), **payload},
                metadata=EventMetadata(correlation_id=request.correlation_id),
                priority=EventPriority.NORMAL,
            )
        )
        self._event_service.dispatch(envelope)

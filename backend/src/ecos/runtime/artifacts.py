"""Typed, versioned serialization for runtime engine artifacts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from ecos.context import ContextObject
from ecos.debate import DebateResult
from ecos.decision import DecisionPackage
from ecos.execution import ExecutionResult
from ecos.governance import GovernanceResult
from ecos.learning import LearningResult
from ecos.observation import ObservationResult
from ecos.orchestrator import (
    EngineStageResult,
    ResumableOrchestrationState,
    StageExecutionStatus,
    TimelineEntry,
)
from ecos.reasoning import ReasoningResult
from ecos.runtime.repository import (
    ArtifactEnvelope,
    SerializedResumableState,
    SerializedStageResult,
)
from ecos.simulation import SimulationReport
from ecos.specialists import Contribution, Specialist


class RuntimeArtifactError(ValueError):
    """Base error for runtime artifact serialization."""


class UnknownArtifactTypeError(RuntimeArtifactError):
    """Raised for an engine or artifact type that has no registered codec."""


class UnknownArtifactVersionError(RuntimeArtifactError):
    """Raised when a serialized artifact uses an unsupported schema version."""


class InvalidArtifactError(RuntimeArtifactError):
    """Raised when an artifact payload cannot be validated."""


class RuntimeArtifactCodec:
    """Encode and decode known runtime artifacts without persisting raw ``Any``."""

    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        model_types: dict[str, type[BaseModel]] = {
            "context": ContextObject,
            "reasoning": ReasoningResult,
            "debate": DebateResult,
            "simulation": SimulationReport,
            "decision": DecisionPackage,
            "decision_support": DecisionPackage,
            "governance": GovernanceResult,
            "execution": ExecutionResult,
            "observation": ObservationResult,
            "learning": LearningResult,
            "memory": LearningResult,
        }
        self._model_types = model_types
        self._artifact_names = {
            engine: model.__name__ for engine, model in model_types.items()
        }

    def encode(self, engine: str, value: object) -> ArtifactEnvelope:
        """Serialize one output using the codec registered for its engine."""
        if value is None:
            return ArtifactEnvelope(
                engine=engine,
                artifact_type="none",
                schema_version=self.SCHEMA_VERSION,
                payload=None,
            )
        if engine == "specialists":
            return self._encode_specialists(value)
        model_type = self._model_types.get(engine)
        if model_type is None:
            raise UnknownArtifactTypeError(f"unknown runtime engine: {engine}")
        if not isinstance(value, model_type):
            raise InvalidArtifactError(
                f"invalid {engine} artifact: expected {model_type.__name__}"
            )
        return ArtifactEnvelope(
            engine=engine,
            artifact_type=self._artifact_names[engine],
            schema_version=self.SCHEMA_VERSION,
            payload=value.model_dump(mode="json"),
        )

    def decode(self, envelope: ArtifactEnvelope) -> object:
        """Validate and restore one typed engine output."""
        self._validate_version(envelope)
        if envelope.artifact_type == "none":
            if envelope.payload is not None:
                raise InvalidArtifactError("none artifact must not contain a payload")
            return None
        if envelope.engine == "specialists":
            return self._decode_specialists(envelope)
        model_type = self._model_types.get(envelope.engine)
        if model_type is None:
            raise UnknownArtifactTypeError(f"unknown runtime engine: {envelope.engine}")
        expected_type = self._artifact_names[envelope.engine]
        if envelope.artifact_type != expected_type:
            raise UnknownArtifactTypeError(
                f"unknown artifact type for {envelope.engine}: {envelope.artifact_type}"
            )
        if envelope.payload is None:
            raise InvalidArtifactError("typed artifact payload is required")
        try:
            return model_type.model_validate(envelope.payload)
        except ValidationError as error:
            raise InvalidArtifactError(
                f"invalid {envelope.engine} artifact payload"
            ) from error

    def serialize_stage_result(
        self, result: EngineStageResult
    ) -> SerializedStageResult:
        """Serialize a stage result with a typed output envelope."""
        return SerializedStageResult(
            stage_id=result.stage_id,
            engine=result.engine,
            status=result.status.value,
            output=self.encode(result.engine, result.output),
            started_at=result.started_at,
            completed_at=result.completed_at,
            duration=result.duration,
            attempt=result.attempt,
            warnings=result.warnings,
            safe_metadata=result.safe_metadata,
        )

    def deserialize_stage_result(
        self, result: SerializedStageResult
    ) -> EngineStageResult:
        """Restore a typed Orchestrator stage result."""
        if result.output.engine != result.engine:
            raise InvalidArtifactError("stage result artifact engine mismatch")
        try:
            status = StageExecutionStatus(result.status)
        except ValueError as error:
            raise InvalidArtifactError("invalid stage execution status") from error
        return EngineStageResult(
            stage_id=result.stage_id,
            engine=result.engine,
            status=status,
            output=self.decode(result.output),
            started_at=result.started_at,
            completed_at=result.completed_at,
            duration=result.duration,
            attempt=result.attempt,
            warnings=result.warnings,
            safe_metadata=result.safe_metadata,
        )

    def serialize_resume_state(
        self, state: ResumableOrchestrationState
    ) -> SerializedResumableState:
        """Serialize a resumable state without retaining raw engine outputs."""
        return SerializedResumableState(
            execution_id=state.execution_id,
            plan_id=state.plan_id,
            session_id=state.session_id,
            organization_id=state.organization_id,
            correlation_id=state.correlation_id,
            pipeline_status=state.pipeline_status,
            blocked_stage=state.blocked_stage,
            completed_stage_ids=state.completed_stage_ids,
            stage_results=tuple(
                self.serialize_stage_result(item) for item in state.stage_results
            ),
            attempts=state.attempts,
            timeline=tuple(item.model_dump(mode="json") for item in state.timeline),
            approval_required=state.approval_required,
            governance_required=state.governance_required,
            created_at=state.created_at,
            updated_at=state.updated_at,
            version=state.version,
        )

    def deserialize_resume_state(
        self, state: SerializedResumableState
    ) -> ResumableOrchestrationState:
        """Restore a resumable state and every typed completed-stage output."""
        if state.version != 1:
            raise UnknownArtifactVersionError(
                f"unsupported resumable state version: {state.version}"
            )
        try:
            timeline = tuple(
                TimelineEntry.model_validate(item) for item in state.timeline
            )
        except ValidationError as error:
            raise InvalidArtifactError("invalid resumable timeline") from error
        return ResumableOrchestrationState(
            execution_id=state.execution_id,
            plan_id=state.plan_id,
            session_id=state.session_id,
            organization_id=state.organization_id,
            correlation_id=state.correlation_id,
            pipeline_status=state.pipeline_status,
            blocked_stage=state.blocked_stage,
            completed_stage_ids=state.completed_stage_ids,
            stage_results=tuple(
                self.deserialize_stage_result(item) for item in state.stage_results
            ),
            attempts=state.attempts,
            timeline=timeline,
            approval_required=state.approval_required,
            governance_required=state.governance_required,
            created_at=state.created_at,
            updated_at=state.updated_at,
            version=state.version,
        )

    def _encode_specialists(self, value: object) -> ArtifactEnvelope:
        if not isinstance(value, dict):
            raise InvalidArtifactError("invalid specialists artifact")
        specialists = value.get("specialists")
        contributions = value.get("contributions")
        if not isinstance(specialists, list) or not all(
            isinstance(item, Specialist) for item in specialists
        ):
            raise InvalidArtifactError("invalid specialists list")
        if not isinstance(contributions, list) or not all(
            isinstance(item, Contribution) for item in contributions
        ):
            raise InvalidArtifactError("invalid specialist contributions")
        return ArtifactEnvelope(
            engine="specialists",
            artifact_type="SpecialistCollection",
            schema_version=self.SCHEMA_VERSION,
            payload={
                "specialists": [item.model_dump(mode="json") for item in specialists],
                "contributions": [
                    item.model_dump(mode="json") for item in contributions
                ],
            },
        )

    def _decode_specialists(self, envelope: ArtifactEnvelope) -> dict[str, list[Any]]:
        if envelope.artifact_type != "SpecialistCollection":
            raise UnknownArtifactTypeError(
                f"unknown artifact type for specialists: {envelope.artifact_type}"
            )
        if envelope.payload is None:
            raise InvalidArtifactError("specialists artifact payload is required")
        try:
            specialists = [
                Specialist.model_validate(item)
                for item in envelope.payload.get("specialists", [])
            ]
            contributions = [
                Contribution.model_validate(item)
                for item in envelope.payload.get("contributions", [])
            ]
        except (TypeError, ValidationError) as error:
            raise InvalidArtifactError(
                "invalid specialists artifact payload"
            ) from error
        return {"specialists": specialists, "contributions": contributions}

    def _validate_version(self, envelope: ArtifactEnvelope) -> None:
        if envelope.schema_version != self.SCHEMA_VERSION:
            raise UnknownArtifactVersionError(
                f"unsupported artifact version: {envelope.schema_version}"
            )

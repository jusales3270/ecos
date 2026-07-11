"""Cognitive session domain entity."""

from uuid import UUID

from pydantic import Field

from ecos.domain.base import DomainEntity
from ecos.domain.enums import SessionStage, SessionStatus
from ecos.domain.objective import Objective


class CognitiveSession(DomainEntity):
    """Represents the state of an ECOS cognitive workflow session."""

    organization_id: UUID = Field(description="Organization that owns the session.")
    objective: Objective = Field(
        description="Objective being evaluated in the session."
    )
    status: SessionStatus = Field(
        default=SessionStatus.CREATED,
        description="Current session lifecycle status.",
    )
    current_stage: SessionStage = Field(
        default=SessionStage.CONTEXT,
        description="Current stage in the cognitive architecture.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Current confidence score from 0.0 to 1.0.",
    )

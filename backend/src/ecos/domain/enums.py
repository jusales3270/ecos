"""Enumerations for ECOS cognitive session state and stages."""

from enum import StrEnum


class SessionStatus(StrEnum):
    """Lifecycle status values for a cognitive session."""

    CREATED = "CREATED"
    INITIALIZED = "INITIALIZED"
    CONTEXT = "CONTEXT"
    REASONING = "REASONING"
    DEBATE = "DEBATE"
    SIMULATION = "SIMULATION"
    RECOMMENDATION = "RECOMMENDATION"
    APPROVAL = "APPROVAL"
    EXECUTION = "EXECUTION"
    OBSERVATION = "OBSERVATION"
    LEARNING = "LEARNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SessionStage(StrEnum):
    """Architecture stages supported by the ECOS cognitive workflow."""

    CONTEXT = "CONTEXT"
    REASONING = "REASONING"
    DEBATE = "DEBATE"
    SIMULATION = "SIMULATION"
    RECOMMENDATION = "RECOMMENDATION"
    APPROVAL = "APPROVAL"
    EXECUTION = "EXECUTION"
    OBSERVATION = "OBSERVATION"
    LEARNING = "LEARNING"

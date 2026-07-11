"""Unit tests for ECOS core domain models."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from ecos.domain import (
    CognitiveSession,
    Objective,
    Organization,
    SessionStage,
    SessionStatus,
    User,
)


def test_organization_creates_identity_and_utc_timestamps() -> None:
    """Organization includes UUID identity and UTC audit timestamps."""
    organization = Organization(name="ACME")

    assert isinstance(organization.id, UUID)
    assert organization.name == "ACME"
    assert organization.created_at.tzinfo is not None
    assert organization.created_at.utcoffset() == UTC.utcoffset(organization.created_at)
    assert organization.updated_at.tzinfo is not None
    assert organization.updated_at.utcoffset() == UTC.utcoffset(organization.updated_at)
    assert organization.updated_at >= organization.created_at


def test_organization_requires_non_blank_name_and_description() -> None:
    """Organization rejects blank names and blank descriptions."""
    with pytest.raises(ValidationError):
        Organization(name="   ")

    with pytest.raises(ValidationError):
        Organization(name="ACME", description="   ")


def test_user_normalizes_email_and_links_organization() -> None:
    """User validates email and stores its owning organization."""
    organization = Organization(name="ACME")
    user = User(
        organization_id=organization.id,
        email="USER@EXAMPLE.COM",
        full_name="Example User",
    )

    assert user.organization_id == organization.id
    assert user.email == "user@example.com"
    assert user.is_active is True


def test_user_rejects_invalid_email_and_blank_name() -> None:
    """User rejects invalid email values and blank names."""
    organization = Organization(name="ACME")

    with pytest.raises(ValidationError):
        User(
            organization_id=organization.id,
            email="invalid-email",
            full_name="Example User",
        )

    with pytest.raises(ValidationError):
        User(
            organization_id=organization.id,
            email="user@example.com",
            full_name="   ",
        )


def test_objective_validates_priority_and_text_fields() -> None:
    """Objective validates priority, title, and optional description."""
    organization = Organization(name="ACME")
    objective = Objective(
        organization_id=organization.id,
        title="Improve decision quality",
        description="Increase decision consistency.",
        priority=5,
    )

    assert objective.organization_id == organization.id
    assert objective.priority == 5

    with pytest.raises(ValidationError):
        Objective(
            organization_id=organization.id,
            title="Invalid priority",
            priority=6,
        )

    with pytest.raises(ValidationError):
        Objective(organization_id=organization.id, title="   ")

    with pytest.raises(ValidationError):
        Objective(
            organization_id=organization.id,
            title="Improve decision quality",
            description="   ",
        )


def test_cognitive_session_uses_entity_id_as_official_identifier() -> None:
    """CognitiveSession uses inherited id and does not expose session_id."""
    organization = Organization(name="ACME")
    objective = Objective(
        organization_id=organization.id,
        title="Improve decision quality",
    )
    session = CognitiveSession(
        organization_id=organization.id,
        objective=objective,
    )

    assert isinstance(session.id, UUID)
    assert "session_id" not in CognitiveSession.model_fields
    assert session.organization_id == organization.id
    assert session.objective == objective
    assert session.status == SessionStatus.CREATED
    assert session.current_stage == SessionStage.CONTEXT
    assert session.confidence == 0.0


def test_cognitive_session_validates_confidence() -> None:
    """CognitiveSession confidence must be between 0.0 and 1.0."""
    organization = Organization(name="ACME")
    objective = Objective(
        organization_id=organization.id,
        title="Improve decision quality",
    )

    CognitiveSession(
        organization_id=organization.id,
        objective=objective,
        confidence=0.0,
    )
    CognitiveSession(
        organization_id=organization.id,
        objective=objective,
        confidence=1.0,
    )

    with pytest.raises(ValidationError):
        CognitiveSession(
            organization_id=organization.id,
            objective=objective,
            confidence=-0.1,
        )

    with pytest.raises(ValidationError):
        CognitiveSession(
            organization_id=organization.id,
            objective=objective,
            confidence=1.1,
        )


def test_domain_entity_rejects_invalid_timestamps() -> None:
    """Domain entities reject non-UTC, naive, and unordered timestamps."""
    created_at = datetime.now(UTC)

    with pytest.raises(ValidationError):
        Organization(
            name="ACME",
            created_at=created_at,
            updated_at=created_at - timedelta(seconds=1),
        )

    with pytest.raises(ValidationError):
        Organization(name="ACME", created_at=datetime.now())

    with pytest.raises(ValidationError):
        Organization(
            name="ACME",
            created_at=datetime.now(timezone(timedelta(hours=-3))),
        )


def test_session_status_and_stage_are_coherent() -> None:
    """Session stages are the active architecture stages within session statuses."""
    workflow_statuses = {
        SessionStatus.CONTEXT,
        SessionStatus.REASONING,
        SessionStatus.DEBATE,
        SessionStatus.SIMULATION,
        SessionStatus.RECOMMENDATION,
        SessionStatus.APPROVAL,
        SessionStatus.EXECUTION,
        SessionStatus.OBSERVATION,
        SessionStatus.LEARNING,
    }

    assert {stage.value for stage in SessionStage} == {
        status.value for status in workflow_statuses
    }
    assert SessionStatus.CREATED not in workflow_statuses
    assert SessionStatus.COMPLETED not in workflow_statuses
    assert SessionStatus.FAILED not in workflow_statuses

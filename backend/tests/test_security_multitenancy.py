"""Sprint 17F tests for local security, auth and multitenancy."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ecos.core.settings import Settings
from ecos.domain import CognitiveSession, Objective
from ecos.domain.enums import SessionStage
from ecos.events import Event, EventMetadata, EventService, EventType
from ecos.governance import (
    ApprovalDecision,
    ApprovalLevel,
    DefaultApprovalPolicyProvider,
    GovernanceActionType,
    GovernanceConfig,
    GovernanceEngine,
    GovernanceRequest,
    HumanDecision,
    ImpactLevel,
    InMemoryPolicyProvider,
    OrganizationalPolicy,
    PolicyDomain,
    PolicyRule,
    PolicyStatus,
    RuleOperator,
    UnauthorizedRoleError,
)
from ecos.knowledge import (
    InMemoryKnowledgeGraphRepository,
    KnowledgeEntity,
    KnowledgeEntityType,
)
from ecos.memory import MemoryObject, MemoryService, MemoryType
from ecos.observability import (
    AuditProjector,
    InMemoryAuditRepository,
    InMemoryEventStore,
    InMemoryObservabilityRepository,
    MetricProjector,
)
from ecos.observability.models import EventQuery, MetricRecord, MetricType
from ecos.planner import (
    CognitivePlan,
    EngineSelection,
    ExecutionStrategy,
    Pipeline,
    PipelineStep,
    PlanningStrategy,
    RiskLevel,
)
from ecos.runtime import FakeEventBus, FakeMemoryRepository, FakeSessionRepository
from ecos.security import (
    AuthenticationError,
    AuthorizationError,
    CrossTenantAccessError,
    InMemorySecurityRepository,
    Permission,
    Role,
    SecurityIdentityPort,
    SecurityService,
    TenantScopedMemoryService,
    TenantScopedSessionService,
)
from ecos.security.postgres import (
    PostgresSecurityRepository,
    SecurityAuthSessionRecord,
    SecurityMembershipRecord,
    SecurityOrganizationRecord,
    SecurityUserRecord,
)
from ecos.session import (
    ManagedSession,
    SessionContext,
    SessionLifecycleStatus,
    SessionService,
    SessionState,
)

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
ORG_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORG_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
SESSION_A = UUID("33333333-3333-4333-8333-333333333333")
PLAN_ID = UUID("44444444-4444-4444-8444-444444444444")
CORRELATION_ID = UUID("55555555-5555-4555-8555-555555555555")
SECRET = "unit-test-auth-secret-000000000000000000"


def make_security(clock=lambda: NOW) -> SecurityService:
    repository = InMemorySecurityRepository()
    service = SecurityService(
        repository,
        token_secret=SECRET,
        issuer="test",
        audience="ecos",
        token_ttl=timedelta(minutes=15),
        event_service=EventService(
            FakeEventBus(),
            InMemoryEventStore(),
            projectors=(AuditProjector(InMemoryAuditRepository()),),
        ),
        clock=clock,
    )
    service.create_local_user(
        email="owner-a@ecos.local",
        display_name="Owner A",
        password="correct-password",
        organization_name="Org A",
        roles=(Role.ADMIN,),
        user_id=USER_A,
        organization_id=ORG_A,
    )
    service.create_local_user(
        email="viewer-b@ecos.local",
        display_name="Viewer B",
        password="correct-password",
        organization_name="Org B",
        roles=(Role.OPERATOR,),
        user_id=USER_B,
        organization_id=ORG_B,
    )
    return service


def login(service: SecurityService):
    return service.login(
        email="owner-a@ecos.local",
        password="correct-password",
        organization_id=ORG_A,
        correlation_id=CORRELATION_ID,
    )


def test_authentication_valid_password_and_role_authorized() -> None:
    service = make_security()

    token, principal = login(service)

    assert token
    assert principal.user_id == USER_A
    assert principal.organization_id == ORG_A
    assert Role.ADMIN in principal.roles
    service.authorize(principal, Permission.ADMINISTER_ORGANIZATION)


def test_authentication_rejects_bad_password_invalid_token_and_missing_credential() -> (
    None
):
    service = make_security()

    with pytest.raises(AuthenticationError):
        service.login(
            email="owner-a@ecos.local",
            password="wrong",
            organization_id=ORG_A,
            correlation_id=CORRELATION_ID,
        )
    with pytest.raises(AuthenticationError):
        service.authenticate_bearer_token("not-a-token", correlation_id=CORRELATION_ID)
    with pytest.raises(AuthenticationError):
        SecurityService(
            InMemorySecurityRepository(),
            token_secret=SECRET,
            issuer="test",
            audience="ecos",
            token_ttl=timedelta(minutes=15),
        ).login(
            email="missing@ecos.local",
            password="x",
            organization_id=ORG_A,
            correlation_id=CORRELATION_ID,
        )


def test_token_expires_and_revocation_is_rejected() -> None:
    service = make_security()
    token, principal = login(service)
    future_service = SecurityService(
        service._repository,
        token_secret=SECRET,
        issuer="test",
        audience="ecos",
        token_ttl=timedelta(minutes=15),
        clock=lambda: NOW + timedelta(hours=1),
    )

    with pytest.raises(AuthenticationError):
        future_service.authenticate_bearer_token(token, correlation_id=CORRELATION_ID)

    service.revoke_token(principal.token_id, correlation_id=CORRELATION_ID)
    with pytest.raises(AuthenticationError):
        service.authenticate_bearer_token(token, correlation_id=CORRELATION_ID)


def test_permission_insufficient_and_role_authorized() -> None:
    service = make_security()
    _, principal = service.login(
        email="viewer-b@ecos.local",
        password="correct-password",
        organization_id=ORG_B,
        correlation_id=CORRELATION_ID,
    )

    service.authorize(principal, Permission.READ_MEMORY)
    with pytest.raises(AuthorizationError):
        service.authorize(principal, Permission.ADMINISTER_ORGANIZATION)


def test_memory_isolation_and_payload_organization_override_is_ignored() -> None:
    service = make_security()
    _, principal = login(service)
    memory = TenantScopedMemoryService(MemoryService(FakeMemoryRepository()), service)
    requested_other_org = MemoryObject(
        organization_id=ORG_B,
        type=MemoryType.SEMANTIC,
        title="Scoped",
        description="Stored under authenticated organization.",
        source="test",
    )

    stored = memory.store(principal, requested_other_org)

    assert stored.organization_id == ORG_A
    assert memory.get(principal, stored.id) == stored
    assert memory.search(principal, "Scoped") == [stored]


def test_known_id_from_other_organization_is_rejected_for_memory_and_sessions() -> None:
    service = make_security()
    _, principal_a = login(service)
    _, principal_b = service.login(
        email="viewer-b@ecos.local",
        password="correct-password",
        organization_id=ORG_B,
        correlation_id=CORRELATION_ID,
    )
    memory_service = TenantScopedMemoryService(
        MemoryService(FakeMemoryRepository()),
        service,
    )
    memory_b = memory_service.store(
        principal_b,
        MemoryObject(
            type=MemoryType.SEMANTIC,
            title="Tenant B",
            description="Private",
            source="test",
        ),
    )

    with pytest.raises(CrossTenantAccessError):
        memory_service.get(principal_a, memory_b.id)

    session_service = TenantScopedSessionService(
        SessionService(FakeSessionRepository()),
        service,
    )
    session_b = managed_session(ORG_B)
    session_service.create_session(principal_b, session_b)
    with pytest.raises(CrossTenantAccessError):
        session_service.get_session(principal_a, session_b.session.id)


def test_knowledge_graph_events_and_observability_are_tenant_scoped() -> None:
    graph = InMemoryKnowledgeGraphRepository()
    graph.append_entity(knowledge_entity("project:a", ORG_A))
    graph.append_entity(knowledge_entity("project:b", ORG_B))
    assert [item.entity_id for item in graph.find_entities(ORG_A)] == ["project:a"]
    assert graph.get_entity(ORG_A, "project:b") is None

    store = InMemoryEventStore()
    store.append(event(EventType.SESSION_CREATED, ORG_A))
    store.append(event(EventType.SESSION_CREATED, ORG_B))
    assert store.count(EventQuery(organization_id=ORG_A)) == 1

    observability = InMemoryObservabilityRepository()
    metric = MetricRecord(
        metric_name="security.test",
        metric_type=MetricType.COUNTER,
        level="platform",
        organization_id=ORG_A,
        component="security",
        value=1,
        occurred_at=NOW,
        source_event_id=uuid4(),
    )
    observability.append_metric(metric)
    assert [item.organization_id for item in observability.metrics] == [ORG_A]


def test_governance_uses_security_identity_and_enforces_segregation_of_functions() -> (
    None
):
    repository = InMemorySecurityRepository()
    security = SecurityService(
        repository,
        token_secret=SECRET,
        issuer="test",
        audience="ecos",
        token_ttl=timedelta(minutes=15),
    )
    security.create_local_user(
        email="manager@ecos.local",
        display_name="Manager",
        password="pw",
        organization_name="Org A",
        roles=(Role.MANAGER,),
        user_id=USER_A,
        organization_id=ORG_A,
    )
    engine = GovernanceEngine(
        policy_provider=InMemoryPolicyProvider((approval_policy(),)),
        approval_policy_provider=DefaultApprovalPolicyProvider(GovernanceConfig()),
        event_service=EventService(FakeEventBus()),
        identity_port=SecurityIdentityPort(repository),
        clock=lambda: NOW,
        id_generator=uuid4,
        config=GovernanceConfig(),
    )
    result = engine.evaluate(governance_request(requester_id=USER_A))

    decision = ApprovalDecision(
        approval_decision_id=uuid4(),
        approval_request_id=result.approval_request.approval_request_id,
        organization_id=ORG_A,
        session_id=SESSION_A,
        plan_id=PLAN_ID,
        actor_id=USER_A,
        actor_role=Role.MANAGER.value,
        decision=HumanDecision.APPROVE,
        decided_at=NOW,
        identity_reference="local",
    )
    with pytest.raises(UnauthorizedRoleError):
        engine.record_decision(
            approval_request=result.approval_request,
            decision=decision,
        )


def test_execution_events_are_isolated_and_security_auditable() -> None:
    bus = FakeEventBus()
    audit_repo = InMemoryAuditRepository()
    store = InMemoryEventStore()
    service = EventService(
        bus,
        store,
        projectors=(
            AuditProjector(audit_repo),
            MetricProjector(InMemoryObservabilityRepository()),
        ),
    )
    service.publish(event(EventType.ACCESS_DENIED, ORG_A, payload={"token": "secret"}))

    audits = audit_repo.list_by_organization(ORG_A)
    assert audits[0].action == "access_denied"
    assert store.query(EventQuery(organization_id=ORG_A))[0].event.payload["token"] == (
        "[REDACTED]"
    )


def test_demo_identity_and_runtime_demo_contract() -> None:
    with TestClient(ContainerApp.app) as client:
        response = client.post(
            "/runtime/demo",
            json={"objective": "Improve organizational decision quality"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["recommendation"] == (
        "Proceed using ECOS context, reasoning, debate and governance."
    )
    assert response.json()["confidence"] == 0.91


def test_api_authentication_flow_and_401_403_contracts() -> None:
    with TestClient(ContainerApp.app) as client:
        container = ContainerApp.app.state.container
        admin = container.security_repository.get_user_by_email("admin@ecos.local")
        membership = next(
            item
            for item in container.security_repository._memberships.values()
            if item.user_id == admin.user_id
        )

        missing = client.get("/security/me")
        login_response = client.post(
            "/auth/login",
            json={
                "email": "admin@ecos.local",
                "password": "change-me-development-only",
                "organization_id": str(membership.organization_id),
            },
        )
        me = client.get(
            "/security/me",
            headers={
                "Authorization": f"Bearer {login_response.json()['access_token']}"
            },
        )

    assert missing.status_code == 401
    assert login_response.status_code == 200
    assert me.status_code == 200
    assert me.json()["organization_id"] == str(membership.organization_id)


def test_postgres_adapter_contracts_are_configurable() -> None:
    settings = Settings(
        security_repository="postgres",
        database_url="postgresql://ecos:ecos@localhost:5432/ecos",
    )

    assert settings.security_repository == "postgres"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    with pytest.raises(ValueError):
        PostgresSecurityRepository()
    assert SecurityUserRecord.__tablename__ == "security_users"
    assert SecurityOrganizationRecord.__tablename__ == "security_organizations"
    assert SecurityMembershipRecord.__tablename__ == "security_memberships"
    assert SecurityAuthSessionRecord.__tablename__ == "security_auth_sessions"


def managed_session(organization_id: UUID) -> ManagedSession:
    objective = Objective(organization_id=organization_id, title="Objective")
    session = CognitiveSession(
        organization_id=organization_id,
        objective=objective,
    )
    return ManagedSession(
        session=session,
        state=SessionState(
            session_id=session.id,
            lifecycle_status=SessionLifecycleStatus.CREATED,
            current_stage=SessionStage.CONTEXT,
        ),
        context=SessionContext(organization_id=organization_id, objective=objective),
    )


def knowledge_entity(entity_id: str, organization_id: UUID) -> KnowledgeEntity:
    return KnowledgeEntity(
        entity_id=entity_id,
        organization_id=organization_id,
        entity_type=KnowledgeEntityType.PROJECT,
        name=entity_id,
        confidence=0.8,
        importance=0.5,
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=UTC),
    )


def event(
    event_type: EventType,
    organization_id: UUID,
    *,
    payload: dict[str, object] | None = None,
) -> Event:
    return Event(
        event_type=event_type,
        source="security-test",
        organization_id=organization_id,
        session_id=SESSION_A,
        metadata=EventMetadata(correlation_id=CORRELATION_ID),
        payload={"organization_id": str(organization_id), **(payload or {})},
        created_at=NOW,
    )


def approval_policy() -> OrganizationalPolicy:
    return OrganizationalPolicy(
        policy_id="approval",
        organization_id=ORG_A,
        name="Approval",
        domain=PolicyDomain.GENERAL,
        version="1",
        status=PolicyStatus.ACTIVE,
        effective_from=NOW - timedelta(days=1),
        applicable_actions=(GovernanceActionType.CONTINUATION,),
        rules=(
            PolicyRule(
                rule_id="risk_low",
                operator=RuleOperator.EQUALS,
                field="risk_level",
                value=RiskLevel.LOW.value,
            ),
        ),
        required_approval_level=ApprovalLevel.LEVEL_2,
        required_roles=(Role.MANAGER.value,),
        minimum_approvals=1,
    )


def governance_request(*, requester_id: UUID) -> GovernanceRequest:
    plan = cognitive_plan()
    return GovernanceRequest(
        governance_id=uuid4(),
        organization_id=ORG_A,
        session_id=SESSION_A,
        plan_id=PLAN_ID,
        correlation_id=CORRELATION_ID,
        user_id=requester_id,
        actor_id=requester_id,
        cognitive_plan=plan,
        current_stage="governance",
        requested_action="continue",
        action_type=GovernanceActionType.CONTINUATION,
        recommendation={
            "objective": "Objective",
            "evidence": ("evidence",),
            "reasoning_summary": "summary",
            "assumptions": ("assumption",),
            "risks": ("risk",),
            "alternatives": ("alternative",),
            "confidence": 0.8,
            "missing_information": (),
            "recommendation": "continue",
        },
        risk_level=RiskLevel.LOW,
        impact_level=ImpactLevel.LOW,
        applicable_policy_ids=("approval",),
    )


def cognitive_plan() -> CognitivePlan:
    objective = Objective(organization_id=ORG_A, title="Objective")
    decision = PipelineStep(order=1, engine="decision")
    governance = PipelineStep(
        order=2,
        engine="governance",
        dependencies=(decision.stage_id,),
    )
    return CognitivePlan(
        plan_id=PLAN_ID,
        session_id=SESSION_A,
        organization_id=ORG_A,
        objective=objective,
        strategy=ExecutionStrategy(
            strategy=PlanningStrategy.BALANCED,
            rationale="test",
        ),
        selected_engines=(
            EngineSelection(engine="decision", reason="test"),
            EngineSelection(engine="governance", reason="test"),
        ),
        pipeline=Pipeline(steps=(decision, governance)),
        risk_level=RiskLevel.LOW,
    )


class ContainerApp:
    """Lazy import holder so TestClient uses the real app once per module."""

    from ecos.main import app

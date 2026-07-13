"""Deterministic operational workflow service for API, UI and E2E tests."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from ecos.events import Event, EventMetadata, EventPriority, EventService, EventType
from ecos.knowledge import (
    KnowledgeEntity,
    KnowledgeEntityType,
    KnowledgeRelationship,
    KnowledgeRelationshipType,
    SemanticQuery,
)
from ecos.knowledge.exceptions import ConflictingVersionError
from ecos.operational.exceptions import OperationalConflictError
from ecos.operational.models import (
    ApprovalStatus,
    ApprovalView,
    ExecutionStatus,
    ExecutionView,
    OperationalMetrics,
    OperationalSessionStatus,
    OperationalSessionView,
    OrganizationOverview,
    RecommendationView,
    TimelineEntry,
)
from ecos.operational.repository import (
    OperationalRepository,
    idempotency_record,
    payload_fingerprint,
)
from ecos.security import (
    AuthenticatedPrincipal,
    AuthenticationError,
    AuthorizationError,
    Permission,
    Role,
    SecurityRepository,
    SecurityService,
)

DEMO_ORG_A = UUID("10000000-0000-4000-8000-000000000001")
DEMO_ORG_B = UUID("20000000-0000-4000-8000-000000000002")
DEMO_OPERATOR = UUID("10000000-0000-4000-8000-000000000101")
DEMO_APPROVER = UUID("10000000-0000-4000-8000-000000000102")
DEMO_AUDITOR = UUID("10000000-0000-4000-8000-000000000103")
DEMO_ADMIN = UUID("10000000-0000-4000-8000-000000000104")
DEMO_TENANT_B_USER = UUID("20000000-0000-4000-8000-000000000201")


class OperationalService:
    """Application service for organization-scoped operational workflows."""

    def __init__(
        self,
        *,
        security_service: SecurityService,
        security_repository: SecurityRepository,
        event_service: EventService,
        knowledge_graph_service,
        repository: OperationalRepository,
        demo_seed_enabled: bool,
        environment: str,
        outbox_service: object | None = None,
        outbox_enabled: bool = False,
    ) -> None:
        self._security_service = security_service
        self._security_repository = security_repository
        self._event_service = event_service
        self._knowledge_graph_service = knowledge_graph_service
        self._repository = repository
        self._outbox_service = outbox_service
        self._outbox_enabled = outbox_enabled
        self._metrics = OperationalMetrics()
        self._idempotency_ttl = timedelta(hours=24)
        if demo_seed_enabled and environment.lower() not in {"production", "prod"}:
            self.seed_demo_data()

    def seed_demo_data(self) -> None:
        """Create explicit development/E2E demo users and graph records."""
        users = (
            (
                "operator@demo.ecos.local",
                "ECOS Demo Operator",
                "operator-demo-password",
                "ECOS Demo Organization",
                DEMO_ORG_A,
                DEMO_OPERATOR,
                (Role.OPERATOR,),
                (Permission.APPROVE_DECISION,),
            ),
            (
                "approver@demo.ecos.local",
                "ECOS Demo Approver",
                "approver-demo-password",
                "ECOS Demo Organization",
                DEMO_ORG_A,
                DEMO_APPROVER,
                (Role.MANAGER,),
                (),
            ),
            (
                "auditor@demo.ecos.local",
                "ECOS Demo Auditor",
                "auditor-demo-password",
                "ECOS Demo Organization",
                DEMO_ORG_A,
                DEMO_AUDITOR,
                (Role.AUDITOR,),
                (),
            ),
            (
                "admin@demo.ecos.local",
                "ECOS Demo Org Admin",
                "admin-demo-password",
                "ECOS Demo Organization",
                DEMO_ORG_A,
                DEMO_ADMIN,
                (Role.ADMIN,),
                (),
            ),
            (
                "operator@tenant-b.ecos.local",
                "Tenant B Operator",
                "tenant-b-demo-password",
                "ECOS Tenant B",
                DEMO_ORG_B,
                DEMO_TENANT_B_USER,
                (Role.OPERATOR,),
                (),
            ),
        )
        for (
            email,
            name,
            password,
            org_name,
            org_id,
            user_id,
            roles,
            permissions,
        ) in users:
            if self._security_repository.get_user_by_email(email) is None:
                self._security_service.create_local_user(
                    email=email,
                    display_name=name,
                    password=password,
                    organization_name=org_name,
                    roles=roles,
                    permissions=permissions,
                    user_id=user_id,
                    organization_id=org_id,
                )
        self._seed_knowledge(DEMO_ORG_A, "demo")
        self._seed_knowledge(DEMO_ORG_B, "tenant-b")

    def resolve_login_organization(self, email: str) -> UUID:
        """Resolve the single active organization for a browser login."""
        user = self._security_repository.get_user_by_email(email)
        if user is None:
            raise AuthenticationError("invalid credentials")
        memberships = [
            item
            for item in self._security_repository.list_memberships(user_id=user.user_id)
            if item.active
        ]
        if len(memberships) != 1:
            raise AuthenticationError("organization selection is required")
        return memberships[0].organization_id

    def organization(self, principal: AuthenticatedPrincipal) -> dict[str, str]:
        """Return the current organization from the authenticated principal."""
        org = self._security_repository.get_organization(principal.organization_id)
        return {
            "organization_id": str(principal.organization_id),
            "name": "Unknown organization" if org is None else org.name,
        }

    def overview(self, principal: AuthenticatedPrincipal) -> OrganizationOverview:
        """Build the organization dashboard."""
        self._security_service.authorize(principal, Permission.READ_SESSIONS)
        sessions = self._sessions_for(principal)
        completed = [item for item in sessions if item.status == "completed"]
        approvals = [
            item.approval
            for item in sessions
            if item.approval is not None
            and item.approval.status
            in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}
        ]
        approved_count = sum(
            1 for item in approvals if item.status == ApprovalStatus.APPROVED
        )
        executions = [item.execution for item in sessions if item.execution is not None]
        successful_executions = sum(
            1 for item in executions if item.status == ExecutionStatus.COMPLETED
        )
        recommendations = [
            item.recommendation for item in sessions if item.recommendation is not None
        ]
        return OrganizationOverview(
            organization=self.organization(principal),
            user=self._user_dict(principal.user_id),
            roles=tuple(role.value for role in principal.roles),
            permissions=tuple(permission.value for permission in principal.permissions),
            recent_sessions=tuple(
                sorted(sessions, key=lambda item: item.created_at)[-5:]
            ),
            sessions_by_status=dict(Counter(item.status.value for item in sessions)),
            pending_approvals=sum(
                1
                for item in sessions
                if item.approval is not None
                and item.approval.status == ApprovalStatus.PENDING
            ),
            running_executions=sum(
                1
                for item in executions
                if item.status in {ExecutionStatus.READY, ExecutionStatus.RUNNING}
            ),
            approval_rate=approved_count / len(approvals) if approvals else 0.0,
            execution_success_rate=(
                successful_executions / len(executions) if executions else 0.0
            ),
            average_recommendation_confidence=(
                sum(item.confidence for item in recommendations) / len(recommendations)
                if recommendations
                else 0.0
            ),
            recent_events=self._event_rows(principal.organization_id, limit=8),
            component_health=(
                {"component": "api", "status": "healthy"},
                {"component": "security", "status": "healthy"},
                {"component": "knowledge_graph", "status": "healthy"},
                {"component": "execution", "status": "dry_run"},
            ),
            observability={
                "stored_events": len(
                    self._event_rows(principal.organization_id, limit=100)
                ),
                "sessions_completed": len(completed),
                "metrics": self._metrics.model_dump(),
            },
        )

    def create_session(
        self,
        principal: AuthenticatedPrincipal,
        *,
        objective: str,
        description: str | None,
        correlation_id: UUID,
        idempotency_key: str | None = None,
    ) -> OperationalSessionView:
        """Create an organization-scoped operational session."""
        self._security_service.authorize(principal, Permission.WRITE_SESSIONS)
        cached = self._idempotency_hit(
            principal,
            "session.create",
            idempotency_key,
            {"objective": objective, "description": description},
        )
        if cached is not None:
            return OperationalSessionView.model_validate(cached)
        session = OperationalSessionView(
            organization_id=principal.organization_id,
            created_by=principal.user_id,
            created_by_email=self._user_email(principal.user_id),
            objective=objective,
            description=description,
            context={"objective": objective, "description": description},
            stages=(),
            correlation_id=correlation_id,
        )
        session = self._append(session, "session.created", "Session created", principal)
        self._save_with_events(
            session,
            expected_version=0,
            event_types=(EventType.SESSION_CREATED,),
            principal=principal,
        )
        self._metrics = self._metrics.model_copy(
            update={"sessions_started": self._metrics.sessions_started + 1}
        )
        self._store_idempotency(
            principal,
            "session.create",
            idempotency_key,
            {"objective": objective, "description": description},
            session.model_dump(mode="json"),
            session.session_id,
        )
        return session

    def list_sessions(
        self,
        principal: AuthenticatedPrincipal,
        *,
        status: str | None = None,
    ) -> list[OperationalSessionView]:
        """List sessions for the authenticated organization."""
        self._security_service.authorize(principal, Permission.READ_SESSIONS)
        return self._repository.list_sessions(principal.organization_id, status=status)

    def sara_interaction(
        self,
        principal: AuthenticatedPrincipal,
        *,
        message: str,
        history: tuple[dict[str, str], ...],
        session_id: UUID | None,
        route_context: str,
        correlation_id: UUID,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Attach presence input to a governed session without starting execution."""
        del history
        if session_id is None:
            session = self.create_session(
                principal,
                objective=message[:200],
                description=f"SARA presence interaction from {route_context}",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        else:
            session = self.get_session(principal, session_id)
            stored = self._repository.get_session(
                principal.organization_id, session.session_id
            )
            if stored is None:
                raise AuthorizationError("resource is not available")
            _, version = stored
            session = self._append(
                session,
                "sara.interaction.received",
                "SARA interaction received without storing message content",
                principal,
            )
            self._save_with_events(
                session,
                expected_version=version,
                event_types=(EventType.SESSION_UPDATED,),
                principal=principal,
            )
        state = session.status.value
        if state == OperationalSessionStatus.WAITING_APPROVAL.value:
            response = (
                "A sessão está aguardando aprovação humana. Posso abrir as "
                "aprovações, mas não aprová-las."
            )
            actions: tuple[dict[str, str], ...] = ({"type": "open_approvals"},)
        elif state == OperationalSessionStatus.EXECUTING.value:
            response = (
                "Acompanho uma execução aprovada registrada nesta sessão. "
                "Posso abrir a área de execuções."
            )
            actions = ({"type": "open_executions"},)
        else:
            response = (
                "Registrei sua entrada como objetivo de uma sessão cognitiva. "
                "A SARA não aprova decisões nem executa ações; abra a sessão "
                "para continuar pelo fluxo governado."
            )
            actions = ({"type": "open_session", "session_id": str(session.session_id)},)
        return {
            "response": response,
            "session_id": str(session.session_id),
            "cognitive_state": state,
            "ui_actions": actions,
            "unavailable": False,
            "incomplete_context": state == OperationalSessionStatus.CREATED.value,
        }

    def get_session(
        self, principal: AuthenticatedPrincipal, session_id: UUID
    ) -> OperationalSessionView:
        """Return one session or fail closed for cross-tenant IDs."""
        self._security_service.authorize(principal, Permission.READ_SESSIONS)
        result = self._repository.get_session(principal.organization_id, session_id)
        if result is None:
            self._metrics = self._metrics.model_copy(
                update={
                    "cross_tenant_attempts": self._metrics.cross_tenant_attempts + 1
                }
            )
            raise AuthorizationError("resource is not available")
        return result[0]

    def start_cognition(
        self,
        principal: AuthenticatedPrincipal,
        session_id: UUID,
        idempotency_key: str | None = None,
    ) -> OperationalSessionView:
        """Run the deterministic cognitive cycle up to human approval."""
        self._security_service.authorize(principal, Permission.CREATE_DECISION)
        cached = self._idempotency_hit(
            principal,
            "session.start",
            idempotency_key,
            {"session_id": str(session_id)},
        )
        if cached is not None:
            return OperationalSessionView.model_validate(cached)
        result = self._repository.get_session(principal.organization_id, session_id)
        if result is None:
            raise AuthorizationError("resource is not available")
        session, version = result
        if session.status not in {OperationalSessionStatus.CREATED}:
            return session
        stages = (
            "context",
            "planner",
            "reasoning",
            "specialists",
            "debate",
            "simulation",
            "decision",
            "governance",
        )
        recommendation = RecommendationView(
            session_id=session.session_id,
            summary="Proceed with a bounded dry-run execution after human approval.",
            confidence=0.91,
            risks=(
                "Execution remains blocked until independent approval.",
                "Dry-run connector must be used for demo and tests.",
            ),
            evidence=(
                "Unified context assembled from organization-scoped inputs.",
                "Deterministic reasoning, debate and simulation completed.",
            ),
            plan=(
                "Validate recommendation and risks.",
                "Collect independent human approval.",
                "Execute deterministic dry-run connector.",
                "Record observation and learning.",
            ),
            reasoning="The objective has sufficient local context for a safe dry-run.",
            debate=(
                "Specialist debate found no blocking conflict for dry-run execution."
            ),
            simulation=(
                "Worst-case impact is limited because no external effects occur."
            ),
            decision="Recommendation is advisory and requires human approval.",
        )
        approval = ApprovalView(
            organization_id=session.organization_id,
            session_id=session.session_id,
            recommendation_id=recommendation.recommendation_id,
            requester_id=session.created_by,
            requester_email=session.created_by_email,
            risks=recommendation.risks,
            plan=recommendation.plan,
            correlation_id=session.correlation_id,
        )
        execution = ExecutionView(
            organization_id=session.organization_id,
            session_id=session.session_id,
            approval_id=approval.approval_id,
            status=ExecutionStatus.BLOCKED,
            approved_plan=recommendation.plan,
            correlation_id=session.correlation_id,
        )
        updated = session.model_copy(
            update={
                "status": OperationalSessionStatus.WAITING_APPROVAL,
                "stages": stages,
                "context": {
                    **session.context,
                    "organization_id": str(session.organization_id),
                    "context_engine": "deterministic",
                    "missing_context": [],
                },
                "recommendation": recommendation,
                "approval": approval,
                "execution": execution,
                "updated_at": _now(),
            }
        )
        for stage in stages:
            updated = self._append(
                updated,
                f"{stage}.completed",
                f"{stage} completed",
                principal,
            )
        updated = self._append(
            updated,
            "approval.requested",
            "Independent approval requested",
            principal,
        )
        self._save_with_events(
            updated,
            expected_version=version,
            event_types=(
                EventType.RECOMMENDATION_CREATED,
                EventType.APPROVAL_REQUESTED,
            ),
            principal=principal,
        )
        self._store_idempotency(
            principal,
            "session.start",
            idempotency_key,
            {"session_id": str(session_id)},
            updated.model_dump(mode="json"),
            updated.session_id,
        )
        return updated

    def list_approvals(
        self,
        principal: AuthenticatedPrincipal,
        *,
        status: str | None = None,
    ) -> list[ApprovalView]:
        """List approval requests visible to the authenticated organization."""
        self._security_service.authorize(principal, Permission.READ_SESSIONS)
        approvals = [
            item.approval for item in self._sessions_for(principal) if item.approval
        ]
        values = [item for item in approvals if item is not None]
        if status:
            values = [item for item in values if item.status.value == status]
        return sorted(values, key=lambda item: item.created_at, reverse=True)

    def decide_approval(
        self,
        principal: AuthenticatedPrincipal,
        approval_id: UUID,
        *,
        approve: bool,
        reason: str | None,
        idempotency_key: str | None = None,
    ) -> ApprovalView:
        """Approve or reject a recommendation with SoD enforcement."""
        self._security_service.authorize(principal, Permission.APPROVE_DECISION)
        operation = "approval.approve" if approve else "approval.reject"
        cached = self._idempotency_hit(
            principal,
            operation,
            idempotency_key,
            {"approval_id": str(approval_id), "reason": reason},
        )
        if cached is not None:
            return ApprovalView.model_validate(cached)
        session, version = self._find_by_approval_with_version(principal, approval_id)
        approval = session.approval
        if approval is None:
            raise AuthorizationError("approval is not available")
        if approval.status != ApprovalStatus.PENDING:
            raise OperationalConflictError("approval has already been decided")
        if approval.requester_id == principal.user_id:
            raise AuthorizationError("requester cannot approve this recommendation")
        if not approve and not reason:
            raise ValueError("rejection reason is required")
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        decided = approval.model_copy(
            update={
                "status": status,
                "decided_by": principal.user_id,
                "decided_by_email": self._user_email(principal.user_id),
                "decided_at": _now(),
                "rejection_reason": reason,
            }
        )
        execution = session.execution
        if execution is not None and approve:
            execution = execution.model_copy(update={"status": ExecutionStatus.READY})
        session_status = (
            OperationalSessionStatus.APPROVED
            if approve
            else OperationalSessionStatus.REJECTED
        )
        updated = session.model_copy(
            update={
                "status": session_status,
                "approval": decided,
                "execution": execution,
                "updated_at": _now(),
            }
        )
        updated = self._append(
            updated,
            "approval.approved" if approve else "approval.rejected",
            "Recommendation approved" if approve else "Recommendation rejected",
            principal,
        )
        approval_event = (
            EventType.APPROVAL_GRANTED if approve else EventType.APPROVAL_REJECTED
        )
        self._save_with_events(
            updated,
            expected_version=version,
            event_types=(approval_event,),
            principal=principal,
        )
        self._metrics = self._metrics.model_copy(
            update={
                "approvals": self._metrics.approvals + (1 if approve else 0),
                "rejections": self._metrics.rejections + (0 if approve else 1),
            }
        )
        self._store_idempotency(
            principal,
            operation,
            idempotency_key,
            {"approval_id": str(approval_id), "reason": reason},
            decided.model_dump(mode="json"),
            approval_id,
        )
        return decided

    def list_executions(self, principal: AuthenticatedPrincipal) -> list[ExecutionView]:
        """List execution records for the authenticated organization."""
        self._security_service.authorize(principal, Permission.READ_SESSIONS)
        return [
            item.execution
            for item in self._sessions_for(principal)
            if item.execution is not None
        ]

    def start_execution(
        self,
        principal: AuthenticatedPrincipal,
        execution_id: UUID,
        idempotency_key: str | None = None,
    ) -> ExecutionView:
        """Execute only an explicitly approved dry-run plan."""
        self._security_service.authorize(principal, Permission.EXECUTE_ACTION)
        cached = self._idempotency_hit(
            principal,
            "execution.start",
            idempotency_key,
            {"execution_id": str(execution_id)},
        )
        if cached is not None:
            return ExecutionView.model_validate(cached)
        session, version = self._find_by_execution_with_version(principal, execution_id)
        execution = session.execution
        if execution is None:
            raise AuthorizationError("execution is not available")
        if (
            session.approval is None
            or session.approval.status != ApprovalStatus.APPROVED
        ):
            raise AuthorizationError("execution requires explicit approval")
        if execution.status == ExecutionStatus.COMPLETED:
            raise OperationalConflictError("execution has already completed")
        if execution.status == ExecutionStatus.RUNNING:
            raise OperationalConflictError("execution is already running")
        running = execution.model_copy(
            update={
                "status": ExecutionStatus.RUNNING,
                "attempts": execution.attempts + 1,
            }
        )
        completed = running.model_copy(
            update={
                "status": ExecutionStatus.COMPLETED,
                "result": "Dry-run connector completed without external effects.",
                "observations": (
                    "Execution result observed from deterministic connector output.",
                ),
                "feedback": ("No external side effects were produced.",),
                "learning": (
                    "Approved dry-run execution can be used as a safe validation path.",
                ),
                "updated_at": _now(),
            }
        )
        updated = session.model_copy(
            update={
                "status": OperationalSessionStatus.COMPLETED,
                "execution": completed,
                "updated_at": _now(),
            }
        )
        for event_type, message in (
            ("execution.started", "Approved dry-run execution started"),
            ("execution.completed", "Approved dry-run execution completed"),
            ("observation.completed", "Execution observation recorded"),
            ("learning.completed", "Learning record validated"),
        ):
            updated = self._append(updated, event_type, message, principal)
        self._save_with_events(
            updated,
            expected_version=version,
            event_types=(
                EventType.EXECUTION_COMPLETED,
                EventType.OBSERVATION_COMPLETED,
                EventType.LEARNING_COMPLETED,
            ),
            principal=principal,
        )
        self._metrics = self._metrics.model_copy(
            update={
                "executions": self._metrics.executions + 1,
                "sessions_completed": self._metrics.sessions_completed + 1,
            }
        )
        self._store_idempotency(
            principal,
            "execution.start",
            idempotency_key,
            {"execution_id": str(execution_id)},
            completed.model_dump(mode="json"),
            execution_id,
        )
        return completed

    def reconcile(self, principal: AuthenticatedPrincipal) -> dict[str, object]:
        """Reconcile interrupted operational flows without auto-approval/execution."""
        self._security_service.authorize(principal, Permission.ADMINISTER_ORGANIZATION)
        sessions = self._repository.interrupted_sessions(principal.organization_id)
        recovered = 0
        failed = 0
        for session in sessions:
            result = self._repository.get_session(
                principal.organization_id, session.session_id
            )
            if result is None:
                continue
            current, version = result
            if current.status in {
                OperationalSessionStatus.PROCESSING,
                OperationalSessionStatus.EXECUTING,
            }:
                current = self._append(
                    current,
                    "reconciliation.failed",
                    "Interrupted operation requires manual review",
                    principal,
                ).model_copy(update={"status": OperationalSessionStatus.FAILED})
                failed += 1
            else:
                current = self._append(
                    current,
                    "reconciliation.checked",
                    "Persisted state is safe to resume manually",
                    principal,
                )
                recovered += 1
            self._save_with_events(
                current,
                expected_version=version,
                event_types=(EventType.OBSERVABILITY_RECOVERED,),
                principal=principal,
            )
        return {"checked": len(sessions), "recovered": recovered, "failed": failed}

    def search_knowledge(
        self, principal: AuthenticatedPrincipal, query: str
    ) -> list[dict[str, object]]:
        """Search the organization-scoped Knowledge Graph."""
        self._security_service.authorize(principal, Permission.READ_KNOWLEDGE_GRAPH)
        results = self._knowledge_graph_service.search(
            SemanticQuery(
                organization_id=principal.organization_id,
                text=query,
                max_results=25,
            )
        )
        return [
            {
                "entity_id": item.entity.entity_id,
                "name": item.entity.name,
                "type": item.entity.entity_type.value,
                "score": item.semantic_score,
                "confidence": item.entity.confidence,
                "importance": item.entity.importance,
                "version": item.entity.version,
                "source": tuple(item.entity.source_references),
            }
            for item in results
        ]

    def get_entity(
        self, principal: AuthenticatedPrincipal, entity_id: str
    ) -> dict[str, object]:
        """Return one graph entity and bounded relationship chains."""
        self._security_service.authorize(principal, Permission.READ_KNOWLEDGE_GRAPH)
        entity = self._knowledge_graph_service._repository.get_entity(
            principal.organization_id, entity_id
        )
        if entity is None:
            raise AuthorizationError("resource is not available")
        neighbors = self._knowledge_graph_service.neighbors(
            principal.organization_id, entity_id
        )
        return {
            "entity": entity.model_dump(mode="json"),
            "relationships": [item.model_dump(mode="json") for item in neighbors],
            "dependency_chain": [
                item.model_dump(mode="json")
                for item in self._knowledge_graph_service.dependency_chain(
                    principal.organization_id, entity_id
                )
            ],
            "impact_chain": [
                item.model_dump(mode="json")
                for item in self._knowledge_graph_service.impact_chain(
                    principal.organization_id, entity_id
                )
            ],
        }

    def events(
        self,
        principal: AuthenticatedPrincipal,
        *,
        limit: int = 100,
        session_id: UUID | None = None,
        event_type: str | None = None,
        correlation_id: UUID | None = None,
    ) -> list[dict[str, object]]:
        """List safe events from the append-only event store."""
        self._security_service.authorize(principal, Permission.READ_EVENTS)
        return self._event_rows(
            principal.organization_id,
            limit=limit,
            session_id=session_id,
            event_type=event_type,
            correlation_id=correlation_id,
        )

    def _event_rows(
        self,
        organization_id: UUID,
        *,
        limit: int,
        session_id: UUID | None = None,
        event_type: str | None = None,
        correlation_id: UUID | None = None,
    ) -> list[dict[str, object]]:
        from ecos.observability.models import EventQuery

        events = self._event_service._event_store.query(
            EventQuery(
                organization_id=organization_id,
                session_id=session_id,
                correlation_id=correlation_id,
                event_types=() if event_type is None else (event_type,),
                limit=limit,
            )
        )
        return [
            {
                "sequence": item.stored_sequence,
                "event_id": str(item.event.event_id),
                "event_type": item.event.event_type.value,
                "category": item.event.category.value,
                "source": item.event.source_component,
                "session_id": None
                if item.event.session_id is None
                else str(item.event.session_id),
                "correlation_id": None
                if item.event.correlation_id is None
                else str(item.event.correlation_id),
                "occurred_at": item.event.occurred_at.isoformat(),
                "payload": item.event.payload,
            }
            for item in events
        ]

    def members(self, principal: AuthenticatedPrincipal) -> list[dict[str, object]]:
        """List organization members for authorized org admins."""
        self._security_service.authorize(principal, Permission.ADMINISTER_ORGANIZATION)
        return [
            {
                "user": self._user_dict(item.user_id),
                "roles": tuple(role.value for role in item.roles),
                "permissions": tuple(
                    permission.value for permission in item.effective_permissions
                ),
                "active": item.active,
            }
            for item in self._security_repository.list_memberships(
                organization_id=principal.organization_id
            )
        ]

    def metrics(self) -> OperationalMetrics:
        """Return current operational counters."""
        if self._outbox_service is None:
            return self._metrics
        repository = getattr(self._outbox_service, "repository", None)
        counts = repository.counts() if repository is not None else {}
        return self._metrics.model_copy(
            update={
                "outbox_pending": counts.get("pending", 0)
                + counts.get("processing", 0),
                "outbox_delivered": counts.get("delivered", 0),
                "outbox_failed": counts.get("failed", 0),
            }
        )

    def record_request(self, *, duration: float, errored: bool) -> None:
        """Record request counters without personal data labels."""
        self._metrics = self._metrics.model_copy(
            update={
                "requests_total": self._metrics.requests_total + 1,
                "errors_total": self._metrics.errors_total + (1 if errored else 0),
                "latency_seconds_total": self._metrics.latency_seconds_total
                + max(duration, 0.0),
            }
        )

    def record_access_denied(self) -> None:
        """Record an authorization failure."""
        self._metrics = self._metrics.model_copy(
            update={"access_denied": self._metrics.access_denied + 1}
        )

    def record_login_throttled(self) -> None:
        self._metrics = self._metrics.model_copy(
            update={"login_throttled": self._metrics.login_throttled + 1}
        )

    def record_login_blocked(self) -> None:
        self._metrics = self._metrics.model_copy(
            update={"login_blocked": self._metrics.login_blocked + 1}
        )

    def record_rate_limit_hit(self) -> None:
        self._metrics = self._metrics.model_copy(
            update={"rate_limit_hits": self._metrics.rate_limit_hits + 1}
        )

    def record_jwt_validation_failure(self) -> None:
        self._metrics = self._metrics.model_copy(
            update={
                "jwt_validation_failures": self._metrics.jwt_validation_failures + 1
            }
        )

    def record_revoked_session(self) -> None:
        self._metrics = self._metrics.model_copy(
            update={"revoked_sessions": self._metrics.revoked_sessions + 1}
        )

    def _sessions_for(
        self, principal: AuthenticatedPrincipal
    ) -> list[OperationalSessionView]:
        return self._repository.list_sessions(principal.organization_id)

    def _find_by_approval(
        self, principal: AuthenticatedPrincipal, approval_id: UUID
    ) -> OperationalSessionView:
        result = self._repository.find_by_approval(
            principal.organization_id, approval_id
        )
        if result is not None:
            return result[0]
        raise AuthorizationError("resource is not available")

    def _find_by_approval_with_version(
        self, principal: AuthenticatedPrincipal, approval_id: UUID
    ) -> tuple[OperationalSessionView, int]:
        result = self._repository.find_by_approval(
            principal.organization_id, approval_id
        )
        if result is not None:
            return result
        raise AuthorizationError("resource is not available")

    def _find_by_execution(
        self, principal: AuthenticatedPrincipal, execution_id: UUID
    ) -> OperationalSessionView:
        result = self._repository.find_by_execution(
            principal.organization_id, execution_id
        )
        if result is not None:
            return result[0]
        raise AuthorizationError("resource is not available")

    def _find_by_execution_with_version(
        self, principal: AuthenticatedPrincipal, execution_id: UUID
    ) -> tuple[OperationalSessionView, int]:
        result = self._repository.find_by_execution(
            principal.organization_id, execution_id
        )
        if result is not None:
            return result
        raise AuthorizationError("resource is not available")

    def _idempotency_hit(
        self,
        principal: AuthenticatedPrincipal,
        operation: str,
        key: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not key:
            return None
        record = self._repository.get_idempotency(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            operation=operation,
            key=key,
        )
        if record is None:
            return None
        if record.request_hash != payload_fingerprint(payload):
            from ecos.operational.exceptions import IdempotencyConflictError

            raise IdempotencyConflictError()
        return record.response_payload

    def _store_idempotency(
        self,
        principal: AuthenticatedPrincipal,
        operation: str,
        key: str | None,
        payload: dict[str, Any],
        response_payload: dict[str, Any],
        resource_id: UUID | None,
    ) -> None:
        if not key:
            return
        self._repository.store_idempotency(
            idempotency_record(
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                operation=operation,
                key=key,
                request_hash=payload_fingerprint(payload),
                response_payload=response_payload,
                resource_id=resource_id,
                ttl=self._idempotency_ttl,
            )
        )

    def _append(
        self,
        session: OperationalSessionView,
        event_type: str,
        message: str,
        principal: AuthenticatedPrincipal,
    ) -> OperationalSessionView:
        entry = TimelineEntry(
            sequence=len(session.timeline) + 1,
            event_type=event_type,
            message=message,
            actor_id=principal.user_id,
            correlation_id=session.correlation_id,
        )
        return session.model_copy(
            update={"timeline": (*session.timeline, entry), "updated_at": _now()}
        )

    def _save_with_events(
        self,
        session: OperationalSessionView,
        *,
        expected_version: int | None,
        event_types: tuple[EventType, ...],
        principal: AuthenticatedPrincipal,
    ) -> None:
        events = tuple(
            self._event(event_type, session, principal) for event_type in event_types
        )
        if self._outbox_enabled and self._repository.supports_transactional_outbox:
            self._repository.save_session_with_events(
                session,
                expected_version=expected_version,
                events=events,
                actor_id=principal.user_id,
            )
            if self._outbox_service is not None:
                process_once = getattr(self._outbox_service, "process_once", None)
                if callable(process_once):
                    process_once()
            return
        self._repository.save_session(session, expected_version=expected_version)
        for event in events:
            envelope = self._event_service.publish(event)
            self._event_service.dispatch(envelope)

    def _publish(
        self,
        event_type: EventType,
        session: OperationalSessionView,
        principal: AuthenticatedPrincipal,
    ) -> None:
        envelope = self._event_service.publish(
            self._event(event_type, session, principal)
        )
        self._event_service.dispatch(envelope)

    @staticmethod
    def _event(
        event_type: EventType,
        session: OperationalSessionView,
        principal: AuthenticatedPrincipal,
    ) -> Event:
        return Event(
            event_type=event_type,
            source="operational_api",
            organization_id=session.organization_id,
            session_id=session.session_id,
            actor_reference=str(principal.user_id),
            payload={
                "organization_id": str(session.organization_id),
                "session_id": str(session.session_id),
                "status": session.status.value,
            },
            metadata=EventMetadata(correlation_id=session.correlation_id),
            priority=EventPriority.NORMAL,
        )

    def _seed_knowledge(self, organization_id: UUID, prefix: str) -> None:
        base = [
            KnowledgeEntity(
                entity_id=f"{prefix}:objective:ops",
                organization_id=organization_id,
                entity_type=KnowledgeEntityType.OBJECTIVE,
                name="Improve operational validation",
                description="Demo objective for operational E2E validation.",
                confidence=0.9,
                importance=0.8,
                source_references=("demo_seed",),
            ),
            KnowledgeEntity(
                entity_id=f"{prefix}:system:execution",
                organization_id=organization_id,
                entity_type=KnowledgeEntityType.SYSTEM,
                name="Deterministic execution connector",
                description="Dry-run connector with no external effects.",
                confidence=0.95,
                importance=0.7,
                source_references=("demo_seed",),
            ),
            KnowledgeEntity(
                entity_id=f"{prefix}:risk:approval",
                organization_id=organization_id,
                entity_type=KnowledgeEntityType.RISK,
                name="Approval independence risk",
                description="Requester must not approve their own recommendation.",
                confidence=0.92,
                importance=0.9,
                source_references=("demo_seed",),
            ),
        ]
        for entity in base:
            if (
                self._knowledge_graph_service._repository.get_entity(
                    organization_id, entity.entity_id
                )
                is None
            ):
                try:
                    self._knowledge_graph_service._repository.append_entity(entity)
                except ConflictingVersionError:
                    pass
        relationships = (
            KnowledgeRelationship(
                relationship_id=f"{prefix}:rel:objective-uses-execution",
                organization_id=organization_id,
                source_entity_id=f"{prefix}:objective:ops",
                target_entity_id=f"{prefix}:system:execution",
                relationship_type=KnowledgeRelationshipType.USES,
                confidence=0.9,
                source_references=("demo_seed",),
            ),
            KnowledgeRelationship(
                relationship_id=f"{prefix}:rel:risk-affects-objective",
                organization_id=organization_id,
                source_entity_id=f"{prefix}:risk:approval",
                target_entity_id=f"{prefix}:objective:ops",
                relationship_type=KnowledgeRelationshipType.AFFECTS,
                confidence=0.9,
                source_references=("demo_seed",),
            ),
        )
        for relationship in relationships:
            if (
                self._knowledge_graph_service._repository.get_relationship(
                    organization_id, relationship.relationship_id
                )
                is None
            ):
                try:
                    self._knowledge_graph_service._repository.append_relationship(
                        relationship
                    )
                except ConflictingVersionError:
                    pass

    def _user_email(self, user_id: UUID) -> str:
        user = self._security_repository.get_user(user_id)
        return "unknown@ecos.local" if user is None else user.email

    def _user_dict(self, user_id: UUID) -> dict[str, str]:
        user = self._security_repository.get_user(user_id)
        return {
            "user_id": str(user_id),
            "email": "unknown@ecos.local" if user is None else user.email,
            "display_name": "Unknown user" if user is None else user.display_name,
        }


def _now() -> datetime:
    return datetime.now(UTC)

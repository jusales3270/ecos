"""Versioned operational API routes."""

from __future__ import annotations

import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ecos.core import Container, settings
from ecos.operational import OperationalService
from ecos.security import (
    AuthenticatedPrincipal,
    AuthenticationError,
    AuthorizationError,
    Permission,
    Role,
    SecurityContext,
)

router = APIRouter(prefix="/api/v1")


class WebLoginRequest(BaseModel):
    """Browser login request."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=500)


class SessionCreateRequest(BaseModel):
    """Create a cognitive operational session."""

    objective: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    organization_id: UUID | None = Field(
        default=None,
        description="Ignored; organization comes from authenticated principal.",
    )


class ApprovalDecisionRequest(BaseModel):
    """Human approval decision body."""

    reason: str | None = Field(default=None, max_length=1000)


def container(request: Request) -> Container:
    """Return the application container."""
    return request.app.state.container


def operational(
    container_: Annotated[Container, Depends(container)],
) -> OperationalService:
    """Return the operational service."""
    return container_.operational_service


def principal(request: Request) -> AuthenticatedPrincipal:
    """Require an authenticated principal."""
    context = getattr(request.state, "security_context", None)
    if not isinstance(context, SecurityContext):
        raise AuthenticationError("authentication required")
    return context.principal


def mutable_principal(request: Request) -> AuthenticatedPrincipal:
    """Require auth and CSRF for cookie-authenticated mutations."""
    value = principal(request)
    if getattr(request.state, "auth_via_cookie", False):
        csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
        csrf_header = request.headers.get(settings.csrf_header_name)
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            raise AuthenticationError("csrf validation failed")
    return value


@router.post("/auth/login")
def web_login(
    payload: WebLoginRequest,
    request: Request,
    response: Response,
    container_: Annotated[Container, Depends(container)],
    ops: Annotated[OperationalService, Depends(operational)],
) -> dict[str, Any]:
    """Authenticate browser clients using HttpOnly cookie sessions."""
    organization_id = ops.resolve_login_organization(payload.email)
    token, principal_ = container_.security_service.login(
        email=payload.email,
        password=payload.password,
        organization_id=organization_id,
        correlation_id=request.state.correlation_id_uuid,
    )
    secure = settings.environment.lower() not in {"development", "local", "test"}
    same_site = "strict" if secure else "lax"
    response.set_cookie(
        settings.web_cookie_name,
        token,
        httponly=True,
        secure=secure,
        samesite=same_site,
        max_age=settings.auth_token_ttl_minutes * 60,
        path="/",
    )
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        httponly=False,
        secure=secure,
        samesite=same_site,
        max_age=settings.auth_token_ttl_minutes * 60,
        path="/",
    )
    return {
        "principal": _principal_payload(principal_),
        "organization": ops.organization(principal_),
        "csrf_token": csrf,
        "demo": settings.demo_seed_enabled,
    }


@router.post("/auth/logout")
def logout(
    response: Response,
    principal_: Annotated[AuthenticatedPrincipal, Depends(mutable_principal)],
    container_: Annotated[Container, Depends(container)],
) -> dict[str, str]:
    """Revoke the current auth session and clear browser cookies."""
    if principal_.token_id is not None:
        container_.security_service.revoke_token(
            principal_.token_id,
            correlation_id=principal_.correlation_id,
        )
    response.delete_cookie(settings.web_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"status": "logged_out"}


@router.get("/auth/me")
def current_principal(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
) -> dict[str, Any]:
    """Return the current browser principal."""
    return {
        "principal": _principal_payload(principal_),
        "organization": ops.organization(principal_),
        "demo": settings.demo_seed_enabled,
    }


@router.get("/organization")
def organization_view(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
) -> dict[str, str]:
    return ops.organization(principal_)


@router.get("/overview")
def overview(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.overview(principal_)


@router.get("/sessions")
def sessions(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
    status: str | None = None,
):
    return ops.list_sessions(principal_, status=status)


@router.post("/sessions")
def create_session(
    payload: SessionCreateRequest,
    request: Request,
    principal_: Annotated[AuthenticatedPrincipal, Depends(mutable_principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.create_session(
        principal_,
        objective=payload.objective,
        description=payload.description,
        correlation_id=request.state.correlation_id_uuid,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


@router.get("/sessions/{session_id}")
def session_detail(
    session_id: UUID,
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.get_session(principal_, session_id)


@router.post("/sessions/{session_id}/start")
def start_cognition(
    session_id: UUID,
    request: Request,
    principal_: Annotated[AuthenticatedPrincipal, Depends(mutable_principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.start_cognition(
        principal_,
        session_id,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


@router.get("/recommendations/{session_id}")
def recommendation(
    session_id: UUID,
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    session = ops.get_session(principal_, session_id)
    if session.recommendation is None:
        raise AuthorizationError("resource is not available")
    return session.recommendation


@router.get("/approvals")
def approvals(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
    status: str | None = None,
):
    return ops.list_approvals(principal_, status=status)


@router.post("/approvals/{approval_id}/approve")
def approve(
    approval_id: UUID,
    request: Request,
    principal_: Annotated[AuthenticatedPrincipal, Depends(mutable_principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.decide_approval(
        principal_,
        approval_id,
        approve=True,
        reason=None,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


@router.post("/approvals/{approval_id}/reject")
def reject(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    request: Request,
    principal_: Annotated[AuthenticatedPrincipal, Depends(mutable_principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.decide_approval(
        principal_,
        approval_id,
        approve=False,
        reason=payload.reason,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


@router.get("/executions")
def executions(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.list_executions(principal_)


@router.post("/executions/{execution_id}/start")
def start_execution(
    execution_id: UUID,
    request: Request,
    principal_: Annotated[AuthenticatedPrincipal, Depends(mutable_principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.start_execution(
        principal_,
        execution_id,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


@router.get("/observations")
def observations(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    principal_.require_permission(Permission.READ_OBSERVATION)
    return [
        item.execution
        for item in ops.list_sessions(principal_)
        if item.execution is not None and item.execution.observations
    ]


@router.get("/learning")
def learning(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    principal_.require_permission(Permission.READ_LEARNING)
    return [
        item.execution
        for item in ops.list_sessions(principal_)
        if item.execution is not None and item.execution.learning
    ]


@router.get("/knowledge/search")
def knowledge_search(
    q: str,
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.search_knowledge(principal_, q)


@router.get("/knowledge/entities/{entity_id}")
def knowledge_entity(
    entity_id: str,
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.get_entity(principal_, entity_id)


@router.get("/events")
def events(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
    limit: int = 100,
    type: str | None = None,
    session_id: UUID | None = None,
    correlation_id: UUID | None = None,
):
    return ops.events(
        principal_,
        limit=min(max(limit, 1), 1000),
        event_type=type,
        session_id=session_id,
        correlation_id=correlation_id,
    )


@router.get("/audit")
def audit(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
    session_id: UUID | None = None,
):
    principal_.require_permission(Permission.READ_AUDIT)
    return ops.events(principal_, session_id=session_id, limit=500)


@router.get("/metrics")
def api_metrics(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    principal_.require_permission(Permission.READ_EVENTS)
    return ops.metrics()


@router.get("/health/components")
def component_health(container_: Annotated[Container, Depends(container)]):
    return container_.health()


@router.get("/admin/members")
def members(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.members(principal_)


@router.get("/admin/roles")
def roles(principal_: Annotated[AuthenticatedPrincipal, Depends(principal)]):
    principal_.require_permission(Permission.ADMINISTER_ORGANIZATION)
    return [role.value for role in Role if role is not Role.GLOBAL_ADMIN]


@router.get("/admin/permissions")
def permissions(principal_: Annotated[AuthenticatedPrincipal, Depends(principal)]):
    principal_.require_permission(Permission.ADMINISTER_ORGANIZATION)
    return [permission.value for permission in Permission]


@router.get("/admin/settings")
def organization_settings(
    principal_: Annotated[AuthenticatedPrincipal, Depends(principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    principal_.require_permission(Permission.READ_ORG_SETTINGS)
    return {
        "organization": ops.organization(principal_),
        "demo_seed_enabled": settings.demo_seed_enabled,
        "execution_mode": "dry_run",
        "global_admin_available_here": False,
    }


@router.post("/admin/reconcile")
def reconcile(
    principal_: Annotated[AuthenticatedPrincipal, Depends(mutable_principal)],
    ops: Annotated[OperationalService, Depends(operational)],
):
    return ops.reconcile(principal_)


def _principal_payload(principal_: AuthenticatedPrincipal) -> dict[str, Any]:
    return {
        "user_id": str(principal_.user_id),
        "organization_id": str(principal_.organization_id),
        "roles": [role.value for role in principal_.roles],
        "permissions": [permission.value for permission in principal_.permissions],
        "authentication_method": principal_.authentication_method.value,
        "session_id": None
        if principal_.session_id is None
        else str(principal_.session_id),
        "token_id": None if principal_.token_id is None else str(principal_.token_id),
        "issued_at": principal_.issued_at.isoformat(),
        "expires_at": principal_.expires_at.isoformat(),
        "correlation_id": str(principal_.correlation_id),
    }

"""FastAPI application entrypoint for the ECOS backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ecos.api import router as api_v1_router
from ecos.core import (
    Container,
    EcosError,
    configure_logging,
    set_correlation_id,
    settings,
)
from ecos.runtime import RuntimeEngine
from ecos.security import (
    AuthenticatedPrincipal,
    AuthenticationError,
    AuthorizationError,
    SecurityContext,
)


class RuntimeDemoRequest(BaseModel):
    """Request body for the runtime demo endpoint."""

    objective: str = Field(
        min_length=1,
        description="Objective to process through the fake cognitive pipeline.",
    )


class RuntimeDemoResponse(BaseModel):
    """Response body for the runtime demo endpoint."""

    session_id: str = Field(description="Cognitive session identifier.")
    status: str = Field(description="Final runtime status.")
    recommendation: str = Field(description="Deterministic recommendation summary.")
    confidence: float = Field(ge=0.0, le=1.0, description="Final confidence.")


class LoginRequest(BaseModel):
    """Local deterministic authentication request."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=500)
    organization_id: UUID


class LoginResponse(BaseModel):
    """Bearer token response without echoing credentials."""

    access_token: str
    token_type: str = "bearer"
    expires_at: str


class PrincipalResponse(BaseModel):
    """Safe authenticated principal view."""

    user_id: UUID
    organization_id: UUID
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    authentication_method: str
    session_id: UUID | None
    token_id: UUID | None
    issued_at: str
    expires_at: str
    correlation_id: UUID


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize application dependencies at startup."""
    configure_logging(settings)
    app.state.container = Container(settings=settings)
    yield


app = FastAPI(title="ECOS Backend", version=settings.version, lifespan=lifespan)
app.include_router(api_v1_router)


@app.exception_handler(EcosError)
async def ecos_error_handler(request: Request, exc: EcosError) -> JSONResponse:
    """Return standardized responses for ECOS domain/application errors."""
    del request
    status_code = 409 if "CONFLICT" in exc.code else 400
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    """Return standardized 401 authentication errors."""
    del request
    return JSONResponse(
        status_code=401,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(AuthorizationError)
async def authorization_error_handler(
    request: Request, exc: AuthorizationError
) -> JSONResponse:
    """Return standardized 403 authorization errors."""
    if hasattr(request.app.state, "container"):
        request.app.state.container.operational_service.record_access_denied()
    return JSONResponse(
        status_code=403,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
    )


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next: Any) -> Any:
    """Attach a correlation ID to each request."""
    correlation_id = set_correlation_id(
        request.headers.get(settings.correlation_id_header)
    )
    request.state.correlation_id_uuid = _correlation_uuid(correlation_id)
    response = await call_next(request)
    response.headers[settings.correlation_id_header] = correlation_id
    return response


@app.middleware("http")
async def metrics_middleware(request: Request, call_next: Any) -> Response:
    """Collect basic request counters without personal labels."""
    started = perf_counter()
    errored = False
    try:
        response: Response = await call_next(request)
        errored = response.status_code >= 500
        return response
    except Exception:
        errored = True
        raise
    finally:
        if hasattr(request.app.state, "container"):
            request.app.state.container.operational_service.record_request(
                duration=perf_counter() - started,
                errored=errored,
            )


@app.middleware("http")
async def security_headers_and_payload_middleware(
    request: Request, call_next: Any
) -> Response:
    """Reject oversized bodies and attach baseline HTTP security headers."""
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > 1_000_000:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": "request payload is too large",
                    "details": {},
                }
            },
        )
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def optional_authentication_middleware(
    request: Request, call_next: Any
) -> Response:
    """Resolve bearer or browser-cookie identity and fail closed for bad tokens."""
    if not hasattr(request.app.state, "container"):
        return await call_next(request)
    container: Container = request.app.state.container
    correlation_id = _correlation_uuid(
        request.headers.get(settings.correlation_id_header)
    )
    authorization = request.headers.get("authorization")
    token: str | None = None
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("invalid authorization header")
        request.state.auth_via_cookie = False
    elif request.cookies.get(settings.web_cookie_name):
        token = request.cookies[settings.web_cookie_name]
        request.state.auth_via_cookie = True
    if token:
        try:
            principal = container.security_service.authenticate_bearer_token(
                token,
                correlation_id=correlation_id,
            )
        except AuthenticationError:
            if getattr(request.state, "auth_via_cookie", False) and not (
                request.url.path.startswith("/api/")
            ):
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "AUTHENTICATION_ERROR",
                        "message": "authentication required",
                        "details": {},
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.security_context = (
            container.security_service.context_for_principal(principal)
        )
    return await call_next(request)


@app.get("/")
def root() -> dict[str, str]:
    """Return the root application status."""
    return {"name": settings.name, "version": settings.version, "status": "running"}


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Return backend, container, providers and runtime health status."""
    container: Container = request.app.state.container
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
        "backend": "ok",
        **container.health(),
    }


@app.get("/health/live")
def health_live() -> dict[str, Any]:
    """Liveness check that does not depend on external services."""
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
    }


@app.get("/health/ready")
def health_ready(request: Request) -> dict[str, Any]:
    """Readiness check for configured dependencies."""
    container: Container = request.app.state.container
    health_payload = container.health()
    ready = (
        bool(health_payload.get("runtime")) and health_payload.get("container") == "ok"
    )
    if settings.knowledge_repository == "postgres":
        ready = (
            ready
            and container.knowledge_graph_service.health().status.value == "healthy"
        )
    return {
        "status": "ready" if ready else "not_ready",
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
        "dependencies": health_payload,
    }


@app.get("/health/version")
def health_version() -> dict[str, str]:
    """Return build/version metadata."""
    return {
        "name": settings.name,
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
    }


@app.get("/metrics")
def metrics(request: Request) -> PlainTextResponse:
    """Expose simple Prometheus-compatible operational metrics."""
    if not settings.metrics_enabled:
        return PlainTextResponse("metrics_disabled 1\n", media_type="text/plain")
    values = request.app.state.container.operational_service.metrics()
    lines = []
    for name, value in values.model_dump().items():
        metric_name = f"ecos_{name}"
        lines.append(f"# TYPE {metric_name} gauge")
        lines.append(f"{metric_name} {value}")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")


@app.post("/auth/login")
def login(request: LoginRequest, http_request: Request) -> LoginResponse:
    """Authenticate with local password credentials."""
    container: Container = http_request.app.state.container
    token, principal = container.security_service.login(
        email=request.email,
        password=request.password,
        organization_id=request.organization_id,
        correlation_id=_correlation_uuid(
            http_request.headers.get(settings.correlation_id_header)
        ),
    )
    return LoginResponse(
        access_token=token,
        expires_at=principal.expires_at.isoformat(),
    )


@app.get("/security/me")
def me(http_request: Request) -> PrincipalResponse:
    """Return the current authenticated principal."""
    context = _required_security_context(http_request)
    principal = context.principal
    return _principal_response(principal)


@app.post("/runtime/demo")
def runtime_demo(
    request: RuntimeDemoRequest,
    http_request: Request,
) -> RuntimeDemoResponse:
    """Run the fake cognitive runtime demo pipeline."""
    container: Container = http_request.app.state.container
    principal = getattr(
        getattr(http_request, "state", object()),
        "security_context",
        None,
    )
    if principal is None:
        if not settings.auth_demo_enabled:
            raise AuthenticationError("demo identity is disabled")
        correlation_id = _correlation_uuid(
            http_request.headers.get(settings.correlation_id_header)
        )
        demo_principal = container.security_service.demo_principal(
            correlation_id=correlation_id
        )
        http_request.state.security_context = SecurityContext(
            principal=demo_principal,
            correlation_id=correlation_id,
        )
    runtime_engine: RuntimeEngine = container.runtime_engine
    result = runtime_engine.run(request.objective)
    return RuntimeDemoResponse(**result.model_dump())


def _required_security_context(request: Request) -> SecurityContext:
    context = getattr(request.state, "security_context", None)
    if not isinstance(context, SecurityContext):
        raise AuthenticationError("authentication required")
    return context


def _correlation_uuid(value: str | None) -> UUID:
    if value is None:
        return uuid4()
    try:
        return UUID(value)
    except ValueError:
        return uuid4()


def _principal_response(principal: AuthenticatedPrincipal) -> PrincipalResponse:
    return PrincipalResponse(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        roles=tuple(role.value for role in principal.roles),
        permissions=tuple(permission.value for permission in principal.permissions),
        authentication_method=principal.authentication_method.value,
        session_id=principal.session_id,
        token_id=principal.token_id,
        issued_at=principal.issued_at.isoformat(),
        expires_at=principal.expires_at.isoformat(),
        correlation_id=principal.correlation_id,
    )


def _frontend_dist() -> Path:
    root = Path(__file__).resolve().parents[3]
    configured = Path(settings.frontend_static_dir)
    return configured if configured.is_absolute() else root / configured


frontend_dist = _frontend_dist()
assets_dir = frontend_dist / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_app(full_path: str) -> Response:
    """Serve the compiled React app with route-refresh fallback."""
    del full_path
    index = _frontend_dist() / "index.html"
    if not index.exists():
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "FRONTEND_NOT_BUILT",
                    "message": "frontend build artifact is not available",
                    "details": {},
                }
            },
        )
    response = FileResponse(index)
    response.headers["Cache-Control"] = "no-store"
    return response

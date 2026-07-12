"""FastAPI application entrypoint for the ECOS backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


@app.exception_handler(EcosError)
async def ecos_error_handler(request: Request, exc: EcosError) -> JSONResponse:
    """Return standardized responses for ECOS domain/application errors."""
    return JSONResponse(
        status_code=400,
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
    del request
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
    response = await call_next(request)
    response.headers[settings.correlation_id_header] = correlation_id
    return response


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
    """Resolve bearer identity when supplied and fail closed for bad tokens."""
    if not hasattr(request.app.state, "container"):
        return await call_next(request)
    container: Container = request.app.state.container
    correlation_id = _correlation_uuid(
        request.headers.get(settings.correlation_id_header)
    )
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("invalid authorization header")
        principal = container.security_service.authenticate_bearer_token(
            token,
            correlation_id=correlation_id,
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

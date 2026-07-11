"""FastAPI application entrypoint for the ECOS backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
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


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next: Any) -> Any:
    """Attach a correlation ID to each request."""
    correlation_id = set_correlation_id(
        request.headers.get(settings.correlation_id_header)
    )
    response = await call_next(request)
    response.headers[settings.correlation_id_header] = correlation_id
    return response


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


@app.post("/runtime/demo")
def runtime_demo(
    request: RuntimeDemoRequest,
    http_request: Request,
) -> RuntimeDemoResponse:
    """Run the fake cognitive runtime demo pipeline."""
    container: Container = http_request.app.state.container
    runtime_engine: RuntimeEngine = container.runtime_engine
    result = runtime_engine.run(request.objective)
    return RuntimeDemoResponse(**result.model_dump())

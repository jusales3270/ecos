"""FastAPI application entrypoint for the ECOS backend."""

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from ecos.config import Settings
from ecos.runtime import RuntimeEngine

settings = Settings()
app = FastAPI(title="ECOS Backend", version=settings.version)


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


@app.get("/health")
def health() -> dict[str, Any]:
    """Return the backend health status."""
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
    }


@app.post("/runtime/demo")
def runtime_demo(request: RuntimeDemoRequest) -> RuntimeDemoResponse:
    """Run the fake cognitive runtime demo pipeline."""
    result = RuntimeEngine().run(request.objective)
    return RuntimeDemoResponse(**result.model_dump())

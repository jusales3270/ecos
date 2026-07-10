"""FastAPI application entrypoint for the ECOS backend."""

from typing import Any

from fastapi import FastAPI

from ecos.config import Settings

settings = Settings()
app = FastAPI(title="ECOS Backend", version=settings.version)


@app.get("/health")
def health() -> dict[str, Any]:
    """Return the backend health status."""
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
    }

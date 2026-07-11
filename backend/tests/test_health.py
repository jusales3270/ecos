"""Tests for the application status and health endpoints."""

from fastapi.testclient import TestClient

from ecos.main import app


def test_root_returns_application_status() -> None:
    """GET / returns the public application status."""
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "ECOS",
        "version": "0.1.0",
        "status": "running",
    }


def test_health_returns_backend_container_provider_and_runtime_status() -> None:
    """GET /health validates backend, container, providers, and runtime."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ecos-backend",
        "version": "0.1.0",
        "backend": "ok",
        "container": "ok",
        "providers": {"CUSTOM": True},
        "runtime": True,
    }

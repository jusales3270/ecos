"""Tests for the health endpoint."""

from fastapi.testclient import TestClient

from ecos.main import app


def test_health_returns_service_status() -> None:
    """GET /health returns status, service name, and version."""
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ecos-backend",
        "version": "0.1.0",
    }

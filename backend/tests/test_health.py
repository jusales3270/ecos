"""Tests for the application status and health endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from ecos.main import app, settings


def test_frontend_root_spa_fallback_and_readiness(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Frontend routes serve the build while readiness remains JSON."""
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><html><body>ECOS frontend</body></html>")
    monkeypatch.setattr(settings, "frontend_static_dir", str(tmp_path))

    with TestClient(app) as client:
        root = client.get("/")
        spa_route = client.get("/arbitrary/react/route")
        ready = client.get("/health/ready")

    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert root.text == index.read_text()
    assert spa_route.status_code == 200
    assert spa_route.headers["content-type"].startswith("text/html")
    assert spa_route.text == index.read_text()
    assert ready.status_code == 200
    assert ready.headers["content-type"].startswith("application/json")
    assert ready.json()["status"] == "ready"


def test_health_returns_backend_container_provider_and_runtime_status() -> None:
    """GET /health validates backend, container, providers, and runtime."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ecos-backend",
        "version": "0.1.0-rc.1",
        "backend": "ok",
        "container": "ok",
        "providers": {"CUSTOM": True},
        "runtime": True,
    }


def test_runtime_demo_preserves_fake_public_contract() -> None:
    """POST /runtime/demo remains deterministic in the default fake mode."""
    with TestClient(app) as client:
        response = client.post(
            "/runtime/demo", json={"objective": "Improve decision quality"}
        )

    payload = response.json()
    assert response.status_code == 200
    assert set(payload) == {"session_id", "status", "recommendation", "confidence"}
    assert payload["status"] == "completed"
    assert payload["recommendation"] == (
        "Proceed using ECOS context, reasoning, debate and governance."
    )
    assert payload["confidence"] == 0.91

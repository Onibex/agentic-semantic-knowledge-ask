"""
ask-admin-api — smoke tests.

Verify the package builds, the FastAPI app boots, and /v1/health responds.
Domain-specific endpoint tests live next to each router as it is added.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_package_importable():
    import ask_admin_api  # noqa: F401
    from ask_admin_api import config, main  # noqa: F401
    from ask_admin_api.auth import xsuaa  # noqa: F401
    from ask_admin_api.routers import health  # noqa: F401


def test_health_returns_ok_unauthenticated():
    """`/v1/health` must answer without credentials (k8s liveness probe)."""
    from ask_admin_api.main import app

    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "ask-admin-api"


def test_dev_bypass_only_active_when_both_flags_align(monkeypatch):
    """Auth bypass requires ENVIRONMENT=local AND DEV_BYPASS_AUTH=true."""
    from ask_admin_api.config import get_settings

    # Combination 1: only DEV_BYPASS_AUTH set → no bypass (production env)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    get_settings.cache_clear()
    assert get_settings().bypass_active is False

    # Combination 2: only ENVIRONMENT=local → no bypass
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "false")
    get_settings.cache_clear()
    assert get_settings().bypass_active is False

    # Combination 3: both align → bypass
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    get_settings.cache_clear()
    assert get_settings().bypass_active is True

    get_settings.cache_clear()

"""RBAC regression tests (Iter SPA-AUTH Phase 1.3).

The admin API is admin-only: sensitive routers are gated with
``require_role("ask-admin")`` at include time (see main.py), while the
``GET /v1/admin/workspaces`` list stays open to any authenticated principal
because the chat SPA (an ``ask-user``) consumes it to scope queries.

We override ``validate_token`` so the tests exercise the role gate directly
without a live IdP/JWKS. The 403 is raised by the router-level dependency
*before* the endpoint body, so the "forbidden" assertions hold even though the
temp harness has no OpenSearch. For the "allowed" cases the request proceeds
into the endpoint and then fails to reach OpenSearch — hence the client is
built with ``raise_server_exceptions=False`` so that backend error surfaces as
a 500 (still ``!= 403``, i.e. auth let it through) instead of propagating.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ask_admin_api.auth.validator import TokenClaims, validate_token
from ask_admin_api.main import app


def _override(roles: list[str]):
    return lambda: TokenClaims(sub="u1", email="u1@example.com", roles=roles, issuer="keycloak")


@pytest.fixture
def client(viz_repo):
    """viz_repo sets ENVIRONMENT/repo env; build a client that turns unhandled
    backend errors into 500s so 'not 403' assertions are meaningful offline."""
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(validate_token, None)


def test_ask_user_forbidden_on_admin_router(client):
    """An ask-user token must be rejected (403) by an admin-gated router."""
    app.dependency_overrides[validate_token] = _override(["ask-user"])
    resp = client.get("/v1/admin/organization")
    assert resp.status_code == 403


def test_no_roles_forbidden_on_admin_router(client):
    """A token with no roles must also be rejected (guards the role-extraction fix)."""
    app.dependency_overrides[validate_token] = _override([])
    resp = client.get("/v1/admin/organization")
    assert resp.status_code == 403


def test_ask_admin_passes_role_gate(client):
    """An ask-admin token must pass the gate (not 403); downstream status may vary."""
    app.dependency_overrides[validate_token] = _override(["ask-admin", "ask-user"])
    resp = client.get("/v1/admin/organization")
    assert resp.status_code != 403


def test_ask_user_allowed_on_workspaces_list(client):
    """The chat SPA (ask-user) must NOT be blocked from the workspaces list."""
    app.dependency_overrides[validate_token] = _override(["ask-user"])
    resp = client.get("/v1/admin/workspaces")
    assert resp.status_code != 403

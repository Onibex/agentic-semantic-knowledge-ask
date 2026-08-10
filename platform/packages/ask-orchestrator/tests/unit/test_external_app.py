"""
Unit tests for the public /external sub-app.

Verify the contract surface:
  - Sub-app is mounted at /external with its own OpenAPI spec.
  - The spec exposes ONLY the public ask endpoint (no chat / admin / internal
    routes leak — that's the whole point of using a sub-app).
  - POST /external/ask invokes run_query_pipeline once (with a fake) and
    correctly maps internal QueryResponse → ExternalAskResponse, dropping
    chat-specific fields like mode_used / tokens_breakdown.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Boot the orchestrator app with a stubbed pipeline so no LLM / DB / KG
    is touched during the test.

    Auth: both external endpoints now depend on ``validate_token`` (OAuth2/OIDC
    bearer). Override it with mock claims so the happy-path tests don't need a
    real issuer — the same pattern the /v1/query integration tests use.
    """
    from ask_orchestrator.auth.validator import TokenClaims, validate_token
    from ask_orchestrator.external.routers import ask as ask_router
    from ask_orchestrator.models.responses import QueryResponse
    from ask_orchestrator.routers import query as query_router

    captured: dict = {}

    def _fake_pipeline(req, user):
        captured["req"] = req
        captured["user"] = user
        return QueryResponse(
            answer="42",
            sql="SELECT 42 AS answer",
            rows=[{"answer": 42}],
            macro_intent="SQL_EXECUTION",
            mode_used=req.mode,
            trace_id="trace-abc",
            tokens_used=123,
            citations=None,
        )

    # Patch the import the router uses (it captured the symbol at module load).
    monkeypatch.setattr(query_router, "run_query_pipeline", _fake_pipeline)
    monkeypatch.setattr(ask_router, "run_query_pipeline", _fake_pipeline)

    # Stub the workspace scope provider so /external/workspaces doesn't hit a
    # real OpenSearch cluster.
    from ask_orchestrator import workspace_scope

    class _StubScope:
        def list_workspaces(self):
            return [
                {
                    "id": "ws-uuid-1",
                    "slug": "sales-and-operations",
                    "name": "Sales & Operations",
                    "description": "S&O analytics",
                },
                {"id": "ws-uuid-2", "slug": "finance", "name": "Finance", "description": ""},
            ]

    monkeypatch.setattr(workspace_scope, "_provider", _StubScope())

    # The external endpoints live on a MOUNTED sub-app (external_app), which
    # resolves dependencies against its OWN dependency_overrides — it does not
    # inherit the parent app's. Override validate_token there.
    from ask_orchestrator.external.app import external_app
    from ask_orchestrator.main import app

    claims = TokenClaims(sub="ext", email="ext@client", roles=["query"], issuer="xsuaa")

    async def _ok():
        return claims

    external_app.dependency_overrides[validate_token] = _ok
    captured["claims"] = claims
    # The custom openapi() caches on external_app.openapi_schema; drop it so the
    # spec is rebuilt against whatever env/settings each test set up.
    external_app.openapi_schema = None
    try:
        yield TestClient(app), captured
    finally:
        external_app.dependency_overrides.clear()
        external_app.openapi_schema = None


def test_external_openapi_is_isolated(client):
    cli, _ = client
    resp = cli.get("/external/openapi.json")
    assert resp.status_code == 200, resp.text
    spec = resp.json()

    # Title comes from the sub-app, not the main orchestrator.
    assert spec["info"]["title"] == "ASK External API"
    assert spec["info"]["version"] == "1.0.0"

    # Only the public endpoints are exposed — no /v1/query, no /v1/profile,
    # no /v1/admin/*, no /v1/internal/*.
    paths = set(spec["paths"].keys())
    assert "/ask" in paths
    assert "/workspaces" in paths
    forbidden = {"/v1/query", "/v1/profile", "/v1/internal/reload", "/v1/health"}
    leaked = forbidden & paths
    assert leaked == set(), f"Internal endpoints leaked into the external spec: {leaked}"


def _iter_schema_nodes(node):
    """Yield every dict node in a JSON document (for structural assertions)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_schema_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_schema_nodes(item)


def test_external_openapi_is_watsonx_ready(client):
    """The three importer gotchas are handled: 3.0.3 version, ABSOLUTE server
    URL, and an OAuth2 clientCredentials security scheme + global requirement.
    This is the exact shape that imported successfully into WatsonX Orchestrate.
    """
    cli, _ = client
    spec = cli.get("/external/openapi.json").json()

    # 1) OpenAPI 3.0.x (importers reject 3.1).
    assert spec["openapi"] == "3.0.3"

    # 2) Single absolute server URL ending in the /external mount prefix.
    assert len(spec["servers"]) == 1
    url = spec["servers"][0]["url"]
    assert url.startswith("http://") or url.startswith("https://")
    assert url.endswith("/external")

    # 3) OAuth2 clientCredentials scheme + global security requirement.
    schemes = spec["components"]["securitySchemes"]
    assert schemes["oauth2"]["type"] == "oauth2"
    token_url = schemes["oauth2"]["flows"]["clientCredentials"]["tokenUrl"]
    assert token_url.endswith("/protocol/openid-connect/token")
    assert spec["security"] == [{"oauth2": []}]


def test_external_openapi_downconverts_nullable_to_30(client):
    """3.1 nullable `anyOf` is collapsed to 3.0 `nullable: true`, and no bare
    `{"type": "null"}` fragment (invalid in 3.0.3) survives anywhere."""
    cli, _ = client
    spec = cli.get("/external/openapi.json").json()

    sql = spec["components"]["schemas"]["ExternalAskResponse"]["properties"]["sql"]
    assert sql["type"] == "string"
    assert sql["nullable"] is True
    assert "anyOf" not in sql

    # No 3.1-only `type: null` node leaks through.
    assert not any(n.get("type") == "null" for n in _iter_schema_nodes(spec))


def test_external_openapi_strips_authorization_param(client):
    """The manual `authorization` header param is removed — auth is expressed
    via the OAuth2 security scheme, so importers don't render a free-text
    Authorization field."""
    cli, _ = client
    spec = cli.get("/external/openapi.json").json()
    for methods in spec["paths"].values():
        for operation in methods.values():
            names = {p.get("name") for p in operation.get("parameters", [])}
            assert "authorization" not in names


def test_external_openapi_urls_derive_from_external_host(monkeypatch):
    """EXTERNAL_HOST is the single knob: it drives both the server base URL and
    the OAuth token URL, matching the deployed EC2 contract."""
    from fastapi.testclient import TestClient

    from ask_orchestrator import config
    from ask_orchestrator.external.app import external_app
    from ask_orchestrator.main import app

    monkeypatch.setenv("EXTERNAL_HOST", "52.14.62.101")
    config.get_settings.cache_clear()
    external_app.openapi_schema = None
    try:
        spec = TestClient(app).get("/external/openapi.json").json()
        assert spec["servers"][0]["url"] == "http://52.14.62.101:8085/external"
        cc = spec["components"]["securitySchemes"]["oauth2"]["flows"]["clientCredentials"]
        assert cc["tokenUrl"] == (
            "http://52.14.62.101:8180/realms/ask-platform/protocol/openid-connect/token"
        )
    finally:
        monkeypatch.delenv("EXTERNAL_HOST", raising=False)
        config.get_settings.cache_clear()
        external_app.openapi_schema = None


def test_main_openapi_does_not_show_external_routes(client):
    """The main /openapi.json (chat-side) should not advertise /external/* routes
    — they live in the mounted sub-app's own spec."""
    cli, _ = client
    spec = cli.get("/openapi.json").json()
    paths = set(spec["paths"].keys())
    leaked = {p for p in paths if p.startswith("/external")}
    assert leaked == set(), f"External routes leaked into the main spec: {leaked}"


def test_external_ask_calls_pipeline_and_maps_response(client):
    cli, captured = client

    payload = {"question": "top 10 customers", "workspace_id": "ws-test", "mode": "smart"}
    resp = cli.post("/external/ask", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Pipeline received the public payload converted to QueryRequest.
    assert captured["req"].question == "top 10 customers"
    assert captured["req"].mode == "smart"
    # Chat-only fields stay None on the way in.
    assert captured["req"].session_id is None
    assert captured["req"].conversation_history is None
    # Identity for log correlation comes from the validated bearer claims.
    assert captured["user"]["email"] == "ext@client"
    assert captured["user"]["bypass"] is False

    # Response trimmed to the public contract.
    assert body["answer"] == "42"
    assert body["sql"] == "SELECT 42 AS answer"
    assert body["rows"] == [{"answer": 42}]
    assert body["macro_intent"] == "SQL_EXECUTION"
    assert body["trace_id"] == "trace-abc"
    assert body["tokens_used"] == 123
    # Chat-only fields not exposed.
    assert "mode_used" not in body
    assert "tokens_breakdown" not in body


def test_external_ask_defaults_mode_to_smart(client):
    """`mode` is optional; default should be `smart` (most stable for B2B)."""
    cli, captured = client

    resp = cli.post("/external/ask", json={"question": "anything", "workspace_id": "ws-test"})
    assert resp.status_code == 200
    assert captured["req"].mode == "smart"


def test_external_ask_defaults_env_to_dev(client):
    """`env` is optional; default should be `dev` (safe — nothing reaches prod
    until explicitly promoted)."""
    cli, captured = client

    resp = cli.post("/external/ask", json={"question": "anything", "workspace_id": "ws-test"})
    assert resp.status_code == 200
    assert captured["req"].env == "dev"


def test_external_ask_forwards_explicit_env(client):
    """An explicit `env` (e.g. `prod`) reaches the internal QueryRequest so the
    pipeline reads the matching published snapshot + DB connection."""
    cli, captured = client

    resp = cli.post(
        "/external/ask",
        json={"question": "anything", "workspace_id": "ws-test", "env": "prod"},
    )
    assert resp.status_code == 200
    assert captured["req"].env == "prod"


def test_external_ask_rejects_unknown_env(client):
    """`env` is constrained to dev|prod — anything else is a 422."""
    cli, _ = client
    resp = cli.post(
        "/external/ask",
        json={"question": "x", "workspace_id": "ws-test", "env": "staging"},
    )
    assert resp.status_code == 422


def test_external_ask_validation_rejects_empty_question(client):
    cli, _ = client
    resp = cli.post("/external/ask", json={"question": "", "workspace_id": "ws-test"})
    assert resp.status_code == 422


def test_external_ask_enforces_auth(client):
    """When the bearer is rejected, /external/ask returns 401 — proving the
    OAuth2/OIDC dependency is actually wired into the route (no anonymous
    access in production)."""
    from fastapi import HTTPException

    from ask_orchestrator.auth.validator import validate_token
    from ask_orchestrator.external.app import external_app

    cli, _ = client

    async def _reject():
        raise HTTPException(status_code=401, detail="no token")

    external_app.dependency_overrides[validate_token] = _reject
    resp = cli.post("/external/ask", json={"question": "x", "workspace_id": "ws-test"})
    assert resp.status_code == 401


# ── /external/workspaces ────────────────────────────────────────────────────


def test_external_workspaces_lists_catalog(client):
    """Returns the workspace catalog (id + slug + name + description) so a B2B
    client can discover the workspace_id to pass to /external/ask."""
    cli, _ = client
    resp = cli.get("/external/workspaces")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [w["slug"] for w in body] == ["sales-and-operations", "finance"]
    assert body[0] == {
        "id": "ws-uuid-1",
        "slug": "sales-and-operations",
        "name": "Sales & Operations",
        "description": "S&O analytics",
    }


def test_external_workspaces_enforces_auth(client):
    """/external/workspaces is gated by the same OAuth2/OIDC dependency."""
    from fastapi import HTTPException

    from ask_orchestrator.auth.validator import validate_token
    from ask_orchestrator.external.app import external_app

    cli, _ = client

    async def _reject():
        raise HTTPException(status_code=401, detail="no token")

    external_app.dependency_overrides[validate_token] = _reject
    resp = cli.get("/external/workspaces")
    assert resp.status_code == 401

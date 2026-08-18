# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Integration test for POST /v1/query (Iter 8.8 — legacy/ removed).

Mocks at the orchestrator boundary:
  - XSUAA auth (covered separately by test_auth_bypass).
  - Macro classifier (LLM-backed; stubbed).
  - ResolveIntentUseCase output (mocked).
  - SqlGenerationService (mocked).
  - SqlExecutorService (mocked) so HANA / Postgres are not touched.

End-to-end behavior with real backends → tests/e2e/test_smoke.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ask_intent_resolution.domain.result import (
    Disambiguation,
    IntentResolutionResult,
    ResolutionTrace,
)
from ask_orchestrator import config as config_module
from ask_orchestrator.auth.validator import TokenClaims, validate_token
from ask_orchestrator.main import app
from ask_orchestrator.models.responses import MacroIntent
from ask_orchestrator.routers import query as query_router
from ask_sql_executor.domain.models import FormattedResult
from ask_sql_generation.domain.models import SqlGenerationResult

_MOCK_CLAIMS = TokenClaims(
    sub="local-dev",
    email="dev@local",
    roles=["query", "admin"],
    issuer="xsuaa",
)


@pytest.fixture(autouse=True)
def bypass_auth_and_reset_settings(monkeypatch):
    async def _ok():
        return _MOCK_CLAIMS

    app.dependency_overrides[validate_token] = _ok
    config_module.get_settings.cache_clear()

    # SettingsCache.get() reads config/settings.json relative to CWD, which is
    # absent when pytest runs from the package dir. Stub it with a minimal dict
    # (DB config no longer lives here — see the fake SecretsProvider below).
    monkeypatch.setattr(
        config_module.SettingsCache,
        "get",
        classmethod(lambda cls, path=None: {}),
    )

    # DB config now lives in the encrypted store (2026-07 migration). Inject a
    # fake SecretsProvider so resolve_db_config / is_db_configured resolve
    # deterministically without OpenSearch: dev is configured (hana), prod is
    # NOT — so the per-env guard blocks prod queries.
    from ask_llm_gateway.infrastructure.secrets import provider as secrets_provider_module

    class _FakeSecrets:
        def get(self, target, force_refresh=False):  # noqa: ARG002 — signature compat
            if target == "db_dev":
                return {
                    "provider": "hana",
                    "model": "",
                    "fields": {
                        "host": "test",
                        "port": "443",
                        "user": "u",
                        "password": "p",
                        "schema": "S",
                    },
                }
            return None  # db_prod / llm / embedder unconfigured

    secrets_provider_module.set_secrets_provider_for_tests(_FakeSecrets())

    # Iter 1: /v1/query now requires a workspace_id and looks up its entity_ids
    # in OpenSearch. Stub the scope provider so tests don't hit a real cluster.
    from ask_orchestrator import organization_context, workspace_scope

    class _StubScope:
        def get_entity_ids(self, workspace_id: str, env: str | None = None):
            # Non-empty list → bypasses the "workspace has no entities" 400.
            return ["silver_x"]

        def get_schema_entity_ids(self, workspace_id: str, env: str | None = None):
            # Schema plane widens the chat scope with composed_of bronzes; with a
            # single stub member there is nothing to widen, so it mirrors the base.
            return ["silver_x"]

    class _StubOrg:
        def get_context_text(self):
            return None

    monkeypatch.setattr(workspace_scope, "_provider", _StubScope())
    monkeypatch.setattr(organization_context, "_provider", _StubOrg())

    yield
    app.dependency_overrides.clear()
    config_module.get_settings.cache_clear()
    secrets_provider_module.set_secrets_provider_for_tests(None)


def _stub_classifier(monkeypatch, intent: MacroIntent) -> None:
    monkeypatch.setattr(query_router._classifier, "classify", lambda question: intent)


def _stub_use_case(monkeypatch, result: IntentResolutionResult) -> dict:
    captured: dict = {}

    class _StubUseCase:
        def resolve(self, request):
            captured["request"] = request
            return result

    monkeypatch.setattr(query_router, "get_default_use_case", lambda: _StubUseCase())
    return captured


def _stub_sql_generator(monkeypatch, result: SqlGenerationResult) -> dict:
    captured: dict = {}

    class _StubGen:
        def generate(self, request):
            captured["request"] = request
            return result

    monkeypatch.setattr(query_router, "_get_sql_generator", lambda *a, **k: _StubGen())
    return captured


def _stub_executor(monkeypatch, rows, answer, *, error=None):
    """Stub the Iter 4 SqlExecutorService that the orchestrator now uses."""
    captured: dict = {}

    class _StubExec:
        def execute_and_format(self, request, *, question):
            captured["sql"] = request.sql
            captured["db_type"] = request.db_type
            captured["question"] = question
            return FormattedResult(
                sql=request.sql,
                rows_dict=rows or [],
                answer=answer,
                error=error,
                row_count=len(rows or []),
            )

    monkeypatch.setattr(query_router, "_get_sql_executor", lambda: _StubExec())
    return captured


def _ir_only(yamls, edges, plan=None):
    return IntentResolutionResult(
        plan=plan or {"intent_summary": "x"},
        yamls=yamls,
        edges=edges,
        disambiguation=None,
        error=None,
        trace=ResolutionTrace(strategy="precise", tokens_used=42),
    )


def _flash_complete(sql, rows, answer):
    return IntentResolutionResult(
        plan={},
        yamls=[],
        edges=[],
        disambiguation=None,
        error=None,
        trace=ResolutionTrace(strategy="flash", tokens_used=15),
        sql=sql,
        rows=rows,
        answer=answer,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Precise/Smart: chain Resolve → SqlGeneration → executor
# ─────────────────────────────────────────────────────────────────────────────
def test_sql_execution_chains_resolve_then_sqlgen_then_exec(monkeypatch):
    _stub_classifier(monkeypatch, "SQL_EXECUTION")
    _stub_use_case(
        monkeypatch,
        _ir_only(
            yamls=[{"id": "silver_x", "raw_yaml": "id: silver_x\nfields: []"}],
            edges=[],
        ),
    )
    sql_capt = _stub_sql_generator(
        monkeypatch,
        SqlGenerationResult(
            sql='SELECT count(*) FROM "SILVER_X"',
            error=None,
            tokens_used=200,
        ),
    )
    exec_capt = _stub_executor(monkeypatch, rows=[{"c": 5}], answer="5 records found.")

    client = TestClient(app)
    response = client.post(
        "/v1/query",
        json={"workspace_id": "ws-test", "question": "how many X?", "mode": "precise"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"] == 'SELECT count(*) FROM "SILVER_X"'
    assert body["rows"] == [{"c": 5}]
    assert body["answer"] == "5 records found."
    assert body["macro_intent"] == "SQL_EXECUTION"
    assert sql_capt["request"].yamls == ["id: silver_x\nfields: []"]
    assert exec_capt["sql"].startswith("SELECT count(*)")


def test_sql_execution_blocked_when_env_db_unconfigured(monkeypatch):
    # The stubbed config has a top-level (dev) DB but NO environments.prod block,
    # so prod is unconfigured. The orchestrator must block with a clear message
    # instead of silently querying the dev database (per-env DB isolation).
    _stub_classifier(monkeypatch, "SQL_EXECUTION")

    client = TestClient(app)
    response = client.post(
        "/v1/query",
        json={
            "workspace_id": "ws-test",
            "question": "how many X?",
            "mode": "precise",
            "env": "prod",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"] is None
    assert body["rows"] is None
    assert "prod" in body["answer"]
    assert "database is configured" in body["answer"].lower()


def test_sql_execution_skips_chain_when_no_yamls_resolved(monkeypatch):
    _stub_classifier(monkeypatch, "SQL_EXECUTION")
    _stub_use_case(monkeypatch, _ir_only(yamls=[], edges=[]))

    client = TestClient(app)
    response = client.post(
        "/v1/query", json={"workspace_id": "ws-test", "question": "x", "mode": "smart"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"] is None
    assert "no schema context" in body["answer"]


def test_sql_generation_error_short_circuits(monkeypatch):
    _stub_classifier(monkeypatch, "SQL_EXECUTION")
    _stub_use_case(
        monkeypatch,
        _ir_only(
            yamls=[{"id": "silver_x", "raw_yaml": "..."}],
            edges=[],
        ),
    )
    _stub_sql_generator(monkeypatch, SqlGenerationResult(sql=None, error="LLM refused"))

    client = TestClient(app)
    response = client.post(
        "/v1/query", json={"workspace_id": "ws-test", "question": "x", "mode": "precise"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"] is None
    assert "LLM refused" in body["answer"]


# ─────────────────────────────────────────────────────────────────────────────
# Flash bypass (Iter 3 Q1)
# ─────────────────────────────────────────────────────────────────────────────
def test_flash_bypasses_sql_generation_chain(monkeypatch):
    _stub_classifier(monkeypatch, "SQL_EXECUTION")
    _stub_use_case(
        monkeypatch,
        _flash_complete(
            sql="SELECT 1",
            rows=[{"x": 1}],
            answer="One row.",
        ),
    )
    # Critical: the SQL generator must NOT be called.
    sql_called = {"flag": False}

    class _BoomGen:
        def generate(self, request):
            sql_called["flag"] = True
            raise AssertionError("Flash must bypass SqlGenerationService")

    monkeypatch.setattr(query_router, "_get_sql_generator", lambda *a, **k: _BoomGen())

    client = TestClient(app)
    response = client.post(
        "/v1/query", json={"workspace_id": "ws-test", "question": "x", "mode": "flash"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"] == "SELECT 1"
    assert body["answer"] == "One row."
    assert sql_called["flag"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Disambiguation short-circuit
# ─────────────────────────────────────────────────────────────────────────────
def test_disambiguation_short_circuits_chain(monkeypatch):
    _stub_classifier(monkeypatch, "SQL_EXECUTION")
    _stub_use_case(
        monkeypatch,
        IntentResolutionResult(
            plan={},
            yamls=[],
            edges=[],
            disambiguation=Disambiguation(level="L2", message="Did you mean A or B?"),
            error=None,
            trace=ResolutionTrace(strategy="precise"),
        ),
    )

    class _BoomGen:
        def generate(self, request):
            raise AssertionError("Disambiguation must short-circuit before SqlGen")

    monkeypatch.setattr(query_router, "_get_sql_generator", lambda *a, **k: _BoomGen())

    client = TestClient(app)
    response = client.post(
        "/v1/query", json={"workspace_id": "ws-test", "question": "x", "mode": "precise"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"] is None
    assert body["answer"] == "Did you mean A or B?"


# ─────────────────────────────────────────────────────────────────────────────
# Schema query routes (Iter 5: ask-schema-service is now the default)
# ─────────────────────────────────────────────────────────────────────────────
def test_schema_query_routes_to_schema_service(monkeypatch):
    """Default Iter 5 path: SCHEMA_QUERY hits ask-schema-service."""
    from ask_schema_service.domain.models import SchemaResponse

    _stub_classifier(monkeypatch, "SCHEMA_QUERY")

    captured: dict = {}

    class _StubSchemaSvc:
        def answer(self, query):
            captured["question"] = query.question
            return SchemaResponse(answer="VBAK has 187 columns.")

    monkeypatch.setattr(query_router, "_get_schema_service", lambda *_a, **_k: _StubSchemaSvc())

    client = TestClient(app)
    response = client.post(
        "/v1/query",
        json={
            "workspace_id": "ws-test",
            "question": "What columns does VBAK have?",
            "mode": "precise",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["macro_intent"] == "SCHEMA_QUERY"
    assert body["answer"] == "VBAK has 187 columns."
    assert captured["question"] == "What columns does VBAK have?"


# ─────────────────────────────────────────────────────────────────────────────
# ACTION_EXECUTION routing (Iter D-revised — service is real, behind a stub here)
# ─────────────────────────────────────────────────────────────────────────────
def test_action_execution_routes_to_action_service(monkeypatch):
    """ACTION_EXECUTION reaches ask-action-execution; orchestrator returns its
    ``answer`` verbatim. The actual SAP MCP call is stubbed."""
    from ask_action_execution.domain.models import ActionResponse

    _stub_classifier(monkeypatch, "ACTION_EXECUTION")

    captured: dict = {}

    class _StubActionSvc:
        def execute(self, request):
            captured["question"] = request.question
            return ActionResponse(answer="Order 4711 created.", action="create_order", success=True)

    monkeypatch.setattr(query_router, "_get_action_service", lambda: _StubActionSvc())

    client = TestClient(app)
    response = client.post(
        "/v1/query",
        json={"workspace_id": "ws-test", "question": "create order for ACME", "mode": "precise"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["macro_intent"] == "ACTION_EXECUTION"
    assert body["answer"] == "Order 4711 created."
    assert captured["question"] == "create order for ACME"


# ─────────────────────────────────────────────────────────────────────────────
# Iter 5 — Docs Service routing
# ─────────────────────────────────────────────────────────────────────────────
def test_docs_query_routes_to_docs_service(monkeypatch):
    """Default Iter 5 path: DOCS_QUERY hits ask-docs-service."""
    from ask_docs_service.domain.models import Citation, DocsResponse

    _stub_classifier(monkeypatch, "DOCS_QUERY")

    captured: dict = {}

    class _StubDocsSvc:
        def answer(self, query):
            captured["question"] = query.question
            captured["top_k"] = query.top_k
            return DocsResponse(
                answer="The sales_order data product …",
                citations=[
                    Citation(entity_id="silver_sales", snippet="id: silver_sales", score=2.5),
                ],
            )

    monkeypatch.setattr(query_router, "_get_docs_service", lambda *_a, **_k: _StubDocsSvc())

    client = TestClient(app)
    response = client.post(
        "/v1/query",
        json={
            "workspace_id": "ws-test",
            "question": "What does sales_order expose?",
            "mode": "precise",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["macro_intent"] == "DOCS_QUERY"
    assert body["answer"].startswith("The sales_order data product")
    # The orchestrator appends the citations footer (Iter 5 minimal contract).
    assert "**Sources**:" in body["answer"]
    assert "silver_sales" in body["answer"]
    assert captured["question"] == "What does sales_order expose?"


def test_docs_query_no_citations_omits_footer(monkeypatch):
    from ask_docs_service.domain.models import DocsResponse

    _stub_classifier(monkeypatch, "DOCS_QUERY")

    class _Svc:
        def answer(self, query):
            return DocsResponse(answer="No data products matched.", citations=[])

    monkeypatch.setattr(query_router, "_get_docs_service", lambda *_a, **_k: _Svc())
    client = TestClient(app)
    response = client.post(
        "/v1/query", json={"workspace_id": "ws-test", "question": "x", "mode": "precise"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "No data products matched."
    assert "**Sources**:" not in body["answer"]


# ─────────────────────────────────────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────────────────────────────────────
def test_pipeline_exception_translates_to_500(monkeypatch):
    _stub_classifier(monkeypatch, "SQL_EXECUTION")

    class _BoomUseCase:
        def resolve(self, request):
            raise RuntimeError("OpenSearch unreachable")

    monkeypatch.setattr(query_router, "get_default_use_case", lambda: _BoomUseCase())
    client = TestClient(app)
    response = client.post(
        "/v1/query", json={"workspace_id": "ws-test", "question": "x", "mode": "precise"}
    )
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["error_code"] == "PIPELINE_ERROR"
    assert "OpenSearch unreachable" in detail["message"]


def test_openapi_lists_query_endpoint():
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/v1/query" in schema["paths"]


def test_query_rejects_invalid_mode():
    client = TestClient(app)
    response = client.post(
        "/v1/query", json={"workspace_id": "ws-test", "question": "x", "mode": "turbo"}
    )
    assert response.status_code == 422

"""
Smoke test (Iter 1) — 1 query per mode against a deployed ASK Orchestrator.

Replaces the formal 9/10-question benchmark for Iter 1 (decision #5 of the
ITERATION_1 plan: benchmark deferred until "stable version"). This test
only verifies that:
  - The HTTP endpoint is reachable.
  - Each mode returns a valid QueryResponse JSON.
  - SQL_EXECUTION-style outputs include a non-empty `sql`.

Configuration (env vars):
  ASK_ORCHESTRATOR_URL    — base URL (default http://localhost:8080)
  ASK_ORCHESTRATOR_TOKEN  — bearer token; if empty, the test assumes the
                            orchestrator is running with ENVIRONMENT=local
                            and DEV_BYPASS_AUTH=true.

Run:
  pytest tests/e2e/test_smoke.py -v -s
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("ASK_ORCHESTRATOR_URL", "http://localhost:8080").rstrip("/")
TOKEN = os.environ.get("ASK_ORCHESTRATOR_TOKEN", "")
TIMEOUT = float(os.environ.get("ASK_ORCHESTRATOR_TIMEOUT", "180"))

# Single representative question per mode. Kept generic so it runs against
# either the customer's HANA instance or the dev PostgreSQL.
SMOKE_QUERIES = [
    ("flash", "How many sales orders are open?"),
    ("precise", "How many sales orders are open?"),
    ("smart", "How many sales orders are open?"),
]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _orchestrator_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/v1/health", timeout=5.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _orchestrator_reachable(),
    reason=f"orchestrator not reachable at {BASE_URL} — start it before running smoke tests",
)


def test_health_endpoint_responds_ok():
    r = httpx.get(f"{BASE_URL}/v1/health", timeout=5.0)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_publishes_query_route():
    r = httpx.get(f"{BASE_URL}/openapi.json", timeout=5.0)
    assert r.status_code == 200
    schema = r.json()
    assert "/v1/query" in schema["paths"]


@pytest.mark.parametrize("mode,question", SMOKE_QUERIES)
def test_query_returns_valid_response(mode: str, question: str):
    r = httpx.post(
        f"{BASE_URL}/v1/query",
        json={"question": question, "mode": mode},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, f"{mode}: HTTP {r.status_code} — {r.text[:300]}"

    body = r.json()
    assert body["mode_used"] == mode
    assert body["macro_intent"] in {
        "SQL_EXECUTION",
        "SCHEMA_QUERY",
        "DOCS_QUERY",
        "DASHBOARD_GEN",
    }, f"{mode}: unexpected macro_intent {body['macro_intent']!r}"
    assert body["trace_id"]
    assert body["answer"], f"{mode}: empty answer"
    if body["macro_intent"] == "SQL_EXECUTION":
        assert body.get("sql"), f"{mode}: missing SQL for SQL_EXECUTION response"
        # Token tracking must survive the provider path (BACKLOG I —
        # Bedrock/Databricks via LiteLLM). The plumbing was verified at code
        # level (AutoTrackingCallback reads LangChain-standard usage_metadata,
        # which ChatLiteLLM populates unconditionally); this is the live half:
        # a real query must report non-zero token usage end-to-end.
        breakdown = body.get("tokens_breakdown") or {}
        total = body.get("tokens_used") or sum(
            v for v in breakdown.values() if isinstance(v, (int, float))
        )
        assert total and total > 0, (
            f"{mode}: tokens_used/tokens_breakdown empty — token tracking lost "
            f"on the live provider path (breakdown={breakdown!r})"
        )

"""Concurrency regression guard for POST /v1/query.

If the endpoint is `async def` while internally running blocking work, every
request serializes on the event loop and 50 concurrent calls take ~50× the
single-call latency. With the endpoint declared as `def`, FastAPI dispatches
to Starlette's thread pool (~40 threads) so the same 50 calls finish in
roughly one or two single-call latencies.

This test pins that behavior: mock `run_query_pipeline` to take 200 ms, fire
50 concurrent POSTs, assert the wall-clock total is well below the
fully-serialized worst case.

Threshold rationale:
  - Fully serialized (regression): 50 × 200 ms = 10 s.
  - Thread-pool concurrent (target): ceil(50 / 40) × 200 ms ≈ 400 ms, plus
    test-client overhead. We assert < 3 s, leaving margin for CI noise while
    still being an order of magnitude below the regression case.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from ask_orchestrator.auth.validator import TokenClaims, validate_token
from ask_orchestrator.main import app
from ask_orchestrator.models.responses import QueryResponse
from ask_orchestrator.routers import query as query_router

_MOCK_CLAIMS = TokenClaims(
    sub="local-dev",
    email="dev@local",
    roles=["query"],
    issuer="xsuaa",
)


@pytest.fixture(autouse=True)
def bypass_auth():
    async def _ok():
        return _MOCK_CLAIMS

    app.dependency_overrides[validate_token] = _ok
    yield
    app.dependency_overrides.clear()


def _fake_response() -> QueryResponse:
    return QueryResponse(
        answer="ok",
        rows=None,
        sql=None,
        macro_intent="SQL_EXECUTION",
        mode_used="precise",
        trace_id="t",
        tokens_used=0,
    )


def test_50_concurrent_requests_do_not_serialize(monkeypatch):
    """If someone reintroduces `async def` on the blocking endpoint, this
    test fails by timeout-budget. With sync `def` + thread pool it passes
    in well under a second."""
    per_request_seconds = 0.2

    def _slow_pipeline(req, user):
        time.sleep(per_request_seconds)
        return _fake_response()

    monkeypatch.setattr(query_router, "run_query_pipeline", _slow_pipeline)

    client = TestClient(app)
    payload = {"question": "ping", "workspace_id": "ws-test", "mode": "precise"}

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=50) as ex:
        futures = [ex.submit(client.post, "/v1/query", json=payload) for _ in range(50)]
        statuses = [f.result().status_code for f in futures]
    elapsed = time.perf_counter() - start

    assert all(s == 200 for s in statuses), f"unexpected statuses: {set(statuses)}"
    # Regression case (async-blocking) would be ~10 s; threshold leaves room
    # for CI noise without being lax.
    assert elapsed < 3.0, (
        f"50 concurrent requests took {elapsed:.2f}s "
        f"(per-request {per_request_seconds}s, fully-serialized worst case "
        f"{50 * per_request_seconds:.0f}s) — endpoint likely blocking the "
        f"event loop again"
    )

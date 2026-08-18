# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Formal 10-question benchmark — Iter 2 re-enablement.

A pytest test that exercises the deployed orchestrator over HTTP. The Iter 2
plan (Q4) chose manual-on-demand: the test only runs when
`ASK_RUN_BENCHMARK=1` is set in the env, otherwise it skips. This avoids
LLM token cost on every PR while still being a one-command regression
check before tagging a release.

Inputs (env):
  ASK_RUN_BENCHMARK         must be "1" to enable
  ASK_ORCHESTRATOR_URL      base URL (default http://127.0.0.1:8080)
  ASK_ORCHESTRATOR_TOKEN    optional bearer token (XSUAA in production)
  ASK_BENCHMARK_MODE        which orchestrator mode to use (default "smart")

Skip rules:
  - flag off → skip (default behaviour, CI-safe).
  - orchestrator unreachable → skip with clear reason.

Pass criteria (semantic, not byte-identity — LLMs are non-deterministic):
  - HTTP 200 with valid QueryResponse.
  - macro_intent ∈ {SQL_EXECUTION, SCHEMA_QUERY, DOCS_QUERY, ACTION_EXECUTION}.
  - For SQL_EXECUTION questions: non-empty `sql`.
  - Question #4 is allowed to fail (data-layer gap: no Silver for RESB).

The 10 questions are kept verbatim across revisions so the regression suite
stays comparable between iterations.
"""

from __future__ import annotations

import os

import httpx
import pytest

BENCHMARK_QUESTIONS: list[str] = [
    "Based on our open sales orders and incoming purchase orders, what is the projected inventory level for Material F226 at Plant 1000 by the end of next week from 2020-12-21?",
    "Which trading goods currently have open sales order volumes that exceed our on-hand stock and scheduled production orders combined?",
    "Are there any open purchase orders that need to be expedited because our current inventory can't cover the demand spike from yesterday's sales orders?",
    "Do we have enough raw materials currently in stock at Plant B to fulfill the scheduled production orders for the next 14 days?",  # #4 — RESB data gap
    "Which plants are holding excess stock of Material Y where there are zero open sales orders for the next week?",
    "How is our trading goods inventory performing across our distribution centers — which materials are overstocked and which are at risk of stockout?",
    "Show me the status of all open purchase orders for raw material X from supplier ABC, including expected delivery dates and quantities.",
    "How many sales orders did we close in Q1 2026 by customer region?",
    "What's the average lead time for our top 10 raw materials over the last 90 days?",
    "List the top 5 plants by total open sales order value this month.",
]
DATA_GAP_INDEX = 3  # 0-based index of question #4

BASE_URL = os.environ.get("ASK_ORCHESTRATOR_URL", "http://127.0.0.1:8080").rstrip("/")
TOKEN = os.environ.get("ASK_ORCHESTRATOR_TOKEN", "")
MODE = os.environ.get("ASK_BENCHMARK_MODE", "smart")
TIMEOUT = float(os.environ.get("ASK_BENCHMARK_TIMEOUT", "240"))


def _flag_active() -> bool:
    return os.environ.get("ASK_RUN_BENCHMARK", "").strip() == "1"


def _orchestrator_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/v1/health", timeout=5.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.skipif(
        not _flag_active(),
        reason="ASK_RUN_BENCHMARK=1 required to run the full benchmark (manual-on-demand).",
    ),
    pytest.mark.skipif(
        not _orchestrator_reachable() and _flag_active(),
        reason=f"orchestrator not reachable at {BASE_URL}",
    ),
]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def _post(question: str) -> httpx.Response:
    return httpx.post(
        f"{BASE_URL}/v1/query",
        json={"question": question, "mode": MODE},
        headers=_headers(),
        timeout=TIMEOUT,
    )


@pytest.mark.parametrize(
    "idx,question",
    list(enumerate(BENCHMARK_QUESTIONS)),
    ids=[f"Q{n + 1:02d}" for n in range(len(BENCHMARK_QUESTIONS))],
)
def test_benchmark_question(idx: int, question: str):
    r = _post(question)
    if idx == DATA_GAP_INDEX:
        # Question #4 hits a known data-layer gap (no Silver for RESB in the
        # demo workspace). We tolerate ANY non-5xx response — the test
        # only fails if the orchestrator itself crashes.
        assert r.status_code < 500, f"Q{idx + 1} should not crash the orchestrator"
        return

    assert r.status_code == 200, f"Q{idx + 1} HTTP {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body["macro_intent"] in {
        "SQL_EXECUTION",
        "SCHEMA_QUERY",
        "DOCS_QUERY",
        "ACTION_EXECUTION",
    }
    assert body["mode_used"] == MODE
    assert body["trace_id"]
    if body["macro_intent"] == "SQL_EXECUTION":
        assert body.get("sql"), f"Q{idx + 1}: SQL missing on a SQL_EXECUTION response"

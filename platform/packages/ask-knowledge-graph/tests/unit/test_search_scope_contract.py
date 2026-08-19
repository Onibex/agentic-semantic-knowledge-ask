# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Contract test: search_hybrid_rrf / search_gold_rescue honour the three-valued
allowed_ids scope (None = unscoped; [] = empty scope = match nothing).

These are the terminal retrieval filters for the Precise pipeline, so treating
an empty workspace scope as falsy (the old ``if allowed_ids:``) would silently
search the WHOLE registry — the exact leak Option B closes. We assert the
emitted query body, with a capturing client (no live OpenSearch needed; the
opensearch-py client only connects on first request).
"""

from __future__ import annotations

from ask_knowledge_graph.infrastructure.opensearch_repository import OpenSearchAskRepository


class _CaptureClient:
    def __init__(self) -> None:
        self.last_body: dict | None = None
        self.last_index: str | None = None

    def search(self, index, body):  # noqa: A002
        self.last_body = body
        return {"hits": {"hits": []}}

    def delete_by_query(self, *, index, body, refresh=None):  # noqa: A002
        self.last_index = index
        self.last_body = body
        return {"deleted": 2}


def _repo() -> OpenSearchAskRepository:
    # Bypass __init__ (it reads config/settings.json + builds a real client).
    # search_hybrid_rrf / search_gold_rescue only touch .client + .INDEX_ENTITY.
    repo = OpenSearchAskRepository.__new__(OpenSearchAskRepository)
    repo.client = _CaptureClient()
    repo.INDEX_ENTITY = "ask-entity-registry-v1"
    return repo


# ── search_hybrid_rrf ────────────────────────────────────────────────────────


def test_hybrid_none_is_unscoped():
    repo = _repo()
    repo.search_hybrid_rrf("q", [0.0, 0.0, 0.0], allowed_ids=None)
    assert "filter" not in repo.client.last_body["query"]["bool"]


def test_hybrid_empty_scope_filters_to_nothing():
    repo = _repo()
    repo.search_hybrid_rrf("q", [0.0, 0.0, 0.0], allowed_ids=[])
    assert repo.client.last_body["query"]["bool"]["filter"] == [{"terms": {"id": []}}]


def test_hybrid_subset_filters_to_ids():
    repo = _repo()
    repo.search_hybrid_rrf("q", [0.0, 0.0, 0.0], allowed_ids=["a", "b"])
    assert repo.client.last_body["query"]["bool"]["filter"] == [{"terms": {"id": ["a", "b"]}}]


# ── search_gold_rescue ───────────────────────────────────────────────────────


def _gold_filter(body: dict) -> list:
    return body["query"]["bool"]["filter"]


def test_gold_none_keeps_only_layer_filter():
    repo = _repo()
    repo.search_gold_rescue("q", allowed_ids=None)
    assert _gold_filter(repo.client.last_body) == [{"term": {"layer": "gold"}}]


def test_gold_empty_scope_adds_empty_terms_filter():
    repo = _repo()
    repo.search_gold_rescue("q", allowed_ids=[])
    assert _gold_filter(repo.client.last_body) == [
        {"term": {"layer": "gold"}},
        {"terms": {"id": []}},
    ]


# ── delete_edges_for_entity (unpublish edge cleanup) ─────────────────────────


def test_delete_edges_targets_env_edge_index_and_both_endpoints():
    repo = OpenSearchAskRepository.__new__(OpenSearchAskRepository)
    repo.client = _CaptureClient()
    repo.INDEX_EDGE = "ask-edge-registry-v1-prod"  # env-suffixed
    n = repo.delete_edges_for_entity("silver_x")
    assert n == 2  # from the fake delete_by_query
    assert repo.client.last_index == "ask-edge-registry-v1-prod"
    should = repo.client.last_body["query"]["bool"]["should"]
    assert {"term": {"source_node": "silver_x"}} in should
    assert {"term": {"target_node": "silver_x"}} in should

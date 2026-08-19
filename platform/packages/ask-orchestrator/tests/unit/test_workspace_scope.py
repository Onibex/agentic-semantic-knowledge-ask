# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for env-gated workspace scope resolution (Option B).

The orchestrator's queryable scope = a workspace's data-product membership
INTERSECTED with the entities actually published to the requested env
(``ask-entity-registry-v1-{env}``). These tests pin:

* membership ∩ env-published (an entity in a DP but not published to {env} is
  excluded — the leak the user reported);
* the three-valued contract — ``None`` (unknown workspace) vs ``[]`` (real empty
  scope) vs a populated list;
* env participates in the cache key (dev and prod must not share a result);
* the per-env published-id set is fetched once and reused across workspaces;
* ``env=None`` (legacy/CLI) skips the intersection (back-compat).
"""

from __future__ import annotations

from opensearchpy.exceptions import NotFoundError

from ask_orchestrator.workspace_scope import (
    BASE_ENTITY_REGISTRY,
    INDEX_BUSINESS_DOMAINS,
    INDEX_WORKSPACES,
    WorkspaceScopeProvider,
)


class _FakeClient:
    """Routes get/search by index. Counts entity-registry searches so the
    per-env cache can be asserted."""

    def __init__(
        self,
        *,
        workspaces: dict[str, list[list[str]]],  # slug -> list of BD data_product_ids
        published: dict[str, list[str]],  # full env index name -> entity ids present
        composed: dict[str, list[str]] | None = None,  # entity id -> composed_of
    ) -> None:
        self._workspaces = workspaces
        self._published = published
        self._composed = composed or {}
        self.registry_search_calls: dict[str, int] = {}

    def get(self, index: str, id: str):  # noqa: A002 — mirrors opensearch-py signature
        raise NotFoundError(404, "not_found", {})  # force the slug-search path

    def search(self, index: str, body: dict):
        if index == INDEX_WORKSPACES:
            slug = body["query"]["term"]["slug"]
            if slug in self._workspaces:
                return {"hits": {"hits": [{"_id": slug}]}}
            return {"hits": {"hits": []}}
        if index == INDEX_BUSINESS_DOMAINS:
            ws_id = body["query"]["term"]["workspace_id"]
            bds = self._workspaces.get(ws_id, [])
            return {"hits": {"hits": [{"_source": {"data_product_ids": dp}} for dp in bds]}}
        if index.startswith(BASE_ENTITY_REGISTRY):
            ids = self._published.get(index)
            if ids is None:
                raise NotFoundError(404, "index_not_found_exception", {})
            if "terms" in body["query"]:
                # composed_of expansion fetch (schema-plane scope).
                wanted = body["query"]["terms"]["id"]
                return {
                    "hits": {
                        "hits": [
                            {"_source": {"composed_of": self._composed.get(i, [])}}
                            for i in wanted
                            if i in ids
                        ]
                    }
                }
            self.registry_search_calls[index] = self.registry_search_calls.get(index, 0) + 1
            return {"hits": {"hits": [{"_source": {"id": i}} for i in ids]}}
        raise AssertionError(f"unexpected index {index!r}")


def _provider(workspaces, published) -> WorkspaceScopeProvider:
    return WorkspaceScopeProvider(client=_FakeClient(workspaces=workspaces, published=published))


WS = "ws-sales"
DEV_IDX = f"{BASE_ENTITY_REGISTRY}-dev"
PROD_IDX = f"{BASE_ENTITY_REGISTRY}-prod"


def test_env_intersection_excludes_unpublished():
    p = _provider(
        workspaces={WS: [["a", "b", "c"]]},
        published={DEV_IDX: ["a", "b"], PROD_IDX: ["a"]},
    )
    assert p.get_entity_ids(WS, env="dev") == ["a", "b"]  # c not published to dev
    assert p.get_entity_ids(WS, env="prod") == ["a"]  # only a is in prod


def test_membership_order_preserved_after_intersection():
    p = _provider(
        workspaces={WS: [["c", "a", "b"]]},
        published={DEV_IDX: ["a", "b", "c"]},
    )
    assert p.get_entity_ids(WS, env="dev") == ["c", "a", "b"]


def test_empty_scope_when_nothing_published_is_list_not_none():
    p = _provider(workspaces={WS: [["a"]]}, published={DEV_IDX: ["a"], PROD_IDX: []})
    result = p.get_entity_ids(WS, env="prod")
    assert result == []  # real empty scope
    assert result is not None  # NOT unscoped


def test_env_index_missing_is_empty_scope():
    # prod index not created yet → NotFoundError → empty scope, not a crash.
    p = _provider(workspaces={WS: [["a"]]}, published={DEV_IDX: ["a"]})
    assert p.get_entity_ids(WS, env="prod") == []


def test_unknown_workspace_is_none():
    p = _provider(workspaces={WS: [["a"]]}, published={DEV_IDX: ["a"]})
    assert p.get_entity_ids("ws-ghost", env="dev") is None


def test_schema_scope_expands_composed_of_bronzes():
    """BACKLOG A/D1: the SCHEMA-plane scope = chat membership ∪ composed_of
    bronzes, so a 'describe VBAK' stays answerable when VBAK composes an
    in-scope Silver. The chat scope itself must NOT widen (Bronze is never
    text-to-SQL — REQ_BRONZE_RETRIEVAL_SCOPE)."""
    p = WorkspaceScopeProvider(
        client=_FakeClient(
            workspaces={WS: [["silver_a"]]},
            published={DEV_IDX: ["silver_a", "bronze_x", "bronze_y"]},
            composed={"silver_a": ["bronze_x", "bronze_y"]},
        )
    )
    assert p.get_entity_ids(WS, env="dev") == ["silver_a"]  # chat scope untouched
    assert p.get_schema_entity_ids(WS, env="dev") == ["silver_a", "bronze_x", "bronze_y"]


def test_schema_scope_passes_through_none_and_empty():
    """The three-valued contract survives the expansion: None (unknown
    workspace) and [] (empty scope) are returned as-is, never widened."""
    p = WorkspaceScopeProvider(
        client=_FakeClient(
            workspaces={WS: [["silver_a"]]},
            published={DEV_IDX: ["silver_a"], PROD_IDX: []},
            composed={"silver_a": ["bronze_x"]},
        )
    )
    assert p.get_schema_entity_ids("ws-ghost", env="dev") is None
    assert p.get_schema_entity_ids(WS, env="prod") == []


def test_schema_scope_tolerates_legacy_table_name_refs():
    """Legacy YAMLs carry composed_of as SAP table names (['VBAK']). Those are
    not entity ids and match nothing downstream (the filter is by id) — they
    pass through harmlessly instead of crashing or being resolved by guess."""
    p = WorkspaceScopeProvider(
        client=_FakeClient(
            workspaces={WS: [["silver_a"]]},
            published={DEV_IDX: ["silver_a"]},
            composed={"silver_a": ["VBAK"]},
        )
    )
    assert p.get_schema_entity_ids(WS, env="dev") == ["silver_a", "VBAK"]


def test_env_participates_in_cache_key():
    # Same workspace, different envs must return different results — proves the
    # cache is keyed by (workspace, env), not workspace alone.
    p = _provider(
        workspaces={WS: [["a", "b"]]},
        published={DEV_IDX: ["a", "b"], PROD_IDX: ["a"]},
    )
    dev = p.get_entity_ids(WS, env="dev")
    prod = p.get_entity_ids(WS, env="prod")
    assert dev == ["a", "b"]
    assert prod == ["a"]


def test_env_none_skips_intersection():
    # Legacy/CLI: no env → full membership, no env index queried.
    client = _FakeClient(workspaces={WS: [["a", "b", "c"]]}, published={DEV_IDX: ["a"]})
    p = WorkspaceScopeProvider(client=client)
    assert p.get_entity_ids(WS, env=None) == ["a", "b", "c"]
    assert client.registry_search_calls == {}  # entity registry never touched


def test_per_env_published_ids_cached_across_workspaces():
    client = _FakeClient(
        workspaces={WS: [["a"]], "ws-ops": [["a", "b"]]},
        published={DEV_IDX: ["a", "b"]},
    )
    p = WorkspaceScopeProvider(client=client)
    p.get_entity_ids(WS, env="dev")
    p.get_entity_ids("ws-ops", env="dev")
    p.get_entity_ids(WS, env="dev")  # cached result
    # The dev registry id-set is fetched once and reused for every workspace.
    assert client.registry_search_calls[DEV_IDX] == 1


def test_invalidate_clears_env_cache():
    client = _FakeClient(workspaces={WS: [["a"]]}, published={DEV_IDX: ["a"]})
    p = WorkspaceScopeProvider(client=client)
    p.get_entity_ids(WS, env="dev")
    p.invalidate()  # admin published something → drop env cache
    p.get_entity_ids(WS, env="dev")
    assert client.registry_search_calls[DEV_IDX] == 2  # re-fetched after invalidate

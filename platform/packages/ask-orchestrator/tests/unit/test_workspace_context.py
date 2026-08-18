# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for WorkspaceContextProvider — renders the active workspace +
its business domains as a system-prompt framing block (the modern replacement
for the dead pipeline_v2 descriptions; threaded through organization_context).
"""

from __future__ import annotations

from opensearchpy.exceptions import NotFoundError

from ask_orchestrator.workspace_context import (
    INDEX_BUSINESS_DOMAINS,
    INDEX_WORKSPACES,
    WorkspaceContextProvider,
    _render,
)


class _FakeClient:
    def __init__(self, *, workspaces: dict[str, dict], domains: dict[str, list[dict]]) -> None:
        # workspaces: slug -> {"_id":, "_source": {name, objective, description}}
        self._workspaces = workspaces
        self._domains = domains  # ws_id -> [{name, description}, ...]
        self.bd_search_calls = 0

    def get(self, index, id):  # noqa: A002 — force the slug-search path
        raise NotFoundError(404, "not_found", {})

    def search(self, index, body):
        if index == INDEX_WORKSPACES:
            slug = body["query"]["term"]["slug"]
            ws = self._workspaces.get(slug)
            return {"hits": {"hits": [ws] if ws else []}}
        if index == INDEX_BUSINESS_DOMAINS:
            self.bd_search_calls += 1
            ws_id = body["query"]["term"]["workspace_id"]
            return {"hits": {"hits": [{"_source": d} for d in self._domains.get(ws_id, [])]}}
        raise AssertionError(f"unexpected index {index!r}")


WS = "sales-and-ops"
WS_DOC = {
    "_id": "ws-1",
    "_source": {
        "name": "Sales and Operations",
        "objective": "OTC + SCM analytics",
        "description": "Sales billing KPIs and inventory projections.",
    },
}
DOMAINS = {
    "ws-1": [
        {"name": "Sales Performance", "description": "Monthly billing KPIs by material/plant."},
        {"name": "Inventory Situation", "description": "Daily-projected stock by material/plant."},
    ]
}


def test_render_includes_workspace_and_domains():
    block = _render(WS_DOC["_source"], DOMAINS["ws-1"])
    assert block is not None
    assert "WORKSPACE CONTEXT" in block
    assert "Workspace: Sales and Operations" in block
    assert "Objective: OTC + SCM analytics" in block
    assert "Business domains in scope:" in block
    assert "- Sales Performance: Monthly billing KPIs by material/plant." in block
    assert "- Inventory Situation: Daily-projected stock by material/plant." in block


def test_render_none_when_empty():
    assert _render({}, []) is None


def test_render_domain_without_description():
    block = _render({"name": "WS"}, [{"name": "BareDomain", "description": ""}])
    assert "- BareDomain" in block
    assert "- BareDomain:" not in block  # no trailing colon when no description


def test_provider_resolves_by_slug_and_renders():
    p = WorkspaceContextProvider(client=_FakeClient(workspaces={WS: WS_DOC}, domains=DOMAINS))
    block = p.get_context_text(WS)
    assert "Sales and Operations" in block
    assert "Inventory Situation" in block


def test_unknown_workspace_is_none():
    p = WorkspaceContextProvider(client=_FakeClient(workspaces={WS: WS_DOC}, domains=DOMAINS))
    assert p.get_context_text("ghost") is None


def test_empty_workspace_id_is_none():
    p = WorkspaceContextProvider(client=_FakeClient(workspaces={}, domains={}))
    assert p.get_context_text("") is None


def test_result_is_cached():
    client = _FakeClient(workspaces={WS: WS_DOC}, domains=DOMAINS)
    p = WorkspaceContextProvider(client=client)
    p.get_context_text(WS)
    p.get_context_text(WS)  # cached — no second BD search
    assert client.bd_search_calls == 1

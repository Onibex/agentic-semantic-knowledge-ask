# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Tests for OpenSearchDictionaryWriter using a fake legacy service."""

from __future__ import annotations

import pytest

from ask_knowledge_graph.domain.errors import DictionaryError
from ask_knowledge_graph.domain.ports import DictionaryWriter
from ask_knowledge_graph.infrastructure.opensearch_dictionary_writer import (
    OpenSearchDictionaryWriter,
)


class _FakeService:
    """Records every call so tests can assert forwarding semantics."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {
            "ensure_index": [],
            "upsert_entry": [],
            "list_entries": [],
            "lookup_term": [],
            "ensure_global_index": [],
            "upsert_entry_global": [],
            "search_hybrid": [],
            "lookup_term_global": [],
            "list_entries_global": [],
            "get_field_enrichments": [],
            "get_field_enrichments_bulk": [],
        }
        self.fail_on: str | None = None
        self.return_overrides: dict[str, object] = {}

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise RuntimeError(f"OpenSearch boom on {name}")

    def _ret(self, name: str, default: object) -> object:
        if name in self.return_overrides:
            return self.return_overrides[name]
        return default

    # ── per-Silver-entity ────────────────────────────────────────────────────
    def ensure_index(self, silver_index):
        self.calls["ensure_index"].append(silver_index)
        self._maybe_fail("ensure_index")

    def upsert_entry(self, silver_index, entry):
        self.calls["upsert_entry"].append((silver_index, entry))
        self._maybe_fail("upsert_entry")
        return self._ret("upsert_entry", True)

    def list_entries(self, silver_index):
        self.calls["list_entries"].append(silver_index)
        self._maybe_fail("list_entries")
        return self._ret("list_entries", [{"business_term": "x"}])

    def lookup_term(self, silver_index, business_term):
        self.calls["lookup_term"].append((silver_index, business_term))
        self._maybe_fail("lookup_term")
        return self._ret("lookup_term", {"business_term": business_term})

    # ── global ───────────────────────────────────────────────────────────────
    def ensure_global_index(self):
        self.calls["ensure_global_index"].append(None)
        self._maybe_fail("ensure_global_index")

    def upsert_entry_global(self, entry):
        self.calls["upsert_entry_global"].append(entry)
        self._maybe_fail("upsert_entry_global")
        return self._ret("upsert_entry_global", True)

    def search_hybrid(self, query, query_vector, module=None, entry_type=None, size=10):
        self.calls["search_hybrid"].append((query, query_vector, module, entry_type, size))
        self._maybe_fail("search_hybrid")
        return self._ret("search_hybrid", [{"_score": 1.0}])

    def lookup_term_global(self, business_term):
        self.calls["lookup_term_global"].append(business_term)
        self._maybe_fail("lookup_term_global")
        return self._ret("lookup_term_global", [{"business_term": business_term}])

    def list_entries_global(self, module=None):
        self.calls["list_entries_global"].append(module)
        self._maybe_fail("list_entries_global")
        return self._ret("list_entries_global", [{"business_term": "a"}])

    # ── enrichment ───────────────────────────────────────────────────────────
    def get_field_enrichments(self, entity_id, field_name=None):
        self.calls["get_field_enrichments"].append((entity_id, field_name))
        self._maybe_fail("get_field_enrichments")
        return self._ret("get_field_enrichments", [{"technical_name": "f"}])

    def get_field_enrichments_bulk(self, entity_ids):
        self.calls["get_field_enrichments_bulk"].append(list(entity_ids))
        self._maybe_fail("get_field_enrichments_bulk")
        return self._ret("get_field_enrichments_bulk", {eid: [] for eid in entity_ids})


# ─────────────────────────────────────────────────────────────────────────────
# Protocol satisfaction
# ─────────────────────────────────────────────────────────────────────────────
def test_protocol_satisfied():
    writer: DictionaryWriter = OpenSearchDictionaryWriter(_FakeService())
    assert writer is not None


# ─────────────────────────────────────────────────────────────────────────────
# Forwarding semantics — per-Silver-entity surface
# ─────────────────────────────────────────────────────────────────────────────
def test_ensure_index_forwards():
    svc = _FakeService()
    OpenSearchDictionaryWriter(svc).ensure_index("silver_x")
    assert svc.calls["ensure_index"] == ["silver_x"]


def test_upsert_entry_forwards_and_coerces_bool():
    svc = _FakeService()
    svc.return_overrides["upsert_entry"] = 1  # truthy non-bool → True
    out = OpenSearchDictionaryWriter(svc).upsert_entry("silver_x", {"k": "v"})
    assert out is True
    assert svc.calls["upsert_entry"] == [("silver_x", {"k": "v"})]


def test_list_entries_forwards():
    svc = _FakeService()
    out = OpenSearchDictionaryWriter(svc).list_entries("silver_x")
    assert out == [{"business_term": "x"}]
    assert svc.calls["list_entries"] == ["silver_x"]


def test_list_entries_coerces_none_to_empty():
    svc = _FakeService()
    svc.return_overrides["list_entries"] = None
    out = OpenSearchDictionaryWriter(svc).list_entries("silver_x")
    assert out == []


def test_lookup_term_forwards_and_returns_none():
    svc = _FakeService()
    svc.return_overrides["lookup_term"] = None
    out = OpenSearchDictionaryWriter(svc).lookup_term("silver_x", "term")
    assert out is None
    assert svc.calls["lookup_term"] == [("silver_x", "term")]


# ─────────────────────────────────────────────────────────────────────────────
# Forwarding semantics — global surface
# ─────────────────────────────────────────────────────────────────────────────
def test_ensure_global_index_forwards():
    svc = _FakeService()
    OpenSearchDictionaryWriter(svc).ensure_global_index()
    assert svc.calls["ensure_global_index"] == [None]


def test_upsert_entry_global_forwards():
    svc = _FakeService()
    out = OpenSearchDictionaryWriter(svc).upsert_entry_global({"canonical_label": "x"})
    assert out is True
    assert svc.calls["upsert_entry_global"] == [{"canonical_label": "x"}]


def test_search_hybrid_forwards_all_kwargs():
    svc = _FakeService()
    OpenSearchDictionaryWriter(svc).search_hybrid(
        "delivery", [0.1, 0.2, 0.3], module="sd", entry_type="metric", size=5
    )
    assert svc.calls["search_hybrid"] == [("delivery", [0.1, 0.2, 0.3], "sd", "metric", 5)]


def test_search_hybrid_default_size_and_optional_filters():
    svc = _FakeService()
    OpenSearchDictionaryWriter(svc).search_hybrid("q", [0.0])
    # module=None, entry_type=None, size=10 are the legacy defaults.
    assert svc.calls["search_hybrid"] == [("q", [0.0], None, None, 10)]


def test_lookup_term_global_forwards():
    svc = _FakeService()
    out = OpenSearchDictionaryWriter(svc).lookup_term_global("client")
    assert out == [{"business_term": "client"}]
    assert svc.calls["lookup_term_global"] == ["client"]


def test_list_entries_global_forwards_module_filter():
    svc = _FakeService()
    OpenSearchDictionaryWriter(svc).list_entries_global("SD")
    assert svc.calls["list_entries_global"] == ["SD"]


def test_list_entries_global_no_filter():
    svc = _FakeService()
    OpenSearchDictionaryWriter(svc).list_entries_global()
    assert svc.calls["list_entries_global"] == [None]


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment surface
# ─────────────────────────────────────────────────────────────────────────────
def test_get_field_enrichments_forwards():
    svc = _FakeService()
    OpenSearchDictionaryWriter(svc).get_field_enrichments("silver_x", "net_value")
    assert svc.calls["get_field_enrichments"] == [("silver_x", "net_value")]


def test_get_field_enrichments_bulk_forwards():
    svc = _FakeService()
    out = OpenSearchDictionaryWriter(svc).get_field_enrichments_bulk(["a", "b"])
    assert out == {"a": [], "b": []}
    assert svc.calls["get_field_enrichments_bulk"] == [["a", "b"]]


# ─────────────────────────────────────────────────────────────────────────────
# Error wrapping — every method translates a legacy raise into DictionaryError
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "method,args,fail_method",
    [
        ("ensure_index", ("silver_x",), "ensure_index"),
        ("upsert_entry", ("silver_x", {}), "upsert_entry"),
        ("list_entries", ("silver_x",), "list_entries"),
        ("lookup_term", ("silver_x", "t"), "lookup_term"),
        ("ensure_global_index", (), "ensure_global_index"),
        ("upsert_entry_global", ({},), "upsert_entry_global"),
        ("lookup_term_global", ("t",), "lookup_term_global"),
        ("list_entries_global", (), "list_entries_global"),
        ("get_field_enrichments", ("eid",), "get_field_enrichments"),
        ("get_field_enrichments_bulk", (["a"],), "get_field_enrichments_bulk"),
    ],
)
def test_failures_wrap_in_typed_error(method, args, fail_method):
    svc = _FakeService()
    svc.fail_on = fail_method
    writer = OpenSearchDictionaryWriter(svc)
    with pytest.raises(DictionaryError) as ei:
        getattr(writer, method)(*args)
    assert fail_method in str(ei.value)


def test_search_hybrid_failure_wraps():
    svc = _FakeService()
    svc.fail_on = "search_hybrid"
    with pytest.raises(DictionaryError):
        OpenSearchDictionaryWriter(svc).search_hybrid("q", [0.0])

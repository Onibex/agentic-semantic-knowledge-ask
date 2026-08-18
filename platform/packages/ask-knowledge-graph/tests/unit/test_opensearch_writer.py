# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Tests for OpenSearchKnowledgeGraphWriter using a fake legacy repo."""

from __future__ import annotations

import pytest

from ask_knowledge_graph.domain.errors import IngestionError
from ask_knowledge_graph.domain.ports import KnowledgeGraphWriter
from ask_knowledge_graph.infrastructure.opensearch_writer import (
    OpenSearchKnowledgeGraphWriter,
)


class _FakeRepo:
    def __init__(self):
        self.calls: dict[str, list] = {
            "save_bronze_node": [],
            "save_silver_node": [],
            "save_gold_node": [],
            "delete_entity_and_fields": [],
        }
        self.fail_on: str | None = None

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise RuntimeError(f"OpenSearch boom on {name}")

    def save_bronze_node(self, node, yaml_content):
        self.calls["save_bronze_node"].append((node, yaml_content))
        self._maybe_fail("save_bronze_node")
        return {"entities": 1, "fields": 5, "edges": 0}

    def save_silver_node(self, node, yaml_content, embedder=None):
        self.calls["save_silver_node"].append((node, yaml_content, embedder))
        self._maybe_fail("save_silver_node")
        return {"entities": 1, "fields": 12, "edges": 3}

    def save_gold_node(self, node, yaml_content, embedder=None):
        self.calls["save_gold_node"].append((node, yaml_content, embedder))
        self._maybe_fail("save_gold_node")
        return {"entities": 1, "fields": 8, "edges": 2}

    def delete_entity_and_fields(self, entity_id):
        self.calls["delete_entity_and_fields"].append(entity_id)
        self._maybe_fail("delete_entity_and_fields")
        return {"entities": 1, "fields": 5, "edges": 2}


def test_protocol_satisfied():
    writer: KnowledgeGraphWriter = OpenSearchKnowledgeGraphWriter(_FakeRepo())
    assert writer is not None


def test_save_bronze_forwards_call():
    repo = _FakeRepo()
    writer = OpenSearchKnowledgeGraphWriter(repo)
    stats = writer.save_bronze("the_node", "yaml: bronze")
    assert stats == {"entities": 1, "fields": 5, "edges": 0}
    assert repo.calls["save_bronze_node"] == [("the_node", "yaml: bronze")]


def test_save_silver_forwards_embedder():
    repo = _FakeRepo()
    writer = OpenSearchKnowledgeGraphWriter(repo)
    stats = writer.save_silver("node", "yaml: silver", embedder="emb")
    assert stats["entities"] == 1
    assert repo.calls["save_silver_node"] == [("node", "yaml: silver", "emb")]


def test_save_gold_forwards_embedder():
    repo = _FakeRepo()
    writer = OpenSearchKnowledgeGraphWriter(repo)
    writer.save_gold("node", "yaml: gold", embedder=None)
    assert repo.calls["save_gold_node"] == [("node", "yaml: gold", None)]


def test_writer_has_no_metric_save_path():
    """The `metric` layer was removed — the writer must not expose save_metric."""
    writer = OpenSearchKnowledgeGraphWriter(_FakeRepo())
    assert not hasattr(writer, "save_metric")


def test_delete_entity_returns_stats():
    repo = _FakeRepo()
    writer = OpenSearchKnowledgeGraphWriter(repo)
    stats = writer.delete_entity("silver_x")
    assert stats == {"entities": 1, "fields": 5, "edges": 2}
    assert repo.calls["delete_entity_and_fields"] == ["silver_x"]


@pytest.mark.parametrize(
    "method,fail_method",
    [
        ("save_bronze", "save_bronze_node"),
        ("save_silver", "save_silver_node"),
        ("save_gold", "save_gold_node"),
    ],
)
def test_save_failures_wrap_in_typed_error(method, fail_method):
    repo = _FakeRepo()
    repo.fail_on = fail_method
    writer = OpenSearchKnowledgeGraphWriter(repo)
    with pytest.raises(IngestionError) as ei:
        getattr(writer, method)("node", "yaml")
    assert fail_method in str(ei.value)


def test_delete_failure_wraps_in_typed_error():
    repo = _FakeRepo()
    repo.fail_on = "delete_entity_and_fields"
    writer = OpenSearchKnowledgeGraphWriter(repo)
    with pytest.raises(IngestionError) as ei:
        writer.delete_entity("silver_x")
    assert "silver_x" in str(ei.value)


def test_legacy_returning_none_is_treated_as_empty_stats():
    """Some legacy paths return None on no-op — wrapper coerces to {}."""

    class _NullRepo:
        def save_silver_node(self, *_, **__):
            return None

        # Other methods unused for this test

    writer = OpenSearchKnowledgeGraphWriter(_NullRepo())
    stats = writer.save_silver("node", "yaml")
    assert stats == {}

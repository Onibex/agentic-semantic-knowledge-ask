"""Tests for OpenSearchKnowledgeGraphReader using a fake legacy repo."""

from __future__ import annotations

import pytest

from ask_knowledge_graph.domain.errors import IndexUnavailableError
from ask_knowledge_graph.domain.ports import KnowledgeGraphReader
from ask_knowledge_graph.infrastructure.opensearch_reader import (
    OpenSearchKnowledgeGraphReader,
)


class _FakeClient:
    """Captures mget calls so we assert the request shape."""

    def __init__(self, response: dict):
        self.calls: list[dict] = []
        self._response = response

    def mget(self, *, index, body, _source):
        self.calls.append({"index": index, "body": body, "_source": _source})
        return self._response


class _FakeRepo:
    """Mimics the surface of legacy OpenSearchAskRepository that the reader wraps."""

    def __init__(self, client_response: dict | None = None) -> None:
        self.client = _FakeClient(client_response or {"docs": []})
        self.calls: dict[str, list] = {
            "get_entity_by_id": [],
            "get_lightweight_entities": 0,
            "search_hybrid_rrf": [],
            "search_gold_rescue": [],
            "search_best_field": [],
            "get_all_edges": 0,
        }

    def get_entity_by_id(self, entity_id):
        self.calls["get_entity_by_id"].append(entity_id)
        if entity_id == "missing":
            raise RuntimeError("not found")
        return {"id": entity_id, "raw_yaml": f"yaml-of-{entity_id}"}

    def get_lightweight_entities(self):
        self.calls["get_lightweight_entities"] += 1
        return [{"id": "silver_x"}, {"id": "gold_y"}]

    def search_hybrid_rrf(self, *, text_query, vector_query, size, layers):
        self.calls["search_hybrid_rrf"].append(
            {"text_query": text_query, "vector_query": vector_query, "size": size, "layers": layers}
        )
        return [{"id": "result_1"}]

    def search_gold_rescue(self, text_query, *, size):
        self.calls["search_gold_rescue"].append({"text_query": text_query, "size": size})
        return [{"id": "gold_only"}]

    def search_best_field(self, text_query, vector_query):
        self.calls["search_best_field"].append(
            {"text_query": text_query, "vector_query": vector_query}
        )
        return {"field": "best"}

    def get_all_edges(self):
        self.calls["get_all_edges"] += 1
        return [{"source_node": "A", "target_node": "B"}]


def test_protocol_satisfied():
    reader: KnowledgeGraphReader = OpenSearchKnowledgeGraphReader(_FakeRepo())
    assert reader is not None  # static check; runtime always passes


def test_get_entity_by_id_returns_record():
    reader = OpenSearchKnowledgeGraphReader(_FakeRepo())
    rec = reader.get_entity_by_id("silver_a")
    assert rec is not None and rec["id"] == "silver_a"


def test_get_entity_by_id_returns_none_on_repo_error():
    reader = OpenSearchKnowledgeGraphReader(_FakeRepo())
    assert reader.get_entity_by_id("missing") is None


def test_get_lightweight_entities_returns_list():
    reader = OpenSearchKnowledgeGraphReader(_FakeRepo())
    assert reader.get_lightweight_entities() == [{"id": "silver_x"}, {"id": "gold_y"}]


def test_mget_raw_yaml_empty_input_short_circuits():
    repo = _FakeRepo()
    reader = OpenSearchKnowledgeGraphReader(repo)
    assert reader.mget_raw_yaml([]) == {}
    assert repo.client.calls == []


def test_mget_raw_yaml_returns_dict_keyed_by_id():
    repo = _FakeRepo(
        client_response={
            "docs": [
                {
                    "_id": "silver_a",
                    "found": True,
                    "_source": {"id": "silver_a", "raw_yaml": "yamlA"},
                },
                {
                    "_id": "silver_b",
                    "found": True,
                    "_source": {"id": "silver_b", "raw_yaml": "yamlB"},
                },
                {"_id": "missing", "found": False},
            ]
        }
    )
    reader = OpenSearchKnowledgeGraphReader(repo)
    result = reader.mget_raw_yaml(["silver_a", "silver_b", "missing"])
    assert result == {"silver_a": "yamlA", "silver_b": "yamlB"}
    assert repo.client.calls[0]["body"] == {"ids": ["silver_a", "silver_b", "missing"]}


def test_mget_raw_yaml_skips_docs_without_raw_yaml():
    repo = _FakeRepo(
        client_response={
            "docs": [
                {"_id": "silver_a", "found": True, "_source": {"id": "silver_a"}},  # no raw_yaml
                {
                    "_id": "silver_b",
                    "found": True,
                    "_source": {"id": "silver_b", "raw_yaml": "yamlB"},
                },
            ]
        }
    )
    reader = OpenSearchKnowledgeGraphReader(repo)
    assert reader.mget_raw_yaml(["silver_a", "silver_b"]) == {"silver_b": "yamlB"}


def test_mget_raw_yaml_wraps_index_errors():
    class _BoomClient:
        def mget(self, **kwargs):
            raise RuntimeError("OpenSearch down")

    class _BoomRepo:
        client = _BoomClient()

    reader = OpenSearchKnowledgeGraphReader(_BoomRepo())
    with pytest.raises(IndexUnavailableError):
        reader.mget_raw_yaml(["x"])


def test_search_hybrid_rrf_forwards_args():
    repo = _FakeRepo()
    reader = OpenSearchKnowledgeGraphReader(repo)
    out = reader.search_hybrid_rrf("orders", [0.1, 0.2], size=20, layers=["silver"])
    assert out == [{"id": "result_1"}]
    assert repo.calls["search_hybrid_rrf"] == [
        {"text_query": "orders", "vector_query": [0.1, 0.2], "size": 20, "layers": ["silver"]}
    ]


def test_search_gold_rescue_forwards_args():
    repo = _FakeRepo()
    reader = OpenSearchKnowledgeGraphReader(repo)
    assert reader.search_gold_rescue("orders") == [{"id": "gold_only"}]
    assert repo.calls["search_gold_rescue"][0]["text_query"] == "orders"


def test_get_all_edges_returns_list():
    reader = OpenSearchKnowledgeGraphReader(_FakeRepo())
    assert reader.get_all_edges() == [{"source_node": "A", "target_node": "B"}]

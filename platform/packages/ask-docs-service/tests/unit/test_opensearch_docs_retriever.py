"""Tests for OpenSearchDocsRetriever using a fake OpenSearch client."""

from __future__ import annotations

import pytest

from ask_docs_service.domain.errors import RetrieverUnavailableError
from ask_docs_service.infrastructure.opensearch_docs_retriever import (
    DOC_TYPE_FILTER,
    DOCS_INDEX,
    OpenSearchDocsRetriever,
    _build_query,
)


class _FakeClient:
    def __init__(self, response: dict | None = None, raises: Exception | None = None):
        self.calls: list[dict] = []
        self._response = response or {"hits": {"hits": []}}
        self._raises = raises

    def search(self, *, index, body):
        self.calls.append({"index": index, "body": body})
        if self._raises:
            raise self._raises
        return self._response


def test_no_hits_returns_empty_list():
    retr = OpenSearchDocsRetriever(_FakeClient())
    out = retr.search_data_products(text="x", vector=[0.1, 0.2], top_k=5)
    assert out == []


def test_hits_are_mapped_to_docs_hit():
    client = _FakeClient(
        response={
            "hits": {
                "hits": [
                    {
                        "_id": "abc",
                        "_score": 2.5,
                        "_source": {
                            "text": "Inventory situation describes on-hand stock per plant.",
                            "metadata": {
                                "data_product_name": "Inventory Situation",
                                "source_file": "inventory.pdf",
                                "doc_type": "data_product_documentation",
                            },
                        },
                    },
                    {
                        "_id": "def",
                        "_score": 1.5,
                        "_source": {
                            "text": "Open order tracker shows pending sales orders.",
                            "metadata": {
                                "data_product_name": "Sales Performance",
                                "source_file": "sales.docx",
                                "doc_type": "data_product_documentation",
                            },
                        },
                    },
                ]
            }
        }
    )
    retr = OpenSearchDocsRetriever(client)
    out = retr.search_data_products(text="orders", vector=[0.1, 0.2], top_k=5)
    assert len(out) == 2
    assert out[0].source_file == "inventory.pdf"
    assert out[0].data_product_name == "Inventory Situation"
    assert out[0].chunk_text.startswith("Inventory situation")
    assert out[0].score == 2.5
    assert out[1].source_file == "sales.docx"


def test_hits_without_text_are_dropped():
    client = _FakeClient(
        response={
            "hits": {
                "hits": [
                    {
                        "_id": "a",
                        "_score": 2.5,
                        "_source": {"metadata": {"source_file": "a.pdf"}},
                    },  # no text
                    {
                        "_id": "b",
                        "_score": 1.5,
                        "_source": {"text": "hello", "metadata": {"source_file": "b.pdf"}},
                    },
                ]
            }
        }
    )
    retr = OpenSearchDocsRetriever(client)
    out = retr.search_data_products(text="x", vector=[0.1], top_k=5)
    assert [h.source_file for h in out] == ["b.pdf"]


def test_client_failure_wraps_in_typed_error():
    retr = OpenSearchDocsRetriever(_FakeClient(raises=RuntimeError("OpenSearch unreachable")))
    with pytest.raises(RetrieverUnavailableError) as ei:
        retr.search_data_products(text="x", vector=[0.1], top_k=5)
    assert "OpenSearch unreachable" in str(ei.value)


# ─────────────────────────────────────────────────────────────────────────────
# Query body shape — these tests pin the OpenSearch contract so unintended
# changes to retrieval are caught early.
# ─────────────────────────────────────────────────────────────────────────────
def test_query_body_has_size_and_source_fields():
    body = _build_query(text="x", vector=[0.1], top_k=7)
    assert body["size"] == 7
    assert "text" in body["_source"]
    assert "metadata" in body["_source"]


def test_query_body_filters_by_doc_type():
    body = _build_query(text="x", vector=[0.1], top_k=5)
    filt = body["query"]["bool"]["filter"][0]
    assert filt == {"term": {"metadata.doc_type": DOC_TYPE_FILTER}}


def test_query_body_has_bm25_and_knn_branches():
    body = _build_query(text="orders", vector=[0.1, 0.2], top_k=5)
    shoulds = body["query"]["bool"]["should"]
    assert any("match" in s and "text" in s.get("match", {}) for s in shoulds)
    assert any("knn" in s for s in shoulds)
    knn_clause = next(s for s in shoulds if "knn" in s)
    assert knn_clause["knn"]["embedding"]["k"] == 5
    assert knn_clause["knn"]["embedding"]["vector"] == [0.1, 0.2]


def test_retriever_passes_correct_index_to_client():
    client = _FakeClient()
    retr = OpenSearchDocsRetriever(client)
    retr.search_data_products(text="x", vector=[0.1], top_k=5)
    assert client.calls[0]["index"] == DOCS_INDEX
    assert DOCS_INDEX == "rag-data-product-docs"

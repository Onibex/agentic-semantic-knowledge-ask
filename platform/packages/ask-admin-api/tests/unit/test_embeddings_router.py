"""Router tests for /v1/admin/embeddings/* — fake RagIndexingService."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _FakeIndexResult:
    def __init__(self, indexed: int, batches_sent: int):
        self.indexed = indexed
        self.batches_sent = batches_sent


class _FakeListEntry:
    def __init__(self, source_file, table_name, doc_count, entity_id=None):
        self.source_file = source_file
        self.table_name = table_name
        self.doc_count = doc_count
        self.entity_id = entity_id


class _FakeListResult:
    def __init__(self, collection, total_docs=0, entries=None):
        self.collection = collection
        self.total_docs = total_docs
        self.entries = entries or []


class _FakeDeleteResult:
    def __init__(self, deleted: int):
        self.deleted = deleted


class _FakeRagService:
    """Records calls so tests can assert behaviour without OpenSearch."""

    def __init__(self) -> None:
        self.indexed_chunks: list[list] = []
        self.list_calls: list[str] = []
        self.delete_calls: list[tuple[str, list[str] | None]] = []

    def index_chunks(self, collection, chunks, *, batch_size=64):
        # Mirror the real service's batching loop so the router sees the same
        # batches_sent counter the real code would produce.
        indexed = 0
        batches_sent = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            self.indexed_chunks.append(list(batch))
            indexed += len(batch)
            batches_sent += 1
        return _FakeIndexResult(indexed=indexed, batches_sent=batches_sent)

    def list_sources(self, collection):
        self.list_calls.append(collection)
        return _FakeListResult(
            collection=collection,
            total_docs=3,
            entries=[
                _FakeListEntry("a.pdf", "tbl_a", 2, entity_id="silver_a"),
                _FakeListEntry("b.pdf", None, 1, entity_id=None),
            ],
        )

    def delete_documents(self, collection, source_files=None, entity_ids=None):
        self.delete_calls.append((collection, source_files, entity_ids))
        return _FakeDeleteResult(deleted=7)


@pytest.fixture
def client(monkeypatch):
    """Boot the app with auth bypassed and the RAG service mocked."""
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    fake_service = _FakeRagService()
    from ask_admin_api.routers import embeddings as emb_router

    emb_router._service_singleton = fake_service

    from ask_admin_api.main import app

    yield TestClient(app), fake_service

    emb_router._service_singleton = None
    get_settings.cache_clear()


def test_index_indexes_chunks_and_reports_count(client):
    cli, svc = client
    payload = {
        "collection_name": "rag_schema",
        "documents": [
            {"page_content": f"chunk {i}", "metadata": {"source_file": "doc.pdf"}} for i in range(5)
        ],
        "batch_size": 2,
    }
    resp = cli.post("/v1/admin/embeddings/index", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 5 chunks at batch_size=2 → 3 batches (2,2,1)
    assert body == {"indexed": 5, "batches_sent": 3, "error": None}
    assert sum(len(b) for b in svc.indexed_chunks) == 5
    assert [len(b) for b in svc.indexed_chunks] == [2, 2, 1]


def test_index_empty_documents_short_circuits(client):
    cli, svc = client
    resp = cli.post(
        "/v1/admin/embeddings/index",
        json={"collection_name": "rag_schema", "documents": []},
    )
    assert resp.status_code == 200
    assert resp.json() == {"indexed": 0, "batches_sent": 0, "error": None}
    assert svc.indexed_chunks == []


def test_index_validation_rejects_invalid_batch_size(client):
    cli, _ = client
    resp = cli.post(
        "/v1/admin/embeddings/index",
        json={
            "collection_name": "x",
            "documents": [{"page_content": "a"}],
            "batch_size": 0,  # < 1
        },
    )
    assert resp.status_code == 422


def test_list_returns_aggregated_entries(client):
    cli, svc = client
    resp = cli.get("/v1/admin/embeddings/rag_schema/list")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["collection"] == "rag_schema"
    assert body["total_docs"] == 3
    assert len(body["entries"]) == 2
    assert body["entries"][0]["source_file"] == "a.pdf"
    # entity_id surfaces all the way through — the Browse Catalog UI
    # uses it as the canonical join key against the catalog.
    assert body["entries"][0]["entity_id"] == "silver_a"
    assert body["entries"][1]["entity_id"] is None
    assert svc.list_calls == ["rag_schema"]


def test_delete_with_source_files(client):
    cli, svc = client
    resp = cli.request(
        method="DELETE",
        url="/v1/admin/embeddings/rag_schema",
        json={"source_files": ["a.pdf"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 7, "error": None}
    assert svc.delete_calls == [("rag_schema", ["a.pdf"], None)]


def test_delete_with_entity_ids(client):
    cli, svc = client
    resp = cli.request(
        method="DELETE",
        url="/v1/admin/embeddings/rag_schema",
        json={"entity_ids": ["silver_s4h_sd_sales_order"]},
    )
    assert resp.status_code == 200, resp.text
    assert svc.delete_calls == [
        ("rag_schema", None, ["silver_s4h_sd_sales_order"]),
    ]


def test_delete_without_source_files_wipes_collection(client):
    cli, svc = client
    resp = cli.request(
        method="DELETE",
        url="/v1/admin/embeddings/rag_schema",
        json={"source_files": None},
    )
    assert resp.status_code == 200
    assert svc.delete_calls == [("rag_schema", None, None)]

"""
Router tests for /v1/admin/dictionary — exercises the FastAPI surface end-to-end
with a fake DictionaryWriter, so no OpenSearch / SAP AI Core needed.

Bypass auth via DEV_BYPASS_AUTH=true + ENVIRONMENT=local (the test fixture sets
both, settings cache cleared per-test).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _FakeDictionaryWriter:
    """In-memory stand-in — captures upserts and answers list calls."""

    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.list_calls: list[str | None] = []
        self.deletes: list[str] = []
        self.list_return: list[dict] = [
            {
                "canonical_label": "net value",
                "module": "SD",
                "type": "metric",
                "_id": "SD_s4h_netwr",
            },
            {
                "canonical_label": "order type label",
                "module": "SD",
                "type": "phrase",
                "_id": "SD_s4h_order_type_label",
            },
        ]

    def upsert_entry_global(self, entry: dict) -> bool:
        self.upserts.append(entry)
        return True

    def list_entries_global(self, module: str | None = None) -> list[dict]:
        self.list_calls.append(module)
        if module is None:
            return self.list_return
        return [e for e in self.list_return if e.get("module") == module]

    def delete_entry_global(self, entry_id: str) -> bool:
        self.deletes.append(entry_id)
        # Simulate "not found" for unknown ids.
        return any(e["_id"] == entry_id for e in self.list_return)


@pytest.fixture
def client(monkeypatch):
    """Boot the FastAPI app with auth bypassed and the writer mocked."""
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    # Reset the lazy singleton across tests; inject our fake.
    from ask_admin_api.routers import dictionary as dictionary_router

    dictionary_router._writer_singleton = _FakeDictionaryWriter()

    from ask_admin_api.main import app

    yield TestClient(app), dictionary_router._writer_singleton

    dictionary_router._writer_singleton = None
    get_settings.cache_clear()


def test_upsert_field_mapping_returns_success(client):
    cli, writer = client
    payload = {
        "type": "metric",
        "canonical_label": "Net Value",
        "technical_name": "NETWR",
        "table": "VBAP",
        "module": "SD",
        "synonyms": "revenue, sales amount",
    }
    resp = cli.post("/v1/admin/dictionary", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert "saved" in body["message"].lower()
    # writer captured exactly one upsert with the same canonical label
    assert len(writer.upserts) == 1
    assert writer.upserts[0]["canonical_label"] == "Net Value"
    assert writer.upserts[0]["module"] == "SD"


def test_upsert_writer_returning_false_is_surfaced(client):
    cli, writer = client

    def _refuse(_):
        return False

    writer.upsert_entry_global = _refuse  # type: ignore[method-assign]

    payload = {
        "type": "phrase",
        "canonical_label": "order header details",
        "technical_name": "VBELN, KUNNR",
        "module": "SD",
    }
    resp = cli.post("/v1/admin/dictionary", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "OpenSearch" in body["message"]


def test_list_defaults_to_phrase_type(client):
    """GET /dictionary with no type_filter returns only phrase entries."""
    cli, writer = client
    resp = cli.get("/v1/admin/dictionary")
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body
    # Only the phrase entry should be returned; the metric one is filtered out.
    assert len(body["entries"]) == 1
    assert body["entries"][0]["type"] == "phrase"
    assert body["entries"][0]["canonical_label"] == "order type label"
    assert writer.list_calls == [None]


def test_list_type_filter_metric_returns_metric_entries(client):
    """GET /dictionary?type_filter=metric returns only metric entries."""
    cli, writer = client
    resp = cli.get("/v1/admin/dictionary?type_filter=metric")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["type"] == "metric"
    assert body["entries"][0]["canonical_label"] == "net value"


def test_list_module_filter_combined_with_type_filter(client):
    """module and type_filter are both applied."""
    cli, writer = client
    resp = cli.get("/v1/admin/dictionary?module=SD&type_filter=phrase")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["module"] == "SD"
    assert body["entries"][0]["type"] == "phrase"
    assert writer.list_calls == ["SD"]


def test_list_no_filter_passes_none_to_writer(client):
    """Writer always receives the module filter (None when not supplied)."""
    cli, writer = client
    resp = cli.get("/v1/admin/dictionary?type_filter=metric")
    assert resp.status_code == 200
    assert writer.list_calls == [None]


def test_delete_existing_entry_returns_success(client):
    cli, writer = client
    resp = cli.delete("/v1/admin/dictionary/SD_s4h_order_type_label")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "SD_s4h_order_type_label" in body["message"]
    assert writer.deletes == ["SD_s4h_order_type_label"]


def test_delete_missing_entry_returns_404(client):
    cli, _ = client
    resp = cli.delete("/v1/admin/dictionary/NONEXISTENT_ID")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_upsert_validation_rejects_missing_required_fields(client):
    cli, _ = client
    # canonical_label is required; technical_name is now optional (defaults to "")
    resp = cli.post("/v1/admin/dictionary", json={"type": "metric", "module": "SD"})
    assert resp.status_code == 422

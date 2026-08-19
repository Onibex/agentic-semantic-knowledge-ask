# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Router test for /v1/internal/reload — verifies all admin-api singletons drop."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    # Inject sentinel singletons in every router so reset_singletons can
    # verify they were cleared without needing OpenSearch / SAP AI Core.
    from ask_admin_api.routers import dictionary, embeddings, yaml_ingestion

    dictionary._writer_singleton = object()
    embeddings._service_singleton = object()
    yaml_ingestion._service_singleton = object()
    yaml_ingestion._reader_singletons[None] = object()
    yaml_ingestion._rag_service_singleton = object()

    from ask_admin_api.main import app

    yield TestClient(app)

    dictionary._writer_singleton = None
    embeddings._service_singleton = None
    yaml_ingestion._service_singleton = None
    yaml_ingestion._reader_singletons.clear()
    yaml_ingestion._rag_service_singleton = None
    get_settings.cache_clear()


def test_reload_clears_every_router_singleton(client):
    resp = client.post("/v1/internal/reload")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["service"] == "ask-admin-api"
    assert body["errors"] == []
    # Each router contributed at least one cleared scope.
    cleared = set(body["cleared"])
    assert "dictionary_writer" in cleared
    assert "rag_indexing_service" in cleared  # embeddings router scope
    assert "ingestion_service" in cleared
    assert "kg_reader" in cleared
    # The yaml_ingestion router also caches its own RAG service for the
    # unified ingest-full endpoint — its scope name matches the embeddings
    # one because they're the same service type. count >= 2 confirms both
    # routers contributed it.
    assert sum(1 for c in body["cleared"] if c == "rag_indexing_service") == 2

    # And the singletons themselves are now None.
    from ask_admin_api.routers import dictionary, embeddings, yaml_ingestion

    assert dictionary._writer_singleton is None
    assert embeddings._service_singleton is None
    assert yaml_ingestion._service_singleton is None
    assert not yaml_ingestion._reader_singletons
    assert yaml_ingestion._rag_service_singleton is None


def test_reload_is_idempotent(client):
    # First call clears.
    r1 = client.post("/v1/internal/reload")
    assert r1.status_code == 200
    cleared_first = list(r1.json()["cleared"])
    assert len(cleared_first) >= 5

    # Second call returns 200 with empty `cleared` (nothing left to clear)
    # and no errors.
    r2 = client.post("/v1/internal/reload")
    assert r2.status_code == 200
    body = r2.json()
    assert body["cleared"] == []
    assert body["errors"] == []

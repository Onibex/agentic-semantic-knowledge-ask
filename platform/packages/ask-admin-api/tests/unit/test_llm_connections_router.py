"""Tests for the multi-LLM connection registry — ``/v1/admin/secrets/llm/...``.

Covers the 2026-07 registry model: N named LLM connections + a single-valued
``llm_active`` pointer (one global active — NO dev/prod), the ``/providers``
metadata reuse, the in-process probe, the projection of the active connection
into the canonical ``llm`` doc, and the one-time legacy ``llm`` singleton import.

Runs the real FastAPI app against an in-memory fake OpenSearch that also
implements ``search`` (the registry list path needs it).
"""

from __future__ import annotations

from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

_TEST_KEY = Fernet.generate_key().decode()


class _FakeOpenSearch:
    """In-memory stand-in with get/index/delete/search + indices."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.indices_state: set[str] = set()
        self.indices = _FakeIndicesClient(self)

    def get(self, *, index: str, id: str):  # noqa: A002
        key = (index, id)
        if key not in self.docs:
            from opensearchpy.exceptions import NotFoundError

            raise NotFoundError(404, "not_found", "doc not found")
        return {"_source": self.docs[key]}

    def index(self, *, index: str, id: str, body, refresh=None):  # noqa: A002
        self.docs[(index, id)] = dict(body)
        return {"result": "created"}

    def delete(self, *, index: str, id: str, refresh=None):  # noqa: A002
        self.docs.pop((index, id), None)
        return {"result": "deleted"}

    def search(self, *, index: str, body=None):  # noqa: ARG002
        hits = [
            {"_id": doc_id, "_source": src}
            for (idx, doc_id), src in self.docs.items()
            if idx == index
        ]
        return {"hits": {"hits": hits}}


class _FakeIndicesClient:
    def __init__(self, parent: _FakeOpenSearch) -> None:
        self._parent = parent

    def exists(self, *, index: str) -> bool:
        return index in self._parent.indices_state

    def create(self, *, index: str, body) -> dict:  # noqa: ARG002
        self._parent.indices_state.add(index)
        return {"acknowledged": True}


@pytest.fixture
def client(monkeypatch) -> TestClient:
    from ask_llm_gateway.infrastructure.secrets import crypto, provider, repository

    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, _TEST_KEY)
    crypto.reset_cache_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    fake = _FakeOpenSearch()
    monkeypatch.setattr(repository, "_build_client", lambda: fake)
    provider.set_secrets_provider_for_tests(None)

    from ask_admin_api.routers import secrets as secrets_router

    secrets_router._REPO = None

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.main import app

    with TestClient(app) as c:
        yield c

    provider.set_secrets_provider_for_tests(None)


_ANTHROPIC = {
    "name": "Claude Sonnet 5",
    "provider": "anthropic",
    "model": "claude-sonnet-5",
    "fields": {"api_key": "sk-ant-secret"},
}
_OPENAI = {
    "name": "GPT-4o fallback",
    "provider": "openai",
    "model": "gpt-4o",
    "fields": {"api_key": "sk-openai-secret", "api_base": "https://api.openai.com/v1"},
}


# ── create / list ─────────────────────────────────────────────────────────────


def test_create_masks_secret_and_lists(client: TestClient):
    created = client.post("/v1/admin/secrets/llm/connections", json=_ANTHROPIC)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["id"].startswith("llmconn:")
    assert body["name"] == "Claude Sonnet 5"
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-sonnet-5"
    assert body["configured"] is True
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["api_key"]["value"] == ""  # sensitive → blank
    assert by_name["api_key"]["source"] == "encrypted"
    assert "sk-ant-secret" not in created.text  # no plaintext / ciphertext leak

    listed = client.get("/v1/admin/secrets/llm/connections").json()
    assert len(listed["connections"]) == 1
    assert listed["active"] == {"active": None}


def test_provider_fields_come_from_shared_providers_endpoint(client: TestClient):
    resp = client.get("/v1/admin/secrets/providers")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()["providers"]}
    assert {"openai", "anthropic", "bedrock", "sap_aicore"} <= ids


# ── set active projects into the canonical llm doc ────────────────────────────


def test_set_active_projects_into_llm_doc(client: TestClient):
    cid = client.post("/v1/admin/secrets/llm/connections", json=_ANTHROPIC).json()["id"]
    resp = client.put("/v1/admin/secrets/llm/connections/active", json={"active": cid})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"active": cid}

    # Reflected in the list …
    active = client.get("/v1/admin/secrets/llm/connections").json()["active"]
    assert active["active"] == cid

    # … and PROJECTED into the canonical `llm` doc the runtime reads.
    llm = client.get("/v1/admin/secrets/llm").json()
    assert llm["provider"] == "anthropic"
    assert llm["model"] == "claude-sonnet-5"
    by_name = {f["name"]: f for f in llm["fields"]}
    assert by_name["api_key"]["source"] == "encrypted"  # ciphertext carried over


def test_set_active_unknown_id_is_400(client: TestClient):
    resp = client.put("/v1/admin/secrets/llm/connections/active", json={"active": "llmconn:nope"})
    assert resp.status_code == 400


def test_set_active_null_clears_projection(client: TestClient):
    cid = client.post("/v1/admin/secrets/llm/connections", json=_ANTHROPIC).json()["id"]
    client.put("/v1/admin/secrets/llm/connections/active", json={"active": cid}).raise_for_status()
    client.put("/v1/admin/secrets/llm/connections/active", json={"active": None}).raise_for_status()

    active = client.get("/v1/admin/secrets/llm/connections").json()["active"]
    assert active["active"] is None
    # Projection emptied → runtime reports "no LLM configured".
    llm = client.get("/v1/admin/secrets/llm").json()
    assert llm["provider"] == ""


# ── update / re-projection ────────────────────────────────────────────────────


def test_update_preserves_blank_secret_and_reprojects_active(client: TestClient):
    cid = client.post("/v1/admin/secrets/llm/connections", json=_ANTHROPIC).json()["id"]
    client.put("/v1/admin/secrets/llm/connections/active", json={"active": cid}).raise_for_status()

    # Change model, leave api_key blank → keep stored secret.
    upd = client.put(
        f"/v1/admin/secrets/llm/connections/{cid}",
        json={
            "name": "Claude (renamed)",
            "provider": "anthropic",
            "model": "claude-opus-4-8",
            "fields": {"api_key": ""},
        },
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["name"] == "Claude (renamed)"
    assert body["model"] == "claude-opus-4-8"
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["api_key"]["source"] == "encrypted"  # still stored

    # Active projection followed the edit.
    llm = client.get("/v1/admin/secrets/llm").json()
    assert llm["model"] == "claude-opus-4-8"


def test_update_missing_connection_is_404(client: TestClient):
    resp = client.put(
        "/v1/admin/secrets/llm/connections/llmconn:ghost",
        json={"name": "x", "provider": "openai", "model": "gpt-4o", "fields": {}},
    )
    assert resp.status_code == 404


def test_update_non_active_does_not_touch_projection(client: TestClient):
    active_id = client.post("/v1/admin/secrets/llm/connections", json=_ANTHROPIC).json()["id"]
    other_id = client.post("/v1/admin/secrets/llm/connections", json=_OPENAI).json()["id"]
    client.put(
        "/v1/admin/secrets/llm/connections/active", json={"active": active_id}
    ).raise_for_status()

    client.put(
        f"/v1/admin/secrets/llm/connections/{other_id}",
        json={"name": "GPT-4o v2", "provider": "openai", "model": "gpt-4.1", "fields": {}},
    ).raise_for_status()

    # Projection still reflects the ACTIVE (anthropic) connection, not the edit.
    llm = client.get("/v1/admin/secrets/llm").json()
    assert llm["provider"] == "anthropic"


# ── delete ─────────────────────────────────────────────────────────────────────


def test_delete_active_clears_pointer_and_projection(client: TestClient):
    cid = client.post("/v1/admin/secrets/llm/connections", json=_ANTHROPIC).json()["id"]
    client.put("/v1/admin/secrets/llm/connections/active", json={"active": cid}).raise_for_status()

    dele = client.delete(f"/v1/admin/secrets/llm/connections/{cid}")
    assert dele.status_code == 200
    assert dele.json() == {"id": cid, "deleted": True}

    after = client.get("/v1/admin/secrets/llm/connections").json()
    assert after["connections"] == []
    assert after["active"] == {"active": None}
    # Projection emptied.
    assert client.get("/v1/admin/secrets/llm").json()["provider"] == ""


# ── legacy import (singleton llm → registry, projection KEPT) ─────────────────


def test_legacy_llm_imported_on_first_list_and_kept_as_projection(client: TestClient):
    # Seed a legacy singleton via the canonical PUT /llm.
    client.put(
        "/v1/admin/secrets/llm",
        json={"provider": "openai", "model": "gpt-4o", "fields": {"api_key": "sk-legacy"}},
    ).raise_for_status()

    listed = client.get("/v1/admin/secrets/llm/connections").json()
    assert len(listed["connections"]) == 1
    conn = listed["connections"][0]
    assert conn["provider"] == "openai"
    assert conn["model"] == "gpt-4o"
    assert listed["active"]["active"] == conn["id"]  # imported connection is active

    # The `llm` projection is KEPT (unlike the DB import which drops db_dev/db_prod).
    llm = client.get("/v1/admin/secrets/llm").json()
    assert llm["provider"] == "openai"

    # Second list does NOT re-import (idempotent).
    again = client.get("/v1/admin/secrets/llm/connections").json()
    assert len(again["connections"]) == 1


# ── in-process probe (build_llm_probe stubbed) ────────────────────────────────


def test_connection_probe_uses_build_llm_probe(client: TestClient, monkeypatch):
    cid = client.post("/v1/admin/secrets/llm/connections", json=_ANTHROPIC).json()["id"]

    captured: dict[str, Any] = {}

    class _FakeLLM:
        def invoke(self, msg):
            captured["invoked"] = msg
            return "ok"

    def _fake_probe(provider: str, model: str, fields: dict):
        captured["provider"] = provider
        captured["model"] = model
        captured["fields"] = fields
        return _FakeLLM()

    monkeypatch.setattr("ask_llm_gateway.application.factory.build_llm_probe", _fake_probe)

    resp = client.post(f"/v1/admin/secrets/llm/connections/{cid}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["provider"] == "anthropic"
    # The decrypted secret reached the probe (server-side only).
    assert captured["fields"]["api_key"] == "sk-ant-secret"


def test_connection_probe_missing_connection_is_404(client: TestClient):
    resp = client.post("/v1/admin/secrets/llm/connections/llmconn:ghost/test")
    assert resp.status_code == 404

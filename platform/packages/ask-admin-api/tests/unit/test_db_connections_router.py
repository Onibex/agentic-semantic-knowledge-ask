"""Tests for the multi-DB connection registry — ``/v1/admin/secrets/db/...``.

Covers the 2026-07 registry model: N named connections + a ``db_active`` pointer
(one active per env), the ``/db/providers`` metadata endpoint, the connection
probe, and the one-time legacy ``db_dev`` / ``db_prod`` → registry import.

Runs the real FastAPI app against an in-memory fake OpenSearch that also
implements ``search`` (the registry list path needs it).
"""

from __future__ import annotations

import sys
import types
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


_SNOWFLAKE = {
    "name": "Snowflake Prod",
    "db_type": "snowflake",
    "fields": {
        "account": "xy123.eu-central-1",
        "user": "ASK_SVC",
        "password": "s3cr3t-token",
        "warehouse": "WH_BI",
        "database": "MARTS",
        "schema": "SALES",
    },
}


# ── /db/providers metadata ────────────────────────────────────────────────────


def test_db_providers_lists_all_engines(client: TestClient):
    resp = client.get("/v1/admin/secrets/db/providers")
    assert resp.status_code == 200, resp.text
    providers = {p["id"]: p for p in resp.json()["providers"]}
    assert {
        "postgresql",
        "hana",
        "snowflake",
        "databricks",
        "bigquery",
        "clickhouse",
        "sqlserver",
        "db2",
        "fabric",
    } <= set(providers)
    # Field specs carry name + sensitive + kind.
    pg = providers["postgresql"]
    by_name = {f["name"]: f for f in pg["fields"]}
    assert by_name["password"]["sensitive"] is True
    assert by_name["port"]["kind"] == "int"
    assert providers["clickhouse"]["fields"]  # has bool kinds
    ch = {f["name"]: f for f in providers["clickhouse"]["fields"]}
    assert ch["secure"]["kind"] == "bool"


# ── create / list / activate ──────────────────────────────────────────────────


def test_create_masks_secret_and_lists(client: TestClient):
    created = client.post("/v1/admin/secrets/db/connections", json=_SNOWFLAKE)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["id"].startswith("dbconn:")
    assert body["name"] == "Snowflake Prod"
    assert body["db_type"] == "snowflake"
    assert body["configured"] is True
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["password"]["value"] == ""  # sensitive → blank
    assert by_name["password"]["source"] == "encrypted"
    assert by_name["account"]["value"] == "xy123.eu-central-1"
    # No plaintext / ciphertext leak.
    assert "s3cr3t-token" not in created.text

    listed = client.get("/v1/admin/secrets/db/connections")
    assert listed.status_code == 200
    lst = listed.json()
    assert len(lst["connections"]) == 1
    assert lst["active"] == {"dev": None, "prod": None}


def test_set_active_per_env(client: TestClient):
    cid = client.post("/v1/admin/secrets/db/connections", json=_SNOWFLAKE).json()["id"]
    resp = client.put("/v1/admin/secrets/db/connections/active", json={"dev": cid, "prod": None})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"dev": cid, "prod": None}
    # Reflected in the list.
    active = client.get("/v1/admin/secrets/db/connections").json()["active"]
    assert active["dev"] == cid
    assert active["prod"] is None


def test_set_active_unknown_id_is_400(client: TestClient):
    resp = client.put(
        "/v1/admin/secrets/db/connections/active",
        json={"dev": "dbconn:does-not-exist", "prod": None},
    )
    assert resp.status_code == 400


# ── update / delete ───────────────────────────────────────────────────────────


def test_update_preserves_blank_secret(client: TestClient):
    cid = client.post("/v1/admin/secrets/db/connections", json=_SNOWFLAKE).json()["id"]
    # Rename + change warehouse, leave password blank → keep stored secret.
    upd = client.put(
        f"/v1/admin/secrets/db/connections/{cid}",
        json={
            "name": "Snowflake Prod (renamed)",
            "db_type": "snowflake",
            "fields": {
                "account": "xy123.eu-central-1",
                "user": "ASK_SVC",
                "password": "",
                "warehouse": "WH_NEW",
                "database": "MARTS",
                "schema": "SALES",
            },
        },
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["name"] == "Snowflake Prod (renamed)"
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["warehouse"]["value"] == "WH_NEW"
    assert by_name["password"]["source"] == "encrypted"  # still stored


def test_update_missing_connection_is_404(client: TestClient):
    resp = client.put(
        "/v1/admin/secrets/db/connections/dbconn:nope",
        json={"name": "x", "db_type": "hana", "fields": {}},
    )
    assert resp.status_code == 404


def test_delete_clears_active_slot(client: TestClient):
    cid = client.post("/v1/admin/secrets/db/connections", json=_SNOWFLAKE).json()["id"]
    client.put(
        "/v1/admin/secrets/db/connections/active", json={"dev": cid, "prod": cid}
    ).raise_for_status()
    dele = client.delete(f"/v1/admin/secrets/db/connections/{cid}")
    assert dele.status_code == 200
    assert dele.json() == {"id": cid, "deleted": True}
    after = client.get("/v1/admin/secrets/db/connections").json()
    assert after["connections"] == []
    assert after["active"] == {"dev": None, "prod": None}


# ── orchestrator invalidation (cross-container cache) ────────────────────────


def test_db_mutations_notify_orchestrator(client: TestClient, monkeypatch):
    """Activating / editing-the-active / deleting-the-active connection must
    POST the orchestrator's /v1/internal/reload.

    The orchestrator is a different container whose SecretsProvider caches the
    ``db_active`` pointer + connection docs — without the notify, a database
    switch from the UI only lands after the 60 s TTL (the exact defect the LLM
    registry endpoints had before they gained the call).
    """
    from ask_admin_api.routers import secrets as secrets_router

    calls: list[str] = []
    monkeypatch.setattr(
        secrets_router, "_notify_orchestrator_reload", lambda trace_id: calls.append(trace_id)
    )

    cid = client.post("/v1/admin/secrets/db/connections", json=_SNOWFLAKE).json()["id"]
    assert calls == []  # creating an (inactive) connection changes nothing at runtime

    client.put(
        "/v1/admin/secrets/db/connections/active", json={"dev": cid, "prod": None}
    ).raise_for_status()
    assert len(calls) == 1  # switch → notify

    client.put(f"/v1/admin/secrets/db/connections/{cid}", json=_SNOWFLAKE).raise_for_status()
    assert len(calls) == 2  # editing the ACTIVE connection → notify

    client.delete(f"/v1/admin/secrets/db/connections/{cid}").raise_for_status()
    assert len(calls) == 3  # deleting the ACTIVE connection clears the slot → notify


def test_update_inactive_connection_does_not_notify(client: TestClient, monkeypatch):
    from ask_admin_api.routers import secrets as secrets_router

    calls: list[str] = []
    monkeypatch.setattr(
        secrets_router, "_notify_orchestrator_reload", lambda trace_id: calls.append(trace_id)
    )
    cid = client.post("/v1/admin/secrets/db/connections", json=_SNOWFLAKE).json()["id"]
    client.put(f"/v1/admin/secrets/db/connections/{cid}", json=_SNOWFLAKE).raise_for_status()
    client.delete(f"/v1/admin/secrets/db/connections/{cid}").raise_for_status()
    assert calls == []  # nothing here touched the active pointer


# ── legacy import (db_dev / db_prod → registry) ───────────────────────────────


def test_legacy_docs_imported_on_first_list(client: TestClient):
    # Seed a legacy dev doc via the old endpoint.
    client.put(
        "/v1/admin/secrets/db/dev",
        json={
            "db_type": "hana",
            "fields": {"host": "legacy.host", "port": "443", "user": "u", "password": "p"},
        },
    ).raise_for_status()

    listed = client.get("/v1/admin/secrets/db/connections").json()
    assert len(listed["connections"]) == 1
    conn = listed["connections"][0]
    assert conn["db_type"] == "hana"
    assert "dev" in conn["name"].lower()
    # It is now active for dev, and the legacy doc was removed.
    assert listed["active"]["dev"] == conn["id"]
    legacy = client.get("/v1/admin/secrets/db/dev").json()
    assert legacy["configured"] is False

    # Second list does NOT re-import (idempotent).
    again = client.get("/v1/admin/secrets/db/connections").json()
    assert len(again["connections"]) == 1


# ── connection probe (drivers stubbed) ────────────────────────────────────────


def test_connection_probe_uses_executor(client: TestClient, monkeypatch):
    cid = client.post("/v1/admin/secrets/db/connections", json=_SNOWFLAKE).json()["id"]

    # Inject a fake ask_sql_executor.infrastructure.db_utils so the probe path
    # runs without real DB drivers.
    captured: dict[str, Any] = {}

    def _fake_test_connection(db_type: str, config: dict):
        captured["db_type"] = db_type
        captured["config"] = config
        return True, "snowflake connection successful."

    mod = types.ModuleType("ask_sql_executor.infrastructure.db_utils")
    mod.test_connection = _fake_test_connection  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ask_sql_executor.infrastructure.db_utils", mod)

    resp = client.post(f"/v1/admin/secrets/db/connections/{cid}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["db_type"] == "snowflake"
    # The decrypted secret reached the probe (server-side only).
    assert captured["config"]["password"] == "s3cr3t-token"
    assert captured["config"]["account"] == "xy123.eu-central-1"


def test_connection_probe_missing_connection_is_404(client: TestClient):
    resp = client.post("/v1/admin/secrets/db/connections/dbconn:ghost/test")
    assert resp.status_code == 404

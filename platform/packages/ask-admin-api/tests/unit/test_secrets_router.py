"""Smoke tests for ``/v1/admin/secrets/*``.

Run the real FastAPI app against an in-memory fake OpenSearch (no network).
The router code path — PUT splits plain/encrypted via the registry, GET masks
encrypted values, the runtime cache invalidates after writes — is the contract
under test. The encrypted-secrets boundary tests (crypto round-trip, registry
lookup) live in ``ask-llm-gateway/tests/unit/test_secrets.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

_TEST_KEY = Fernet.generate_key().decode()


class _FakeOpenSearch:
    """Minimal in-memory stand-in. Only the methods the repo touches are wired."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.indices_state: set[str] = set()
        self.indices = _FakeIndicesClient(self)

    def get(self, *, index: str, id: str):  # noqa: A002 — matches OS API
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


class _FakeIndicesClient:
    def __init__(self, parent: _FakeOpenSearch) -> None:
        self._parent = parent

    def exists(self, *, index: str) -> bool:
        return index in self._parent.indices_state

    def create(self, *, index: str, body) -> dict:  # noqa: ARG002
        self._parent.indices_state.add(index)
        return {"acknowledged": True}


@pytest.fixture
def secrets_client(monkeypatch) -> TestClient:
    """Boot admin-api with auth bypassed + fake OpenSearch wired into the repo."""
    from ask_llm_gateway.infrastructure.secrets import crypto, provider, repository

    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, _TEST_KEY)
    crypto.reset_cache_for_tests()
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    # Clear provider env vars so source resolution sees a clean slate (other
    # tests in this session may have set them via export_to_env).
    for env_name in (
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
        "AWS_REGION_NAME",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "LLM_API_KEY",
        "LLM_API_BASE",
        "LLM_API_VERSION",
        "EMBEDDER_API_KEY",
        "EMBEDDER_API_BASE",
    ):
        monkeypatch.delenv(env_name, raising=False)

    fake = _FakeOpenSearch()
    monkeypatch.setattr(repository, "_build_client", lambda: fake)
    # Reset the global SecretsProvider so it picks up the fake repo.
    provider.set_secrets_provider_for_tests(None)
    # Reset router-level singleton too.
    from ask_admin_api.routers import secrets as secrets_router

    secrets_router._REPO = None
    from ask_admin_api.routers import setup_effective as setup_router

    setup_router._REPO = None

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.main import app

    with TestClient(app) as client:
        yield client

    provider.set_secrets_provider_for_tests(None)


# ── GET on empty store ──────────────────────────────────────────────────────


def test_get_llm_returns_empty_view_when_nothing_stored(secrets_client: TestClient):
    resp = secrets_client.get("/v1/admin/secrets/llm")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "target": "llm",
        "provider": "",
        "model": "",
        "fields": [],
        "updated_at": "",
        "updated_by": "",
    }


# ── PUT splits plain vs encrypted ───────────────────────────────────────────


def test_put_llm_persists_and_masks_sensitive_fields(secrets_client: TestClient):
    """PUT a Bedrock config → GET returns AWS_BEARER_TOKEN_BEDROCK masked + AWS_REGION plain."""
    payload = {
        "provider": "bedrock",
        "model": "bedrock/converse/us.amazon.nova-lite-v1:0",
        "fields": {
            "AWS_BEARER_TOKEN_BEDROCK": "ABSK_supersecret",
            "AWS_REGION": "us-east-2",
        },
    }
    resp = secrets_client.put("/v1/admin/secrets/llm", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "bedrock"
    assert body["model"] == payload["model"]

    field_by_name = {f["name"]: f for f in body["fields"]}
    assert field_by_name["AWS_BEARER_TOKEN_BEDROCK"]["value"] == "***"
    assert field_by_name["AWS_BEARER_TOKEN_BEDROCK"]["source"] == "encrypted"
    assert field_by_name["AWS_BEARER_TOKEN_BEDROCK"]["sensitive"] is True
    assert field_by_name["AWS_REGION"]["value"] == "us-east-2"
    assert field_by_name["AWS_REGION"]["source"] == "plain"
    assert field_by_name["AWS_REGION"]["sensitive"] is False

    # The raw token (Fernet) MUST NOT leak through the API.
    assert "ABSK_supersecret" not in resp.text


def test_put_then_get_matches(secrets_client: TestClient):
    payload = {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "fields": {"api_key": "sk-ant-test"},
    }
    secrets_client.put("/v1/admin/secrets/llm", json=payload).raise_for_status()
    resp = secrets_client.get("/v1/admin/secrets/llm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-haiku-4-5"
    api_key = next(f for f in body["fields"] if f["name"] == "api_key")
    assert api_key["value"] == "***"
    assert api_key["source"] == "encrypted"


def test_put_unknown_provider_field_is_dropped(secrets_client: TestClient):
    """A field not declared in the registry for this provider must not be saved."""
    secrets_client.put(
        "/v1/admin/secrets/llm",
        json={
            "provider": "openai",
            "model": "gpt-4o",
            "fields": {
                "api_key": "sk-foo",
                "AWS_BEARER_TOKEN_BEDROCK": "should_not_persist",
            },
        },
    ).raise_for_status()
    body = secrets_client.get("/v1/admin/secrets/llm").json()
    names = {f["name"] for f in body["fields"]}
    # openai registry declares api_key + api_base only.
    assert names == {"api_key", "api_base"}


def test_put_embedder_separate_from_llm(secrets_client: TestClient):
    """LLM and Embedder docs are independent singletons (different _id)."""
    secrets_client.put(
        "/v1/admin/secrets/llm",
        json={"provider": "openai", "model": "gpt-4o", "fields": {"api_key": "sk-llm"}},
    ).raise_for_status()
    secrets_client.put(
        "/v1/admin/secrets/embedder",
        json={
            "provider": "openai",
            "model": "text-embedding-3-large",
            "fields": {"api_key": "sk-embedder"},
        },
    ).raise_for_status()

    llm = secrets_client.get("/v1/admin/secrets/llm").json()
    embedder = secrets_client.get("/v1/admin/secrets/embedder").json()
    assert llm["model"] == "gpt-4o"
    assert embedder["model"] == "text-embedding-3-large"


# ── setup_effective consumes the new store ──────────────────────────────────


def test_setup_effective_reflects_secrets_store(secrets_client: TestClient):
    secrets_client.put(
        "/v1/admin/secrets/llm",
        json={
            "provider": "bedrock",
            "model": "bedrock/converse/us.amazon.nova-lite-v1:0",
            "fields": {"AWS_BEARER_TOKEN_BEDROCK": "xxx", "AWS_REGION": "us-east-2"},
        },
    ).raise_for_status()
    resp = secrets_client.get("/v1/admin/setup/effective")
    assert resp.status_code == 200
    sections = {s["id"]: s for s in resp.json()["sections"]}
    llm_section = sections["llm"]
    assert llm_section["provider"] == "bedrock"
    field_by_name = {f["name"]: f for f in llm_section["fields"]}
    assert field_by_name["AWS_BEARER_TOKEN_BEDROCK"]["value"] == "***"
    assert field_by_name["AWS_BEARER_TOKEN_BEDROCK"]["source"] == "encrypted"
    assert field_by_name["AWS_REGION"]["value"] == "us-east-2"
    assert field_by_name["AWS_REGION"]["source"] == "plain"


# ── DB config secrets (per-environment) — 2026-07 migration ──────────────────


def test_get_db_returns_empty_view_when_nothing_stored(secrets_client: TestClient):
    resp = secrets_client.get("/v1/admin/secrets/db/dev")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["env"] == "dev"
    assert body["db_type"] == ""
    assert body["fields"] == []
    assert body["configured"] is False


def test_get_db_invalid_env_is_400(secrets_client: TestClient):
    resp = secrets_client.get("/v1/admin/secrets/db/staging")
    assert resp.status_code == 400


def test_put_db_persists_and_masks_password(secrets_client: TestClient):
    payload = {
        "db_type": "hana",
        "fields": {
            "host": "abc.hanacloud.ondemand.com",
            "port": "443",
            "user": "DBADMIN",
            "password": "s3cr3t",
            "schema": "MY_SCHEMA",
        },
    }
    resp = secrets_client.put("/v1/admin/secrets/db/dev", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["db_type"] == "hana"
    assert body["configured"] is True

    by_name = {f["name"]: f for f in body["fields"]}
    # Password is sensitive → returned blank, marked stored.
    assert by_name["password"]["value"] == ""
    assert by_name["password"]["sensitive"] is True
    assert by_name["password"]["source"] == "encrypted"
    # Host is plain → real value round-trips.
    assert by_name["host"]["value"] == "abc.hanacloud.ondemand.com"
    assert by_name["host"]["source"] == "plain"

    # The raw password MUST NOT leak (neither plaintext nor Fernet token).
    assert "s3cr3t" not in resp.text


def test_put_db_preserves_blank_password_on_edit(secrets_client: TestClient):
    """Editing host without re-typing the password keeps the stored secret."""
    secrets_client.put(
        "/v1/admin/secrets/db/dev",
        json={
            "db_type": "hana",
            "fields": {"host": "old.host", "port": "443", "user": "u", "password": "keep-me"},
        },
    ).raise_for_status()

    # Re-save with a new host + BLANK password.
    resp = secrets_client.put(
        "/v1/admin/secrets/db/dev",
        json={
            "db_type": "hana",
            "fields": {"host": "new.host", "port": "443", "user": "u", "password": ""},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_name = {f["name"]: f for f in body["fields"]}
    assert by_name["host"]["value"] == "new.host"
    # Password still present (source encrypted) despite the blank submit.
    assert by_name["password"]["source"] == "encrypted"


def test_put_db_dev_and_prod_are_independent(secrets_client: TestClient):
    secrets_client.put(
        "/v1/admin/secrets/db/dev",
        json={
            "db_type": "hana",
            "fields": {"host": "dev.host", "port": "443", "user": "u", "password": "p"},
        },
    ).raise_for_status()
    secrets_client.put(
        "/v1/admin/secrets/db/prod",
        json={
            "db_type": "hana",
            "fields": {"host": "prod.host", "port": "443", "user": "u", "password": "p"},
        },
    ).raise_for_status()

    dev = secrets_client.get("/v1/admin/secrets/db/dev").json()
    prod = secrets_client.get("/v1/admin/secrets/db/prod").json()
    dev_host = next(f for f in dev["fields"] if f["name"] == "host")["value"]
    prod_host = next(f for f in prod["fields"] if f["name"] == "host")["value"]
    assert dev_host == "dev.host"
    assert prod_host == "prod.host"


def test_delete_db_prod_clears_it(secrets_client: TestClient):
    secrets_client.put(
        "/v1/admin/secrets/db/prod",
        json={
            "db_type": "hana",
            "fields": {"host": "prod.host", "port": "443", "user": "u", "password": "p"},
        },
    ).raise_for_status()
    del_resp = secrets_client.delete("/v1/admin/secrets/db/prod")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    body = secrets_client.get("/v1/admin/secrets/db/prod").json()
    assert body["configured"] is False


def test_put_db_drops_undeclared_fields(secrets_client: TestClient):
    """A field not in the hana DB registry must not be stored."""
    secrets_client.put(
        "/v1/admin/secrets/db/dev",
        json={
            "db_type": "hana",
            "fields": {"host": "h", "port": "443", "user": "u", "password": "p", "bogus": "x"},
        },
    ).raise_for_status()
    body = secrets_client.get("/v1/admin/secrets/db/dev").json()
    names = {f["name"] for f in body["fields"]}
    # hana registry: host, port, user, password, schema — no 'bogus'.
    assert "bogus" not in names
    assert {"host", "port", "user", "password", "schema"} == names

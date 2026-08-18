# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for the encrypted-secrets backend.

Cover:
  * crypto.py — round-trip, fail-closed on missing / malformed key, key mismatch
  * registry.py — sensitive bit lookup
  * repository.py — plain/encrypted split via the registry (without OpenSearch)
  * provider.py — cache + export_to_env (mocked repo)

OpenSearch is NOT touched — the repository's split logic lives in pure
functions that can be exercised directly. End-to-end tests live in the
admin-api router tests with a real OpenSearch.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

# Generate a stable key once per session so all tests share a master.
_TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _master_key(monkeypatch):
    """Seed the env var + reset the cached Fernet so each test starts clean."""
    from ask_llm_gateway.infrastructure.secrets import crypto

    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, _TEST_KEY)
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


# ── crypto.py ────────────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    from ask_llm_gateway.infrastructure.secrets import crypto

    plaintext = "AWS_BEARER_TOKEN_BEDROCK_value_xyz"
    token = crypto.encrypt(plaintext)
    assert token != plaintext
    assert crypto.decrypt(token) == plaintext


def test_decrypt_with_wrong_key_raises_permission_error(monkeypatch):
    from ask_llm_gateway.infrastructure.secrets import crypto

    token = crypto.encrypt("secret")
    # Rotate the key — old token must no longer decrypt.
    new_key = Fernet.generate_key().decode()
    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, new_key)
    crypto.reset_cache_for_tests()
    with pytest.raises(PermissionError, match="ENCRYPTION_KEY_MISMATCH"):
        crypto.decrypt(token)


def test_missing_master_key_aborts_at_first_use(monkeypatch):
    from ask_llm_gateway.infrastructure.secrets import crypto

    monkeypatch.delenv(crypto.ENCRYPTION_KEY_ENV, raising=False)
    crypto.reset_cache_for_tests()
    with pytest.raises(SystemExit, match="ENCRYPTION_KEY_MISSING"):
        crypto.encrypt("anything")


def test_malformed_master_key_aborts_at_first_use(monkeypatch):
    from ask_llm_gateway.infrastructure.secrets import crypto

    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, "not-a-real-fernet-key")
    crypto.reset_cache_for_tests()
    with pytest.raises(SystemExit, match="ENCRYPTION_KEY_INVALID_FORMAT"):
        crypto.encrypt("anything")


# ── registry.py ──────────────────────────────────────────────────────────────


def test_registry_marks_bedrock_aws_token_sensitive():
    from ask_llm_gateway.infrastructure.secrets import registry

    entries = dict(registry.provider_fields("bedrock"))
    assert entries["AWS_BEARER_TOKEN_BEDROCK"] is True
    assert entries["AWS_REGION"] is False


def test_registry_unknown_provider_returns_empty_list():
    from ask_llm_gateway.infrastructure.secrets import registry

    assert registry.provider_fields("not-a-real-provider") == []


# ── repository.py — split logic ──────────────────────────────────────────────


def test_repository_split_routes_fields_by_registry():
    """The split helper sends sensitive fields through Fernet + drops unknowns."""
    from ask_llm_gateway.infrastructure.secrets import crypto, repository

    plain, encrypted = repository._split_by_registry(
        "bedrock",
        {
            "AWS_BEARER_TOKEN_BEDROCK": "ABSK_token_value",
            "AWS_REGION": "us-east-2",
            "unknown_field": "garbage",  # not in registry → dropped
            "AWS_ACCESS_KEY_ID": "AKIA...",
        },
    )
    assert plain == {"AWS_REGION": "us-east-2"}
    # Encrypted fields are present as Fernet tokens — verify by round-trip.
    assert set(encrypted.keys()) == {"AWS_BEARER_TOKEN_BEDROCK", "AWS_ACCESS_KEY_ID"}
    assert crypto.decrypt(encrypted["AWS_BEARER_TOKEN_BEDROCK"]) == "ABSK_token_value"


def test_repository_split_drops_empty_values():
    """Empty string = "delete this field" — should NOT make it into either bucket."""
    from ask_llm_gateway.infrastructure.secrets import repository

    plain, encrypted = repository._split_by_registry(
        "openai",
        {"api_key": "", "api_base": "https://x.openai.com"},
    )
    assert plain == {"api_base": "https://x.openai.com"}
    assert encrypted == {}


# ── provider.py — cache + export_to_env ──────────────────────────────────────


class _FakeRepo:
    def __init__(self, resolved):
        self._resolved = resolved
        self.calls = 0

    def get_resolved(self, target):  # noqa: ARG002 — signature compat
        self.calls += 1
        return self._resolved


def test_provider_caches_repository_reads():
    from ask_llm_gateway.infrastructure.secrets.provider import SecretsProvider

    repo = _FakeRepo({"provider": "anthropic", "model": "claude", "fields": {}})
    provider = SecretsProvider(repository=repo, ttl_seconds=60)
    provider.get("llm")
    provider.get("llm")
    assert repo.calls == 1, "second get() should hit the cache"


def test_provider_invalidate_drops_cache():
    from ask_llm_gateway.infrastructure.secrets.provider import SecretsProvider

    repo = _FakeRepo({"provider": "anthropic", "model": "claude", "fields": {}})
    provider = SecretsProvider(repository=repo, ttl_seconds=60)
    provider.get("llm")
    provider.invalidate("llm")
    provider.get("llm")
    assert repo.calls == 2


def test_provider_export_to_env_uses_prefixed_names(monkeypatch):
    """Convenience fields (api_key, api_base) get the LLM_/EMBEDDER_ prefix."""
    from ask_llm_gateway.infrastructure.secrets.provider import SecretsProvider

    repo = _FakeRepo(
        {
            "provider": "anthropic",
            "model": "claude",
            "fields": {"api_key": "sk-foo", "api_base": "https://api.anthropic.com"},
        }
    )
    provider = SecretsProvider(repository=repo)

    # Pre-clean so a previous test cannot leak state.
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_BASE", raising=False)

    written = provider.export_to_env("llm")
    assert "LLM_API_KEY" in written
    assert "LLM_API_BASE" in written

    import os

    assert os.environ["LLM_API_KEY"] == "sk-foo"
    assert os.environ["LLM_API_BASE"] == "https://api.anthropic.com"


def test_provider_export_to_env_keeps_aws_vars_verbatim(monkeypatch):
    """Provider-specific vars (AWS_*, VERTEXAI_*) must keep their original names."""
    from ask_llm_gateway.infrastructure.secrets.provider import SecretsProvider

    repo = _FakeRepo(
        {
            "provider": "bedrock",
            "model": "bedrock/...",
            "fields": {
                "AWS_BEARER_TOKEN_BEDROCK": "ABSK_...",
                "AWS_REGION": "us-east-2",
            },
        }
    )
    provider = SecretsProvider(repository=repo)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)

    written = provider.export_to_env("llm")
    assert "AWS_BEARER_TOKEN_BEDROCK" in written
    assert "AWS_REGION" in written

    import os

    assert os.environ["AWS_BEARER_TOKEN_BEDROCK"] == "ABSK_..."
    assert os.environ["AWS_REGION"] == "us-east-2"


# ── DB registry (2026-07 DB-config migration) ────────────────────────────────


def test_db_registry_marks_password_sensitive_and_port_int():
    from ask_llm_gateway.infrastructure.secrets import registry

    entries = {
        name: (sensitive, kind) for name, sensitive, kind in registry.db_provider_fields("hana")
    }
    assert entries["password"][0] is True
    assert entries["host"][0] is False
    assert entries["port"][1] == "int"


def test_db_registry_bigquery_credentials_json_is_encrypted():
    from ask_llm_gateway.infrastructure.secrets import registry

    entries = {
        name: sensitive for name, sensitive, _kind in registry.db_provider_fields("bigquery")
    }
    assert entries["credentials_json"] is True
    assert entries["credentials_path"] is False  # a path, not the key material


def test_db_registry_does_not_collide_with_llm_databricks():
    """`databricks` exists in both planes with different fields — no bleed."""
    from ask_llm_gateway.infrastructure.secrets import registry

    llm_fields = {name for name, _s in registry.provider_fields("databricks")}
    db_fields = {name for name, _s, _k in registry.db_provider_fields("databricks")}
    assert "api_key" in llm_fields
    assert "access_token" in db_fields
    assert "access_token" not in llm_fields


def test_db_registry_unknown_returns_empty():
    from ask_llm_gateway.infrastructure.secrets import registry

    assert registry.db_provider_fields("not-a-db") == []


# ── repository split under a DB target ───────────────────────────────────────


def test_repository_split_uses_db_registry_for_db_target():
    from ask_llm_gateway.infrastructure.secrets import crypto, repository

    plain, encrypted = repository._split_by_registry(
        "hana",
        {"host": "h.example", "port": "443", "password": "p@ss", "bogus": "drop"},
        target="db_dev",
    )
    assert plain == {"host": "h.example", "port": "443"}
    assert set(encrypted) == {"password"}
    assert crypto.decrypt(encrypted["password"]) == "p@ss"


# ── resolve_db_config (store-backed read path) ───────────────────────────────


class _FakeByTargetRepo:
    """get_resolved keyed by target — models db_dev configured, db_prod absent."""

    def __init__(self, by_target: dict):
        self._by = by_target

    def get_resolved(self, target):
        return self._by.get(target)


def _db_provider(by_target: dict):
    from ask_llm_gateway.infrastructure.secrets.provider import SecretsProvider

    return SecretsProvider(repository=_FakeByTargetRepo(by_target))


def test_resolve_db_config_coerces_types_and_reads_dev():
    from ask_llm_gateway.infrastructure.secrets.db_config import resolve_db_config

    provider = _db_provider(
        {
            "db_dev": {
                "provider": "clickhouse",
                "fields": {"host": "h", "port": "8443", "secure": "False", "final": "True"},
            }
        }
    )
    db_type, cfg = resolve_db_config("dev", provider=provider)
    assert db_type == "clickhouse"
    assert cfg["port"] == 8443  # int-coerced from "8443"
    assert cfg["secure"] is False  # "False" → bool False (not truthy string)
    assert cfg["final"] is True


def test_resolve_db_config_prod_unconfigured_is_empty():
    from ask_llm_gateway.infrastructure.secrets.db_config import (
        is_db_configured,
        resolve_db_config,
    )

    provider = _db_provider(
        {"db_dev": {"provider": "hana", "fields": {"host": "h", "password": "p"}}}
    )
    # prod not in the store → unconfigured (empty), never inherits dev.
    db_type, cfg = resolve_db_config("prod", provider=provider)
    assert cfg == {}
    assert is_db_configured("prod", provider=provider) is False
    assert is_db_configured("dev", provider=provider) is True


def test_resolve_db_config_env_none_reads_dev():
    from ask_llm_gateway.infrastructure.secrets.db_config import resolve_db_config

    provider = _db_provider(
        {"db_dev": {"provider": "postgresql", "fields": {"host": "h", "port": "5432"}}}
    )
    db_type, cfg = resolve_db_config(None, provider=provider)
    assert db_type == "postgresql"
    assert cfg["port"] == 5432


# ── resolve via the active-connection pointer (multi-DB registry) ─────────────


def test_resolve_db_config_via_active_pointer_per_env():
    """The pointer can route dev and prod to DIFFERENT engines."""
    from ask_llm_gateway.infrastructure.secrets.db_config import resolve_db_config

    provider = _db_provider(
        {
            "db_active": {"provider": "", "fields": {"dev": "dbconn:aa", "prod": "dbconn:bb"}},
            "dbconn:aa": {"provider": "snowflake", "fields": {"account": "acc", "warehouse": "w"}},
            "dbconn:bb": {"provider": "hana", "fields": {"host": "h", "port": "443"}},
        }
    )
    dev_type, dev_cfg = resolve_db_config("dev", provider=provider)
    prod_type, prod_cfg = resolve_db_config("prod", provider=provider)
    assert dev_type == "snowflake"
    assert dev_cfg["account"] == "acc"
    assert prod_type == "hana"
    assert prod_cfg["port"] == 443  # int-coerced


def test_resolve_db_config_pointer_takes_priority_over_legacy():
    from ask_llm_gateway.infrastructure.secrets.db_config import resolve_db_config

    provider = _db_provider(
        {
            "db_active": {"provider": "", "fields": {"dev": "dbconn:new"}},
            "dbconn:new": {"provider": "databricks", "fields": {"server_hostname": "x"}},
            "db_dev": {"provider": "postgresql", "fields": {"host": "legacy"}},
        }
    )
    db_type, cfg = resolve_db_config("dev", provider=provider)
    assert db_type == "databricks"  # pointer wins over the stale legacy doc


def test_resolve_db_config_pointer_to_missing_conn_falls_back_to_legacy():
    from ask_llm_gateway.infrastructure.secrets.db_config import resolve_db_config

    provider = _db_provider(
        {
            "db_active": {"provider": "", "fields": {"dev": "dbconn:gone"}},
            "db_dev": {"provider": "hana", "fields": {"host": "h", "password": "p"}},
        }
    )
    db_type, cfg = resolve_db_config("dev", provider=provider)
    assert db_type == "hana"  # dangling pointer → legacy fallback
    assert cfg["host"] == "h"


# ── LLM connection registry (2026-07 multi-LLM, single active) ────────────────


class _FakeOSClient:
    """Minimal in-memory OpenSearch stand-in for the repository's client calls."""

    class _Indices:
        def __init__(self) -> None:
            self.created = True

        def exists(self, index):  # noqa: ARG002
            return self.created

        def create(self, index, body=None):  # noqa: ARG002
            self.created = True

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}
        self.indices = _FakeOSClient._Indices()

    def get(self, index, id):  # noqa: A002 — mirrors the OpenSearch client kwarg
        from opensearchpy.exceptions import NotFoundError

        if id not in self._docs:
            raise NotFoundError(404, "not_found")
        return {"_source": dict(self._docs[id])}

    def index(self, index, id, body, refresh=None):  # noqa: A002, ARG002
        self._docs[id] = dict(body)

    def delete(self, index, id, refresh=None):  # noqa: A002, ARG002
        from opensearchpy.exceptions import NotFoundError

        if id not in self._docs:
            raise NotFoundError(404, "not_found")
        del self._docs[id]

    def search(self, index, body=None):  # noqa: ARG002
        hits = [{"_id": k, "_source": dict(v)} for k, v in self._docs.items()]
        return {"hits": {"hits": hits}}


def _llm_repo():
    from ask_llm_gateway.infrastructure.secrets.repository import SecretsRepository

    return SecretsRepository(client=_FakeOSClient())


def test_validate_target_accepts_llm_registry_ids():
    from ask_llm_gateway.infrastructure.secrets import repository as r

    r._validate_target("llm_active")  # no raise
    r._validate_target("llmconn:abc123")  # no raise
    with pytest.raises(ValueError):
        r._validate_target("bogus:xyz")


def test_repository_split_uses_llm_registry_for_llmconn_target():
    """A ``llmconn:*`` target routes through the LLM registry, not the DB one."""
    from ask_llm_gateway.infrastructure.secrets import crypto, repository

    plain, encrypted = repository._split_by_registry(
        "openai",
        {"api_key": "sk-x", "api_base": "https://x", "password": "drop"},
        target="llmconn:abc",
    )
    assert plain == {"api_base": "https://x"}
    assert set(encrypted) == {"api_key"}  # 'password' is not an openai field → dropped
    assert crypto.decrypt(encrypted["api_key"]) == "sk-x"


def test_llm_active_pointer_roundtrip_and_clear():
    repo = _llm_repo()
    assert repo.get_active_llm() is None
    repo.set_active_llm("llmconn:aa", updated_by="me")
    assert repo.get_active_llm() == "llmconn:aa"
    repo.set_active_llm(None, updated_by="me")
    assert repo.get_active_llm() is None


def test_project_active_llm_copies_connection_into_llm_doc():
    """Projection copies provider/model/plain/encrypted verbatim (ciphertext kept)."""
    repo = _llm_repo()
    repo.upsert_raw(
        "llmconn:aa",
        {
            "provider": "bedrock",
            "model": "bedrock/nova",
            "plain": {"AWS_REGION": "us-east-1"},
            "encrypted": {"AWS_ACCESS_KEY_ID": "gAAA-cipher"},
            "name": "Nova",
            "kind": "llm_connection",
        },
    )
    projected = repo.project_active_llm("llmconn:aa", updated_by="me")
    assert projected["provider"] == "bedrock"

    llm_doc = repo.get_raw("llm")
    assert llm_doc["provider"] == "bedrock"
    assert llm_doc["model"] == "bedrock/nova"
    assert llm_doc["plain"] == {"AWS_REGION": "us-east-1"}
    assert llm_doc["encrypted"] == {"AWS_ACCESS_KEY_ID": "gAAA-cipher"}  # ciphertext preserved
    assert "name" not in llm_doc  # name/kind stripped from the runtime projection
    assert "kind" not in llm_doc


def test_project_active_llm_none_writes_empty_provider():
    repo = _llm_repo()
    repo.upsert_raw("llm", {"provider": "openai", "model": "gpt-4o", "plain": {}, "encrypted": {}})
    repo.project_active_llm(None, updated_by="me")
    llm_doc = repo.get_raw("llm")
    assert llm_doc["provider"] == ""  # deterministic "no LLM configured"
    assert llm_doc["model"] == ""


def test_project_active_llm_missing_conn_writes_empty_provider():
    repo = _llm_repo()
    repo.project_active_llm("llmconn:gone", updated_by="me")
    assert repo.get_raw("llm")["provider"] == ""


def test_list_llm_connections_filters_prefix_and_sorts_by_updated_at():
    repo = _llm_repo()
    repo.upsert_raw(
        "llmconn:b",
        {
            "provider": "openai",
            "model": "m",
            "plain": {},
            "encrypted": {},
            "updated_at": "2026-07-02",
        },
    )
    repo.upsert_raw(
        "llmconn:a",
        {
            "provider": "anthropic",
            "model": "m",
            "plain": {},
            "encrypted": {},
            "updated_at": "2026-07-01",
        },
    )
    # Other planes in the SAME index must be excluded.
    repo.upsert_raw(
        "dbconn:x",
        {"provider": "hana", "plain": {}, "encrypted": {}, "updated_at": "2026-07-03"},
    )
    repo.upsert_raw("embedder", {"provider": "openai", "plain": {}, "encrypted": {}})

    conns = repo.list_llm_connections()
    ids = [cid for cid, _ in conns]
    assert ids == ["llmconn:a", "llmconn:b"]  # sorted asc by updated_at; dbconn/embedder excluded


# ── export_fields_to_env (public probe helper) ───────────────────────────────


def test_export_fields_to_env_prefixes_llm_and_keeps_aws_verbatim(monkeypatch):
    import os

    from ask_llm_gateway.infrastructure.secrets import export_fields_to_env

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    written = export_fields_to_env("llm", {"api_key": "sk-1", "AWS_REGION": "us-east-1"})
    assert "LLM_API_KEY" in written
    assert "AWS_REGION" in written
    assert os.environ["LLM_API_KEY"] == "sk-1"
    assert os.environ["AWS_REGION"] == "us-east-1"


# ── build_llm_probe (connection /test path) ──────────────────────────────────


def test_build_llm_probe_seeds_env_and_calls_litellm(monkeypatch):
    import os

    from ask_llm_gateway.application import factory

    captured: dict = {}

    def _fake_build(**kwargs):
        captured.update(kwargs)
        return "CHAT"

    monkeypatch.setattr(
        "ask_llm_gateway.infrastructure.litellm_llm.build_litellm_chat", _fake_build
    )
    monkeypatch.delenv("AWS_REGION", raising=False)

    out = factory.build_llm_probe(
        "bedrock", "bedrock/nova", {"AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "AKIA"}
    )
    assert out == "CHAT"
    assert os.environ["AWS_REGION"] == "us-east-1"  # env seeded for the env-var provider
    assert captured["provider"] == "bedrock"
    assert captured["model"] == "bedrock/nova"


def test_build_llm_probe_empty_provider_raises():
    from ask_llm_gateway.application import factory

    with pytest.raises(ValueError):
        factory.build_llm_probe("", "m", {})

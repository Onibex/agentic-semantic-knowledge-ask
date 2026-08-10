"""
Unit tests for ``factory.llm_revision`` / ``factory.embedder_revision``.

Why this exists
───────────────
``build_llm`` bakes ``model=`` into the ``ChatLiteLLM`` constructor, so every
consumer that caches a build_llm-derived object (a prompt|llm|parser chain, a
SQL generator, a strategy bundle) pins itself to the model that was active when
it was built. Before the revision key, switching the active LLM in ASK Setup had
NO runtime effect until the process restarted — the store said one model and the
answers came from another.

These tests pin the contract those caches rely on: the fingerprint must change
whenever anything that would produce a different LLM changes, and must stay
stable otherwise (or every request would rebuild).
"""

from __future__ import annotations

import pytest


class _FakeByTargetRepo:
    """``get_resolved`` keyed by target — mirrors the fixture in test_secrets."""

    def __init__(self, by_target: dict):
        self.by_target = by_target

    def get_resolved(self, target):
        return self.by_target.get(target)


@pytest.fixture
def store(monkeypatch):
    """Install a fake secrets store as the process-wide provider.

    Returns the mutable ``by_target`` dict so a test can rewrite a doc and
    observe the fingerprint move. TTL is 0 so every read re-hits the fake repo —
    the cache itself is covered in test_secrets.
    """
    from ask_llm_gateway.infrastructure.secrets.provider import (
        SecretsProvider,
        set_secrets_provider_for_tests,
    )

    by_target: dict = {}
    set_secrets_provider_for_tests(
        SecretsProvider(repository=_FakeByTargetRepo(by_target), ttl_seconds=0)
    )
    # Env overrides outrank the store — make sure a developer's shell or a
    # previous test cannot leak into these assertions.
    for var in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_MAX_TOKENS",
        "EMBEDDER_PROVIDER",
        "EMBEDDER_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield by_target
    set_secrets_provider_for_tests(None)


# ── llm_revision ─────────────────────────────────────────────────────────────


def test_llm_revision_empty_when_nothing_stored(store):
    """No secrets doc = the legacy settings.json plane, which is not
    fingerprinted (it keeps using the explicit /v1/internal/reload hook)."""
    from ask_llm_gateway.application.factory import llm_revision

    assert llm_revision() == ""


def test_llm_revision_is_stable_for_an_unchanged_doc(store):
    """Must NOT change between calls, or every request would rebuild its LLM."""
    from ask_llm_gateway.application.factory import llm_revision

    store["llm"] = {
        "provider": "bedrock",
        "model": "converse/us.amazon.nova-pro-v1:0",
        "fields": {},
        "updated_at": "2026-08-03T22:35:13+00:00",
    }
    assert llm_revision() == llm_revision()
    assert llm_revision() != ""


def test_llm_revision_changes_when_the_active_model_changes(store):
    """The reported bug: activating a different connection must move the
    fingerprint so cached chains rebuild."""
    from ask_llm_gateway.application.factory import llm_revision

    store["llm"] = {
        "provider": "bedrock",
        "model": "converse/us.amazon.nova-pro-v1:0",
        "fields": {},
        "updated_at": "2026-08-03T22:35:13+00:00",
    }
    before = llm_revision()

    # What project_active_llm writes when the admin activates another connection.
    store["llm"] = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "fields": {},
        "updated_at": "2026-08-03T23:10:00+00:00",
    }
    assert llm_revision() != before


def test_llm_revision_changes_on_credential_rotation_alone(store):
    """provider+model identical, only updated_at moved — e.g. the api_key was
    rotated on the active connection. updated_at is the ONLY signal that
    catches this, which is why it is in the fingerprint."""
    from ask_llm_gateway.application.factory import llm_revision

    doc = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "fields": {"api_key": "old"},
        "updated_at": "2026-08-03T21:44:20+00:00",
    }
    store["llm"] = doc
    before = llm_revision()

    store["llm"] = {**doc, "fields": {"api_key": "new"}, "updated_at": "2026-08-03T23:00:00+00:00"}
    assert llm_revision() != before


def test_llm_revision_honours_env_override(store, monkeypatch):
    """LLM_MODEL outranks the store in build_llm, so it must outrank it here
    too — otherwise the fingerprint would describe a model that is not the one
    actually constructed."""
    from ask_llm_gateway.application.factory import llm_revision

    store["llm"] = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "fields": {},
        "updated_at": "2026-08-03T21:44:20+00:00",
    }
    stored = llm_revision()

    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5")
    overridden = llm_revision()
    assert overridden != stored
    assert "claude-haiku-4-5" in overridden


def test_llm_revision_tracks_max_tokens_env(store, monkeypatch):
    """max_tokens is a constructor arg of ChatLiteLLM, so changing it produces a
    different model object and must bust the caches."""
    from ask_llm_gateway.application.factory import llm_revision

    store["llm"] = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "fields": {},
        "updated_at": "2026-08-03T21:44:20+00:00",
    }
    before = llm_revision()
    monkeypatch.setenv("LLM_MAX_TOKENS", "16384")
    assert llm_revision() != before


# ── embedder_revision ────────────────────────────────────────────────────────


def test_embedder_revision_reads_the_embedder_target(store):
    """Independent target: an LLM change must not move the embedder
    fingerprint, or the Precise bundle would rebuild its vectorstore wiring for
    no reason (and vice-versa)."""
    from ask_llm_gateway.application.factory import embedder_revision, llm_revision

    store["embedder"] = {
        "provider": "bedrock",
        "model": "amazon.titan-embed-text-v2:0",
        "fields": {},
        "updated_at": "2026-08-03T13:40:24+00:00",
    }
    emb_before = embedder_revision()
    assert emb_before != ""

    store["llm"] = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "fields": {},
        "updated_at": "2026-08-03T23:00:00+00:00",
    }
    assert embedder_revision() == emb_before
    assert llm_revision() != emb_before


def test_embedder_revision_changes_on_vector_space_change(store):
    from ask_llm_gateway.application.factory import embedder_revision

    store["embedder"] = {
        "provider": "bedrock",
        "model": "amazon.titan-embed-text-v2:0",
        "fields": {},
        "updated_at": "2026-08-03T13:40:24+00:00",
    }
    before = embedder_revision()

    store["embedder"] = {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "fields": {},
        "updated_at": "2026-08-04T09:00:00+00:00",
    }
    assert embedder_revision() != before

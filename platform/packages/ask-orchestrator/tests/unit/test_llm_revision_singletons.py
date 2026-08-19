# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: the orchestrator's LLM-derived singletons must be keyed on the
active-LLM fingerprint.

The bug these pin
────────────────
``build_llm`` has no cache and re-reads the store on every call — but the
CONSUMERS cached its result forever. ``ChatLiteLLM`` bakes ``model=`` into its
constructor, so an admin switching the active LLM in ASK Setup changed the store
while the orchestrator kept answering with the previous model until the process
restarted. Measured 2026-08-03: the store said Nova Pro, the answers came from
Sonnet, and only the per-request builders (``/v1/title``, ``/v1/artifact``)
picked up the switch.

Each test drives the CACHE-HIT path with a sentinel so nothing heavy is built:
same revision → the sentinel is returned; changed revision → the sentinel must
NOT be returned (the code falls through to a real build, which we intercept).
"""

from __future__ import annotations

import pytest

from ask_llm_gateway.application import factory as gateway_factory
from ask_orchestrator.classification.macro_classifier import MacroIntentClassifier
from ask_orchestrator.profile.builder import ProfileBuilder
from ask_orchestrator.routers import query as query_router


@pytest.fixture(autouse=True)
def _clean_singletons():
    """Every test starts and ends with empty caches so ordering cannot leak."""
    query_router.reset_singletons()
    MacroIntentClassifier.reset()
    ProfileBuilder.reset()
    yield
    query_router.reset_singletons()
    MacroIntentClassifier.reset()
    ProfileBuilder.reset()


def _pin_revision(monkeypatch, value: str) -> None:
    """Stub the fingerprint. Consumers import it lazily inside the function, so
    patching the factory attribute is enough."""
    monkeypatch.setattr(gateway_factory, "llm_revision", lambda: value)


def _pin_db_type(monkeypatch, db_type: str = "postgresql") -> None:
    from ask_llm_gateway.infrastructure import secrets as secrets_pkg

    monkeypatch.setattr(secrets_pkg, "resolve_db_config", lambda env: (db_type, {}))


class _StubPath:
    """Stands in for ``Path("config/settings.json")``.

    ``MacroIntentClassifier`` and ``ProfileBuilder`` read settings.json BEFORE
    calling ``build_llm``, and the test process's cwd is the package dir, not the
    repo root — so without this the fall-through would surface as an incidental
    FileNotFoundError instead of reaching the build we want to observe.
    """

    def __init__(self, *_a, **_kw):
        pass

    def read_text(self, *_a, **_kw):
        return "{}"


def _stub_settings(monkeypatch) -> None:
    """Neutralise settings.json reads on every path that does one."""
    import ask_orchestrator.classification.macro_classifier as classifier_mod
    import ask_orchestrator.profile.builder as builder_mod

    monkeypatch.setattr(query_router.SettingsCache, "get", staticmethod(lambda: {}))
    monkeypatch.setattr(classifier_mod, "Path", _StubPath)
    monkeypatch.setattr(builder_mod, "Path", _StubPath)


def _fail_on_build(monkeypatch) -> None:
    """Make a rebuild loudly observable. Reaching this proves the cached entry
    was rejected — which is exactly what the revision key is for."""
    _stub_settings(monkeypatch)

    def _boom(_cfg):
        raise AssertionError("BUILD_ATTEMPTED")

    monkeypatch.setattr(gateway_factory, "build_llm", _boom)


# ── SQL generator (per db_type AND per revision) ─────────────────────────────


def test_sql_generator_is_reused_while_the_revision_is_unchanged(monkeypatch):
    _pin_revision(monkeypatch, "rev-A")
    _pin_db_type(monkeypatch)
    sentinel = object()
    query_router._sql_gen_singletons[("rev-A", "postgresql")] = sentinel

    assert query_router._get_sql_generator("dev") is sentinel


def test_sql_generator_is_rebuilt_when_the_active_llm_changes(monkeypatch):
    """The core regression. A generator built under rev-A must not serve a
    request made under rev-B."""
    _pin_revision(monkeypatch, "rev-B")
    _pin_db_type(monkeypatch)
    query_router._sql_gen_singletons[("rev-A", "postgresql")] = object()
    _fail_on_build(monkeypatch)

    # Falling through to a build is the proof it did not serve the stale entry.
    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        query_router._get_sql_generator("dev")


def test_sql_generator_cache_is_keyed_by_db_type_within_one_revision(monkeypatch):
    """Envs on different engines must still get different generators — the
    revision key must not collapse the pre-existing per-dialect caching."""
    _pin_revision(monkeypatch, "rev-A")
    _pin_db_type(monkeypatch, "hana")
    query_router._sql_gen_singletons[("rev-A", "postgresql")] = object()
    _fail_on_build(monkeypatch)

    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        query_router._get_sql_generator("prod")  # hana → different key → miss


def test_stale_revisions_are_evicted_so_the_cache_cannot_grow(monkeypatch):
    """A long-lived process that has seen several switches must keep at most one
    generator per db_type, not one per (switch × db_type)."""
    _pin_revision(monkeypatch, "rev-B")
    _pin_db_type(monkeypatch)
    query_router._sql_gen_singletons[("rev-A", "postgresql")] = object()
    query_router._sql_gen_singletons[("rev-A", "hana")] = object()

    _stub_settings(monkeypatch)
    monkeypatch.setattr(gateway_factory, "build_llm", lambda _cfg: object())

    class _StubGen:
        def __init__(self, **_kw):
            pass

    import ask_sql_generation.application.sql_generator as sqlgen_mod

    monkeypatch.setattr(sqlgen_mod, "FreeformSqlGenerator", _StubGen)

    query_router._get_sql_generator("dev")

    keys = list(query_router._sql_gen_singletons)
    assert keys == [("rev-B", "postgresql")], f"stale revisions leaked: {keys}"


# ── SQL executor (formatter wraps an LLM) ────────────────────────────────────


def test_sql_executor_is_reused_while_the_revision_is_unchanged(monkeypatch):
    _pin_revision(monkeypatch, "rev-A")
    sentinel = object()
    query_router._sql_exec_singleton = ("rev-A", sentinel)

    assert query_router._get_sql_executor() is sentinel


def test_sql_executor_is_rebuilt_when_the_active_llm_changes(monkeypatch):
    _pin_revision(monkeypatch, "rev-B")
    query_router._sql_exec_singleton = ("rev-A", object())
    _fail_on_build(monkeypatch)

    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        query_router._get_sql_executor()


# ── Macro classifier chain ───────────────────────────────────────────────────


def test_classifier_chain_is_reused_while_the_revision_is_unchanged(monkeypatch):
    _pin_revision(monkeypatch, "rev-A")
    sentinel = ("chain", "parser")
    MacroIntentClassifier._chain = sentinel
    MacroIntentClassifier._chain_revision = "rev-A"

    assert MacroIntentClassifier._get_chain() is sentinel


def test_classifier_chain_is_rebuilt_when_the_active_llm_changes(monkeypatch):
    """Macro classification is itself an LLM call, so a frozen chain means every
    request's FIRST call still goes to the superseded model."""
    _pin_revision(monkeypatch, "rev-B")
    MacroIntentClassifier._chain = ("stale-chain", "stale-parser")
    MacroIntentClassifier._chain_revision = "rev-A"
    _fail_on_build(monkeypatch)

    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        MacroIntentClassifier._get_chain()


def test_classifier_reset_clears_the_revision_too(monkeypatch):
    """A dangling revision after reset() would let the next build be skipped."""
    MacroIntentClassifier._chain = ("chain", "parser")
    MacroIntentClassifier._chain_revision = "rev-A"

    assert MacroIntentClassifier.reset() is True
    assert MacroIntentClassifier._chain is None
    assert MacroIntentClassifier._chain_revision is None


# ── Profile builder ──────────────────────────────────────────────────────────


def test_profile_builder_llm_is_reused_while_the_revision_is_unchanged(monkeypatch):
    _pin_revision(monkeypatch, "rev-A")
    sentinel = object()
    ProfileBuilder._llm = sentinel
    ProfileBuilder._llm_revision = "rev-A"

    assert ProfileBuilder._get_llm() is sentinel


def test_profile_builder_llm_is_rebuilt_when_the_active_llm_changes(monkeypatch):
    _pin_revision(monkeypatch, "rev-B")
    ProfileBuilder._llm = object()
    ProfileBuilder._llm_revision = "rev-A"
    _fail_on_build(monkeypatch)

    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        ProfileBuilder._get_llm()


def test_profile_builder_reset_clears_the_revision_too():
    ProfileBuilder._llm = object()
    ProfileBuilder._llm_revision = "rev-A"

    assert ProfileBuilder.reset() is True
    assert ProfileBuilder._llm is None
    assert ProfileBuilder._llm_revision is None

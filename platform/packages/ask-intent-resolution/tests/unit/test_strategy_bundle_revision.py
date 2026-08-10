"""
Regression tests: the three strategy bundles must be keyed on the active-LLM
fingerprint, not on the publish env alone.

Each bundle wires an LLM (Precise also an embedder) into long-lived services.
``ChatLiteLLM`` bakes ``model=`` into its constructor, so a bundle cached under
env ``dev`` outlived every model switch and pinned the whole chat path to the
model that was active when the process first served a request. Measured
2026-08-03: the store said Nova Pro, the answers came from Sonnet.

The tests drive the CACHE-HIT path with a sentinel so no OpenSearch client,
vectorstore or LLM is ever constructed: same revision → the sentinel comes back;
changed revision → it must NOT, and the fall-through to a real build is
intercepted as proof.
"""

from __future__ import annotations

import pytest

from ask_intent_resolution.flash.strategy import FlashStrategy
from ask_intent_resolution.precise.strategy import PreciseStrategy
from ask_intent_resolution.smart.strategy import SmartStrategy
from ask_llm_gateway.application import factory as gateway_factory

# Precise keys on BOTH fingerprints (it builds an embedder too), so its key is
# "<llm_revision>//<embedder_revision>" while Flash/Smart use the LLM one alone.
_STRATEGIES = [
    pytest.param(FlashStrategy, False, id="flash"),
    pytest.param(SmartStrategy, False, id="smart"),
    pytest.param(PreciseStrategy, True, id="precise"),
]


@pytest.fixture(autouse=True)
def _clean_bundles():
    for cls in (FlashStrategy, SmartStrategy, PreciseStrategy):
        cls.reset()
    yield
    for cls in (FlashStrategy, SmartStrategy, PreciseStrategy):
        cls.reset()


def _pin(monkeypatch, llm_rev: str, emb_rev: str = "emb-A") -> None:
    monkeypatch.setattr(gateway_factory, "llm_revision", lambda: llm_rev)
    monkeypatch.setattr(gateway_factory, "embedder_revision", lambda: emb_rev)


def _key(llm_rev: str, env: str | None, *, with_embedder: bool, emb_rev: str = "emb-A") -> tuple:
    return (f"{llm_rev}//{emb_rev}" if with_embedder else llm_rev, env)


def _fail_on_build(monkeypatch) -> None:
    """Any attempt to build proves the cached bundle was rejected."""

    def _boom(*_a, **_kw):
        raise AssertionError("BUILD_ATTEMPTED")

    monkeypatch.setattr(gateway_factory, "build_llm", _boom)
    monkeypatch.setattr(gateway_factory, "build_embedder", _boom)
    # Every strategy loads settings.json before touching the factory; the reads
    # happen from the test's cwd, so neutralise them to keep the fall-through
    # observable as BUILD_ATTEMPTED rather than an incidental IO error.
    for mod_name in (
        "ask_intent_resolution.flash.strategy",
        "ask_intent_resolution.smart.strategy",
        "ask_intent_resolution.precise.strategy",
    ):
        import importlib

        mod = importlib.import_module(mod_name)
        if hasattr(mod, "_load_settings"):
            monkeypatch.setattr(mod, "_load_settings", lambda: {})


@pytest.mark.parametrize("cls,with_embedder", _STRATEGIES)
def test_bundle_is_reused_while_the_revision_is_unchanged(cls, with_embedder, monkeypatch):
    """No rebuild on an unchanged config — otherwise every request would
    reconstruct OpenSearch clients and vectorstores."""
    _pin(monkeypatch, "rev-A")
    sentinel = {"llm": "stub"}
    cls._bundles[_key("rev-A", "dev", with_embedder=with_embedder)] = sentinel

    assert cls._get_bundle("dev") is sentinel


@pytest.mark.parametrize("cls,with_embedder", _STRATEGIES)
def test_bundle_is_rebuilt_when_the_active_llm_changes(cls, with_embedder, monkeypatch):
    """The core regression."""
    _pin(monkeypatch, "rev-B")
    cls._bundles[_key("rev-A", "dev", with_embedder=with_embedder)] = {"llm": "stale"}
    _fail_on_build(monkeypatch)

    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        cls._get_bundle("dev")


@pytest.mark.parametrize("cls,with_embedder", _STRATEGIES)
def test_bundle_cache_is_still_keyed_by_env(cls, with_embedder, monkeypatch):
    """dev and prod read different env-suffixed indices and may target different
    databases, so adding the revision must not collapse the per-env caching."""
    _pin(monkeypatch, "rev-A")
    cls._bundles[_key("rev-A", "dev", with_embedder=with_embedder)] = {"llm": "dev-bundle"}
    _fail_on_build(monkeypatch)

    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        cls._get_bundle("prod")


def test_precise_bundle_is_rebuilt_when_only_the_embedder_changes(monkeypatch):
    """Precise wires an embedder into the entity resolver, semantic dictionary
    and fase1 graph. Switching the embedder changes the vector space, so a
    bundle built against the previous one must not be reused."""
    _pin(monkeypatch, "rev-A", emb_rev="emb-B")
    PreciseStrategy._bundles[_key("rev-A", "dev", with_embedder=True, emb_rev="emb-A")] = {
        "llm": "stale"
    }
    _fail_on_build(monkeypatch)

    with pytest.raises(AssertionError, match="BUILD_ATTEMPTED"):
        PreciseStrategy._get_bundle("dev")


def test_flash_bundle_ignores_embedder_revision(monkeypatch):
    """Flash builds no embedder, so an embedder change must NOT churn its bundle
    (it would needlessly rebuild the vectorstore + SQL executor)."""
    _pin(monkeypatch, "rev-A", emb_rev="emb-A")
    sentinel = {"llm": "stub"}
    FlashStrategy._bundles[("rev-A", "dev")] = sentinel

    _pin(monkeypatch, "rev-A", emb_rev="emb-Z")
    assert FlashStrategy._get_bundle("dev") is sentinel

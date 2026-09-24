# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Minimal smoke test for ask-llm-gateway.

Goal: catch regressions in the package build / install path. Full coverage
lives in the other test modules; this one guards `pip install -e` and the
LiteLLM surface the rest of the platform depends on.
"""

from __future__ import annotations

import os

import pytest


def test_package_importable():
    """The package itself imports cleanly (regression for the broken
    `setuptools.backends.legacy:build` build-backend that prevented this
    until Iter 8.5 fixed pyproject.toml)."""
    import ask_llm_gateway  # noqa: F401
    from ask_llm_gateway import embedding_space, runtime_settings  # noqa: F401
    from ask_llm_gateway.application import factory  # noqa: F401
    from ask_llm_gateway.domain import models, ports  # noqa: F401
    from ask_llm_gateway.infrastructure import (  # noqa: F401
        litellm_embedder,
        litellm_llm,
        provider_env,
        token_tracker,
    )


def test_embedder_protocol_satisfied():
    """The LiteLLM adapter satisfies the EmbedderPort Protocol."""
    from ask_llm_gateway.domain.ports import EmbedderPort
    from ask_llm_gateway.infrastructure.litellm_embedder import LiteLLMEmbedder

    # Protocol is structural; we cannot isinstance-check without
    # @runtime_checkable on every method, but the relevant method names
    # must exist.
    assert callable(getattr(LiteLLMEmbedder, "embed_query", None))
    assert callable(getattr(LiteLLMEmbedder, "embed_documents", None))
    # EmbedderPort is itself runtime_checkable per ports.py.
    assert hasattr(EmbedderPort, "embed_query")
    assert hasattr(EmbedderPort, "embed_documents")


# ── LiteLLM (direct path) ─────────────────────────────────────────────────────


def test_provider_env_maps_convenience_fields(monkeypatch):
    """api_key/api_base/api_version land on the provider's expected env vars,
    and `params` are exported verbatim (the any-provider escape hatch)."""
    from ask_llm_gateway.infrastructure.provider_env import ensure_litellm_provider_env

    for var in (
        "ANTHROPIC_API_KEY",
        "AZURE_API_KEY",
        "AZURE_API_BASE",
        "AZURE_API_VERSION",
        "AWS_REGION_NAME",
    ):
        monkeypatch.delenv(var, raising=False)

    ensure_litellm_provider_env("anthropic", api_key="sk-ant-xyz")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-xyz"

    ensure_litellm_provider_env(
        "azure",
        api_key="az-key",
        api_base="https://x.openai.azure.com",
        api_version="2024-02-01",
    )
    assert os.environ["AZURE_API_KEY"] == "az-key"
    assert os.environ["AZURE_API_BASE"] == "https://x.openai.azure.com"
    assert os.environ["AZURE_API_VERSION"] == "2024-02-01"

    # Bedrock-style literal passthrough.
    ensure_litellm_provider_env("bedrock", params={"AWS_REGION_NAME": "us-east-1"})
    assert os.environ["AWS_REGION_NAME"] == "us-east-1"


def test_provider_env_never_clobbers_with_empty(monkeypatch):
    """An empty/absent value must not wipe an already-set env var (Kyma Secret)."""
    from ask_llm_gateway.infrastructure.provider_env import ensure_litellm_provider_env

    monkeypatch.setenv("OPENAI_API_KEY", "preset")
    ensure_litellm_provider_env("openai", api_key=None)
    assert os.environ["OPENAI_API_KEY"] == "preset"


def test_litellm_model_string():
    """provider/model assembly: alias mapping + always route by the SELECTED
    provider (only a redundant self-prefix is stripped).

    The old contract was "a slash means already-qualified, pass through". That
    broke the shape production actually uses: Bedrock ids carry their OWN slash
    (`converse/...`, inference profiles), and passthrough routed them to a
    provider named `converse`. The provider is chosen separately in the UI, so it
    is authoritative — see the docstring on `_litellm_model_string`.
    """
    from ask_llm_gateway.infrastructure.litellm_llm import _litellm_model_string

    assert (
        _litellm_model_string("bedrock", "anthropic.claude-3-5-sonnet-v1:0")
        == "bedrock/anthropic.claude-3-5-sonnet-v1:0"
    )
    assert _litellm_model_string("google", "gemini-2.0-flash") == "gemini/gemini-2.0-flash"
    # A model id that carries its own slash keeps it and is STILL prefixed with
    # the selected provider (the live Bedrock Converse shape).
    assert (
        _litellm_model_string("bedrock", "converse/us.amazon.nova-pro-v1:0")
        == "bedrock/converse/us.amazon.nova-pro-v1:0"
    )
    # A redundant self-prefix is stripped, never doubled.
    assert _litellm_model_string("azure", "azure/my-deployment") == "azure/my-deployment"
    # A prefix that is NOT the selected provider is data, not routing.
    assert (
        _litellm_model_string("bedrock", "azure/my-deployment") == "bedrock/azure/my-deployment"
    )

    with pytest.raises(ValueError):
        _litellm_model_string("openai", "")


def test_build_llm_routes_to_litellm(monkeypatch):
    """build_llm dispatches the provider through build_litellm_chat, passing the
    resolved model/credentials, without importing langchain_litellm."""
    import ask_llm_gateway.infrastructure.litellm_llm as litellm_llm
    from ask_llm_gateway.application.factory import build_llm

    captured = {}

    def _fake_build(**kwargs):
        captured.update(kwargs)
        return "FAKE_LLM"

    monkeypatch.setattr(litellm_llm, "build_litellm_chat", _fake_build)

    cfg = {
        "llm": {
            "provider": "bedrock",
            "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "params": {"AWS_REGION_NAME": "us-east-1"},
        }
    }
    out = build_llm(cfg)

    assert out == "FAKE_LLM"
    assert captured["provider"] == "bedrock"
    assert captured["model"] == "anthropic.claude-3-5-sonnet-20240620-v1:0"
    assert captured["params"] == {"AWS_REGION_NAME": "us-east-1"}

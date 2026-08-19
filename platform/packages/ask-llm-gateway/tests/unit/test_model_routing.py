# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Model-string routing — bare model id + selected provider → LiteLLM route.

The model field carries the BARE model id (the provider is selected separately
in the UI). The router prepends the selected provider and tolerates a
legacy/typed prefix, including bedrock ids that themselves contain a slash
(``converse/`` / inference profiles) — the case the old ``"/" in model``
heuristic mis-routed.
"""

from __future__ import annotations

import pytest

# ── LLM (litellm_llm._litellm_model_string) ──────────────────────────────────


def test_llm_bare_model_gets_provider_prefix():
    from ask_llm_gateway.infrastructure.litellm_llm import _litellm_model_string

    assert (
        _litellm_model_string("bedrock", "amazon.nova-pro-v1:0") == "bedrock/amazon.nova-pro-v1:0"
    )
    assert _litellm_model_string("anthropic", "claude-sonnet-5") == "anthropic/claude-sonnet-5"
    assert _litellm_model_string("openai", "gpt-4o") == "openai/gpt-4o"


def test_llm_existing_prefix_is_idempotent():
    from ask_llm_gateway.infrastructure.litellm_llm import _litellm_model_string

    # Migrated / typed value already carrying the provider prefix must not double up.
    assert (
        _litellm_model_string("bedrock", "bedrock/amazon.nova-pro-v1:0")
        == "bedrock/amazon.nova-pro-v1:0"
    )


def test_llm_bedrock_converse_with_internal_slash():
    """The old ``"/" in model`` heuristic dropped the bedrock prefix here."""
    from ask_llm_gateway.infrastructure.litellm_llm import _litellm_model_string

    assert (
        _litellm_model_string("bedrock", "converse/us.amazon.nova-lite-v1:0")
        == "bedrock/converse/us.amazon.nova-lite-v1:0"
    )
    assert (
        _litellm_model_string("bedrock", "bedrock/converse/us.amazon.nova-lite-v1:0")
        == "bedrock/converse/us.amazon.nova-lite-v1:0"
    )


def test_llm_google_alias_maps_to_gemini():
    from ask_llm_gateway.infrastructure.litellm_llm import _litellm_model_string

    assert _litellm_model_string("google", "gemini-2.0-flash") == "gemini/gemini-2.0-flash"


def test_llm_empty_model_raises():
    from ask_llm_gateway.infrastructure.litellm_llm import _litellm_model_string

    with pytest.raises(ValueError):
        _litellm_model_string("bedrock", "")


# ── Embedder (litellm_embedder._model_string) ────────────────────────────────


def test_embedder_openai_routed_without_prefix():
    from ask_llm_gateway.infrastructure.litellm_embedder import _model_string

    assert _model_string("openai", "text-embedding-3-large") == "text-embedding-3-large"
    # A typed openai/ prefix is stripped (still no prefix for openai).
    assert _model_string("openai", "openai/text-embedding-3-large") == "text-embedding-3-large"


def test_embedder_bedrock_prefix_idempotent():
    from ask_llm_gateway.infrastructure.litellm_embedder import _model_string

    assert (
        _model_string("bedrock", "amazon.titan-embed-text-v2:0")
        == "bedrock/amazon.titan-embed-text-v2:0"
    )
    assert (
        _model_string("bedrock", "bedrock/amazon.titan-embed-text-v2:0")
        == "bedrock/amazon.titan-embed-text-v2:0"
    )

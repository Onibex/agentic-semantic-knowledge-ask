# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""LiteLLM chat adapter — the single direct (non-SAP) LLM backend.

One ``ChatLiteLLM`` instance covers Bedrock, Azure, OpenAI, Anthropic,
Vertex/Gemini, Mistral, Cohere and 100+ providers. ``ChatLiteLLM`` is a real
LangChain ``BaseChatModel``, so ``prompt | llm | parser`` chains and
``with_structured_output`` keep working exactly as with the old per-provider
adapters — consumers see no difference.

Adding a provider is configuration, not code: set ``provider`` + ``model`` and
the credentials LiteLLM expects (via :mod:`provider_env`).

Model routing
-------------
LiteLLM keys on a ``"<provider>/<model>"`` string:
    bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0
    azure/<deployment-name>
    anthropic/claude-sonnet-4-...
    gemini/gemini-2.0-flash
    openai/gpt-4o            (plain "gpt-4o" also works for OpenAI)

Required packages: litellm>=1.50, langchain-litellm>=0.2  (the `direct` extra).
"""

from __future__ import annotations

import logging
from typing import Any

from .provider_env import ensure_litellm_provider_env

logger = logging.getLogger(__name__)

try:
    from ask_llm_gateway.infrastructure.token_tracker import AutoTrackingCallback

    _TOKEN_TRACKER_AVAILABLE = True
except ImportError:
    _TOKEN_TRACKER_AVAILABLE = False

# Note: `litellm.drop_params = True` is set in provider_env on first import,
# so we don't need to repeat it here — it applies to every litellm call.

# Friendly aliases → LiteLLM's canonical provider id. Keeps existing configs
# that say "google" working; LiteLLM itself calls it "gemini".
_PROVIDER_ALIASES: dict[str, str] = {
    "google": "gemini",
}


def _auto_tracking_callbacks(model_name: str) -> list[Any]:
    if not _TOKEN_TRACKER_AVAILABLE:
        return []
    return [AutoTrackingCallback(model=model_name or "unknown")]


def _litellm_model_string(provider: str, model: str) -> str:
    """Build the ``provider/model`` string LiteLLM routes on.

    The model field carries the BARE model id (the provider is selected
    separately in the UI). We always route by the SELECTED provider, tolerating
    a provider prefix the admin may have typed or a migrated value — so bedrock
    ids that themselves contain a slash (``converse/...`` / inference profiles)
    route correctly instead of being mistaken for a fully-qualified model.
    """
    if not model:
        raise ValueError(
            "LLM_MODEL is required for the LiteLLM path. "
            "Set config['llm']['model'] or the LLM_MODEL env var "
            "(e.g. 'anthropic.claude-3-5-sonnet-20240620-v1:0' — bare model id; "
            "the provider is prepended automatically)."
        )
    prov = _PROVIDER_ALIASES.get(provider, provider)
    bare = model.strip().removeprefix(f"{prov}/")
    return f"{prov}/{bare}"


def build_litellm_chat(
    *,
    provider: str,
    model: str,
    scope: str = "llm",
    api_key: str | None = None,
    api_base: str | None = None,
    api_version: str | None = None,
    params: dict[str, Any] | None = None,
    max_tokens: int = 8192,
) -> Any:
    """Return a ``ChatLiteLLM`` LangChain model for any LiteLLM provider.

    Credentials are exported to the environment first (version-stable across
    langchain-litellm releases); the constructor stays on the universally
    present fields. ``AutoTrackingCallback`` is attached for token accounting.

    ``scope`` names the writer for the env ledger — ``"llm"`` for the active
    model, ``"probe"`` for a ``/test`` call against a connection that is not
    active. Keeping the probe separate stops a test from retiring the
    credentials the live model is using.

    Raises ValueError if ``model`` is missing, ImportError if langchain-litellm
    is not installed.
    """
    ensure_litellm_provider_env(
        provider,
        scope=scope,
        api_key=api_key,
        api_base=api_base,
        api_version=api_version,
        params=params,
    )

    model_str = _litellm_model_string(provider, model)

    from langchain_litellm import ChatLiteLLM  # type: ignore[import-not-found]

    # Log the effective output ceiling — the decisive check when SQL truncates.
    logger.info("build_litellm_chat: model=%s max_tokens=%s", model_str, max_tokens)

    return ChatLiteLLM(
        model=model_str,
        temperature=0,
        max_tokens=max_tokens,
        callbacks=_auto_tracking_callbacks(model_str),
    )

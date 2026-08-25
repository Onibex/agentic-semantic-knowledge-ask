# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Credential→environment authority for the LiteLLM (direct) path.

LiteLLM resolves provider credentials from process environment variables
(``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``AWS_ACCESS_KEY_ID``,
``AZURE_API_BASE`` …) regardless of which LangChain-wrapper version is
installed. Relying on env vars — rather than per-version constructor fields —
is the version-stable way to pass credentials, and it mirrors how
``aicore_env.export_aicore_env`` already boots the SAP AI Core path.

Two layers, applied in order (later wins):

  1. Convenience fields  — ``api_key`` / ``api_base`` / ``api_version`` are mapped
     to the env var the active provider expects (e.g. ``anthropic`` → ``ANTHROPIC_API_KEY``).
  2. Literal passthrough — every key in ``params`` is exported verbatim. This is
     the escape hatch for ANY provider: drop the exact env vars LiteLLM documents
     (e.g. ``AWS_REGION_NAME``, ``VERTEXAI_PROJECT``) and they reach the call
     untouched. ``params`` keys override convenience fields on conflict.

Only sets a var when a value is present — never clobbers an existing env var
with an empty string (so a Kyma Secret / shell export is not wiped out).

Writes go through :mod:`env_ledger`, which also **retires** what a previous
configuration wrote. Without that, switching providers leaves the old one's
variables in the process: an ``AWS_ACCESS_KEY_ID`` from a config that is gone
still reaches boto3, which stops at the first credential source it finds. The
``scope`` argument names the writer — the live LLM, the embedder, a ``/test``
probe — so retiring one never strips a variable another still needs.
"""

from __future__ import annotations

from typing import Any

from .env_ledger import apply as _apply_env

# Set LiteLLM-wide flags exactly once, at the earliest point in the import
# graph that the direct path can be wired from.
#
#  * drop_params=True — silently trim params the active provider doesn't
#    accept (DeepSeek R1 doesn't take ``temperature``, Anthropic doesn't
#    take ``frequency_penalty``, etc.). Without it, those calls raise.
#  * num_retries=3 — retry transient errors (429 RateLimit, 5xx, timeouts)
#    with exponential backoff. New Bedrock accounts hit aggressive throttling
#    for premium models; one retry is rarely enough, three is the LiteLLM
#    sweet spot. Errors that don't make sense to retry (auth, validation)
#    are NOT retried — LiteLLM filters those.
#  * request_timeout=120 — guard against hanging connections; some providers
#    occasionally stall and the default of "no timeout" lets requests dangle.
try:
    import litellm  # type: ignore[import-not-found]

    litellm.drop_params = True
    litellm.num_retries = 3
    litellm.request_timeout = 120
except ImportError:
    # litellm is a base dependency of ask-llm-gateway, so this should not happen
    # in a normal install. Guarded defensively for partial/editable installs that
    # skipped deps; the LiteLLM adapters already error out clearly when missing.
    pass

# Provider → env var that holds its API key. Covers the common key-based
# providers; anything exotic uses the `params` literal-passthrough escape hatch.
_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "azure": "AZURE_API_KEY",
    "azure_ai": "AZURE_AI_API_KEY",  # Azure AI Foundry Models (MaaS): Llama, Mistral, Phi, Cohere…
    "cohere": "COHERE_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "together_ai": "TOGETHERAI_API_KEY",
    "databricks": "DATABRICKS_API_KEY",
}

# Provider → (api_base env var, api_version env var). Azure is the common case;
# openai-compatible custom endpoints use OPENAI_API_BASE.
_BASE_ENV: dict[str, str] = {
    "azure": "AZURE_API_BASE",
    "azure_ai": "AZURE_AI_API_BASE",
    "openai": "OPENAI_API_BASE",
    "databricks": "DATABRICKS_API_BASE",
}
_VERSION_ENV: dict[str, str] = {
    "azure": "AZURE_API_VERSION",
}


def _stage(pending: dict[str, str], name: str, value: str | None) -> None:
    """Queue ``name`` only when both ``name`` and ``value`` are non-empty.

    Skipping empty names matters when the active provider has no entry in
    ``_API_KEY_ENV`` / ``_BASE_ENV`` / ``_VERSION_ENV``: ``dict.get(prov, "")``
    returns ``""`` and an empty env var name is not writable. Such providers
    rely on the ``params`` literal-passthrough escape hatch.
    """
    if name and value:
        pending[name] = str(value)


def ensure_litellm_provider_env(
    provider: str,
    *,
    scope: str = "llm",
    api_key: str | None = None,
    api_base: str | None = None,
    api_version: str | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    """Export the credentials LiteLLM needs for ``provider`` into ``os.environ``.

    ``provider`` is the LiteLLM provider id (``bedrock``, ``azure``, ``anthropic``,
    ``vertex_ai`` …). ``params`` is a literal env-var map applied last.

    ``scope`` identifies the writer — ``"llm"``, ``"embedder"``, ``"probe"``.
    Each scope's contribution is replaced wholesale, so a provider switch retires
    the previous provider's variables instead of leaving them to be found by
    boto3 later. Variables another scope still contributes are left alone.
    """
    prov = (provider or "").strip().lower()
    pending: dict[str, str] = {}

    # Layer 1 — convenience fields mapped to the provider's expected env var.
    _stage(pending, _API_KEY_ENV.get(prov, ""), api_key)
    _stage(pending, _BASE_ENV.get(prov, ""), api_base)
    _stage(pending, _VERSION_ENV.get(prov, ""), api_version)

    # Layer 2 — literal passthrough (overrides on conflict). Escape hatch for
    # Bedrock (AWS_*), Vertex (VERTEXAI_*/GOOGLE_APPLICATION_CREDENTIALS), etc.
    for key, value in (params or {}).items():
        _stage(pending, str(key), value)

    _apply_env(f"litellm:{scope}", pending)

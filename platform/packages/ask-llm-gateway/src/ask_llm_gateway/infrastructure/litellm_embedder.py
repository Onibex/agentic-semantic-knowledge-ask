# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""LiteLLM embedder adapter — the single direct (non-SAP) embedding backend.

Wraps ``litellm.embedding`` behind the gateway's ``EmbedderPort`` so OpenAI,
Bedrock, Azure, Vertex, Cohere and friends all share one code path. Local
sentence-transformers embeddings stay in ``huggingface_embedder`` (no API to
proxy).

Credentials are exported to the environment via :mod:`provider_env`, mirroring
the chat adapter.

Required packages: litellm>=1.50  (the `direct` extra).
"""

from __future__ import annotations

from typing import Any

from .provider_env import ensure_litellm_provider_env

# Friendly aliases → LiteLLM canonical provider id (kept in sync with litellm_llm).
_PROVIDER_ALIASES: dict[str, str] = {
    "google": "gemini",
}


def _model_string(provider: str, model: str) -> str:
    """Route by the SELECTED provider from a BARE model id.

    Mirrors ``litellm_llm._litellm_model_string``: prepend the selected
    provider, tolerating a typed/migrated prefix (so ``bedrock/...`` ids and
    slash-containing model ids route correctly). OpenAI embeddings are routed
    without a prefix by LiteLLM.
    """
    if not model:
        raise ValueError(
            "EMBEDDER_MODEL is required for the LiteLLM path. "
            "Set config['embedder']['model'] or the EMBEDDER_MODEL env var "
            "(e.g. 'text-embedding-3-large' — bare model id; the provider is "
            "prepended automatically)."
        )
    prov = _PROVIDER_ALIASES.get(provider, provider)
    bare = model.strip().removeprefix(f"{prov}/")
    # OpenAI embedding models are routed without a prefix by LiteLLM.
    return bare if prov == "openai" else f"{prov}/{bare}"


class LiteLLMEmbedder:
    """Adapter for any LiteLLM-supported embedding provider.

    Satisfies the gateway ``EmbedderPort`` Protocol (embed_query / embed_documents).
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        ensure_litellm_provider_env(
            provider,
            api_key=api_key,
            api_base=api_base,
            api_version=api_version,
            params=params,
        )
        self._model = _model_string(provider, model)

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        import litellm  # type: ignore[import-not-found]

        resp = litellm.embedding(model=self._model, input=inputs)
        # litellm returns an EmbeddingResponse: {"data": [{"embedding": [...]}, ...]}
        data = resp["data"] if isinstance(resp, dict) else resp.data
        return [[float(x) for x in item["embedding"]] for item in data]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(list(texts))

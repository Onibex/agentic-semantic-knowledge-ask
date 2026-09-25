# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""LiteLLM embedder adapter: the embedding backend for every API provider.

Wraps ``litellm.embedding`` behind the gateway's ``EmbedderPort`` so OpenAI,
Bedrock, Azure, Vertex, SAP AI Core, Cohere and friends all share one code
path. Local sentence-transformers embeddings stay in ``huggingface_embedder``
(no API to proxy).

Every call asks for the search index's vector size (see
:mod:`ask_llm_gateway.embedding_space`). Models that can shorten their output
(``text-embedding-3`` on OpenAI or SAP AI Core, Titan Text Embeddings V2 on
Bedrock) comply; for the rest LiteLLM drops the parameter, because
``provider_env`` sets ``drop_params``, and the embedder test in ASK Setup
reports the mismatch. Azure and SAP AI Core are asked differently, see
``_size_request``.

Credentials are exported to the environment via :mod:`provider_env`, mirroring
the chat adapter.

Required packages: litellm, at the version pinned in pyproject.toml.
"""

from __future__ import annotations

from typing import Any

from ..embedding_space import index_embedding_dim
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


def _size_request(provider: str, model: str) -> dict[str, Any]:
    """The kwargs that ask ``provider`` for the index's vector size.

    * Azure gets nothing. LiteLLM forwards `dimensions` to it unchecked, and an
      Azure model is a deployment name, so LiteLLM cannot tell a
      text-embedding-3 deployment (which accepts it) from an ada-002 one (which
      rejects the whole call). There the deployment must already produce the
      index's size, and the embedder test says when it does not.
    * SAP AI Core gets it inside `parameters`. LiteLLM's `sap` adapter accepts
      the standard `dimensions` and then drops it (its ``map_openai_params``
      returns nothing), and the request carries only what arrives as
      `parameters`. Measured on 2026-09-24 against SAP AI Core with
      text-embedding-3-large: `dimensions=1024` gave 3072 dimensions,
      `parameters={"dimensions": 1024}` gave 1024. Only text-embedding-3 is
      asked, the models LiteLLM declares the parameter for.
    * Every other provider gets `dimensions`, which LiteLLM maps where the
      model supports it and drops where it does not (``drop_params``).
    """
    if provider == "azure":
        return {}
    if provider == "sap":
        if "text-embedding-3" not in model:
            return {}
        return {"parameters": {"dimensions": index_embedding_dim()}}
    return {"dimensions": index_embedding_dim()}


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
            scope="embedder",
            api_key=api_key,
            api_base=api_base,
            api_version=api_version,
            params=params,
        )
        self._model = _model_string(provider, model)
        self._size_request = _size_request(_PROVIDER_ALIASES.get(provider, provider), model)

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        import litellm  # type: ignore[import-not-found]

        resp = litellm.embedding(model=self._model, input=inputs, **self._size_request)
        # litellm returns an EmbeddingResponse: {"data": [{"embedding": [...]}, ...]}
        data = resp["data"] if isinstance(resp, dict) else resp.data
        return [[float(x) for x in item["embedding"]] for item in data]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(list(texts))

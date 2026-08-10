"""
SAP AI Core embedding model adapter.

Handles SDK auth (temp file), batching (16 texts/request to avoid rate limits),
and two fallback init strategies (init_embedding_model → OpenAIEmbeddings).
"""

from __future__ import annotations

from ask_llm_gateway.infrastructure.aicore_env import (
    export_aicore_env,
    write_aicore_service_key_file,
)


class SAPAICoreEmbedder:
    """Adapter for SAP AI Core embedding deployments via gen_ai_hub SDK."""

    def __init__(self, deployment_id: str, aicore_config: dict) -> None:
        self._tmpfile_path = write_aicore_service_key_file(aicore_config)
        export_aicore_env(aicore_config)

        self._deployment_id = deployment_id
        self._emb = None
        self._init_embedder()

    def _init_embedder(self) -> None:
        try:
            from gen_ai_hub.proxy.langchain.init_models import init_embedding_model

            self._emb = init_embedding_model(self._deployment_id)
        except Exception:
            try:
                from gen_ai_hub.proxy.langchain.openai import OpenAIEmbeddings

                self._emb = OpenAIEmbeddings(deployment_id=self._deployment_id)
            except Exception as exc:
                raise RuntimeError(f"Could not initialize SAP AI Core embedder: {exc}") from exc

    def embed_query(self, text: str) -> list[float]:
        return self._emb.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Batch in groups of 16 to avoid AI Core rate limits."""
        results: list[list[float]] = []
        for i in range(0, len(texts), 16):
            results.extend(self._emb.embed_documents(texts[i : i + 16]))
        return results

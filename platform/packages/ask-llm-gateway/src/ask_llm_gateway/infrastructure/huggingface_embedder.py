"""HuggingFace embedder adapter for the direct (non-SAP) deployment path.

Uses langchain-huggingface's HuggingFaceEmbeddings (sentence-transformers
running locally) with optional Hub token for private or gated models.

Two modes, selected automatically:
  - api_key absent → local inference via sentence-transformers (no network auth)
  - api_key present → Hub-authenticated download (private / gated models)

Required package: langchain-huggingface>=0.1  (pulls in sentence-transformers)
"""

from __future__ import annotations

_DEFAULT_MODEL = "sentence-transformers/all-mpnet-base-v2"


class HuggingFaceEmbedder:
    """Adapter for HuggingFace embedding models via langchain-huggingface."""

    def __init__(self, model: str = "", api_key: str = "") -> None:
        from langchain_huggingface import HuggingFaceEmbeddings  # type: ignore[import-not-found]

        kwargs: dict = {"model_name": model or _DEFAULT_MODEL}
        if api_key:
            # Hub token enables private / gated model downloads.
            kwargs["huggingfacehub_api_token"] = api_key

        self._emb = HuggingFaceEmbeddings(**kwargs)

    def embed_query(self, text: str) -> list[float]:
        raw = self._emb.embed_query(text)
        return [float(x) for x in raw]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self._emb.embed_documents(texts)]

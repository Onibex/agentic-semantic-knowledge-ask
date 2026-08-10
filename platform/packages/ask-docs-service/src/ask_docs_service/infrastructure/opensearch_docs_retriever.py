"""
OpenSearchDocsRetriever — dedicated retriever for the Docs Service.

The retriever targets the `rag-data-product-docs` OpenSearch index, which
is populated by the Embeddings admin page when the user picks
"Data Product Documentation" (3_Embeddings.py → admin-api → OpenSearch).

Document shape in that index (per
`ask_knowledge_graph.infrastructure.rag_vectorstore_client`):
    {
      "text":      "<chunk content>",
      "metadata":  {"data_product_name": ..., "source_file": ...,
                    "doc_type": "data_product_documentation", ...},
      "embedding": [<knn vector>]
    }

ARCHITECTURE NOTE (Iter 5 Q6 — DELIBERATE DUPLICATION)
─────────────────────────────────────────────────────────
This retriever uses its OWN OpenSearch query body. It does NOT reuse the
helpers in `ask-knowledge-graph` or `ask-intent-resolution.flash`. Each
side can evolve independently (different filters, different scoring
preferences) without risking regressions in the other.

ENFORCEMENT: `.importlinter` has a contract forbidding `ask_docs_service`
from importing `ask_knowledge_graph`.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.errors import RetrieverUnavailableError
from ..domain.models import DocsHit
from ..domain.ports import DocsRetriever

logger = logging.getLogger(__name__)

DOCS_INDEX = "rag-data-product-docs"
DOC_TYPE_FILTER = "data_product_documentation"


class OpenSearchDocsRetriever(DocsRetriever):
    """Dedicated docs retriever — own client, own query, own scoring.

    The OpenSearch client is injected at construction time (so tests can
    pass a fake). The orchestrator builds it once at startup.
    """

    def __init__(self, client: Any, env: str | None = None) -> None:
        self._client = client
        # env-suffixed index (dev/prod) so a DOCS_QUERY reads the same env the
        # chat user selected. The {base}-{env} scheme is duplicated here on
        # purpose — the peer-isolation contract forbids importing
        # ask_knowledge_graph.infrastructure.env_index.
        self._index = f"{DOCS_INDEX}-{env}" if env in ("dev", "prod") else DOCS_INDEX

    def search_data_products(
        self,
        *,
        text: str,
        vector: list[float],
        top_k: int,
    ) -> list[DocsHit]:
        body = _build_query(text=text, vector=vector, top_k=top_k)
        try:
            resp = self._client.search(index=self._index, body=body)
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            raise RetrieverUnavailableError(
                f"docs retrieval against {self._index} failed: {exc}"
            ) from exc

        out: list[DocsHit] = []
        for hit in (resp.get("hits") or {}).get("hits") or []:
            src = hit.get("_source") or {}
            chunk_text = src.get("text") or ""
            metadata = src.get("metadata") or {}
            if not chunk_text:
                continue
            out.append(
                DocsHit(
                    source_file=str(metadata.get("source_file", "") or ""),
                    data_product_name=str(metadata.get("data_product_name", "") or ""),
                    chunk_text=chunk_text,
                    score=float(hit.get("_score") or 0.0),
                )
            )
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Query body — kept module-level (and not on the class) so tests can assert
# its shape without instantiating an OpenSearch client.
# ─────────────────────────────────────────────────────────────────────────────
def _build_query(*, text: str, vector: list[float], top_k: int) -> dict[str, Any]:
    """Compose the OpenSearch search body.

    Strategy: hybrid kNN + BM25 inside a `bool` query, with a metadata
    filter that restricts the pool to chunks ingested as
    `doc_type = data_product_documentation`. Both `should` clauses
    contribute scores additively; at least one must match.
    """
    return {
        "size": top_k,
        "_source": ["text", "metadata"],
        "query": {
            "bool": {
                "filter": [{"term": {"metadata.doc_type": DOC_TYPE_FILTER}}],
                "should": [
                    # BM25 over the chunk text
                    {"match": {"text": {"query": text}}},
                    # kNN over the embedding field
                    {
                        "knn": {
                            "embedding": {
                                "vector": vector,
                                "k": top_k,
                            }
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        },
    }

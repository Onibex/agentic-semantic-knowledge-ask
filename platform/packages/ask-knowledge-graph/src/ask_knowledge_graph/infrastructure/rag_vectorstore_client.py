# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_knowledge_graph.infrastructure.rag_vectorstore_client
─────────────────────────────────────────────────────────────────────────────
Hybrid retrieval against the RAG collections (rag-schema, rag-data-product-docs).

BM25 + kNN → RRF fusion → Min-Max + additive tier/priority bonuses. Same
3-stage pipeline as the OCSL SML retriever, adapted for the chunk-RAG
collections. Was previously at
`ask_intent_resolution.flash.infrastructure.opensearch_vectorstore` — moved
here because the Knowledge Graph package is the semantic owner of every ASK
OpenSearch index (entity/field/edge registry AND the RAG collections); the
Flash strategy is just one of its consumers, not its host.

Stages:
  Stage 1 : RRF(BM25, kNN)  pool = max(k*8, 50)
  Stage 2 : Min-Max normalisation + additive bonuses
              layer:     gold   → +0.40  |  silver → +0.15
              priority:  critical/mandatory → +0.20  |  high → +0.10
  Stage 3 : return top-k Documents

Collections:
  rag_schema              → rag-schema
  rag_data_product_docs   → rag-data-product-docs
"""

from __future__ import annotations

import os
import uuid

from langchain_core.documents import (
    Document,  # 0.3 + 1.x compatible (avoids langchain.schema eager import)
)

from .env_index import env_index

# ── Index name mapping ────────────────────────────────────────────────────────

COLLECTION_INDEX_MAP = {
    "rag_schema": "rag-schema",
    "rag_data_product_docs": "rag-data-product-docs",
}


def _index_for(collection_name: str, env: str | None = None) -> str:
    base = COLLECTION_INDEX_MAP.get(collection_name, f"rag-{collection_name.replace('_', '-')}")
    return env_index(base, env)


# ── Index mapping ─────────────────────────────────────────────────────────────


def _build_mapping(embedding_dim: int, language: str | None = None) -> dict:
    """The RAG chunk index (Flash + docs). ``text`` gets the deployment's
    analyzer so its BM25 leg folds accents and stems in the corpus's language —
    the same reasoning as the registry indices (PLAN_SEMANTIC_LANGUAGE.md W3)."""
    from .language_config import resolve_semantic_language
    from .opensearch_repository import _ASK_TEXT_ANALYZER, _text_analysis_settings

    lang = language or resolve_semantic_language().value
    return {
        "settings": {
            "index.knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": _text_analysis_settings(lang),
        },
        "mappings": {
            "properties": {
                "text": {"type": "text", "analyzer": _ASK_TEXT_ANALYZER},
                "metadata": {"type": "object", "enabled": True},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": embedding_dim,
                    "method": {
                        "engine": "faiss",
                        "space_type": "innerproduct",
                        "name": "hnsw",
                        "parameters": {"ef_construction": 256, "m": 48},
                    },
                },
            }
        },
    }


# ── OpenSearch client factory ─────────────────────────────────────────────────


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _get_os_client(os_config: dict):
    from opensearchpy import OpenSearch

    # Env-first (OPENSEARCH_*) with the passed settings.json config as fallback —
    # env vars win so this survives stripping ``opensearch`` from settings.json.
    host = os.getenv("OPENSEARCH_HOST")
    port_env = os.getenv("OPENSEARCH_PORT")
    use_ssl_env = os.getenv("OPENSEARCH_USE_SSL")
    username = os.getenv("OPENSEARCH_USER") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or None

    if not host:
        host = os_config.get("host", "localhost")
        port = int(port_env or os_config.get("port", 9200))
        use_ssl = (
            bool(os_config.get("use_ssl", False)) if use_ssl_env is None else _truthy(use_ssl_env)
        )
        username = username or os_config.get("username") or None
        password = password or os_config.get("password") or None
        verify_certs = bool(os_config.get("verify_certs", False))
    else:
        port = int(port_env or 9200)
        use_ssl = _truthy(use_ssl_env or "")
        verify_certs = _truthy(os.getenv("OPENSEARCH_VERIFY_CERTS", ""))

    kwargs: dict = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
        "maxsize": int(os_config.get("pool_maxsize", 20)),  # avoid size-1 pool churn
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)


# ── Bonus helpers ─────────────────────────────────────────────────────────────

_TIER_BONUS = {"gold": 0.40, "silver": 0.15}
_PRIO_BONUS = {"critical": 0.20, "high": 0.10}


def _tier_bonus(meta: dict) -> float:
    return _TIER_BONUS.get(meta.get("layer", ""), 0.0)


def _prio_bonus(meta: dict) -> float:
    if meta.get("is_mandatory"):
        return 0.20
    return _PRIO_BONUS.get(str(meta.get("priority", "")).lower(), 0.0)


# ── Vector store ──────────────────────────────────────────────────────────────


class OpenSearchVectorStore:
    """
    Hybrid vector store with RRF(BM25 + kNN) retrieval.

    Public interface (LangChain-compatible):
      add_documents(docs)                    → None
      similarity_search(query, k, filter)    → list[Document]
      similarity_search_with_score(...)      → list[tuple[Document, float]]
    """

    # RRF / pool tuning (matches OCSL SML spec defaults)
    _POOL_MULTIPLIER = 8
    _POOL_MIN = 50
    _RRF_K = 60

    def __init__(self, collection_name: str, embeddings, os_config: dict, env: str | None = None):
        self._collection = collection_name
        self._env = env
        self._index = _index_for(collection_name, env)
        self._embeddings = embeddings
        self._os_config = os_config
        self._client = _get_os_client(os_config)
        self._embedding_dim: int | None = None
        self._ensure_index()

    # ── DDL ───────────────────────────────────────────────────────────────────

    def _get_embedding_dim(self) -> int:
        if self._embedding_dim is None:
            self._embedding_dim = len(self._embeddings.embed_query("test"))
        return self._embedding_dim

    def _ensure_index(self) -> None:
        if not self._client.indices.exists(index=self._index):
            self._client.indices.create(
                index=self._index,
                body=_build_mapping(self._get_embedding_dim()),
            )

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_documents(self, docs: list[Document]) -> None:
        """
        Embeds and indexes documents one at a time with retry + backoff.
        SAP AI Core drops the connection on large batches, so we embed
        each chunk individually and accumulate the OpenSearch actions.
        """
        if not docs:
            return
        import time as _time

        from opensearchpy import helpers

        actions = []
        for doc in docs:
            for attempt in range(4):
                try:
                    vec = self._embeddings.embed_query(doc.page_content)
                    break
                except Exception as e:
                    if attempt == 3:
                        raise e
                    _time.sleep(2**attempt)

            actions.append(
                {
                    "_index": self._index,
                    "_id": str(uuid.uuid4()),
                    "_source": {
                        "text": doc.page_content,
                        "metadata": doc.metadata,
                        "embedding": vec,
                    },
                }
            )

        helpers.bulk(self._client, actions, raise_on_error=True)
        self._client.indices.refresh(index=self._index)

    # ── Low-level search primitives ───────────────────────────────────────────

    def _bm25_search(self, query: str, k: int, filter_clause: dict | None) -> list[dict]:
        """BM25 full-text search on the `text` field, with optional filter."""
        base = {"match": {"text": {"query": query}}}
        body = {
            "size": k,
            "query": _with_filter(base, filter_clause),
            "_source": False,
        }
        return self._client.search(index=self._index, body=body)["hits"]["hits"]

    def _knn_search(self, query_vec: list[float], k: int) -> list[dict]:
        """
        Approximate kNN — always runs WITHOUT filter.

        nmslib engine does not reliably support post-filters inside bool queries
        and silently returns 0 results when combined with bool.filter.
        Filtering is applied in Python after mget (see _matches_filter).
        """
        body = {
            "size": k,
            "query": {"knn": {"embedding": {"vector": query_vec, "k": k}}},
            "_source": False,
        }
        return self._client.search(index=self._index, body=body)["hits"]["hits"]

    def _mget(self, doc_ids: list[str]) -> dict[str, dict]:
        """Bulk-fetch full documents in a single HTTP request."""
        if not doc_ids:
            return {}
        body = {"docs": [{"_index": self._index, "_id": did} for did in doc_ids]}
        resp = self._client.mget(body=body)
        return {item["_id"]: item["_source"] for item in resp["docs"] if item.get("found")}

    # ── Stage 1: RRF fusion ───────────────────────────────────────────────────

    def _rrf_pool(
        self,
        query: str,
        query_vec: list[float],
        pool: int,
        filter_clause: dict | None,
    ) -> dict[str, float]:
        """
        Reciprocal Rank Fusion:  score(d) = Σ 1 / (rrf_k + rank_i(d))

        BM25 runs WITH filter (reliable for keyword fields).
        kNN runs WITHOUT filter (nmslib doesn't support bool.filter reliably).
        The filter is enforced in Python after mget via _matches_filter.
        """
        bm25_hits = self._bm25_search(query, pool, filter_clause)
        knn_hits = self._knn_search(query_vec, pool)

        bm25_ranks = {h["_id"]: i + 1 for i, h in enumerate(bm25_hits)}
        knn_ranks = {h["_id"]: i + 1 for i, h in enumerate(knn_hits)}

        all_ids = set(bm25_ranks) | set(knn_ranks)
        rrf: dict[str, float] = {}
        for did in all_ids:
            score = 0.0
            if did in bm25_ranks:
                score += 1.0 / (self._RRF_K + bm25_ranks[did])
            if did in knn_ranks:
                score += 1.0 / (self._RRF_K + knn_ranks[did])
            rrf[did] = score
        return rrf

    # ── Stage 2: Min-Max + additive bonuses ───────────────────────────────────

    @staticmethod
    def _rerank(
        rrf: dict[str, float],
        sources: dict[str, dict],
        pool_ids: list[str],
    ) -> list[tuple[float, dict]]:
        """
        Normalise RRF scores to [0, 1] then add flat tier/priority bonuses.

        Why flat bonuses (not multiplicative)?
        RRF scores are compressed (~0.010–0.033 for 50 docs).
        A ×1.5 multiplier on gold (0.021 → 0.031) can still lose to a
        bronze doc at 0.032.  A flat +0.40 on gold (0.021 → 0.421) always wins.
        Gold doc beats any bronze as long as gold has *any* retrieval signal.
        """
        valid = [(did, rrf[did]) for did in pool_ids if did in sources]
        if not valid:
            return []

        scores = [s for _, s in valid]
        lo, hi = min(scores), max(scores)
        rng = hi - lo or 1e-10

        ranked = []
        for did, raw_score in valid:
            src = sources[did]
            meta = src.get("metadata", {})
            norm = (raw_score - lo) / rng
            final = norm + _tier_bonus(meta) + _prio_bonus(meta)
            ranked.append((final, src))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    # ── Python post-filter ────────────────────────────────────────────────────

    @staticmethod
    def _matches_filter(src: dict, filter_clause: dict | None) -> bool:
        """
        Evaluates a filter clause against a document's metadata in Python.

        Supports the OpenSearch DSL subset used in this app:
          {"term":  {"metadata.field":         value}}
          {"term":  {"metadata.field.keyword":  value}}
          {"bool":  {"must": [...], "filter": [...]}}   (recursive)

        This catches any kNN results that slipped through without the filter
        because nmslib doesn't support post-filters in bool queries.
        """
        if not filter_clause:
            return True
        meta = src.get("metadata", {})

        if "term" in filter_clause:
            for field_path, expected in filter_clause["term"].items():
                key = field_path.removeprefix("metadata.").removesuffix(".keyword")
                if meta.get(key) != expected:
                    return False
            return True

        if "terms" in filter_clause:
            for field_path, expected_list in filter_clause["terms"].items():
                key = field_path.removeprefix("metadata.").removesuffix(".keyword")
                if meta.get(key) not in expected_list:
                    return False
            return True

        if "bool" in filter_clause:
            b = filter_clause["bool"]
            clauses = []
            if "must" in b:
                must = b["must"]
                clauses += must if isinstance(must, list) else [must]
            if "filter" in b:
                filt = b["filter"]
                clauses += filt if isinstance(filt, list) else [filt]
            return all(OpenSearchVectorStore._matches_filter(src, c) for c in clauses)

        # Unknown clause type — allow through (don't block valid results)
        return True

    # ── Public API ────────────────────────────────────────────────────────────

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter: dict | None = None,
    ) -> list[Document]:
        """
        Hybrid search: BM25 + kNN → RRF → Min-Max + layer/priority bonuses.
        `filter` must be an OpenSearch DSL clause, e.g.:
            {"term": {"metadata.doc_type": "schema_technical"}}
        BM25 enforces the filter at query time; kNN results are post-filtered
        in Python so no docs of the wrong type leak through.
        """
        pool = max(k * self._POOL_MULTIPLIER, self._POOL_MIN)
        query_vec = self._embeddings.embed_query(query)

        # Stage 1 — RRF (kNN unfiltered; BM25 filtered)
        rrf = self._rrf_pool(query, query_vec, pool, filter)
        pool_ids = sorted(rrf, key=lambda x: rrf[x], reverse=True)[:pool]

        # Bulk fetch + Python post-filter
        sources = {
            did: src
            for did, src in self._mget(pool_ids).items()
            if self._matches_filter(src, filter)
        }

        # Stage 2 — rerank with bonuses
        ranked = self._rerank(rrf, sources, pool_ids)

        return [
            Document(
                page_content=src.get("text", ""),
                metadata=src.get("metadata", {}),
            )
            for _, src in ranked[:k]
        ]

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        filter: dict | None = None,
    ) -> list[tuple[Document, float]]:
        pool = max(k * self._POOL_MULTIPLIER, self._POOL_MIN)
        query_vec = self._embeddings.embed_query(query)

        rrf = self._rrf_pool(query, query_vec, pool, filter)
        pool_ids = sorted(rrf, key=lambda x: rrf[x], reverse=True)[:pool]
        sources = {
            did: src
            for did, src in self._mget(pool_ids).items()
            if self._matches_filter(src, filter)
        }
        ranked = self._rerank(rrf, sources, pool_ids)

        return [
            (
                Document(
                    page_content=src.get("text", ""),
                    metadata=src.get("metadata", {}),
                ),
                score,
            )
            for score, src in ranked[:k]
        ]

    @property
    def document_count(self) -> int:
        try:
            return self._client.count(
                index=self._index,
                body={"query": {"match_all": {}}},
            )["count"]
        except Exception:
            return 0


# ── Filter helper ─────────────────────────────────────────────────────────────


def _with_filter(base_query: dict, filter_clause: dict | None) -> dict:
    """Wrap a query clause inside bool.must + bool.filter if a filter is given."""
    if not filter_clause:
        return base_query
    filters = filter_clause if isinstance(filter_clause, list) else [filter_clause]
    return {
        "bool": {
            "must": base_query,
            "filter": filters,
        }
    }


# ── Compatibility factory (same signature as before) ─────────────────────────


def get_or_create_opensearch_vectorstore(
    config: dict,
    index_name: str,
    embedding_function,
    env: str | None = None,
) -> OpenSearchVectorStore:
    """
    Drop-in replacement for the old langchain OpenSearchVectorSearch wrapper.
    Returns an OpenSearchVectorStore with hybrid RRF retrieval.

    ``env`` (Iter 2) suffixes the resolved RAG index (``rag-schema-dev`` etc.)
    so per-environment publishes stay isolated. ``None`` keeps the legacy name.
    """
    return OpenSearchVectorStore(
        collection_name=index_name,
        embeddings=embedding_function,
        os_config=config,
        env=env,
    )


# ── Connection test ───────────────────────────────────────────────────────────


def test_opensearch_connection(os_config: dict) -> tuple[bool, str]:
    try:
        client = _get_os_client(os_config)
        version = client.info().get("version", {}).get("number", "unknown")
        return True, f"Connection successful. OpenSearch {version}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"

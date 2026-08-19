# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
src/pipeline/application/semantic_dictionary_service.py
─────────────────────────────────────────────────────────────────────────────
SemanticDictionaryService — Global Semantic Dictionary + Silver Extensions.

Responsibilities:
  1. Global index `ask-semantic-dictionary-v1`: Enriched business terms with
     synonyms, context clues, and kNN embeddings. Supports hybrid search
     (BM25 + kNN) for the 3-level disambiguation system.
  2. Legacy `{silver}_ext` indices: Per-entity Silver extensions for
     Phase 2 short-circuit (backward-compatible, to deprecate).
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from opensearchpy import OpenSearch

logger = logging.getLogger(__name__)

GLOBAL_INDEX = "ask-semantic-dictionary-v1"


class SemanticDictionaryService:
    """Manages the global semantic dictionary and Silver extensions."""

    def __init__(self, os_client: OpenSearch, embedder=None, embedding_dim: int = 1024) -> None:
        self.client = os_client
        self.embedder = embedder
        self.embedding_dim = embedding_dim

    # ─────────────────────────────────────────────────────────────────────────
    # LEGACY: Per-entity Silver extension indices ({silver}_ext)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_ext_index(self, silver_index: str) -> str:
        return f"{silver_index}_ext"

    def ensure_index(self, silver_index: str) -> None:
        ext_index = self._get_ext_index(silver_index)
        if not self.client.indices.exists(index=ext_index):
            body = {
                "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
                "mappings": {
                    "properties": {
                        "type": {"type": "keyword"},
                        "business_term": {"type": "keyword"},
                        "technical_value": {"type": "text"},
                        "description": {"type": "text"},
                        "updated_at": {"type": "date"},
                    }
                },
            }
            self.client.indices.create(index=ext_index, body=body)

    def upsert_entry(self, silver_index: str, entry: Dict[str, Any]) -> bool:
        ext_index = self._get_ext_index(silver_index)
        self.ensure_index(silver_index)
        business_term_lower = entry["business_term"].lower().strip()
        doc_id = business_term_lower.replace(" ", "_")
        entry["business_term"] = business_term_lower
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self.client.index(index=ext_index, id=doc_id, body=entry, refresh=True)
            return True
        except Exception as e:
            logger.error(f"Error saving to {ext_index}: {e}")
            return False

    def list_entries(self, silver_index: str) -> List[Dict[str, Any]]:
        ext_index = self._get_ext_index(silver_index)
        if not self.client.indices.exists(index=ext_index):
            return []
        try:
            resp = self.client.search(index=ext_index, body={"size": 1000, "query": {"match_all": {}}})
            return [hit["_source"] for hit in resp["hits"]["hits"]]
        except Exception as e:
            logger.error(f"Error listing {ext_index}: {e}")
            return []

    def lookup_term(self, silver_index: str, business_term: str) -> Optional[Dict[str, Any]]:
        ext_index = self._get_ext_index(silver_index)
        if not self.client.indices.exists(index=ext_index):
            return None
        term_lower = business_term.lower().strip()
        try:
            resp = self.client.search(index=ext_index, body={"query": {"term": {"business_term": term_lower}}})
            hits = resp["hits"]["hits"]
            if hits:
                return hits[0]["_source"]
        except Exception as e:
            logger.error(f"Error in lookup_term for {ext_index}: {e}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # GLOBAL INDEX: ask-semantic-dictionary-v1 (enriched + kNN)
    # ─────────────────────────────────────────────────────────────────────────

    def ensure_global_index(self) -> None:
        """
        Creates the global index with enriched mapping + kNN if it doesn't exist.

        Schema v2 (2026-04) adds three value-level enrichment fields:
          - examples:        array of typical values ("F226", "Z", ...)
          - value_synonyms:  {user_said: actual_value} map (flattened)
          - is_preferred_id: bool — mark as the ID column when user gives a code

        These are used by the Freeform SQL Generator prompt to disambiguate
        column choice (ID vs description) and value mapping ("finalized"→"Completed").

        If the index already exists, `_migrate_global_index_schema()` adds the
        new mappings idempotently via put_mapping.
        """
        if self.client.indices.exists(index=GLOBAL_INDEX):
            self._migrate_global_index_schema()
            return

        body = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100,
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                },
            },
            "mappings": {
                "properties": {
                    # Core identification
                    "technical_name": {"type": "keyword"},
                    "table": {"type": "keyword"},
                    "module": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    # Semantic fields (BM25 searchable)
                    "canonical_label": {"type": "text", "analyzer": "english"},
                    "synonyms": {"type": "text"},
                    "description": {"type": "text", "analyzer": "english"},
                    "context_clues": {"type": "text"},
                    "disambiguation_hint": {"type": "text"},
                    # References
                    "entity_id": {"type": "keyword"},
                    "source_system": {"type": "keyword"},
                    # Backward compat (exact lookup)
                    "business_term": {"type": "keyword"},
                    # Value-level enrichment (schema v2) ─────────────────────
                    "examples":        {"type": "keyword"},     # ["F226","Z",...]
                    "value_synonyms":  {"type": "object", "dynamic": True},   # {finalized:"Completed"}
                    "is_preferred_id": {"type": "boolean"},
                    # Vector
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": self.embedding_dim,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "lucene",
                        },
                    },
                    "updated_at": {"type": "date"},
                },
            },
        }
        self.client.indices.create(index=GLOBAL_INDEX, body=body)
        logger.info(f"Global index '{GLOBAL_INDEX}' created with kNN support.")

    def _migrate_global_index_schema(self) -> None:
        """
        Idempotently add the v2 value-level enrichment fields to an existing
        global dictionary index. Safe to call on every upsert — if the mappings
        already exist, OpenSearch returns success without change.
        """
        try:
            self.client.indices.put_mapping(
                index=GLOBAL_INDEX,
                body={
                    "properties": {
                        "examples":        {"type": "keyword"},
                        "value_synonyms":  {"type": "object", "dynamic": True},
                        "is_preferred_id": {"type": "boolean"},
                    }
                },
            )
        except Exception as e:
            # Non-fatal: an existing incompatible mapping would raise. Log and
            # continue — the main upsert will still work, only enrichment
            # queries may be degraded.
            logger.warning(f"Schema migration for {GLOBAL_INDEX} skipped: {e}")

    def upsert_entry_global(self, entry: Dict[str, Any]) -> bool:
        """
        Saves an enriched term to the global index.
        Auto-generates embedding from canonical_label + synonyms + description.
        """
        self.ensure_global_index()

        canonical = (entry.get("canonical_label") or "").strip()
        tech_name = (entry.get("technical_name") or canonical).strip()
        module = (entry.get("module") or "UNKNOWN").upper().strip()
        source_system = (entry.get("source_system") or "s4h").lower().strip()

        doc_id = f"{module}_{source_system}_{tech_name.lower().replace(' ', '_')}"

        # Normalize synonyms/context_clues to lists
        synonyms = entry.get("synonyms", [])
        if isinstance(synonyms, str):
            synonyms = [s.strip() for s in synonyms.split(",") if s.strip()]
        entry["synonyms"] = synonyms

        context_clues = entry.get("context_clues", [])
        if isinstance(context_clues, str):
            context_clues = [c.strip() for c in context_clues.split(",") if c.strip()]
        entry["context_clues"] = context_clues

        # ── Schema v2: value-level enrichment ───────────────────────────────
        # examples: list of typical values (["F226","Z",...])
        examples = entry.get("examples", [])
        if isinstance(examples, str):
            examples = [e.strip() for e in examples.split(",") if e.strip()]
        entry["examples"] = examples

        # value_synonyms: map user-wording → actual value. Accept either a
        # dict or a CSV "finalized=Completed, pending=Open".
        value_synonyms = entry.get("value_synonyms", {})
        if isinstance(value_synonyms, str):
            parsed: Dict[str, str] = {}
            for pair in value_synonyms.split(","):
                pair = pair.strip()
                if not pair or "=" not in pair:
                    continue
                k, v = pair.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k and v:
                    parsed[k.lower()] = v
            value_synonyms = parsed
        elif isinstance(value_synonyms, dict):
            # Normalize keys to lowercase for case-insensitive lookup
            value_synonyms = {str(k).lower().strip(): str(v).strip()
                              for k, v in value_synonyms.items() if k and v}
        else:
            value_synonyms = {}
        entry["value_synonyms"] = value_synonyms

        # is_preferred_id: truthy → True, else False
        entry["is_preferred_id"] = bool(entry.get("is_preferred_id"))
        # ───────────────────────────────────────────────────────────────────

        # Backward compat: business_term = canonical_label (lowercased)
        entry["business_term"] = canonical.lower()
        entry["module"] = module
        entry["source_system"] = source_system
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Auto-generate embedding — required by the knn_vector mapping.
        if "embedding" not in entry:
            if not self.embedder:
                raise RuntimeError(
                    "Embedder not available — cannot save dictionary entry to a "
                    "knn_vector index without an embedding. "
                    "Check config['embedder']['provider'] and container logs for "
                    "'Embedder construction failed'."
                )
            embed_text = f"{canonical} {' '.join(synonyms)} {entry.get('description', '')}"
            try:
                raw_vec = self.embedder.embed_query(embed_text)
            except Exception as exc:
                raise RuntimeError(
                    f"embed_query raised for '{canonical}': {exc}"
                ) from exc
            # Force plain Python floats — sentence-transformers returns numpy
            # scalars that opensearchpy's JSON serializer converts to null.
            try:
                vector: list = [float(x) for x in raw_vec] if raw_vec is not None else []
            except (TypeError, ValueError):
                vector = []
            if not vector:
                raise RuntimeError(
                    f"Embedder returned empty/null vector for '{canonical}' "
                    f"(type={type(raw_vec).__name__}). "
                    f"Model may still be initialising — retry in a moment."
                )
            # Guard against NaN/Inf — Python json.dumps encodes float('nan') as the
            # non-standard token `NaN`; OpenSearch's Jackson parser converts it to null,
            # causing knn_vector mapping failures even though the list is non-empty.
            import math as _math
            bad = [i for i, v in enumerate(vector) if not _math.isfinite(v)]
            if bad:
                raise RuntimeError(
                    f"Embedder returned {len(bad)} non-finite (NaN/Inf) values in the "
                    f"vector for '{canonical}'. Indices: {bad[:5]}. "
                    f"Try restarting the container — the model may have loaded incorrectly."
                )
            logger.info(
                "embedding ok: dim=%d type=%s sample=%s",
                len(vector), type(vector[0]).__name__, vector[:3],
            )
            entry["embedding"] = vector

        # Diagnostic: reveal exactly what opensearchpy will serialise.
        import json as _json
        emb = entry.get("embedding")
        try:
            _sample = _json.dumps(emb[:3] if isinstance(emb, list) else emb)
        except Exception as _je:
            _sample = f"JSON_ERR:{_je}"
        logger.info(
            "pre-index: embedding type=%s len=%s json_sample=%s",
            type(emb).__name__,
            len(emb) if isinstance(emb, list) else "N/A",
            _sample,
        )

        try:
            self.client.index(index=GLOBAL_INDEX, id=doc_id, body=entry, refresh=True)
            return True
        except Exception as e:
            logger.error(f"Error saving to {GLOBAL_INDEX}: {e}")
            raise RuntimeError(f"OpenSearch rejected the entry: {e}") from e

    def search_hybrid(
        self,
        query: str,
        query_vector: list,
        module: Optional[str] = None,
        entry_type: Optional[str] = None,
        size: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search: BM25 (text fields) + kNN (semantic embedding).
        Returns results sorted by combined relevance score.

        Args:
            query:        Natural language search text.
            query_vector: embedding of the query (dimension must match the index).
            module:       Optional SAP module filter (SD, MM, PP...).
            entry_type:   Optional type filter (metric, dimension, phrase...).
            size:         Max results to return.

        Returns:
            List of dicts, each with '_score' + all source fields.
        """
        if not self.client.indices.exists(index=GLOBAL_INDEX):
            return []

        filters = []
        if module:
            filters.append({"term": {"module": module.upper().strip()}})
        if entry_type:
            filters.append({"term": {"type": entry_type.lower().strip()}})

        body = {
            "size": size,
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": [
                                    "canonical_label^2.0",
                                    "synonyms^1.5",
                                    "description^1.2",
                                    "context_clues^1.0",
                                    "disambiguation_hint^0.8",
                                ],
                                "type": "best_fields",
                            }
                        },
                        {
                            "knn": {
                                "embedding": {"vector": query_vector, "k": size}
                            }
                        },
                    ],
                    "filter": filters if filters else None,
                }
            },
        }

        # Clean None filter
        if not filters:
            del body["query"]["bool"]["filter"]

        try:
            resp = self.client.search(index=GLOBAL_INDEX, body=body)
            results = []
            for hit in resp["hits"]["hits"]:
                entry = hit["_source"]
                entry["_score"] = hit["_score"]
                # Exclude embedding from results to save memory
                entry.pop("embedding", None)
                results.append(entry)
            return results
        except Exception as e:
            logger.error(f"Error in search_hybrid: {e}")
            return []

    def lookup_term_global(self, business_term: str) -> List[Dict[str, Any]]:
        """Exact keyword match (backward compat fallback)."""
        if not self.client.indices.exists(index=GLOBAL_INDEX):
            return []
        term_lower = business_term.lower().strip()
        try:
            resp = self.client.search(
                index=GLOBAL_INDEX,
                body={"size": 50, "query": {"term": {"business_term": term_lower}}},
            )
            return [hit["_source"] for hit in resp["hits"]["hits"]]
        except Exception as e:
            logger.error(f"Error in lookup_term_global: {e}")
            return []

    def list_entries_global(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists all entries, optionally filtered by module.

        Each returned dict includes ``_id`` (the OpenSearch document id) so
        callers can reference individual entries for deletion.
        """
        if not self.client.indices.exists(index=GLOBAL_INDEX):
            return []
        if module:
            query = {"size": 1000, "query": {"term": {"module": module.upper().strip()}}}
        else:
            query = {"size": 1000, "query": {"match_all": {}}}
        try:
            resp = self.client.search(index=GLOBAL_INDEX, body=query)
            results = []
            for hit in resp["hits"]["hits"]:
                entry = dict(hit["_source"])
                entry["_id"] = hit["_id"]
                results.append(entry)
            return results
        except Exception as e:
            logger.error(f"Error listing {GLOBAL_INDEX}: {e}")
            return []

    def delete_entry_global(self, entry_id: str) -> bool:
        """Deletes a single entry from the global index by its document id.

        ``entry_id`` must be the OpenSearch ``_id`` string as returned by
        ``list_entries_global`` (e.g. ``"SD_s4h_net_value"``).
        Returns ``True`` on success, ``False`` if the document was not found
        or an error occurred.
        """
        if not self.client.indices.exists(index=GLOBAL_INDEX):
            logger.warning("delete_entry_global: index %s does not exist", GLOBAL_INDEX)
            return False
        try:
            resp = self.client.delete(index=GLOBAL_INDEX, id=entry_id, refresh=True)
            result = resp.get("result", "")
            if result == "deleted":
                return True
            if result == "not_found":
                logger.warning("delete_entry_global: id %r not found", entry_id)
                return False
            return True
        except Exception as e:
            logger.error(f"Error deleting {entry_id} from {GLOBAL_INDEX}: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # SCHEMA v2: Runtime lookup of value-level enrichments
    # ─────────────────────────────────────────────────────────────────────────

    def get_field_enrichments(
        self,
        entity_id: str,
        field_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Returns dictionary entries for a given entity that carry value-level
        enrichment data (examples, value_synonyms, is_preferred_id, or
        disambiguation_hint). Consumed by `FreeformSQLGeneratorService` to
        build the FIELD ENRICHMENTS prompt block.

        Args:
            entity_id:   Entity id whose fields to look up.
            field_name:  Optional specific `technical_name` filter.

        Returns:
            List of dicts with fields: technical_name, canonical_label, type,
            description, examples, value_synonyms, is_preferred_id,
            disambiguation_hint. Entries without any enrichment data are
            excluded (reduces prompt noise).
        """
        if not self.client.indices.exists(index=GLOBAL_INDEX):
            return []

        must: List[Dict[str, Any]] = [
            {"term": {"entity_id": entity_id}}
        ]
        if field_name:
            must.append({"term": {"technical_name": field_name}})

        body = {
            "size": 500,
            "_source": [
                "technical_name", "canonical_label", "type", "table",
                "description", "disambiguation_hint",
                "examples", "value_synonyms", "is_preferred_id",
            ],
            "query": {"bool": {"must": must}},
        }

        try:
            resp = self.client.search(index=GLOBAL_INDEX, body=body)
        except Exception as e:
            logger.error(f"Error in get_field_enrichments({entity_id}): {e}")
            return []

        out: List[Dict[str, Any]] = []
        for hit in resp["hits"]["hits"]:
            src = hit.get("_source", {}) or {}
            # Keep only entries that actually carry enrichment data or a useful hint.
            has_data = (
                bool(src.get("examples"))
                or bool(src.get("value_synonyms"))
                or bool(src.get("is_preferred_id"))
                or bool(src.get("disambiguation_hint"))
            )
            if not has_data:
                continue
            out.append(
                {
                    "technical_name":       src.get("technical_name"),
                    "canonical_label":      src.get("canonical_label"),
                    "type":                 src.get("type"),
                    "table":                src.get("table"),
                    "description":          src.get("description"),
                    "disambiguation_hint":  src.get("disambiguation_hint"),
                    "examples":             src.get("examples") or [],
                    "value_synonyms":       src.get("value_synonyms") or {},
                    "is_preferred_id":      bool(src.get("is_preferred_id")),
                }
            )
        return out

    def get_field_enrichments_bulk(
        self,
        entity_ids: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Same as `get_field_enrichments` but for multiple entities in one call.
        Returns a dict keyed by entity_id.
        """
        out: Dict[str, List[Dict[str, Any]]] = {}
        for eid in entity_ids:
            if not eid:
                continue
            out[eid] = self.get_field_enrichments(eid)
        return out

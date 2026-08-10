"""
Ports for the Knowledge Graph package — read + write surfaces.

Iter 4 introduced KnowledgeGraphReader. Iter 6 adds KnowledgeGraphWriter and
IngestionService so the entire R/W lifecycle is consumable through typed
contracts (no more direct OpenSearchAskRepository imports outside the
infrastructure adapters). Iter 8 adds DictionaryWriter so the semantic-admin
admin page can drop its direct legacy imports too.
"""

from __future__ import annotations

from typing import Any, Protocol

from .models import DictionaryTerm, EntityRecord, IngestionRequest, IngestionResult


class KnowledgeGraphReader(Protocol):
    """The single read contract for the orchestrator and ask_intent_resolution.

    Concrete implementation: infrastructure.opensearch_reader.OpenSearchKnowledgeGraphReader.
    """

    # ── Entity lookups ──────────────────────────────────────────────────────
    def get_entity_by_id(self, entity_id: str) -> EntityRecord | None: ...

    def get_lightweight_entities(self) -> list[EntityRecord]: ...

    def mget_raw_yaml(self, entity_ids: list[str]) -> dict[str, str]:
        """Bulk fetch raw_yaml strings keyed by entity id. Missing ids omitted.

        Replaces direct `os_repo.client.mget(...)` poking by the strategies.
        """
        ...

    # ── Search ──────────────────────────────────────────────────────────────
    def search_hybrid_rrf(
        self,
        text_query: str,
        vector_query: list[float],
        size: int = 10,
        layers: list[str] | None = None,
    ) -> list[EntityRecord]: ...

    def search_gold_rescue(self, text_query: str, size: int = 5) -> list[EntityRecord]: ...

    def search_best_field(self, text_query: str, vector_query: list[float]) -> dict[str, Any]: ...

    # ── Edges ───────────────────────────────────────────────────────────────
    def get_all_edges(self) -> list[dict[str, Any]]: ...


# ─────────────────────────────────────────────────────────────────────────────
# Iter 6 — write side
# ─────────────────────────────────────────────────────────────────────────────
class KnowledgeGraphWriter(Protocol):
    """Low-level write contract over the ask-* indices.

    Concrete impl: infrastructure.opensearch_writer.OpenSearchKnowledgeGraphWriter
    (wraps the legacy OpenSearchAskRepository save_*/delete_* methods).

    Signatures intentionally mirror the legacy methods — `node` is a parsed
    domain object (BronzeNode / SilverNode / GoldNode) and `yaml_content` is
    the original YAML text. The wrapper receives a legacy_repo at construction
    time and forwards calls.
    """

    def save_bronze(self, node: Any, yaml_content: str) -> dict[str, int]: ...

    def save_silver(
        self, node: Any, yaml_content: str, embedder: Any | None = None
    ) -> dict[str, int]: ...

    def save_gold(
        self, node: Any, yaml_content: str, embedder: Any | None = None
    ) -> dict[str, int]: ...

    def delete_entity(self, entity_id: str) -> dict[str, int]: ...


class IngestionService(Protocol):
    """High-level ingestion contract — what admin tooling and the CLI use.

    Wraps parsing + writing in one call so callers do not have to know how
    YAMLs are turned into domain nodes. Concrete impl:
      application.ingestion_service.MetadataIngestionServiceWrapper
    """

    def ingest_yaml(self, request: IngestionRequest) -> IngestionResult: ...

    def ingest_sap_json(self, raw_json: dict[str, Any]) -> IngestionResult:
        """Iter 8 — ingest a SAP JSON metadata dump.

        The legacy service parses the JSON into Bronze + Silver nodes,
        optionally serialises them back to YAML on disk, and indexes
        each node. Returns aggregate stats wrapped in an IngestionResult.
        """
        ...

    def delete_entity(self, entity_id: str) -> IngestionResult: ...


# ─────────────────────────────────────────────────────────────────────────────
# Iter 8 — semantic-dictionary side
#
# The legacy SemanticDictionaryService manages two sets of indices:
#   1. The global enriched dictionary `ask-semantic-dictionary-v1` (kNN + BM25)
#   2. Per-Silver-entity extension indices `{silver_index}_ext`
# Both surfaces are exposed through this single Protocol so admin tooling
# (5_Semantic_Admin.py) does not need direct legacy imports. Concrete impl:
#   infrastructure.opensearch_dictionary_writer.OpenSearchDictionaryWriter
# Despite the "Writer" name (kept for parity with KnowledgeGraphWriter), the
# Protocol covers reads as well — see ADR-015 / Iter 8 Q2.
# ─────────────────────────────────────────────────────────────────────────────
class DictionaryWriter(Protocol):
    # ── Per-Silver-entity extension indices (legacy `{silver}_ext`) ─────────
    def ensure_index(self, silver_index: str) -> None: ...

    def upsert_entry(self, silver_index: str, entry: dict[str, Any]) -> bool: ...

    def list_entries(self, silver_index: str) -> list[DictionaryTerm]: ...

    def lookup_term(self, silver_index: str, business_term: str) -> DictionaryTerm | None: ...

    # ── Global enriched dictionary (`ask-semantic-dictionary-v1`) ───────────
    def ensure_global_index(self) -> None: ...

    def upsert_entry_global(self, entry: dict[str, Any]) -> bool: ...

    def search_hybrid(
        self,
        query: str,
        query_vector: list[float],
        module: str | None = None,
        entry_type: str | None = None,
        size: int = 10,
    ) -> list[DictionaryTerm]: ...

    def lookup_term_global(self, business_term: str) -> list[DictionaryTerm]: ...

    def list_entries_global(self, module: str | None = None) -> list[DictionaryTerm]: ...

    def delete_entry_global(self, entry_id: str) -> bool: ...

    # ── Schema v2 — value-level enrichment lookup (consumed by SQL gen) ────
    def get_field_enrichments(
        self, entity_id: str, field_name: str | None = None
    ) -> list[DictionaryTerm]: ...

    def get_field_enrichments_bulk(
        self, entity_ids: list[str]
    ) -> dict[str, list[DictionaryTerm]]: ...

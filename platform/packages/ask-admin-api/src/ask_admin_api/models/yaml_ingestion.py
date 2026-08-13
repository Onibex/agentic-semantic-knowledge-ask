"""Request / response models for ``/v1/admin/yaml/*`` (Knowledge Graph ingestion)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SapJsonIngestRequest(BaseModel):
    """Wrap an SAP metadata JSON payload (parsed by the UI from file upload)."""

    data: dict[str, Any]


class YamlIngestRequest(BaseModel):
    """Wrap one YAML body string (Bronze / Silver / Gold).

    Used by the deprecated ``/ingest`` and ``/ingest-full`` endpoints.
    Pass I replaces both with ``/import`` and ``ImportYamlRequest``.
    """

    yaml_content: str


class ImportYamlRequest(BaseModel):
    """Body for ``POST /v1/admin/yaml/import`` (Pass I).

    Lands a hand-authored YAML in the workspace at the canonical path
    derived from the entity. Does NOT touch the runtime catalog — that's
    a separate Publish action.
    """

    yaml_content: str
    force: bool = False  # overwrite if the target workspace file exists


class ImportYamlResult(BaseModel):
    entity_id: str
    layer: str
    file_path: str  # POSIX path relative to repo root
    overwritten: bool  # True when force was honoured against an existing file


class DeriveYamlRequest(BaseModel):
    """Body for ``POST /v1/admin/yaml/derive`` — preview the EntityDeriver
    normalization on a draft YAML without writing anything."""

    yaml_content: str


class DerivedFieldFlag(BaseModel):
    """Per-field record of which keys the deriver added/rewrote."""

    name: str
    derived: list[str] = Field(default_factory=list)


class DeriveYamlResult(BaseModel):
    """Result of ``/derive``: the assembled node + which fields were derived.

    ``validation_error`` is non-null when the completed node still fails the
    layer schema (e.g. the author omitted a required *semantic* field like
    ``description``) so the SPA can surface "still missing X" inline.
    """

    layer: str
    node: dict[str, Any]
    entity_derived: list[str] = Field(default_factory=list)
    fields: list[DerivedFieldFlag] = Field(default_factory=list)
    validation_error: str | None = None


class DdlImportRequest(BaseModel):
    """Body for ``POST /v1/admin/yaml/import/ddl`` (Iter 6 / CH-6).

    The admin pastes/uploads SQL DDL; the AI maps it to ASK YAML at ``layer``
    (Q11). May produce more than one entity (one per CREATE TABLE).
    """

    ddl: str
    layer: str = "bronze"  # bronze | silver | gold
    source_system: str = "s4h"
    force: bool = False
    # Optional free-text business context ("what are these tables for?") injected
    # into the mapping prompt so the model writes accurate business descriptions
    # / aliases instead of guessing from column names alone.
    context: str = ""
    # OPTIONAL override for the silver/gold `module` (workspace path + grouping).
    # Normally omitted: the module is AUTO-DETECTED per relation from the
    # physical table name (`SILVER_SD_*` → `sd`) against a whitelist, falling
    # back to `gen` (owner decision 2026-08-12 — there is no Module picker in the
    # UI). Set it only to force one module on every relation in the batch.
    module: str | None = None


class DdlImportItem(BaseModel):
    """Per-entity outcome of a DDL import."""

    entity_id: str | None = None
    layer: str | None = None
    file_path: str | None = None
    outcome: str  # "created" | "overwritten" | "error"
    reason: str | None = None


class DdlImportResult(BaseModel):
    """Result of a DDL import: the AI-generated YAML + per-entity outcomes."""

    generated_yaml: str
    tokens_used: int = 0
    items: list[DdlImportItem] = Field(default_factory=list)
    # Non-fatal robustness flags (§7.1) — e.g. fewer documents than CREATE TABLE
    # statements in the input. Surfaced so the user reviews the generated YAML.
    warnings: list[str] = Field(default_factory=list)


class IngestionResult(BaseModel):
    """Mirror of ``ask_knowledge_graph.domain.models.IngestionResult`` plus
    a transport-layer ``rag_chunks_indexed`` counter for endpoints that
    cascade to ``rag_schema`` automatically (the SAP JSON paths).

    The Silver entity produced by SAP JSON ingestion is rendered + chunked
    + indexed into ``rag_schema`` so the chat agent's Flash strategy can
    retrieve it by hybrid RRF (same coherence invariant the manual YAML
    path holds). When zero, either no Silver was produced (Bronze-only
    payload) or the RAG cascade was skipped/failed (see logs)."""

    entities_indexed: int = 0
    fields_indexed: int = 0
    edges_indexed: int = 0
    rag_chunks_indexed: int = 0
    error: str | None = None
    # Pass C: per-entity publish cascade
    cascade_indexed: list[str] = Field(default_factory=list)
    cascade_warnings: list[str] = Field(default_factory=list)


class PublishEnvResult(BaseModel):
    """Result of an environment publish (``/index/{id}/dev|prod``, Iter 2).

    Carries the env, the env-branch commit SHA, and indexing totals so the
    caller can confirm the DP landed in ``ask-*-{env}`` and on the env branch.
    """

    entity_id: str
    env: str
    committed_sha: str | None = None
    entities_indexed: int = 0
    fields_indexed: int = 0
    edges_indexed: int = 0
    rag_chunks_indexed: int = 0
    indexed_paths: list[str] = Field(default_factory=list)
    cascade_indexed: list[str] = Field(default_factory=list)
    cascade_warnings: list[str] = Field(default_factory=list)


class UnpublishEnvResult(BaseModel):
    """Result of an environment UNpublish (``DELETE /index/{id}/dev|prod``).

    The inverse of :class:`PublishEnvResult`: reports what was removed from
    ``ask-*-{env}`` + the env branch for the PRIMARY entity (no cascade).
    """

    entity_id: str
    env: str
    committed_sha: str | None = None
    entities_removed: int = 0
    fields_removed: int = 0
    edges_removed: int = 0
    rag_chunks_removed: int = 0
    warnings: list[str] = Field(default_factory=list)


class DomainPublishItem(BaseModel):
    """Per-DataProduct outcome inside a domain-level bulk publish (Iter 5/CH-5)."""

    entity_id: str
    outcome: str  # "published" | "skipped" | "error"
    committed_sha: str | None = None
    reason: str | None = None  # skip reason / error message


class DomainPublishResult(BaseModel):
    """Result of ``POST /v1/admin/business-domains/{id}/publish/{env}`` (Iter 5).

    Iterates the Business Domain's data products; publishes the ones that have
    changes pending for the env and skips those already up to date / not ready
    (prod needs a dev publish first). The per-DP ``items`` drive the SPA result
    modal + summary chip (audit §6.5).
    """

    business_domain_id: str
    env: str
    total: int = 0
    published: int = 0
    skipped: int = 0
    failed: int = 0
    items: list[DomainPublishItem] = Field(default_factory=list)


class DomainPublishRequest(BaseModel):
    """Body for the streaming domain publish (``/publish/{env}/stream``).

    ``entity_ids=None`` (or omitted) publishes every member — same contract as
    the non-streaming endpoint. A provided list restricts the batch to the SPA
    checklist selection; ids that are not members of the domain are ignored
    server-side (never publish something outside the domain). The per-DP gate
    still applies, so a selected DP already up to date is reported ``skipped``.
    """

    entity_ids: list[str] | None = None


class DeletionResult(BaseModel):
    """Result of a delete-entity call. Covers both the catalog branch
    (``entities_deleted`` + ``fields_deleted`` from the KG writer) and the
    cascading RAG cleanup (``rag_chunks_deleted`` from rag_schema)."""

    entities_deleted: int = 0
    fields_deleted: int = 0
    rag_chunks_deleted: int = 0
    error: str | None = None


class LightweightEntity(BaseModel):
    """One row of the catalog browser — small payload for list rendering."""

    id: str
    name: str | None = None
    layer: str | None = None


class CatalogResponse(BaseModel):
    entities: list[LightweightEntity] = Field(default_factory=list)


class EntityDetailResponse(BaseModel):
    """Full entity document — loose because raw_yaml + arbitrary metadata."""

    entity: dict[str, Any] | None = None
    found: bool = True


# ── Unified ingest (catalog + RAG in one call) ──────────────────────────────
class FullIngestRequest(BaseModel):
    """Body for ``POST /v1/admin/yaml/ingest-full``.

    Posts a single ASK Spec YAML and indexes it into BOTH the catalog
    (ask-entity / field / edge registries) and the RAG vectorstore
    (``rag_schema``) in one call. ``also_index_rag=False`` opts out of the
    RAG branch (useful for Bronze entities that don't need to be searchable
    in chunk-RAG).
    """

    yaml_content: str
    version: str = "v1.0"
    source_file: str | None = None
    also_index_rag: bool = True


class RagIndexResult(BaseModel):
    """Per-call summary of the RAG branch of the unified ingest."""

    chunks_indexed: int = 0
    batches_sent: int = 0
    collection: str = "rag_schema"
    skipped: bool = False
    skip_reason: str | None = None


class FullIngestResult(BaseModel):
    """Response from ``POST /v1/admin/yaml/ingest-full``.

    Carries both the catalog ingestion stats and the RAG indexing stats so
    the UI can show a single consolidated success message with 6 metrics.
    """

    kg: IngestionResult
    rag: RagIndexResult | None = None
    error: str | None = None


class ResetIndicesResult(BaseModel):
    """Response from ``POST /v1/admin/yaml/reset-indices``."""

    dropped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    embedding_dim: int = 1024


# ── Publish workspace → index (bulk) ─────────────────────────────────────────
class IndexWorkspaceRequest(BaseModel):
    """Body for ``POST /v1/admin/yaml/index-workspace``.

    Indexes every YAML in the workspace into OpenSearch. Optional ``layer``
    filter lets callers restrict the run (e.g. publish only Silvers/Golds
    and let the per-entity cascade pick up the referenced Bronces).
    """

    layers: list[str] | None = None  # default: all layers


class IndexWorkspaceItem(BaseModel):
    entity_id: str
    layer: str | None = None
    status: str  # "indexed" | "skipped" | "error"
    entities_indexed: int = 0
    fields_indexed: int = 0
    edges_indexed: int = 0
    rag_chunks_indexed: int = 0
    error: str | None = None


class IndexWorkspaceResult(BaseModel):
    total: int = 0
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    layers: list[str] = Field(default_factory=list)
    items: list[IndexWorkspaceItem] = Field(default_factory=list)
    entities_indexed: int = 0
    fields_indexed: int = 0
    edges_indexed: int = 0
    rag_chunks_indexed: int = 0

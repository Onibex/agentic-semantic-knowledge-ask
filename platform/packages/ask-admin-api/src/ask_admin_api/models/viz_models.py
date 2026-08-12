"""Pydantic models for the YAML Visualizer API (/v1/viz/*)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class VizLayer(str, Enum):
    bronze = "bronze"
    silver = "silver"
    gold = "gold"


class VizField(BaseModel):
    name: str
    type: str | None = None
    alias: str | None = None
    field_role: str | None = None
    description: str | None = None
    aggregation_behavior: str | None = None
    # Axis 2 of the aggregation contract — see REQ_ADDITIVITY_CONTRACT.md.
    # additive | semi_additive | non_additive; absent means additive.
    additivity: str | None = None
    # Grain dimensions to collapse before aggregating. Set iff semi_additive.
    non_additive_over: list[str] = []
    key_field: bool = False
    source: str | None = None  # Silver/Gold: "TABLE.FIELD"
    synonyms: list[str] = []
    normalization_flag: str | None = None  # currency | uom | none


class VizJoinCondition(BaseModel):
    left_table: str
    right_table: str
    join_type: str
    condition: str
    sequence: int = 1


class VizRelationship(BaseModel):
    """A declared lineage/relationship to another curated entity (Silver/Gold).

    Sourced from the YAML's top-level ``relationships`` block. Silvers point to
    other Silvers; Golds point to Silvers and other Golds (never Bronze).
    """

    target_entity: str
    relationship_type: str | None = None
    join_condition: str | None = None
    semantic_label: str | None = None
    traversal_cost: float | None = None
    aggregation_safety: str | None = None
    cross_module: bool | None = None
    description: str | None = None


class VizMeta(BaseModel):
    """Per-YAML governance metadata. The state machine (draft/review/production)
    was retired — git is the source of truth for change history; ``Publish``
    is the only runtime-visible transition. What remains:

    * ``field_enrichments``: which fields were curated by hand, so SAP merges
      don't pisar them without producing a conflict.
    * ``entity_enrichments``: which entity-level (header) properties — e.g.
      ``description``, ``alias`` — the admin touched. Same semantics as
      field_enrichments but at the YAML's top level.
    * ``conflicts``: pending SAP-vs-curation deltas awaiting human resolution.
    """

    field_enrichments: dict[str, list[str]] = {}
    entity_enrichments: list[str] = []
    conflicts: list[dict] = []


class VizGrain(BaseModel):
    entity_grain: list[str] = []  # composite key fields
    business_grain: str | None = None


class VizHeader(BaseModel):
    """The `§3.1 top-level keys` of an entity that the catalog READS but never writes.

    Every one of these is already sitting in the parsed YAML that
    ``YAMLFileService._ensure_cache`` holds, so projecting them costs no extra I/O
    (see ``list_yamls``). Shared by the list summary and the full node so the two
    can never drift into showing a different header for the same entity.

    All optional: a Bronze declares only ``version`` / ``source_system`` /
    ``description`` of this set (``BronzeNode``), so the rest come back ``None``
    there and the UI simply omits the row.
    """

    description: str | None = None
    # Standards §3.1: required at Silver/Gold. The business axis the catalog was
    # missing — `ORDER TO CASH`, `PROCURE TO PAY`, … Never a module code.
    business_process: str | None = None
    entity_role: str | None = None  # fact | dimension | reference
    classification: str | None = None  # M master | T transactional | C configuration
    db_table_name: str | None = None  # the physical table SQL targets
    source_system: str | None = None  # s4h | ecc | generic | …
    # Bronze numbers its source instance `source_system_id`, Silver/Gold
    # `source_system_no`. Normalised to one field so the UI need not branch on
    # layer to show the same fact.
    source_system_no: int | None = None
    version: str | None = None  # the YAML's spec version — NOT the lifecycle version
    internal_id: str | None = None
    # Declared in the contract for catalog faceting (GOLD_LAYER.md §3.1). Until
    # now they never left the API, which is why no faceting was possible.
    tag1: str | None = None
    tag2: str | None = None


class VizYAMLNode(VizHeader):
    # `description` / `entity_role` / `classification` / `db_table_name` and the
    # rest of the §3.1 header come from VizHeader — the same projection the list
    # summary uses, so the catalog row and the opened entity can never disagree.
    id: str
    layer: VizLayer
    module: str | None = None
    name: str
    alias: str | None = None
    primary_key: list[str] = []  # Bronze only — its declared key
    grain: VizGrain | None = None  # entity_grain + business_grain (read-only)
    file_path: str  # relative to repo root, POSIX separators
    fields: list[VizField] = []
    join_graph: list[VizJoinCondition] = []
    composed_of: list[str] = []
    relationships: list[VizRelationship] = []
    normalization: dict | None = None  # currency / UoM conversion block (enrichable)
    meta: VizMeta = VizMeta()


class VizYAMLSummary(VizHeader):
    id: str
    layer: VizLayer
    module: str | None = None
    name: str
    alias: str | None = None
    file_path: str
    # ── Structure, projected for the catalog's expandable detail ──────────────
    entity_grain: list[str] = []
    business_grain: str | None = None
    primary_key: list[str] = []  # Bronze's structural key (its grain analogue)
    field_count: int = 0
    measure_count: int = 0  # answers "is there anything to aggregate here?"
    relationship_count: int = 0
    has_normalization: bool = False  # a currency / UoM conversion block is declared


class VizFieldUpdate(BaseModel):
    name: str  # field identifier (required, not editable)
    alias: str | None = None  # Bronze only
    description: str | None = None  # all layers
    field_role: (
        Literal["measure", "dimension", "timestamp", "identifier", "attribute", "status_flag"]
        | None
    ) = None
    aggregation_behavior: (
        Literal["SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX", "none"] | None
    ) = None
    # Axis 2 — REQ_ADDITIVITY_CONTRACT.md. The full contract (measures only,
    # non_additive_over required iff semi_additive and restricted to timestamp
    # grain fields) is enforced on SilverField at save time, not here: this model
    # only patches individual props and cannot see the entity's grain.
    additivity: Literal["additive", "semi_additive", "non_additive"] | None = None
    non_additive_over: list[str] | None = None
    synonyms: list[str] | None = None
    normalization_flag: Literal["currency", "uom", "none"] | None = None


class VizFieldFull(BaseModel):
    """Complete field spec for a FULL structural replace (add / remove / rename /
    retype / key / source) — distinct from VizFieldUpdate, which only patches the
    enrichment props of EXISTING fields by name. Per-layer props are optional; the
    deriver normalizes (canonical type, derived role, primary_key) on save."""

    name: str
    type: str | None = None
    description: str | None = None
    # Bronze
    alias: str | None = None
    key_field: bool | None = None
    # Silver / Gold
    source: str | None = None
    field_role: str | None = None
    aggregation_behavior: str | None = None
    additivity: str | None = None
    non_additive_over: list[str] | None = None
    synonyms: list[str] | None = None


class VizGrainSpec(BaseModel):
    entity_grain: list[str] | None = None
    business_grain: str | None = None


class VizYAMLUpdateRequest(BaseModel):
    # author_* are accepted for backward compat but the commit author is derived
    # server-side from the validated JWT (TokenClaims) — never trusted from the body.
    author_name: str = ""
    author_email: str = ""
    description: str | None = None
    alias: str | None = None
    # Core structural fields (standards §4.1/§4.2) editable in the global editor
    # so a curator can correct a wrong SAP-derived default. db_table_name +
    # classification are common-header (any layer); entity_role is a Silver/Gold
    # body field (§5.1) — never written onto Bronze. None = "leave unchanged".
    db_table_name: str | None = None
    entity_role: str | None = None
    classification: str | None = None
    fields: list[VizFieldUpdate] | None = None
    join_graph: list[VizJoinCondition] | None = None
    relationships: list[VizRelationship] | None = None
    normalization: dict | None = None
    # ── Full structural replace (edit-in-full parity with Create) ──────────────
    # When present, these REPLACE the corresponding YAML section wholesale, after
    # which the body is re-normalized by EntityDeriver (canonical types, derived
    # roles, primary_key, Gold source) and re-validated. None = leave unchanged.
    # ``fields_full`` is mutually exclusive with the per-field ``fields`` patch.
    fields_full: list[VizFieldFull] | None = None
    composed_of: list[str] | None = None
    grain: VizGrainSpec | None = None
    module: str | None = None
    # ``source`` drives the git commit message so the history tells you HOW a
    # change reached the workspace (manual editor vs AI-assisted enrichment vs
    # SAP merge etc.). Default is ``manual`` — the existing behaviour.
    source: Literal[
        "manual",
        "ai_assist",
        "ai_suggest_relationship",
        "import",
        "merge",
        "history_restore",
    ] = "manual"
    # Free-text notes the caller wants surfaced in the git commit message
    # WITHOUT polluting the YAML body. Used by the AI-suggest-relationship
    # flow to record per-relationship caveats (confidence level + LLM
    # decision rationale) so the audit lives in git, not in the file.
    commit_notes: list[str] | None = None


class CommitEntry(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    timestamp: datetime


# ── Iter 5: SAP JSON Merge models ────────────────────────────────────────────


class ConflictType(str, Enum):
    field_modified = "field_modified"
    field_removed = "field_removed"
    field_type_changed = "field_type_changed"
    entity_modified = "entity_modified"  # Pass G header-level


class ConflictBlock(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    yaml_id: str
    field_name: str
    conflict_type: ConflictType
    sap_value: dict
    current_value: dict
    enriched_properties: list[str]
    resolved: bool = False
    resolution: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class AutoAppliedChange(BaseModel):
    yaml_id: str
    field_name: str
    change_type: str  # "added" | "removed" | "type_changed"
    old_value: dict | None = None
    new_value: dict | None = None


class MergeResult(BaseModel):
    silver_id: str
    auto_applied: list[AutoAppliedChange] = []
    conflicts: list[ConflictBlock] = []
    baseline_updated: bool = False
    # Identifier-hygiene warnings from the SAP parser (values the normalizer
    # had to change). Non-blocking; a mismatch risk under alias column naming.
    naming_warnings: list[str] = []


class ConflictResolutionRequest(BaseModel):
    decision: str  # "keep_enriched" | "accept_sap"
    author_email: str = ""  # commit author derived server-side from JWT


class BulkResolutionItem(BaseModel):
    conflict_id: str
    decision: str  # "keep_enriched" | "accept_sap"


class BulkConflictResolutionRequest(BaseModel):
    """Resolve many conflicts of ONE entity in a single pass — the fast path
    for upload-first ingests where a whole export's worth of differences lands
    at once. One YAML write + one commit instead of N."""

    resolutions: list[BulkResolutionItem]
    author_email: str = ""


class IngestSapJsonRequest(BaseModel):
    payload: dict  # the raw SAP JSON
    author_email: str = ""  # commit author derived server-side from JWT


# ── Iter 6: History / restore models ─────────────────────────────────────────


class RestoreRequest(BaseModel):
    author_email: str = ""  # commit author derived server-side from JWT
    reason: str = ""


# ── Stats / search models ─────────────────────────────────────────────────────


class StatsResponse(BaseModel):
    total_yamls: int
    by_layer: dict[str, int]
    pending_conflicts: int
    recently_updated: int

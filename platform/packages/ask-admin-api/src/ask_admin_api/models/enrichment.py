"""Pydantic models for ``/v1/admin/enrich/*`` — AI-assisted YAML enrichment."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Scope selection (Step 1 of the entity flow) ─────────────────────────────


class EnrichEntityScopeDefaults(BaseModel):
    """Body for ``GET /v1/admin/enrich/entity/{id}/scope-defaults``.

    Pre-computed scope the SPA renders as the checklist:
      * ``enrichable_fields`` — eligible fields with priority hint
      * ``technical_fields`` — auto-excluded (mandt, ernam, audit, …)
      * ``entity_level`` — whether the entity-level description / alias is enrichable
      * ``default_selection`` — fields the SPA pre-checks (empty / short / missing synonyms)
    """

    entity_id: str
    layer: str
    enrichable_fields: list[FieldScopeRow]
    technical_fields: list[str]
    entity_level: EntityLevelScope
    default_selection: DefaultSelection
    # Optional plain-text framing the backend will feed the LLM when this
    # entity is enriched inside ``workspace_id`` (Data Products that own the
    # entity + sibling entities + workspace objective). Surfaced verbatim in
    # the SPA so the admin sees exactly what the model is biased toward — no
    # hidden context. ``None`` when no workspace_id was passed OR when the
    # entity isn't part of any DP in that workspace.
    workspace_context: str | None = None


class FieldScopeRow(BaseModel):
    name: str
    current_description: str = ""
    has_description: bool
    has_synonyms: bool
    priority: Literal["empty", "short", "good"]
    # True when the field matches a boolean / status / flag pattern (is_*,
    # has_*, *_flag, *_status, type=C1, etc.). The SPA renders a chip to
    # warn the admin "this is short by design, not by neglect — only enrich
    # if you have a strong reason". These rows are NOT auto-selected.
    is_likely_flag: bool = False


class EntityLevelScope(BaseModel):
    """Snapshot of the entity-level enrichable fields.

    Mirrors the per-field `FieldScopeRow` shape so the SPA can render the
    same kind of preview ("here is the current value, here is the priority
    bucket") for entity-level metadata as it does for fields.
    """

    has_description: bool
    has_alias: bool
    has_business_process: bool
    current_description: str = ""
    current_alias: str = ""
    current_business_process: str = ""
    priority: Literal["empty", "short", "good"] = "good"


class DefaultSelection(BaseModel):
    entity_level: bool
    field_names: list[str]


# ── Preview (Step 2 of the entity flow) ─────────────────────────────────────


class EnrichEntityScope(BaseModel):
    """Step-1 selection sent to ``POST /v1/admin/enrich/entity/preview``."""

    entity_level: bool = False
    field_names: list[str] = Field(default_factory=list)


class EnrichEntityRequest(BaseModel):
    entity_id: str
    scope: EnrichEntityScope
    # Optional workspace context — when supplied, the backend looks up the
    # workspace + its Data Products + sibling entities and feeds that to the
    # LLM as additional framing (e.g. "this entity is part of the OTC
    # sales-performance Data Product, sibling entities are A, B, C"). Lets
    # the model write descriptions / synonyms that align with how the entity
    # is consumed in this specific workspace, not just generic SAP semantics.
    workspace_id: str | None = None


# ── Body-aware (draft) variants — AI on a not-yet-saved entity ───────────────
# The create form has no saved id; these accept the DRAFT YAML body instead and
# reuse the SAME service methods (which already take ``raw_yaml``). Design §3.4.


class EnrichEntityDraftRequest(BaseModel):
    """``POST /entity/preview/draft`` — entity-level (and bulk-field) enrichment
    over a draft node."""

    raw_yaml: dict[str, Any]
    scope: EnrichEntityScope
    workspace_id: str | None = None
    entity_id: str | None = None  # optional label for logs / response echo


class EnrichFieldDraftRequest(BaseModel):
    """``POST /field/draft`` — single-field enrichment over a draft node."""

    raw_yaml: dict[str, Any]
    field_name: str
    entity_id: str | None = None


class RelationshipSuggestDraftRequest(BaseModel):
    """``POST /relationships-suggest/draft`` — Mode-2 suggest where the source is
    the in-progress draft and the target is an existing persisted entity."""

    source_raw_yaml: dict[str, Any]
    target_entity_id: str
    workspace_id: str | None = None
    source_entity_id: str | None = None


class FieldDiff(BaseModel):
    """One field's proposed changes. Either / both keys are present."""

    field_name: str
    description: ValueDiff | None = None
    synonyms: SynonymsDiff | None = None


class ValueDiff(BaseModel):
    old: str
    new: str


class SynonymsDiff(BaseModel):
    old: list[str] = Field(default_factory=list)
    new: list[str] = Field(default_factory=list)


class EntityDiff(BaseModel):
    """Entity-level proposed changes. Each key is null when unchanged."""

    description: ValueDiff | None = None
    alias: ValueDiff | None = None
    business_process: ValueDiff | None = None


class EnrichmentDiagnostic(BaseModel):
    """Why the diff is the way it is — helps the admin debug a problematic run.

    Surfaced in the SPA in two situations:
      * 0-change diff (the model spent tokens but produced nothing usable)
      * parse failure (the model returned malformed YAML)

    Lets the admin see whether the model copied the YAML through, renamed
    fields (hallucination), got truncated, or emitted garbage at a specific
    line — without forcing them to dig through server logs.
    """

    original_field_count: int = 0
    enriched_field_count: int = 0
    matched_field_count: int = 0
    fields_only_in_enriched: list[str] = Field(default_factory=list)
    fields_only_in_original: list[str] = Field(default_factory=list)
    response_chars: int = 0
    response_preview: str = ""
    response_tail: str = ""
    parse_error: str | None = None


class EnrichEntityResponse(BaseModel):
    entity_id: str
    provider: str
    model: str
    entity_diff: EntityDiff
    field_diffs: list[FieldDiff]
    fields_skipped_technical: list[str] = Field(default_factory=list)
    fields_unchanged: list[str] = Field(default_factory=list)
    # Caveats emitted by the description-preservation validator: when the LLM
    # rewrites a description that already had value mappings (``'C' = CLOSE``),
    # source citations (``VBAK.NETWR``), or alternative-field hints, and the
    # rewrite would drop those tokens, the backend rejects the change and
    # records the reason here. Surfaced in the SPA preview so the admin
    # sees what was preserved and why.
    caveats: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    elapsed_ms: int = 0
    diagnostic: EnrichmentDiagnostic | None = None


# ── Relationship suggestion (Modo 2 — Complete) ─────────────────────────────

# We don't reuse ``VizRelationship`` from viz_models.py to avoid a
# cross-module import cycle (enrichment models live below viz models in the
# package dep order). The shape mirrors VizRelationship 1:1 — the SPA
# adapter handles the type identity.


class SuggestedRelationship(BaseModel):
    """Mirror of ``VizRelationship`` — what the LLM returns and what the SPA
    pegs into the editor."""

    target_entity: str
    relationship_type: str | None = None
    join_condition: str | None = None
    semantic_label: str | None = None
    traversal_cost: float | None = None
    aggregation_safety: str | None = None
    cross_module: bool | None = None
    description: str | None = None


class RelationshipSuggestRequest(BaseModel):
    """Body for ``POST /v1/admin/enrich/relationships-suggest`` (mode=complete).

    The admin already picked the target_entity in the editor; this endpoint
    asks the LLM to fill in the join_condition + cardinality + safety +
    cost + label + description for that specific pair.
    """

    source_entity_id: str
    target_entity_id: str
    # Workspace context is optional — same as in ``preview_entity``. When
    # supplied the prompt gets the workspace framing (DPs + sibling
    # entities). Skipped when the admin is editing outside any workspace.
    workspace_id: str | None = None


class RelationshipSuggestResponse(BaseModel):
    """Three-state outcome: clean match / match-with-caveats / no match.

    The shape was designed so that the SPA can render the three UX flavours
    (green Apply / amber Apply with caveats / red "no suggestion") without
    inspecting nested fields. The ``relationship`` field is ``None`` iff the
    LLM declined to invent one — see ``no_match_reason``.
    """

    provider: str
    model: str

    relationship: SuggestedRelationship | None = None
    confidence: Literal["high", "medium", "low"] = "low"
    caveats: list[str] = Field(default_factory=list)
    no_match_reason: str | None = None

    tokens_used: int = 0
    elapsed_ms: int = 0
    # Reused diagnostic shape — populated on parse / response anomalies so
    # the SPA can show "the model returned malformed JSON / response was
    # truncated" without spelunking the logs.
    diagnostic: EnrichmentDiagnostic | None = None


# ── Prompt preview (read-only "show me what the LLM sees") ──────────────────


class PromptPreviewRequest(BaseModel):
    """Body for ``POST /v1/admin/enrich/entity/{id}/prompt-preview``.

    Mirrors ``EnrichEntityRequest`` but the endpoint does NOT call the LLM —
    it just returns the composed (system, user) pair so the admin can audit
    exactly what the model would see for this scope.
    """

    scope: EnrichEntityScope
    workspace_id: str | None = None


class PromptPreviewResponse(BaseModel):
    entity_id: str
    provider: str
    model: str
    system_message: str
    user_message: str
    # Convenience counts so the SPA can show "you're about to send N chars"
    # without doing utf-8 math client-side.
    system_chars: int
    user_chars: int


# ── Per-field one-shot ──────────────────────────────────────────────────────


class EnrichFieldRequest(BaseModel):
    entity_id: str
    field_name: str


class EnrichFieldResponse(BaseModel):
    entity_id: str
    field_name: str
    provider: str
    model: str
    diff: FieldDiff
    tokens_used: int = 0
    elapsed_ms: int = 0
    # Preservation-guard messages (same contract as EnrichEntityResponse):
    # when the AI rewrite would drop critical tokens (value mappings,
    # TABLE.FIELD citations) the change is cancelled and explained here.
    caveats: list[str] = Field(default_factory=list)


# Forward refs — Pydantic v2 resolves these automatically when models are
# evaluated, but be explicit so the import order is robust.
EnrichEntityScopeDefaults.model_rebuild()
FieldScopeRow.model_rebuild()
FieldDiff.model_rebuild()

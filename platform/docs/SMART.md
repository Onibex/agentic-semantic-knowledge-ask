# Pipeline v2 — Technical Reference

> Version: v2.0  ·  Shipped: 2026-04-21
> Scope: Catalog-driven LLM-as-retriever + Graph RAG + freeform SQL generator
> Status: All 7 phases DONE. 9/9 benchmark questions execute against HANA without DB errors.

> ⚠️ **Historical file paths.** This reference predates the Strangler-Fig refactor. Every `src/pipeline_v2/...` and `src/pipeline/...` path below is **dead** — that code now lives in `packages/ask-intent-resolution/` (the **Smart** strategy + its `pipeline_v2/` backend). The *concepts* (catalog-driven LLM-as-retriever, Graph RAG, freeform SQL) are current; only the locations moved. See [CLAUDE.md](../CLAUDE.md) for the authoritative package map. Repointing every inline path is a pending cleanup.

This document unifies:
- The architectural specification (Onibex ASK Specification v1.0, © 2026).
- The concrete implementation — historically `src/pipeline_v2/`, now `packages/ask-intent-resolution/` (see banner above).
- The operational artifacts (config, scripts, UI).

It is meant as the definitive **technical reference** for the pipeline v2 flow ("Smart" engine in the chat selector).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Why a second pipeline](#2-why-a-second-pipeline)
3. [Architectural alignment with the ASK spec](#3-architectural-alignment-with-the-ask-spec)
4. [End-to-end data flow](#4-end-to-end-data-flow)
5. [Components — services in detail](#5-components--services-in-detail)
6. [Domain models](#6-domain-models)
7. [OpenSearch data model](#7-opensearch-data-model)
8. [Configuration](#8-configuration)
9. [YAML ingestion](#9-yaml-ingestion)
10. [LangGraph topology](#10-langgraph-topology)
11. [UI integration](#11-ui-integration)
12. [Testing and preview scripts](#12-testing-and-preview-scripts)
13. [Metrics and benchmark](#13-metrics-and-benchmark)
14. [Intentional divergences from the spec](#14-intentional-divergences-from-the-spec)
15. [Known gaps and roadmap](#15-known-gaps-and-roadmap)
16. [How to extend](#16-how-to-extend)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. Overview

Pipeline v2 resolves a natural-language business question into executable SQL through **four deterministic stages**, two of which call an LLM:

```
User question
    │
    ▼
  [Stage 1] CatalogService         (no LLM, reads OpenSearch)
    │   ↓ injects compact entity catalog into prompt
    ▼
  [Stage 2] EntitySelectorService  (LLM call #1 — Claude 4.6 Sonnet)
    │   ↓ produces SemanticPlanIRv2
    ▼
  [Stage 3] PathResolver           (no LLM, Dijkstra on Edge Registry)
    │   ↓ produces ResolvedPlan with edges + join conditions
    ▼
  [Stage 4] SQLGeneratorServiceV2  (LLM call #2 — Claude 4.6 Sonnet, freeform)
    │   ↓ produces SQL string
    ▼
  [Stage 5] execute_sql_query      (no LLM, SAP HANA or PostgreSQL)
    │   ↓ returns rows
    ▼
Response to user
```

**Principles:**
- **Source of truth**: the Bronze / Silver / Gold YAMLs in the semantic-layer repo. OpenSearch indices are caches.
- **Graph-first**: cross-entity queries are resolved through the Edge Registry, not LLM guessing.
- **Gold-first**: the selector naturally prefers pre-aggregated Gold entities when they cover the query intent.
- **Hard-require**: if a required piece (raw_yaml, edge, entity) is missing, the pipeline fails loud.
- **No silent fallbacks**: every error path is explicit.

---

## 2. Why a second pipeline

Pipeline v1 (`src/pipeline/`) worked but had two operational problems:

| Problem | Root cause | Impact |
|---|---|---|
| ~$1/query cost | Passed 5 full raw YAMLs to the SQL generator unconditionally | Unsustainable at production scale |
| Doesn't scale past ~100 entities | kNN+BM25 retrieval struggles to discriminate among many similar entities | Blocker for large customer catalogs |
| Cross-module queries are guesswork | Hybrid retrieval doesn't know which edges connect modules | Pipeline makes invalid JOINs |

The key insight came from reading the ASK specification PDF (already authored internally): it prescribes a **three-registry graph model** (Entity, Field, Edge) with `cross_module` as a first-class edge property. v1 implemented the registries but did not exploit the graph for path planning. v2 does.

v1 remains intact and usable. Both are strategies behind the same `IntentResolver` Protocol, selected per request by the `mode` field of `POST /v1/query`.

---

## 3. Architectural alignment with the ASK spec

The ASK Specification defines three processing layers. Pipeline v2 implements two of them verbatim and intentionally diverges on the third.

| ASK Spec | Pipeline v2 component | File | Status |
|---|---|---|---|
| **Layer 1 — Intent Resolution** (Sec 12–13) | CatalogService + EntitySelectorService | `application/catalog_service.py`, `application/entity_selector.py` | Implemented |
| **Layer 2 — Semantic Plan IR** (Sec 10) | SemanticPlanIRv2 + PathResolver | `domain/ir.py`, `application/path_resolver.py` | Implemented |
| **Layer 3a — Path Selection** (Sec 8.2, 8.3) | PathResolver (Dijkstra + cross_module) | `application/path_resolver.py` | Implemented |
| **Layer 3b — Graph Compiler** (Sec 11) | — | — | **Not aligned** — replaced by FreeformSQLGenerator |
| **Layer 3c — SQL Generation** (Sec 11 Phase 8) | SQLGeneratorServiceV2 (freeform adapter) | `application/sql_generator.py` | Implemented differently |
| **Dialect Transpilation** (Sec 11 Phase 9) | — | — | LLM emits HANA dialect directly |

The deterministic compiler (Sec 11) was deliberately skipped — it cannot express CTEs, arithmetic composition, window functions, or multi-stream patterns that our benchmark requires. Freeform SQL generation (reused from v1) handles these patterns while still being constrained by:
- The resolved entity set (from the Path Resolver).
- The declarative JOIN hints injected into the prompt.
- The strict HANA syntax rules in the freeform prompt template.

---

## 4. End-to-end data flow

### State container — `AgentStateV2`

All stages read and write a `TypedDict` defined in [`src/pipeline_v2/graph/state.py`](../src/pipeline_v2/graph/state.py). Every field is JSON-serializable so the LangGraph checkpointer can persist it across invocations.

```python
class AgentStateV2(TypedDict, total=False):
    # Input
    question: str
    original_question: Optional[str]
    conversation_history: Optional[str]
    user_role_id: Optional[str]

    # Selector output
    ir_dict: Optional[dict]             # SemanticPlanIRv2.model_dump()
    selector_invalid_ids: Optional[list[str]]
    selector_retry_count: Optional[int]

    # Path resolver output
    resolved_plan_dict: Optional[dict]  # ResolvedPlan.model_dump()

    # SQL stage output
    sql_query: Optional[str]
    sql_error: Optional[str]

    # DB execution output
    sql_results: Optional[list[dict]]
    row_count: Optional[int]

    # UI output
    response: Optional[str]
    error: Optional[str]
    trace: Optional[dict]               # for Pipeline Trace expander
```

### Sequence diagram

```
┌─────────┐   question    ┌──────────────────┐
│  User   ├──────────────>│ LangGraph invoke │
└─────────┘                └────────┬─────────┘
                                    │
                           START ───┘
                                    │
                           ┌────────▼─────────┐
                           │ select_entities  │
                           │                  │
                           │ 1. CatalogService.get_catalog(allowed_ids)
                           │ 2. EntitySelectorService.select(question)
                           │    → LLM call #1 (Sonnet, temp=0)
                           │    → parses JSON → SemanticPlanIRv2
                           │    → validates IDs against catalog.valid_ids()
                           │    → retry up to 2x if IDs hallucinated
                           │                  │
                           │ Output: ir_dict, trace.selector_*
                           └────────┬─────────┘
                                    │
                           selector_router
                              ┌─────┴─────┐
                              │           │
                      (base_entity    (empty base)
                          present)         │
                              │            ▼
                              │          END (error in state)
                              ▼
                           ┌──────────────────┐
                           │  resolve_paths   │
                           │                  │
                           │ 1. Load edges from ask-edge-registry-v1
                           │    (cached per process)
                           │ 2. Filter edges: both endpoints in allowed_entities
                           │ 3. Build NetworkX DiGraph (weight=traversal_cost)
                           │ 4. For each target in ir.traversals[]:
                           │      Dijkstra shortest_path(base → target)
                           │                  │
                           │ Output: resolved_plan_dict, trace.resolved_*
                           └────────┬─────────┘
                                    │
                           path_router
                              ┌─────┴─────┐
                              │           │
                      (base_entity_id  (empty base)
                          present)         │
                              │            ▼
                              │          END
                              ▼
                           ┌──────────────────┐
                           │   generate_sql   │
                           │                  │
                           │ 1. mget raw_yaml for all entities in resolved_plan
                           │    (fails loud if any missing)
                           │ 2. Render edges as declarative JOIN hints
                           │ 3. SQLGeneratorServiceV2.generate(question, ir, plan)
                           │    → delegates to FreeformSQLGeneratorService
                           │    → LLM call #2 (Sonnet, freeform)
                           │                  │
                           │ Output: sql_query, trace.sql_chars
                           └────────┬─────────┘
                                    │
                           sql_router
                              ┌─────┴─────┐
                              │           │
                        (sql_query     (error)
                           present)        │
                              │            ▼
                              │          END
                              ▼
                           ┌──────────────────┐
                           │   execute_sql    │
                           │                  │
                           │ If db_config is provided:
                           │   execute_sql_query(sql, db_type, db_config)
                           │   → returns rows + columns
                           │ Else: dry-run, response = SQL as text
                           │                  │
                           │ Output: sql_results, row_count, response
                           └────────┬─────────┘
                                    │
                                   END
```

---

## 5. Components — services in detail

### 5.1 `CatalogService`

**File:** [`src/pipeline_v2/application/catalog_service.py`](../src/pipeline_v2/application/catalog_service.py)
**Spec reference:** Sec 7.1 (Entity Registry), Sec 13.1 (Retrieval Ranking — uses only fields for selection, not vectors).

**Responsibility:** Build a compact, stable, deterministic catalog of queryable entities for injection into the selector's system prompt.

**Filter logic (3 layers):**
1. **Hard filter at query**: `layer in ["silver", "gold"]` at OpenSearch level. Bronze excluded categorically.
2. **Static class filter**: `CatalogEntry.layer: Literal["silver", "gold"]` — Pydantic rejects invalid values at parse time.
3. **Data product filter**: `get_catalog(allowed_ids=...)` — narrows to the active data product's entity IDs.

**Key methods:**
```python
def get_catalog(allowed_ids: set[str] | None = None, force_refresh: bool = False) -> Catalog
def render_as_prompt_context(catalog: Catalog | None = None) -> str
def refresh() -> Catalog
@staticmethod
def resolve_active_entity_ids(config: dict) -> set[str] | None
```

**Rendered catalog format** (stable for prompt caching):
```yaml
=== ENTITY CATALOG (Silver + Gold) ===
total_entities: 10
groups: 5

## MM  (count: 4)
- id: silver_ecc_mm_inv_mov_stock
  name: inv_mov_stock
  layer: silver | role: fact
  description: Inventory movements (MKPF/MSEG) and current stock positions ...

## MM,PP,SD  (count: 2)
- id: gold_ecc_inventory_situation
  name: inventory_situation
  layer: gold | role: fact
  description: Inventory situation and future stock projections ...
...
```

Entities are grouped by `module` (Silver) or `Gold / <domain>` (Gold), alphabetically sorted within each group. The rendering is **byte-stable** across calls — identical catalog produces identical string — enabling Claude prompt caching.

**Cost:** ~950 input tokens for 10 entities. Cacheable. Steady-state per query: ~$0.0002 USD.

### 5.2 `EntitySelectorService`

**File:** [`src/pipeline_v2/application/entity_selector.py`](../src/pipeline_v2/application/entity_selector.py)
**Spec reference:** Sec 10 (Semantic Plan IR Specification), Sec 24.1 (Intent Resolution example).

**Responsibility:** Single LLM call that produces a `SemanticPlanIRv2` from the user's question + the catalog.

**Prompt structure (3 blocks, all in system message):**

1. **SYSTEM RULES** — role definition, constraints, JSON output schema, format rules.
2. **ENTITY CATALOG** — the compact catalog (byte-stable).
3. **FEW-SHOT EXAMPLES** — 3 examples: single-fact aggregation, cross-entity with conditional filter, unresolvable.

The user message contains only the conversation history + the question, making the system prompt a large stable prefix that benefits from prompt caching.

**Validation pipeline:**
1. Strip markdown code fences if present (defensive).
2. Locate first `{` and last `}` — tolerant to leading/trailing text.
3. `json.loads` the substring.
4. `SemanticPlanIRv2.model_validate(data)` — Pydantic enforces schema.
5. Check `base_entity` ∈ `catalog.valid_ids()`.
6. Check each `traversals[]` id ∈ `catalog.valid_ids()`.
7. If any invalid → retry with feedback prompt (max 2 retries).

**Output:** `SelectorOutput(ir, invalid_entity_ids, retry_count)`.

**Observations from benchmark (9 questions):**
- 9/9 produced valid IR on first attempt.
- 0 retries required.
- 0 invalid IDs (no hallucinations).
- Selector is "honest" — when the query references an entity not in scope (e.g., sales orders in an inventory-scoped catalog), it documents the limitation in `reasoning` and finds the best alternative.
- **Gold-first emerges naturally**: in all 9 benchmark questions the selector picked a Gold entity as `base_entity` when available. This is not a hardcoded rule — it emerges from the LLM reading the Gold entities' rich descriptions ("future stock projections", "incoming tracking") and matching them to the question intent.

### 5.3 `PathResolver`

**File:** [`src/pipeline_v2/application/path_resolver.py`](../src/pipeline_v2/application/path_resolver.py)
**Spec reference:** Sec 7.3 (Edge Registry), Sec 8 (Path and Traversal Model), Sec 8.3 (Multi-Hop Cross-Module Query Planning).

**Responsibility:** Deterministically resolve the shortest path from `base_entity` to each target in `ir.traversals[]` using the Edge Registry graph.

**Algorithm:**
1. Load all edges from `ask-edge-registry-v1` via `helpers.scan` (cached per process).
2. Filter edges where both endpoints are in `allowed_entities` (data product scope).
3. Build NetworkX `DiGraph`: nodes = entity_ids, edges weighted by `traversal_cost`.
4. For each `target` in IR traversals: `nx.shortest_path(g, source=base, target=target, weight="weight")`.
5. Reconstruct `TraversalPath` with edges + join_keys + cross_module flags.
6. If target unreachable → add to `unresolved_targets` (caller decides policy).

**Spec alignment — Path Selection Rules (Sec 8.2):**
- **Rule 1 — Grain correctness**: placeholder (returns True). Future: check `aggregation_safety` on each edge.
- **Rule 2 — Aggregation safety**: edges with `aggregation_safety=="unsafe"` filtered from the graph at build time.
- **Rule 3 — Lowest cost**: Dijkstra's weight=`traversal_cost` selects minimum-cost path.
- **Rule 4 — Shortest path**: implicit tie-break in Dijkstra (visits fewer nodes first).

**Multi-hop example from benchmark (Q2):**
- base_entity: `silver_ecc_mm_inv_mov_stock`
- target: `silver_ecc_pp_production_confirmation`
- No direct edge exists between them.
- Dijkstra finds: `stock → silver_ecc_sd_plant → production_confirmation` (cost 1.5 + 1.5 = 3.0). The second hop uses a reverse edge (`is_reverse=True`).

### 5.4 `SQLGeneratorServiceV2`

**File:** [`src/pipeline_v2/application/sql_generator.py`](../src/pipeline_v2/application/sql_generator.py)
**Spec reference:** Sec 11 (Graph Compiler) — **intentionally not aligned**. Pipeline v2 uses an adapter to the freeform generator from v1 (`src/pipeline/application/freeform_sql_generator.py`).

**Responsibility:** Adapter layer that prepares the inputs for the freeform generator:

1. **Fetch raw YAMLs** — `mget` on `ask-entity-registry-v1` for all entities in `resolved_plan.all_entities`. Hard require: if any entity doc lacks `raw_yaml`, raises `RuntimeError` (forces operator to re-ingest).

2. **Render edges hint** — iterate all paths in `resolved_plan.paths`, for each edge emit one declarative line:
```
# Edge: silver_ecc_mm_inv_mov_stock LEFT JOIN silver_ecc_sd_plant
  ON SILVER_ECC_MM_INV_MOV_STOCK.werks_marc = SILVER_PLANTS.werks_t001w
  (cost=1.5, cross_module=True)
```

3. **Call `FreeformSQLGeneratorService.generate`** with:
   - `question` (verbatim).
   - `ir_hints` = `ir.model_dump(exclude_none=True)`.
   - `yamls` = list of raw_yaml strings.
   - `glossary` = the edges hint block (injected as authoritative JOIN reference).
   - `conversation_history` = passed through.

**Why reuse v1's FreeformSQLGeneratorService:**
- The prompt handles HANA SQL dialect constraints that took weeks to tune (`ADD_DAYS`, `LIST_AGG`, CTE double-quoting, etc.).
- The freeform generator is tagged with `track_phase("freeform_sql_generation")`, preserving backwards-compatible token metrics.
- Re-implementing would duplicate maintenance.

---

## 6. Domain models

### 6.1 `CatalogEntry` + `Catalog` (catalog.py)

```python
class CatalogEntry(BaseModel):
    id: str                              # e.g., "silver_ecc_sd_sales_order"
    name: str
    layer: Literal["silver", "gold"]     # Bronze excluded by type
    module: str | None                   # "SD", "MM", etc. Silver has it; Gold inferred
    entity_role: Literal["fact", "dimension", "reference"]
    description: str
    entity_type: str | None              # Spec Sec 7.1 — e.g., "journal_entry"
    business_process: str | None         # For Gold: domain like "AR", "OTC"

    @property
    def grouping_key(self) -> str: ...   # "MM" or "Gold / AR"
```

### 6.2 `SemanticPlanIRv2` (ir.py) — spec Sec 10

```python
class SemanticPlanIRv2(BaseModel):
    intent: str                          # NL description
    base_entity: str                     # entity ID (or "" if unresolvable)
    measures: list[str]                  # business-term names
    dimensions: list[str]                # business-term names
    filters: list[IRFilter]              # {field, operator, value | values}
    time_context: IRTimeContext | None   # {field, start, end, granularity}
    traversals: list[str]                # entity IDs to reach
    output_shape: Literal["table", "scalar", "time_series", "ranked_list"]
    sorting: list[IRSort]                # [{field, direction}]
    limit: int | None
    module_hints: list[str]              # v2 extension, not in spec
    reasoning: str | None                # v2 extension, for trace
```

Supported filter operators: `EQ`, `NE`, `GT`, `GE`, `LT`, `LE`, `IN`, `NOT_IN`, `LIKE`, `NOT_LIKE`, `IS_NULL`, `IS_NOT_NULL`, `BETWEEN`.

Supported granularities: `day`, `week`, `month`, `quarter`, `year`.

### 6.3 `EdgeInfo` + `TraversalPath` + `ResolvedPlan` (path.py)

```python
class EdgeInfo(BaseModel):
    source_entity: str
    target_entity: str
    relationship_type: str | None
    join_keys: list[tuple[str, str]]     # [(left_field, right_field), ...]
    join_type: Literal["INNER", "LEFT", "RIGHT", "FULL", "CROSS"]
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"] | None
    traversal_cost: float = 1.0          # spec Sec 6.5
    aggregation_safety: Literal["safe", "unsafe", "conditional"] = "safe"
    cross_module: bool = False           # spec first-class flag
    semantic_label: str | None
    is_reverse: bool = False

    def as_sql_hint(self) -> str: ...    # declarative line for prompt

class TraversalPath(BaseModel):
    base_entity: str
    target_entity: str
    entity_chain: list[str]              # ordered nodes
    edges: list[EdgeInfo]
    total_cost: float
    grain_preserved: bool
    aggregation_safe: bool

    def is_single_hop(self) -> bool: ...
    def has_cross_module_hop(self) -> bool: ...

class ResolvedPlan(BaseModel):
    base_entity_id: str
    paths: list[TraversalPath]
    all_entities: list[str]              # base + all targets + intermediaries
    unresolved_targets: list[str]        # targets that couldn't be reached

    def is_complete(self) -> bool: ...
```

---

## 7. OpenSearch data model

Pipeline v2 **reuses** v1's indices. No new indices were created.

| Index | Content | Used by v2 |
|---|---|---|
| `ask-entity-registry-v1` | 1 doc per entity: id, layer, module, entity_role, name, description, raw_yaml, embedding, fields summary, etc. | CatalogService (read-only), SQLGeneratorServiceV2 (`mget` for raw_yaml) |
| `ask-field-registry-v1` | 1 doc per field per entity: name, field_role, type, description, aggregation_behavior | **Not used by v2** (fields are extracted from raw_yaml at SQL gen time) |
| `ask-edge-registry-v1` | 1 doc per edge (forward + auto-generated reverse): source_node, target_node, join_type, conditions (list of {left_field, right_field, operator}), cardinality, traversal_cost, is_reverse, semantic_label, cross_module | PathResolver (read-only, scanned once and cached) |
| `ask-semantic-dictionary-v1` | v1 glossary | **Not used by v2** |

### Entity Registry doc example

```json
{
  "id": "gold_ecc_inventory_situation",
  "internal_id": "gold_ecc_inventory_situation",
  "db_table_name": "GOLD_INVENTORY_SITUATION",
  "layer": "gold",
  "version": "1",
  "source_system": "ecc",
  "business_process": "SCM",
  "module": "MM,PP,SD",
  "name": "inventory_situation",
  "description": "Inventory situation and future stock projections...",
  "entity_role": "fact",
  "grain": {"entity_grain": ["client", "plant_id", "material_id", "future_date"]},
  "composed_of": ["MY_SCHEMA.GOLD_INVENTORY_SITUATION"],
  "raw_yaml": "<full YAML text>",
  "embedding": [<3072 floats>]
}
```

### Edge Registry doc example

```json
{
  "source_node": "silver_ecc_mm_inv_mov_stock",
  "target_node": "silver_ecc_sd_plant",
  "join_type": "LEFT OUTER",
  "conditions": [
    {
      "left_field": "SILVER_ECC_MM_INV_MOV_STOCK.werks_marc",
      "right_field": "SILVER_PLANTS.werks_t001w",
      "operator": "="
    }
  ],
  "cardinality": "many_to_one",
  "traversal_cost": 1.5,
  "is_reverse": false,
  "semantic_label": "stock_at_plant",
  "cross_module": true
}
```

Note that `conditions[].left_field` and `right_field` use **fully qualified physical names** (`TABLE.column`). This is what the SQL generator sees when composing JOINs.

---

## 8. Configuration

### 8.1 `config/settings.json` — `pipeline_v2` section

```json
{
  "pipeline_v2": {
    "active_data_product": "inventory_situation",
    "data_products": {
      "inventory_situation": {
        "description": "Inventory visibility — stock, POs, production orders, material master, plus Gold analytical products for projection + reception + open-orders.",
        "entity_ids": [
          "gold_ecc_inventory_situation",
          "gold_ecc_order_tracking_reception",
          "gold_ecc_open_order_tracker",
          "silver_ecc_mm_inv_mov_stock",
          "silver_ecc_mm_purchase_order",
          "silver_ecc_pp_production_confirmation",
          "silver_ecc_mm_material_group",
          "silver_ecc_mm_material_hierarchy",
          "silver_ecc_sd_plant",
          "silver_ecc_sd_trading_goods"
        ]
      }
    }
  }
}
```

### 8.2 Adding a new data product

Add a new key under `data_products` with its own `entity_ids` list, then switch `active_data_product` to that name. No code changes needed.

```json
"data_products": {
  "inventory_situation": { ... },
  "accounts_receivable": {
    "description": "AR visibility — customer balances, invoices, aging.",
    "entity_ids": ["gold_ar_journal_entries_summary", ...]
  }
}
```

### 8.3 Switching data product at runtime

`active_data_product` is read once at service initialization. Restart the backend process to switch.

Future: let the caller select the product per request.

---

## 9. YAML ingestion

### 9.1 Source of truth

The semantic-layer git repository on disk (bind-mounted into the admin-api as `/app/semantic-layer`). Structure:

```
semantic-layer/
├── silver/
│   ├── mm/{inv_mov_stock, purchase_order, material_group (SD dir but module MM), material_hierarchy}.yaml
│   ├── pp/{production_confirmation}.yaml
│   └── sd/{customer_master, customer_sales_district, distribution_channel, invoice, plant,
│            sales_division, sales_office, sales_order, sales_organization, shipping_condition,
│            trading_goods, ...}.yaml
└── gold/
    ├── gold_inventory_situation.yml
    ├── gold_ecc_order_tracking_reception.yml
    ├── gold_ecc_sd_open_order_tracker.yml
    └── gold_ec_sd_sales_performance.yml        ← excluded from scope
```

Silver uses `.yaml`, Gold uses `.yml` (historical inconsistency — preserved as-is).

### 9.2 Ingestion entry point

**Ingestion goes through `ask-admin-api`** — one authoritative path, driven by the ASK Studio:

1. `POST /v1/admin/yaml/import` writes the YAML into the semantic-layer repo (git-versioned).
2. `POST /v1/admin/yaml/index/{entity_id}/{env}` publishes it: the payload is parsed and dispatched to `save_silver_node` or `save_gold_node` based on the `layer` field.
3. Idempotent: same `_id` → OpenSearch upserts.
4. A whole Business Domain can be published at once (`POST /v1/admin/business-domains/{id}/publish/{env}`), which streams per-Data-Product progress.

The ingestion service itself lives in `ask-knowledge-graph` (`application/ingestion_service.py`) and is shared by both engines.

### 9.3 Bugs fixed during pipeline v2 development

Two critical bugs existed in v1's ingestion path, only exposed when we attempted Gold ingestion:

**Bug 1 — `ingestion_service.py` called `save_silver_node` for Gold layer.**
Fix: dispatch Gold layer to `save_gold_node` and generate embedding from `name + description`.

**Bug 2 — `save_gold_node` iterated `node.dimensions` and `node.metrics`, attributes that the current `GoldNode` class does not have.**
Fix: iterate `node.fields` and classify by `field_role` (measure / timestamp / dimension), same pattern as `save_silver_node`. Also added `module`, `version`, `grain` to the Gold entity doc so the CatalogService can read them consistently with Silver.

Both fixes are in [`src/pipeline/application/ingestion_service.py`](../src/pipeline/application/ingestion_service.py) and [`src/pipeline/infrastructure/repositories/opensearch_repository.py`](../src/pipeline/infrastructure/repositories/opensearch_repository.py).

---

## 10. LangGraph topology

### 10.1 Compile entry point

```python
from ask_intent_resolution.pipeline_v2.graph.v2_graph import build_v2_graph

graph = build_v2_graph(
    catalog_service=catalog_service,
    entity_selector=entity_selector,
    path_resolver=path_resolver,
    sql_generator=sql_generator,
    db_type="hana",
    db_config=DB_CONFIG,              # None = dry-run (skips DB execution)
    allowed_entity_ids={"silver_...", "gold_..."},
    checkpointer=MemorySaver(),
)

result = graph.invoke(
    {
        "question": "How many units of Material Z arrive today?",
        "conversation_history": "...",
    },
    config={"configurable": {"thread_id": "session-123"}},
)
```

### 10.2 Node definitions

Each node closes over the injected services. Nodes return **partial** state updates — LangGraph merges them with the existing state.

| Node | Responsibility | State written |
|---|---|---|
| `select_entities` | Run Selector → produce IR | `ir_dict`, `selector_invalid_ids`, `selector_retry_count`, `trace.selector_*` |
| `resolve_paths` | Run PathResolver → produce plan | `resolved_plan_dict`, `trace.resolved_*` |
| `generate_sql` | Run SQL Generator | `sql_query` OR `sql_error`, `trace.sql_chars` |
| `execute_sql` | Execute against DB if `db_config` provided | `sql_results`, `row_count`, `response` |

### 10.3 Routers

| Router | From | Decision logic | Destinations |
|---|---|---|---|
| `selector_router` | `select_entities` | `ir_dict.base_entity` non-empty? | `resolve_paths` or `END` |
| `path_router` | `resolve_paths` | `resolved_plan_dict.base_entity_id` non-empty? | `generate_sql` or `END` |
| `sql_router` | `generate_sql` | `sql_query` present AND no `sql_error`? | `execute_sql` or `END` |

The graph is **stateless between invocations** for each `thread_id` unless the checkpointer restores it (MemorySaver does, for UI sessions).

---

## 11. UI integration

### 11.1 Engine selection

The chat SPA sends `mode: "smart"` on `POST /v1/query`; the orchestrator resolves it to the Smart strategy. Nothing else in the request changes between engines.

### 11.2 Pipeline trace

The `trace` returned per answer carries:
- **Selector**: base_entity, traversals, invalid_ids, retry_count, reasoning.
- **Path Resolver**: all_entities in subgraph, unresolved targets, a dataframe of paths with columns (target, hops, total_cost, cross_module, chain).
- **SQL Generator**: SQL character count.

It is populated node by node in `AgentStateV2` and returned in `QueryResponse.trace`.

### 11.3 Token tracker

Each request creates a `TokenTracker`. The `track_phase("entity_selection")` and `track_phase("freeform_sql_generation")` context managers tag each LLM call; the totals travel back in `QueryResponse.tokens_breakdown`, which the chat SPA renders per turn.

### 11.4 "0 rows" handling

When HANA executes the SQL successfully but returns 0 rows, the answer says:
> "Query executed successfully but returned 0 rows. The SQL is structurally correct; the filter values may not match existing data."

This is critical to distinguish **data gap** vs **pipeline bug**.

---

## 12. Testing and preview scripts

| Suite | Covers |
|---|---|
| `packages/ask-intent-resolution/tests/unit/test_smart_entity_selection.py` | EntitySelectorService (Stage 2) |
| `packages/ask-intent-resolution/tests/unit/test_smart_catalog_scope.py` | CatalogService scoping (Stage 1) |
| `tests/e2e/test_smoke.py` | One live query per mode against a deployed orchestrator |
| `tests/benchmark/test_full_benchmark.py` | Opt-in question-set benchmark (`ASK_RUN_BENCHMARK=1`) |

For ad-hoc inspection, call `POST /v1/query` with `{"mode": "smart"}` against a locally booted orchestrator and read the returned `trace` — it exposes the catalog selection, the resolved paths and the generated SQL.

---

## 13. Metrics and benchmark

### 13.1 Benchmark composition

9 inventory questions (listed in the preview scripts), plus a known-excluded 10th (sales-related, out of scope).

### 13.2 End-to-end results against HANA (2026-04-21)

| Stage | Tokens/query | Cost/query | Notes |
|---|---|---|---|
| CatalogService | 0 | $0 | No LLM, cached |
| EntitySelectorService | ~2,270 | $0.010 | Claude Sonnet 4.6, 1 call, 0 retries |
| PathResolver | 0 | $0 | Deterministic, NetworkX |
| SQLGeneratorServiceV2 (via FreeformSQLGenerator) | ~22,000 | $0.088 | Dominant cost (raw YAMLs in prompt) |
| execute_sql | 0 | $0 | HANA connection cost, no LLM |
| **TOTAL** | **~24,500** | **$0.100** | Avg across 9 questions |

### 13.3 Gold-first emergence

All 9 benchmark questions selected a Gold entity as `base_entity`:

| Question focus | base_entity selected |
|---|---|
| Q1, Q2, Q3, Q4, Q5, Q8 (inventory projection / stock coverage) | `gold_ecc_inventory_situation` |
| Q6, Q9 (incoming / next batch arrival) | `gold_ecc_order_tracking_reception` |
| Q7 (SO-to-stock fulfillment) | `gold_ecc_open_order_tracker` |

This validates the Gold-first pattern from spec Sec 13.1 rank 1 without requiring an explicit algorithmic rule — the LLM reads the Gold descriptions and matches them to the question intent.

### 13.4 Comparison vs v1

| Dimension | v1 (estimate) | v2 measured | Factor |
|---|---|---|---|
| Cost per query | ~$1.00 | $0.100 | **10× cheaper** |
| Entities passed to SQL gen | 5 raw YAMLs always | 2–4 (chosen by PathResolver) | Fewer |
| SQL executes against HANA | 9/10 (1 data-layer gap) | 9/9 (zero DB errors) | Equal+ |
| Cross-module reasoning | Implicit (LLM guesses) | Explicit (Edge Registry `cross_module` flag) | Qualitatively better |
| Retrieval retries / hallucinations | Occasional | 0/0 in benchmark | Better |

---

## 14. Intentional divergences from the spec

### 14.1 Freeform SQL instead of Graph Compiler (Sec 11)

The ASK spec prescribes a deterministic 9-phase compiler: IR Validation → Entity Resolution → Path Selection → Join Expansion → Grain Enforcement → Security Injection → Normalization → SQL Generation → Dialect Transpilation.

Pipeline v2 implements phases 1, 2, 3 (the graph planning side) and delegates phases 4–9 to the freeform generator. Why:

- The compiler cannot express CTEs, window functions, conditional aggregations, or multi-stream UNION-ALL patterns that the benchmark queries require.
- The freeform generator resolves 9/9 queries with correct HANA syntax, while the compiler would require continued extension.
- Cost: freeform is more expensive per call (~$0.088 vs projected ~$0.02 for compiler), but the benefit of never failing on SQL complexity outweighs it for the current scope.

This is a **permanent** architectural decision, not a temporary hack.

### 14.2 RBAC not yet enforced (Sec 17)

Spec prescribes row_filter and column_masking injection during SQL Generation Phase 6. Pipeline v2 does not yet inject security filters — all queries run with the configured DB user's permissions.

### 14.3 Metric Model removed (Sec 9)

The `metric` layer is gone across the platform: no metric YAMLs remain in the corpus, the `MetricNode` class was deleted, and ingesting a `layer: metric` YAML now raises. v2 never ingested or retrieved metrics. Metric concepts are expressed by the LLM inline in the IR (e.g., `measures: ["net_value"]`).

### 14.4 `entity_type` and `entity_sub_type` not used for ranking

Spec Sec 13.1 ranks 2 and 3 are `entity_type` and `entity_sub_type` match. Pipeline v2 doesn't use these for ranking because the selector is LLM-driven (no explicit rank algorithm).

---

## 15. Known gaps and roadmap

### 15.1 Data coverage

6 of 9 benchmark questions return 0 rows because their filter values (Material Y, Plant B, Sales Order #12345) are hypothetical identifiers. The SQL is structurally correct. To achieve rows > 0 for all 9, the benchmark needs to use real IDs that exist in the target HANA tables.

### 15.2 Raw-YAML prompt size

The dominant cost (~$0.088 of $0.100 per query) is in the freeform SQL generator prompt, which includes full raw YAMLs for all resolved entities. Next optimization: condensation (`llm_schema_view`) — a pre-computed compact YAML-ish representation stored alongside `raw_yaml`, expected to reduce input tokens by 60-70% and drop per-query cost to ~$0.03.

This optimization is specified in an internal design doc and is still available.

### 15.3 Module field formatting for Gold

Gold entities ingested with `module: ["MM", "PP", "SD"]` (list) get saved as a comma-joined string (`"MM,PP,SD"`) to match Silver's string shape. In the catalog this renders as a group `"MM,PP,SD"` instead of separate groups. Cosmetic; doesn't affect selection quality.

### 15.4 No hybrid retrieval fallback

If the selector picks a `base_entity` that exists in the catalog but has no edges in the Edge Registry, and the query requires traversals, the PathResolver returns `unresolved_targets`. The `generate_sql` node currently still runs (accepts partial paths) but the SQL may be incomplete. Future: explicit error state.

### 15.5 Inspection surface

The chat SPA does not yet expose:
- Switching the active data product per session.
- Viewing the raw catalog, field registry, or edge registry inline.
- Exporting SQL + results to files.

These are UX improvements, not architectural gaps.

---

## 16. How to extend

### 16.1 Add a new Silver entity

1. Create the YAML under `silver/<module>/<name>.yaml` in the semantic-layer repo, following the authoring standard (layer, grain, fields with field_role, relationships) — see [semantic-layer/](semantic-layer/README.md).
2. Import + publish it through the ASK Studio (§9.2).
3. Add the entity ID to `config/settings.json` → `pipeline_v2.data_products.<active>.entity_ids`.
4. Ask a question that should hit it and check the returned `trace` catalog.

### 16.2 Add a new Gold entity

Same as 16.1 but under `gold/`.

### 16.3 Add a new data product

In `config/settings.json`:
```json
"data_products": {
  "existing_product": { ... },
  "my_new_product": {
    "description": "...",
    "entity_ids": ["silver_...", "gold_..."]
  }
}
```

Switch `active_data_product` to `"my_new_product"` and restart the backend.

### 16.4 Change the LLM model

Edit `config/settings.json`:
```json
"model_name": "anthropic--claude-4.6-sonnet",  // or "anthropic--claude-4-haiku", etc.
"deployments": { "llm": "<deployment_id>" }
```

Both selector and SQL generator will use the configured LLM (built by `ask_llm_gateway`).

### 16.5 Add a new entity role

`CatalogEntry.entity_role` is a Pydantic `Literal["fact", "dimension", "reference"]`. To add a new role (e.g., `"hierarchy"`), update:
1. `src/pipeline_v2/domain/catalog.py` (expand the Literal).
2. Adjust rendering logic if needed.
3. The ingestion path must pass the new role through without normalization errors.

### 16.6 Add a new filter operator

`src/pipeline_v2/domain/ir.py` — `Operator` Literal. Add to the list, then:
1. Update the selector's system prompt (add to "Operators allowed" section).
2. Ensure the freeform SQL generator handles the new operator in prompts/examples.

---

## 17. Troubleshooting

### Pipeline errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `Selector returned empty base_entity` | Question doesn't match any catalog entity | Check the selector's `reasoning`; add a relevant entity to the data product or rephrase question |
| `invalid_entity_ids` non-empty after 2 retries | LLM hallucinated IDs not in catalog | Rare. Check catalog for similarly-named IDs. If persistent, reduce temperature or inspect prompt |
| `PathResolver: target X unreachable` | No edges connect base to target | Check `ask-edge-registry-v1` — run the diagnostic queries in `docs/` or Postman |
| `Missing raw_yaml in ask-entity-registry-v1 for entities: [...]` | Incomplete ingestion | Re-publish the YAML through the ASK Studio (§9.2) |
| DB error "column X not found" | SQL generator invented a column | Should be rare with path resolver hints; check the YAMLs for correct field names; regenerate by rerunning |
| 0 rows returned but SQL is correct | Filter values don't match existing data | Not a pipeline bug — verify the filter values exist in the HANA tables |

### Diagnostic queries (Postman / curl)

```bash
# Entity registry — by data product scope
POST http://localhost:9200/ask-entity-registry-v1/_search
{
  "_source": ["id", "layer", "module", "description"],
  "query": {"terms": {"layer": ["silver", "gold"]}}
}

# Edge registry — cross-module edges
POST http://localhost:9200/ask-edge-registry-v1/_search
{
  "size": 50,
  "_source": ["source_node", "target_node", "traversal_cost", "cross_module"],
  "query": {"term": {"cross_module": true}}
}

# Entity registry — single entity
GET http://localhost:9200/ask-entity-registry-v1/_doc/silver_ecc_mm_inv_mov_stock
```

### Re-initializing a clean state

```bash
# Re-publish the YAMLs through the admin API (the ASK Studio drives it):
#   POST /v1/admin/yaml/index/{entity_id}/{env}

# Exercise the full pipeline (the response carries catalog + paths + SQL in `trace`):
#   POST /v1/query  {"question": "your question here", "mode": "smart"}
```

---

## Appendix A — File manifest

```
src/pipeline_v2/
├── __init__.py                                 Architecture overview + spec refs
├── domain/
│   ├── __init__.py
│   ├── catalog.py                              CatalogEntry, Catalog
│   ├── ir.py                                   SemanticPlanIRv2, SelectorOutput, IRFilter, IRTimeContext, IRSort
│   └── path.py                                 EdgeInfo, TraversalPath, ResolvedPlan
├── application/
│   ├── __init__.py
│   ├── catalog_service.py                      CatalogService (filter + render + cache)
│   ├── entity_selector.py                      EntitySelectorService (LLM #1)
│   ├── path_resolver.py                        PathResolver (NetworkX Dijkstra)
│   └── sql_generator.py                        SQLGeneratorServiceV2 (adapter to freeform)
├── graph/
│   ├── __init__.py
│   ├── state.py                                AgentStateV2 TypedDict
│   └── v2_graph.py                             build_v2_graph() — node bodies + routers
└── infrastructure/
    └── __init__.py                              (empty — shared with src/pipeline/)

tests/
├── e2e/test_smoke.py                           One live query per mode
└── benchmark/test_full_benchmark.py            Opt-in question-set benchmark

ask-chat-spa/
└── src/layouts/AppLayout.tsx                   Chat UI header (engine selector)

config/
└── settings.json                               pipeline_v2.active_data_product + data_products

semantic-layer repo
├── silver/                                     Silver YAMLs
└── gold/                                       Gold YAMLs

docs/
└── SMART.md                                    This document
```

---

## Appendix B — Spec section-to-file map

| Spec Sec. | Topic | Implementation file |
|---|---|---|
| 6.1 | Bronze Validation | `src/pipeline/infrastructure/parsers/sap_json_parser.py` |
| 6.2 | Silver Validation | `src/pipeline/domain/entities.py` (SilverNode validators) |
| 6.3 | Gold Validation | `src/pipeline/domain/entities.py` (GoldNode validators) |
| 6.4 | Join Graph Definition | Silver YAML `join_graph` field |
| 6.5 | Entity Relationships | Silver YAML `relationships` field → Edge Registry |
| 7.1 | Entity Registry | `src/pipeline/infrastructure/repositories/opensearch_repository.py` (save_silver_node, save_gold_node) |
| 7.2 | Field Registry | Same file, field registry actions |
| 7.3 | Edge Registry | Same file, edge registry actions with `cross_module` |
| 8.1 | Traversal Path Definition | `src/pipeline_v2/domain/path.py::TraversalPath` |
| 8.2 | Path Selection Rules | `src/pipeline_v2/application/path_resolver.py::PathResolver.resolve` |
| 8.3 | Multi-Hop Cross-Module | Same — `cross_module` flag in edges enables planning |
| 10.1 | IR Schema | `src/pipeline_v2/domain/ir.py::SemanticPlanIRv2` |
| 10.2 | IR Validation Rules | `src/pipeline_v2/application/entity_selector.py::_parse_and_validate` |
| 11 | Graph Compiler | **Not implemented** — replaced by freeform SQL |
| 12 | Execution Pipeline | `src/pipeline_v2/graph/v2_graph.py::build_v2_graph` |
| 13.1 | Retrieval Ranking | Emergent from LLM selector (not explicit rank algorithm) |
| 14 | Gold Layer YAML Spec | `src/pipeline/domain/entities.py::GoldNode` + the semantic-layer repo's `gold/*.yml` |
| 16 | Validation Rules | Silver/Gold Pydantic validators |
| 21 | ID Grammar | `src/pipeline/domain/entities.py` — regex validators on `id` fields |
| 24 | End-to-End Walkthrough | Validated against the 9-question benchmark in `tests/benchmark/` |

---

*End of Pipeline V2 Technical Reference. For questions, check the relevant section above or the source files linked inline.*

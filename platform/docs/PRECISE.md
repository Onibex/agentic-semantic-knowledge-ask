# Pipeline v1 — Technical Reference

> Version: v1 (semi-deterministic, hybrid retrieval)
> Status: SHIPPED in production. Tier-1 improvements landed 2026-04-21 (edges hint + Dijkstra resurrection + post-SQL scope validation).
> Scope: Hybrid retrieval (RRF + Medallion re-ranking) + IR generation + BFS context expansion + Dijkstra path selection + freeform SQL generation with scope audit.

> ⚠️ **Historical file paths.** This reference predates the Strangler-Fig refactor. Every `src/pipeline/...` path below is **dead** — that code now lives in `packages/ask-intent-resolution/` (the **Precise** strategy + its cluster-1 algorithms). The *concepts* (RRF + Medallion re-ranking, IR generation, BFS expansion, Dijkstra path selection, freeform SQL + scope audit) are current; only the locations moved. See [CLAUDE.md](../CLAUDE.md) for the authoritative package map. Repointing every inline path is a pending cleanup.

This document unifies:
- The architectural specification (Onibex ASK Specification v1.0, © 2026).
- The concrete implementation — historically `src/pipeline/`, now `packages/ask-intent-resolution/` (see banner above).
- The operational artifacts (config, scripts, UI).

It is meant as the definitive **technical reference** for the pipeline v1 flow ("Precise" engine in the chat selector).

For the catalog-first / LLM-as-retriever variant, see [SMART.md](SMART.md).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Why a hybrid semi-deterministic pipeline](#2-why-a-hybrid-semi-deterministic-pipeline)
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

Pipeline v1 resolves a natural-language business question into executable SQL through **four phases**, two of which call an LLM:

```
User question
    │
    ▼
  [Phase 0] MacroIntentClassifierService     (LLM call #1 — classify intent)
    │   ↓ routes SQL_EXECUTION to the 4-phase pipeline below
    │   ↓ routes SCHEMA / DOCS / DASHBOARD to dedicated handlers
    ▼
  [Phase 1] IRGeneratorService               (LLM call #2 — produces SemanticPlanIR)
    │   ↓ if IR empty, falls back to SemanticDictionaryService (3-level disambiguation)
    ▼
  [Phase 2] EntityResolutionService          (no LLM, hybrid retrieval)
    │   ↓ OCSL Hybrid Retriever — RRF + Medallion re-ranking + governance gate
    │   ↓ produces top-K anchor YAMLs
    ▼
  [Phase 3] PathSelectorService              (no LLM, deterministic graph algorithms)
    │   ↓ BFS context expansion + edges hint extraction + Dijkstra path selection
    ▼
  [Phase 4] FreeformSQLGeneratorService      (LLM call #3 — freeform SQL with scope audit)
    │   ↓ optional 2-pass flow: Gold-only → Gold + Silver-on-demand
    │   ↓ post-SQL scope audit + retry feedback loop
    ▼
  [Phase 5] execute_sql_query                (no LLM, SAP HANA or PostgreSQL)
    │   ↓ returns rows
    ▼
Response to user
```

**Principles:**
- **Source of truth**: the Bronze / Silver / Gold YAMLs in the semantic-layer repo. OpenSearch indices are caches.
- **Hybrid retrieval is algorithmic**: kNN + BM25 fused via Reciprocal Rank Fusion, then re-ranked with deterministic Medallion tier/role/priority bonuses. The same question selects the same entities.
- **Gold-first by governance gate**: explicit policy, not emergent from LLM judgment.
- **Determinism in the planning layer**: BFS, Dijkstra, edge filtering and scope validation are pure functions — no randomness, no LLM, fully reproducible.
- **Semi-deterministic SQL stage**: the LLM writes SQL, but the prompt is constrained by the resolved YAMLs, the explicit edges hint, and a scope auditor that re-prompts on out-of-scope tables.

---

## 2. Why a hybrid semi-deterministic pipeline

Pipeline v1 was the first production design after the legacy "Chunk RAG" engine ("Flash"). The Flash engine retrieved arbitrary YAML chunks via free OpenSearch search and let the LLM generate SQL ad-hoc — that approach has no scope guarantees and no path planning.

The v1 design imposed determinism where the cost is highest:

| Problem in legacy Flash | v1 mitigation | Component |
|---|---|---|
| Entity selection drifted across runs | RRF + Medallion re-ranking is a pure function of inputs | [`ocsl_retriever.py`](../src/pipeline/application/ocsl_retriever.py) |
| Cross-entity JOINs were guessed by the LLM | `get_edges_between(...)` injects authoritative JOIN conditions | [`path_selector.py:293`](../src/pipeline/application/path_selector.py) |
| SQL referenced tables outside the data product | Post-SQL `audit_sql_scope` + feedback retry loop | [`sql_scope_validator.py`](../src/pipeline/application/sql_scope_validator.py) |
| Multi-hop traversals were lossy | Dijkstra over the entity graph (spec §8.2) | [`path_selector.py:344`](../src/pipeline/application/path_selector.py) |
| Ambiguous business terms produced bad IR silently | 3-level disambiguation via global semantic dictionary | [`fase1_ir_graph.py`](../src/pipeline/graph/fase1_ir_graph.py) + [`semantic_dictionary_service.py`](../src/pipeline/application/semantic_dictionary_service.py) |

After v1 shipped, pipeline v2 was developed in parallel as a catalog-first / LLM-as-retriever alternative ([SMART.md](SMART.md)). v1 remains in production as the **"Precise" engine** in the chat UI's engine selector and is the recommended motor when reproducibility / auditability matter more than throughput.

---

## 3. Architectural alignment with the ASK spec

| ASK Spec | Pipeline v1 component | File | Status |
|---|---|---|---|
| **Layer 1 — Intent Resolution** (Sec 12–13, hybrid retrieval) | OCSL Hybrid Retriever + EntityResolutionService | `application/ocsl_retriever.py`, `application/entity_resolution.py` | Implemented (algorithmic) |
| **Layer 2 — Semantic Plan IR** (Sec 10) | SemanticPlanIR + IRGeneratorService | `domain/ir_models.py`, `application/ir_generator.py` | Implemented |
| **Layer 3a — Path Selection** (Sec 8.2, 8.3) | PathSelectorService (BFS + Dijkstra + cross-module edges) | `application/path_selector.py` | Implemented |
| **Layer 3b — Graph Compiler** (Sec 11) | — | — | **Not aligned** — replaced by FreeformSQLGenerator |
| **Layer 3c — SQL Generation** (Sec 11 Phase 8) | FreeformSQLGeneratorService | `application/freeform_sql_generator.py` | Implemented (freeform with scope validator) |
| **Dialect Transpilation** (Sec 11 Phase 9) | — | — | LLM emits HANA / PostgreSQL dialect directly per `db_type` config |
| **3-level disambiguation** (Sec 13.2) | dictionary_check_node + SemanticDictionaryService | `graph/fase1_ir_graph.py`, `application/semantic_dictionary_service.py` | Implemented |

The spec's deterministic compiler (Sec 11) was deliberately skipped — it cannot express CTEs, window functions, conditional aggregations, or multi-stream UNION-ALL patterns required by real questions. Freeform SQL with strict prompt rules + post-SQL scope validation is the v1 answer.

---

## 4. End-to-end data flow

### 4.1 State container — `AgentState`

All nodes read/write a `TypedDict` defined in [`src/pipeline/graph/state.py`](../src/pipeline/graph/state.py). Every field is JSON-serializable so the LangGraph checkpointer can persist it across invocations.

```python
class AgentState(TypedDict, total=False):
    # ── Input ─────────────────────────────────────────────
    question: str
    original_question: str | None
    conversation_history: str | None
    user_role_id: str | None
    user_department: str | None

    # ── Phase 0 — Macro Intent ────────────────────────────
    macro_intent: MacroIntent          # SQL_EXECUTION | SCHEMA_QUERY | DOCS_QUERY | DASHBOARD_GEN

    # ── Phase 1 — IR Generation ───────────────────────────
    plan_ir_dict: dict | None          # SemanticPlanIR.model_dump()
    disambiguation_message: str | None # Level 2/3 message if ambiguous

    # ── Phase 2 — Entity Resolution ───────────────────────
    anchor_yamls: list[dict]           # top-K entities with raw_yaml + final_score

    # ── Phase 3 — Context + Paths ─────────────────────────
    expanded_yamls: list[dict]         # anchors + neighbors (BFS, with hop_distance)
    scope_edges: list[dict]            # forward edges, JSON-serializable
    resolved_paths: dict               # {base_entity, paths[], unreachable[]}

    # ── Phase 4 — SQL Generation ──────────────────────────
    sql_query: str | None
    scope_audit: dict | None           # {ok, referenced[], out_of_scope[], allowed[]}
    scope_warning: str | None          # human-friendly warning if scope violation persisted
    expansion_rounds: int | None       # 2-pass flow trace
    expansion_trace: list[dict] | None
    expansion_exhausted: bool | None
    field_enrichments: dict            # {entity_id: {field: enrichment}}

    # ── Phase 5 — DB Execution ────────────────────────────
    sql_results: list[dict] | None
    response: str                      # NL final response
    error: str | None
```

### 4.2 Sequence diagram

```
┌─────────┐   question    ┌──────────────────┐
│  User   ├──────────────>│ LangGraph invoke │
└─────────┘                └────────┬─────────┘
                                    │
                           START ───┘
                                    │
                           ┌────────▼─────────┐
                           │ classify_intent  │
                           │                  │
                           │ MacroIntentClassifierService.classify(question)
                           │   → LLM call #1 (intent classification)
                           │   → MacroIntent enum
                           └────────┬─────────┘
                                    │
                                 router
                            ┌───────┼───────┬───────┐
                            │       │       │       │
                       (SCHEMA) (DOCS) (DASH)  (SQL_EXECUTION)
                            │       │       │       │
                           …       …       …        ▼
                                                    │
                           ┌────────────────────────▼──────────┐
                           │  fase1_subgraph (compiled inline) │
                           │                                   │
                           │  ▶ generate_ir_node               │
                           │     IRGeneratorService.generate_plan
                           │       → LLM call #2 (IR extraction)
                           │       → SemanticPlanIR
                           │                                   │
                           │  ▶ dictionary_check_node          │
                           │     If IR has metrics or dimensions
                           │       → PASS-THROUGH               │
                           │     Else fallback to SemanticDictionaryService
                           │       → Level 1 auto-resolve OR    │
                           │       → Level 2 multi-module list  │
                           │       → Level 3 "contact trainer"  │
                           │                                   │
                           │  ▶ insufficient_context_node       │
                           │     (only if disambiguation msg)   │
                           └─────────────┬─────────────────────┘
                                         │
                                  fase1_router
                                ┌────────┴────────┐
                                │                 │
                        (plan_ir_dict)      (error / disambig)
                                │                 │
                                ▼                 ▼
                                                 END
                           ┌──────────────────────┐
                           │ execute_sql_pipeline │
                           │                      │
                           │  ▶ Phase 2 — Entity Resolution
                           │     entity_resolver.select_relevant_yamls(plan_ir, top_k)
                           │       → OCSLHybridRetriever
                           │       → anchor_yamls
                           │                      │
                           │  ▶ Phase 3 — Context + Paths
                           │     path_selector.expand_context(anchors, max_hops)
                           │       → expanded_yamls
                           │     path_selector.get_edges_between(ids)
                           │       → scope_edges (authoritative JOINs)
                           │     path_selector.select_resolved_paths(anchors, ids)
                           │       → Dijkstra resolved_paths
                           │                      │
                           │  ▶ Phase 2.5 — Field enrichments (optional)
                           │     semantic_dictionary.get_field_enrichments_bulk(ids)
                           │                      │
                           │  ▶ Phase 4 — Freeform SQL
                           │     If use_two_pass_flow:
                           │       call 1: Gold-only YAMLs
                           │         if need_more_context:
                           │           fetch_entities_by_ids(requested)
                           │           call 2: Gold + Silvers
                           │     Else: single-pass with full expanded set
                           │       → LLM call #3 (freeform SQL)
                           │     Post-SQL scope_validator.audit_sql_scope
                           │       if out_of_scope: 1× retry with feedback
                           │                      │
                           │  ▶ Phase 5 — DB Execution (if db_config)
                           │     execute_sql_query(sql, db_type, db_config)
                           │       → rows + columns
                           └──────────┬───────────┘
                                      │
                                     END
```

---

## 5. Components — services in detail

### 5.1 `MacroIntentClassifierService`

**File:** [`src/pipeline/application/macro_intent_classifier.py`](../src/pipeline/application/macro_intent_classifier.py)

**Responsibility:** Classify the question into one of four macro-intents to decide routing.

**Input/Output:**
- Input: `question: str` (any language).
- Output: `MacroIntent` enum — `SQL_EXECUTION | SCHEMA_QUERY | DOCS_QUERY | DASHBOARD_GEN`.
- Trace metadata: `MacroIntentOutput` with `confidence` (`high|medium|low`) and `reasoning`.

**LLM call:** `ChatPromptTemplate → LLM → PydanticOutputParser`. Tagged `track_phase("macro_intent")`. No retries — on parse failure, `classify_intent` falls back to `SQL_EXECUTION` and surfaces the error in state (see [`ask_graph.py:147`](../src/pipeline/graph/ask_graph.py#L147)).

**Determinism:** depends on LLM (semi-deterministic).

### 5.2 `IRGeneratorService`

**File:** [`src/pipeline/application/ir_generator.py`](../src/pipeline/application/ir_generator.py)

**Responsibility:** Phase 1 — translate the question into a `SemanticPlanIR` using business-term vocabulary only (no SQL, no physical table/column names).

**Input/Output:**
- Input: `question: str`, optional `conversation_history`.
- Output: `SemanticPlanIR` (see §6.1) or raises if `is_impossible=True`.

**LLM call:** single call, tagged `track_phase("ir_generation")`. Prompt is a strict system message defining the IR schema, the allowed operators, the `module_hint` enum (`SD|MM|PP|FI|CO|WM`), and rules on how to populate `time_context`.

**Determinism:** semi-deterministic.

### 5.3 `OCSLHybridRetriever` (Phase 2 retrieval engine)

**File:** [`src/pipeline/application/ocsl_retriever.py`](../src/pipeline/application/ocsl_retriever.py)

**Responsibility:** The deterministic retrieval engine behind `EntityResolutionService`. Three stages:

#### Stage A — RRF expansion

- `search_hybrid_rrf(query, query_vec, size=50)` against `ask-entity-registry-v1`: BM25 + kNN fused via Reciprocal Rank Fusion.
- `search_gold_rescue(query, size=5)`: brute-force search restricted to `layer:gold` to mitigate Gold starvation when BM25 buries them.
- Merge + deduplicate by `_id`.

#### Stage B — Medallion re-ranking (the deterministic core)

```
final_score = normalized_BM25_kNN
            + TIER_BONUS[layer]          # gold=0.40, silver=0.15, bronze=0.0
            + PRIORITY_BONUS[priority]   # critical=0.20, high=0.10, normal=0.0
            + ROLE_BONUS[role]           # fact=0.20, reference=0.05, dimension=0.0
                                         # role bonus skipped if has_metrics=False
```

`_normalize_scores` (line 189) min-max normalizes the hybrid score to `[0, 1]` before adding bonuses, keeping the bonus weights interpretable.

#### Stage C — Governance gate (Gold-first policy)

| Mode | Condition | Result |
|---|---|---|
| `gold_authoritative` | top Gold score ≥ 0.75 | only Golds + tail |
| `gold_with_silver_support` | a Gold exists but score < 0.75 | Golds + up to 4 Silvers |
| `fallback_no_gold` | no Gold matched | top 5 Silvers |

**Determinism:** 100%. No randomness, no LLM. Same `(query, query_vec, OS state)` → same output.

**Output shape:**
```python
{
  "mode": "gold_authoritative" | "gold_with_silver_support" | "fallback_no_gold",
  "documents": [
    {"id": ..., "layer": ..., "llm_prompt_context": ..., "raw_source": {...}},
    ...
  ]
}
```

### 5.4 `EntityResolutionService` (Phase 2 facade)

**File:** [`src/pipeline/application/entity_resolution.py`](../src/pipeline/application/entity_resolution.py)

**Responsibility:** Public Phase 2 facade that the graph node calls.

**Methods:**
- `select_relevant_yamls(plan_ir, top_k=5, layers=("silver","gold"))` — phrase expansion via dictionary, build enriched retrieval query (`entity_hint + intent_summary + IR top-5 terms`), invoke `OCSLHybridRetriever`, return up to `top_k` entities with `raw_yaml`.
- `select_gold_anchors(plan_ir, top_k=5)` — wrapper that filters to Golds only (used by 2-pass flow as starter).
- `fetch_entities_by_ids(entity_ids, layers=...)` — direct lookup by ID, no ranking. Used by 2-pass flow when the SQL generator requests additional Silvers.

**Phrase expansion** (`_expand_phrases`, line 35) — best-effort: each dimension is searched in the semantic dictionary; if any term has `type=="phrase"`, expand. Optional, falls through if dictionary unavailable.

**LLM calls:** none (pure retrieval + dictionary lookup).

### 5.5 `PathSelectorService` (Phase 3)

**File:** [`src/pipeline/application/path_selector.py`](../src/pipeline/application/path_selector.py)

**Responsibility:** Three deterministic graph operations on the cached Edge Registry.

#### A. `expand_context(anchor_yamls, max_hops=2, max_total=10, layers=...)`

Multi-source BFS from anchors, radius ≤ `max_hops`. Filters by layer (Silver/Gold; Bronze opt-in). Caps at `max_total` to guard against token blow-up. Output: anchors (`hop_distance=0`) + neighbors sorted by `(hop, id)`.

#### B. `get_edges_between(entity_ids)` — the **edges hint** (Tier-1 improvement, 2026-04-21)

Iterates the cached Edge Registry, returns forward edges (`is_reverse=False`) where both endpoints are in `entity_ids`. Deduplicates same-pair edges keeping the lowest `traversal_cost`. Output: `list[RelationEdge]` ordered by `(source, target)`.

This list is rendered as **declarative JOIN hints** in the SQL prompt:

```
# Edge: silver_ecc_mm_inv_mov_stock LEFT JOIN silver_ecc_sd_plant
  ON SILVER_ECC_MM_INV_MOV_STOCK.werks_marc = SILVER_PLANTS.werks_t001w
  (cost=1.5, cross_module=True)
```

#### C. `select_resolved_paths(anchors, expanded_ids=None)` — Dijkstra (Tier-1 improvement, 2026-04-21)

1. Pick `base_entity`: prefer `entity_role==fact`, tie-break by score.
2. Build NetworkX `DiGraph`: nodes = entity_ids, edge weight = `traversal_cost`.
3. For each non-base entity → `nx.shortest_path` from base.
4. Compute `grain_impact`: `fan_out_risk = True` if any edge in the path has `cardinality in {one_to_many, many_to_many}`.
5. Return `{base_entity, paths: [{target, entity_chain, edges, total_cost, hops, grain_impact}], unreachable}`.

**Caching:** the entity graph is loaded lazily once per process and reused. `refresh()` invalidates after re-ingestion.

**Determinism:** 100%.

### 5.6 `FreeformSQLGeneratorService` (Phase 4)

**File:** [`src/pipeline/application/freeform_sql_generator.py`](../src/pipeline/application/freeform_sql_generator.py)

**Responsibility:** Generate SQL from raw YAMLs + IR hints + edges hint + field enrichments + glossary, with post-SQL scope validation.

**Prompt structure:**
1. **HANA / PostgreSQL syntax rules** — casing, window functions, `LIST_AGG`, date arithmetic, CTE double-quoting, etc. (lines 56–118).
2. **YAML reading rules** — `db_table_name` is the only physical table; fields are columns; joins are external (line 121).
3. **IR hints** — orientative, non-binding, formatted via `_format_ir_hints`.
4. **Edges hint block** — authoritative JOIN reference rendered from `scope_edges` and `resolved_paths`.
5. **Schema block** — raw YAMLs separated by `---`.
6. **Conversation history** — passed through if available.
7. **Context expansion protocol** — present only when `use_two_pass_flow=True`; explains how the LLM can reply with `need_more_context`.

**Output JSON contract:**
```python
{
  "table_name": str,
  "sql": str,
  "explanation": str,
  "grain": "transactional" | "aggregated",
  "is_dashboard_ready": bool,
  "rules_applied": list[str],
  "error": str | None
}
```

In 2-pass mode the LLM may instead return:
```python
{"need_more_context": true, "requested_entities": [{"id": str, "reason": str}]}
```

**LLM call:** tagged `track_phase("freeform_sql_generation")`. Up to 1 retry with scope feedback if the post-SQL audit fails.

#### 2-pass flow (optional, configured via `use_two_pass_flow`)

```
Pass 1: LLM sees only Gold YAMLs + edges hint + IR.
   ├─ If response = SQL → run scope audit.
   └─ If response = need_more_context:
        fetch_entities_by_ids(requested) → Silver YAMLs.
        record expansion_rounds += 1, expansion_trace[].
        If expansion_rounds < max_expansion_rounds:
           Pass 2: LLM sees Gold + Silvers.
        Else: expansion_exhausted = True, fall back.
```

The 2-pass flow keeps Pass 1 input small (cheaper, lower latency) when the question is fully answerable from Gold; falls back to full context when Gold is insufficient.

### 5.7 `SQLScopeValidator` (Tier-1 improvement, 2026-04-21)

**File:** [`src/pipeline/application/sql_scope_validator.py`](../src/pipeline/application/sql_scope_validator.py)

**Responsibility:** Post-SQL audit — every table referenced by `FROM | JOIN | INTO | UPDATE` must come from the resolved YAML set.

**Methods:**
- `build_allowed_tables(yamls)` — extracts `db_table_name` (fallback `name`) from each YAML, uppercased.
- `extract_referenced_tables(sql)` — regex pass that ignores CTE-defined names (`WITH x AS …`) and SQL noise.
- `audit_sql_scope(sql, allowed_tables)` — `{ok, referenced[], out_of_scope[], allowed[]}`.
- `format_scope_feedback(audit, previous_sql)` — human-readable feedback for the retry prompt.

**Non-destructive:** the validator only reports. The caller (`execute_sql_pipeline` in `ask_graph.py`) decides whether to retry once, warn the user, or accept the SQL.

**Conservative scope:** only **table-level** validation. Column-level validation is intentionally skipped (column aliases would generate false positives — see §14).

### 5.8 `SemanticDictionaryService`

**File:** [`src/pipeline/application/semantic_dictionary_service.py`](../src/pipeline/application/semantic_dictionary_service.py)

**Responsibility:** Two roles:
1. **Phase 1 fallback** — `dictionary_check_node` invokes hybrid search when the IR is empty. Used by the 3-level disambiguation logic.
2. **Phase 2.5 enrichment** — `get_field_enrichments_bulk(entity_ids)` returns per-field enrichments (synonyms, value codes, business glossary) injected into the SQL prompt.

**Indices:**
- `ask-semantic-dictionary-v1` — global dictionary (BM25 + kNN, embedding dim 3072).
- `{silver_index}_ext` — legacy per-entity extensions (deprecated, kept for backward compatibility).

### 5.9 `SchemaCatalogService`

**File:** [`src/pipeline/application/schema_catalog_service.py`](../src/pipeline/application/schema_catalog_service.py)

**Responsibility:** Handles `SCHEMA_QUERY` macro-intent — entity metadata lookup.

Two LLM calls: one to parse the query (entity name + layer hint), one to render the YAML as an NL response with strict prompt rules.

### 5.10 `DashboardPlannerService`

**File:** [`src/pipeline/application/dashboard_planner_service.py`](../src/pipeline/application/dashboard_planner_service.py)

**Responsibility:** Handles `DASHBOARD_GEN` — decomposes the request into 1–4 analytical sub-intents, each with a suggested chart type. Each sub-intent is then routed back through the SQL pipeline by the UI (each panel runs the full 4-phase pipeline independently — by design).

### 5.11 `MetadataIngestionService`

**File:** [`src/pipeline/application/ingestion_service.py`](../src/pipeline/application/ingestion_service.py)

**Responsibility:** YAML → OpenSearch (entity / field / edge registries) + optional file storage. Shared between v1 and v2 (v2 reuses the same indices).

The two ingestion bugs surfaced during pipeline v2 development are documented in [SMART.md §9.3](SMART.md) and were fixed in this same file.

---

## 6. Domain models

### 6.1 `SemanticPlanIR` and supporting types (`ir_models.py`)

```python
class SemanticPlanIR(BaseModel):
    intent_summary: str                          # 1–2 lines
    semantic_metrics: list[str] = []             # ["net value", "count of orders"]
    semantic_dimensions: list[str] = []          # ["customer", "plant", "month"]
    filters: list[IRFilter] = []
    module_hint: str | None                      # "SD" | "MM" | "PP" | "FI" | "CO" | "WM"
    time_context: TimeContext | None
    sorting: list[SortSpec] | None
    limit: int | None
    is_impossible: bool = False                  # True → greeting/nonsense
    detected_entity_hint: str | None             # "sales order" | "purchase order" | ...

class IRFilter(BaseModel):
    semantic_field: str                          # "customer", "status"
    operator: str                                # "=" "!=" ">" "<" ">=" "<="
                                                 # "BETWEEN" "IN" "NOT IN"
                                                 # "LIKE" "NOT LIKE"
                                                 # "IS NULL" "IS NOT NULL"
    value: Any                                   # scalar, list, or null

class TimeContext(BaseModel):
    field: str
    start: str | None                            # ISO 8601
    end: str | None
    granularity: str | None                      # "day" | "week" | "month" | "quarter" | "year"

class SortSpec(BaseModel):
    field: str
    direction: Literal["ASC", "DESC"]
```

### 6.2 Entity models (`entities.py`)

```python
class BronzeNode(BaseModel):
    id: str                                      # "bronze_{system}_{table}_{alias}" (lowercase)
    layer: Literal["bronze"]
    version: str
    source_system: str
    source_system_id: int
    name: str                                    # SAP TABNAME
    alias: str
    description: str
    primary_key: list[str]
    fields: dict[str, BronzeField]

class SilverNode(BaseModel):
    id: str                                      # "silver_{system}_{module}_{entity}"
    internal_id: str
    db_table_name: str | None
    layer: Literal["silver"]
    version: str
    source_system: str
    source_system_no: int
    business_process: str
    module: str | list[str]
    name: str
    classification: str
    description: str
    entity_role: Literal["fact", "dimension", "reference"]
    grain: Grain                                  # {entity_grain: list[str], business_grain: str}
    composed_of: list[str]                        # bronze tables (lineage)
    join_graph: list[JoinCondition] | None        # ETL joins, not runtime
    fields: list[SilverField]
    relationships: list[Relationship]             # cross-entity navigation

class GoldNode(SilverNode):
    # id pattern: "gold_{system}_{entity}"
    # validator: if composed_of has > 1 source → join_graph required.

class SilverField(BaseModel):
    name: str                                    # physical column
    source: str                                  # lineage "EKKO.EBELN"
    field_role: Literal["measure", "dimension", "identifier", "timestamp", "attribute", "status_flag"]
    type: str
    description: str
    aggregation_behavior: str | None             # "additive" | "non-additive" | ...
```

### 6.3 Graph models (`graph_models.py`)

```python
@dataclass
class RelationEdge:
    source_node: str
    target_node: str
    join_type: JoinType                          # INNER | LEFT OUTER | RIGHT OUTER | CROSS
    conditions: list[JoinCondition]              # [{left_field, right_field, operator}]
    cardinality: Cardinality                     # one_to_one | one_to_many | many_to_many
    traversal_cost: float = 1.0
    is_reverse: bool = False                     # auto-generated inverse, filtered in get_edges_between
```

---

## 7. OpenSearch data model

Pipeline v1 was the original consumer of the `ask-*` indices. v2 reuses them.

| Index | Content | Used by v1 |
|---|---|---|
| `ask-entity-registry-v1` | 1 doc per entity. Fields: `id`, `layer`, `module`, `entity_role`, `name`, `description`, `raw_yaml` (stored), `embedding` (kNN, dim 3072), priority/role flags. | `OCSLHybridRetriever` (BM25 + kNN), `EntityResolutionService.fetch_entities_by_ids` |
| `ask-field-registry-v1` | 1 doc per field per entity. Fields: `node_id`, `name`, `field_role`, `type`, `description`, `embedding`. | Used by Phase 2.5 enrichments + legacy field-level lookups |
| `ask-edge-registry-v1` | 1 doc per edge (forward + auto-generated reverse). Fields: `source_node`, `target_node`, `join_type`, `conditions[]`, `cardinality`, `traversal_cost`, `is_reverse`, `cross_module`, `semantic_label`. | `PathSelectorService` (cached scan) |
| `ask-semantic-dictionary-v1` | Global business-term dictionary. Fields: `business_term`, `synonyms`, `context_clues`, `module`, `embedding`. | Phase 1 fallback (3-level disambiguation), Phase 2 phrase expansion, Phase 2.5 enrichments |
| `{silver_index}_ext` | Legacy per-entity extensions. **Deprecated** — kept for backward compatibility. | Optional Phase 2.5 fallback |

---

## 8. Configuration

### 8.1 `config/settings.json` — `hybrid_pipeline` section

```json
{
  "hybrid_pipeline": {
    "anchor_top_k": 3,
    "expand_max_hops": 1,
    "expand_max_total": 5,
    "use_two_pass_flow": true,
    "max_expansion_rounds": 1
  }
}
```

| Key | Purpose | Default |
|---|---|---|
| `anchor_top_k` | Max anchor YAMLs from Phase 2 | 3 |
| `expand_max_hops` | BFS radius around anchors | 1 |
| `expand_max_total` | Hard cap on total YAMLs in prompt (token guard) | 5 |
| `use_two_pass_flow` | Enable Gold-only first pass with on-demand Silver expansion | true |
| `max_expansion_rounds` | Max LLM rounds asking for more context | 1 |

### 8.2 Shared sections (with v2)

- `db_type`: `"hana" | "postgresql"`.
- `hana` / `postgresql`: connection details.
- `opensearch`: host/port/SSL.
- `sap_ai_core.config_path`: path to `aicore_config.json`.
- `model_name`: e.g., `"anthropic--claude-4.6-sonnet"`.
- `deployments.llm`, `deployments.embeddings`: SAP AI Core deployment IDs.

### 8.3 Tuning notes

- Lower `anchor_top_k` → less context, lower cost, more risk of missing the right entity. With Medallion gate active, 3 is usually enough.
- `expand_max_hops=1` is the sweet spot for most data products. `=2` only when cross-module reasoning is required and 1-hop isn't enough.
- `use_two_pass_flow=true` adds latency on questions that genuinely need Silvers but saves cost on Gold-only questions.

---

## 9. YAML ingestion

Ingestion is the **same path used by v2** — see [SMART.md §9](SMART.md). The authoritative entry point is `ask-admin-api`: `POST /v1/admin/yaml/import` writes the YAML to the semantic-layer repo and `POST /v1/admin/yaml/index/{id}/{env}` publishes it into the registries. The ASK Studio drives both.

The ingestion service itself lives in `ask-knowledge-graph` (`application/ingestion_service.py`); v1 and v2 share it.

---

## 10. LangGraph topology

### 10.1 Compile entry point

```python
from langgraph.checkpoint.memory import MemorySaver
from src.pipeline.graph.ask_graph import build_ask_graph

graph = build_ask_graph(
    llm=llm,
    ir_generator=ir_generator,
    entity_resolver=entity_resolver,
    path_selector=path_selector,
    freeform_sql_generator=freeform_sql_generator,
    schema_service=schema_service,
    dashboard_planner=dashboard_planner,
    semantic_dictionary=semantic_dictionary,
    embedder=embedder,
    db_type="hana",
    db_config=DB_CONFIG,
    checkpointer=MemorySaver(),
    anchor_top_k=3,
    expand_max_hops=1,
    expand_max_total=5,
    use_two_pass_flow=True,
    max_expansion_rounds=1,
)

result = graph.invoke(
    {"question": "How many open POs by plant this month?"},
    config={"configurable": {"thread_id": "session-123"}},
)
```

### 10.2 Main graph topology

```
                START
                  │
           [classify_intent]                       ← Node 0: MacroIntentClassifier
                  │
              router (cond.)
   ┌──────────────┼──────────────┬─────────────────┐
   │              │              │                 │
[handle_schema] [handle_docs] [handle_dashboard] [fase1_subgraph]
   │              │              │                 │
  END            END            END                │
                                          fase1_router (cond.)
                                          ┌────────┴────────┐
                                          │                 │
                                  [execute_sql_pipeline]   END
                                          │
                                         END
```

### 10.3 Sub-graph `fase1_subgraph` (`fase1_ir_graph.py`)

The Phase-1 sub-graph implements **3-level disambiguation** without interrupts.

```
              START
                │
        [generate_ir_node]                       ← LLM extracts IR
                │
            ir_router
        ┌───────┴───────┐
        │               │
    (error)        [dictionary_check_node]      ← fallback if IR empty
        │               │
        ▼          dictionary_router
       END         ┌────┴────┐
                   │         │
              (Level 1)  (Level 2/3)
                   │         │
                   ▼         ▼
                  END   [insufficient_context_node] → END
```

**3-level disambiguation logic** (`dictionary_check_node`):

| Level | Condition | Action |
|---|---|---|
| **L1 — auto-resolve** | dictionary returns a single dominant module | populate IR with the resolved term, continue |
| **L2 — multi-module** | dictionary returns hits across ≥ 2 modules | set `disambiguation_message` listing the options, exit to UI |
| **L3 — no matches** | dictionary returns nothing | set `disambiguation_message` = "contact the Agentic Trainer", exit to UI |

The original chat-based clarification HiTL was removed — see memory `project_hitl_removal.md`.

### 10.4 Routers

| Router | From | Decision logic | Destinations |
|---|---|---|---|
| `router` (main) | `classify_intent` | by `MacroIntent` enum | one of `fase1_subgraph`, `handle_schema`, `handle_docs`, `handle_dashboard` |
| `fase1_router` | `fase1_subgraph` | `disambiguation_message` set OR (`error` and no `plan_ir_dict`)? | `END` if disambiguation/error, else `execute_sql_pipeline` |
| (no explicit router after `execute_sql_pipeline`) | — | terminal node | `END` |

---

## 11. UI integration

### 11.1 Engine selection — chat SPA → orchestrator

The chat SPA sends the chosen engine as the `mode` field of `POST /v1/query`:

| Selector label | Engine | `mode` |
|---|---|---|
| `Flash` | Chunk RAG | `"flash"` |
| `Precise` | **Pipeline v1 (this document)** | `"precise"` |
| `Smart` | Pipeline v2 | `"smart"` |

The orchestrator resolves the mode to a strategy behind the single `IntentResolver` Protocol, so the three engines are swappable without any UI change.

### 11.2 Response shape

Every engine answers with the same `QueryResponse` (`sql`, `rows`, `answer`, `error`, `trace`, `tokens_breakdown`), which is what lets the chat thread render all three identically.

### 11.3 Token tracker

Each request creates a `TokenTracker` (`ask_llm_gateway`). Each LLM call is wrapped in `track_phase("...")` with one of:
- `macro_intent`
- `ir_generation`
- `freeform_sql_generation`
- (plus `schema_resolution` for the non-SQL handlers)

The per-request totals travel back in `QueryResponse.tokens_breakdown`; the chat SPA renders them per turn.

---

## 12. Testing and preview scripts

| File | Covers |
|---|---|
| `packages/ask-orchestrator/tests/unit/test_macro_classifier.py` | `MacroIntentClassifier` |
| `packages/ask-intent-resolution/tests/unit/test_resolve_intent_use_case.py` | The `IntentResolver` use case + strategy dispatch |
| `packages/ask-intent-resolution/tests/unit/test_precise_expand_scope.py` | Precise context expansion / scope |
| `tests/e2e/test_smoke.py` | One query per mode against a live orchestrator |

There is **no canonical end-to-end preview script for v1**. Debugging runs through:
- The chat SPA (`Precise` engine).
- `POST /v1/query` with `{"mode": "precise"}` against a locally booted orchestrator, reading the returned `trace`.

---

## 13. Metrics and benchmark

> **Note:** unlike v2, pipeline v1 does not have a versioned end-to-end benchmark in the repo. The numbers below are observational, drawn from prior comparative analysis logged in conversation memory. Treat them as reference, not as a contract.

| Stage | Tokens / query (approx.) | Cost / query (approx.) | Notes |
|---|---|---|---|
| MacroIntentClassifier | ~1,400 | ~$0.005 | Single call |
| IRGeneratorService | ~5,000 | ~$0.02 | Single call |
| OCSL retrieval + Path selection | 0 | $0 | No LLM (algorithmic) |
| FreeformSQLGenerator | ~16,000 | ~$0.06 | Dominant cost |
| **TOTAL** | **~22,000** | **~$0.09** | Average across the 9-question reference set |
| Latency | ~60s | — | 3 LLM calls + retrieval + SQL exec |

Benchmark coverage on the same 9-question reference set used for v2: **7 of 9 questions executed against HANA without DB errors** in prior runs. Two failures were connection-related, not pipeline bugs.

### Why v1 is the more deterministic engine

- **Phase 2** (entity selection) is purely algorithmic — RRF + Medallion bonuses are pure functions of the input. Same question → same anchors.
- **Phase 3** (BFS, edges hint, Dijkstra) is deterministic graph traversal.
- **Phase 4** (LLM-driven SQL generation) is the only non-deterministic step, and it is constrained by an explicit edges hint, scope validation, and a retry loop.

This is the key trade-off versus v2:
- **v1** is more reproducible (better fit for audit / regression suites).
- **v2** is faster and has higher observed pass rate on the benchmark (9/9 vs 7/9), but uses an LLM as the entity retriever, which introduces sampling-based variability.

See memory `project_engine_retrieval_tradeoff.md` for the full discussion.

---

## 14. Intentional divergences from the spec

### 14.1 Freeform SQL instead of Graph Compiler (Sec 11)

Same rationale as v2 — the deterministic compiler can't express CTEs, window functions, conditional aggregations, or multi-stream UNION-ALL patterns required by real questions. v1 implements spec phases 1–3 (Intent → IR → Path Selection) plus its own scope validator, and delegates phases 4–9 to the freeform generator.

### 14.2 No column-level scope validation

`SQLScopeValidator` only audits **table-level** scope. Column-level validation was tried and rejected: the LLM aliases columns freely (`SUM(x) AS total_revenue`), and a regex-based column scope check produced too many false positives. Column safety is achieved by passing the YAMLs (which list allowed columns explicitly) to the SQL prompt.

### 14.3 Reverse edges filtered in `get_edges_between`

The Edge Registry stores both forward and auto-generated reverse edges. `path_selector.get_edges_between` filters `is_reverse=True` because the forward edge already carries condition + direction. Including the reverse would duplicate JOIN hints and confuse the LLM.

### 14.4 Phrase expansion is best-effort

`EntityResolutionService._expand_phrases` looks up each dimension in the semantic dictionary and expands when `type=="phrase"`. It uses individual lookups (no LLM); if the dictionary doesn't have the term, it falls through silently. This is **not** the LLM-based fuzzy matching of `SemanticFieldMapperService` (legacy, not used in the v1 core path).

### 14.5 `use_two_pass_flow` is configurable, not the default

The 2-pass flow (Gold-only first, Silvers on demand) is implemented and exposed as a config flag. Default in the active config is `true`, but the single-pass code path is still present in `ask_graph.py` for fallback and A/B comparison.

### 14.6 RBAC fields plumbed but not enforced (spec Sec 17)

`AgentState` carries `user_role_id` and `user_department`, and the SSO hook populates them. However, no row filter or column mask is currently injected into the SQL. RBAC enforcement is on the v2 roadmap and would be implemented identically for v1 once landed.

### 14.7 The metric registry is removed

The `metric` layer no longer exists: `MetricNode`, its write path and its renderer were deleted, ingesting a `layer: metric` YAML raises, and retrieval only ever returns Silver + Gold (Bronze opt-in). Metrics are expressed inline in the IR (`semantic_metrics: ["..."]`) and resolved by the SQL generator from the entity YAMLs — a measure is a `field_role: measure` field with an `aggregation_behavior` on its owning Silver/Gold.

---

## 15. Known gaps and roadmap

### 15.1 No canonical end-to-end benchmark

Unlike v2, v1 doesn't have a versioned `preview_graph_v1.py` running on a fixed question set with results checked in. This makes regression testing manual. **Action:** mirror v2's `tests/preview_graph_v2.py` for v1.

### 15.2 Raw-YAML prompt size is the dominant cost

Phase 4 input includes full raw YAMLs for all entities resolved by Phase 3. The condensation idea (`llm_schema_view` — a pre-computed compact representation) was scoped in `project_roadmap_post_v1.md` but superseded by v2's catalog approach. Re-applying it to v1 would drop per-query cost from ~$0.09 to an estimated ~$0.03.

### 15.3 No path-level grain enforcement

`select_resolved_paths` reports `grain_impact.fan_out_risk` when a one-to-many or many-to-many edge appears in the chain, but the SQL prompt doesn't yet *require* the LLM to handle it (e.g., via window functions or `DISTINCT`). The LLM usually does the right thing, but the contract isn't enforced.

### 15.4 Field enrichments lookup is best-effort

If `semantic_dictionary.get_field_enrichments_bulk(...)` raises, the pipeline logs a warning and continues without enrichments. This is intentional (non-fatal), but a slow OpenSearch can quietly degrade prompt quality.

### 15.5 Dashboard sub-pipeline cost

Each of the up-to-4 dashboard widgets runs the **full 4-phase pipeline independently**. By PO requirement, no optimization is planned. A future option is sharing Phase 1+2 across widgets when the IRs are similar.

### 15.6 No retry loop on IR generation

If `IRGeneratorService` returns an unparseable response, `generate_ir_node` raises and the sub-graph exits with `error`. There is no retry with feedback (unlike v2's selector retry with `invalid_entity_ids`).

---

## 16. How to extend

### 16.1 Add a new Silver or Gold entity

Same path as v2 — see [SMART.md §16.1–16.2](SMART.md). Add the YAML, publish it through the ASK Studio, and v1 will pick it up on next retrieval (the OpenSearch index is the cache).

### 16.2 Tune retrieval ranking

Edit the constants at the top of [`ocsl_retriever.py`](../src/pipeline/application/ocsl_retriever.py):

```python
TIER_BONUS = {"gold": 0.40, "silver": 0.15, "bronze": 0.0}
PRIORITY_BONUS = {"critical": 0.20, "high": 0.10, "normal": 0.0}
ROLE_BONUS = {"fact": 0.20, "reference": 0.05, "dimension": 0.0}
GOLD_AUTHORITATIVE_THRESHOLD = 0.75
```

After changes, re-run retrieval on a known set of questions and verify ordering didn't regress.

### 16.3 Add a filter operator

1. Update `IRFilter` operators list in [`ir_models.py`](../src/pipeline/domain/ir_models.py).
2. Update the IR generator's system prompt in [`ir_generator.py`](../src/pipeline/application/ir_generator.py) to mention the new operator and provide an example.
3. Update the freeform SQL prompt in [`freeform_sql_generator.py`](../src/pipeline/application/freeform_sql_generator.py) to document the SQL emission rule for the new operator.

The Tier-1 implementation roadmap for `IS NULL`, `NOT_IN`, `LIKE`, plus SAP zero-padding and empty-string normalization, is documented in memory `project_tier1_implementation.md`.

### 16.4 Change the LLM model

Edit `config/settings.json`:

```json
"model_name": "anthropic--claude-4.6-sonnet",
"deployments": { "llm": "<deployment_id>" }
```

`get_chat_llm` ([`src/shared/llm_factory.py`](../src/shared/llm_factory.py)) routes Claude vs GPT vs Bedrock and is the single place that touches `gen_ai_hub`.

### 16.5 Add a new macro intent

1. Extend `MacroIntent` enum in [`macro_intent_classifier.py`](../src/pipeline/application/macro_intent_classifier.py).
2. Update the classifier's system prompt with the new intent's decision rules and an example.
3. Add a handler node in [`ask_graph.py`](../src/pipeline/graph/ask_graph.py) (e.g., `handle_training`).
4. Register the route in `router` and add the destination in `add_conditional_edges`.

---

## 17. Troubleshooting

### Pipeline errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `plan_ir_dict empty — Phase 1 sub-graph did not produce a plan` | IR generator failed to parse, or the question is non-actionable | Inspect the IR generator's raw response; rephrase the question |
| `disambiguation_message` set with Level 2/3 message | Term not found unambiguously in the dictionary | Add the term to `ask-semantic-dictionary-v1` via the admin API's dictionary endpoints (`/v1/admin/dictionary`) |
| Phase 2 returns empty `anchor_yamls` | OpenSearch retrieval found no entities | Lower retrieval threshold (rare); verify the relevant entity is ingested |
| Phase 3 `unreachable` non-empty in `resolved_paths` | No edge path between base entity and target | Inspect `ask-edge-registry-v1`; the edge may not have been indexed during ingestion |
| `scope_warning` after retry | Post-SQL audit detected out-of-scope tables and the 1× retry didn't fix it | Inspect `scope_audit.out_of_scope`; usually means the LLM hallucinated a SAP table — check that the relevant Silver YAML is in the prompt |
| `expansion_exhausted=True` (2-pass flow) | LLM kept asking for more entities beyond `max_expansion_rounds` | Either increase `max_expansion_rounds`, or fall back to single-pass (`use_two_pass_flow=false`) for that question |
| DB error "column X not found" | LLM emitted a column name that doesn't exist | Check the YAML for the correct column name; the LLM should never hallucinate columns when the YAML is correct |
| 0 rows but SQL is structurally correct | Filter values don't match existing data | Not a pipeline bug — verify the filter values exist in the target tables |

### Diagnostic queries (Postman / curl)

```bash
# Inspect a specific entity
GET http://localhost:9200/ask-entity-registry-v1/_doc/silver_ecc_sd_sales_order

# Find all edges in scope of a given pair
POST http://localhost:9200/ask-edge-registry-v1/_search
{
  "size": 100,
  "query": {
    "bool": {
      "filter": [
        {"term": {"is_reverse": false}},
        {"terms": {"source_node": ["silver_ecc_mm_inv_mov_stock"]}}
      ]
    }
  }
}

# Look up a business term in the global dictionary
POST http://localhost:9200/ask-semantic-dictionary-v1/_search
{"query": {"match": {"business_term": "open order"}}}
```

### Re-initializing a clean state

```bash
# Re-publish the YAMLs through the admin API (the ASK Studio drives it):
#   POST /v1/admin/yaml/index/{entity_id}/{env}

# Drive the v1 pipeline for debugging:
#   POST /v1/query  {"question": "...", "mode": "precise"}
```

---

## Appendix A — File manifest

```
src/pipeline/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── entities.py                              BronzeNode, SilverNode, GoldNode, Relationship
│   ├── graph_models.py                          RelationEdge, JoinType, JoinCondition, Cardinality
│   └── ir_models.py                             SemanticPlanIR, IRFilter, TimeContext, SortSpec
├── application/
│   ├── __init__.py
│   ├── macro_intent_classifier.py               Phase 0 — intent classification
│   ├── ir_generator.py                          Phase 1 — IR extraction
│   ├── semantic_dictionary_service.py           Global dictionary + Phase 2.5 enrichments
│   ├── semantic_field_mapper.py                 Legacy LLM-based fuzzy matching (not in core path)
│   ├── ocsl_retriever.py                        Hybrid retrieval (RRF + Medallion + governance gate)
│   ├── entity_resolution.py                     Phase 2 — facade over OCSL + phrase expansion
│   ├── path_selector.py                         Phase 3 — BFS + edges hint + Dijkstra
│   ├── freeform_sql_generator.py                Phase 4 — freeform SQL with 2-pass flow
│   ├── sql_scope_validator.py                   Post-SQL scope audit + retry feedback
│   ├── schema_catalog_service.py                SCHEMA_QUERY handler
│   ├── dashboard_planner_service.py             DASHBOARD_GEN handler
│   └── ingestion_service.py                     YAML → OpenSearch (shared with v2)
├── graph/
│   ├── __init__.py
│   ├── state.py                                 AgentState TypedDict
│   ├── fase1_ir_graph.py                        Phase 1 sub-graph (IR + disambiguation)
│   └── ask_graph.py                             Main graph (classify → route → execute_sql_pipeline)
└── infrastructure/
    ├── __init__.py
    ├── embedders/embedders.py                   SAPAICoreEmbedder (3072-dim)
    ├── parsers/sap_json_parser.py               SAP JSON → BronzeNode/SilverNode
    ├── parsers/yaml_parser.py                   YAML → domain models
    ├── repositories/file_storage_repo.py        File-system YAML storage
    ├── repositories/opensearch_repository.py    ask-* index actions
    └── serializers/yaml_serializer.py           Domain models → YAML

ask-chat-spa/
└── src/layouts/AppLayout.tsx                    Chat UI header (engine selector)

config/
└── settings.json                                hybrid_pipeline.* + shared sections

tests/
├── e2e/test_smoke.py                            One query per mode against a live orchestrator
└── benchmark/test_full_benchmark.py             Opt-in question-set benchmark

docs/
├── PRECISE.md                                   This document
├── SMART.md                                     Catalog-first / Graph RAG variant
└── FLASH.md                                     Single-call chunk-RAG variant
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
| 7.1 | Entity Registry | `src/pipeline/infrastructure/repositories/opensearch_repository.py::save_silver_node, save_gold_node` |
| 7.2 | Field Registry | Same file, field registry actions |
| 7.3 | Edge Registry | Same file, edge registry actions with `cross_module` |
| 8.1 | Traversal Path Definition | `src/pipeline/application/path_selector.py::select_resolved_paths` |
| 8.2 | Path Selection Rules | Same — Dijkstra with `traversal_cost` |
| 8.3 | Multi-Hop Cross-Module | Edge Registry `cross_module` flag honored in BFS + Dijkstra |
| 10.1 | IR Schema | `src/pipeline/domain/ir_models.py::SemanticPlanIR` |
| 10.2 | IR Validation Rules | `src/pipeline/application/ir_generator.py` (Pydantic + `is_impossible`) |
| 11 | Graph Compiler | **Not implemented** — replaced by freeform SQL + scope validator |
| 12 | Execution Pipeline | `src/pipeline/graph/ask_graph.py::build_ask_graph` |
| 13.1 | Retrieval Ranking | `src/pipeline/application/ocsl_retriever.py` (RRF + Medallion bonuses) |
| 13.2 | Disambiguation | `src/pipeline/graph/fase1_ir_graph.py::dictionary_check_node` (3 levels) |
| 14 | Gold Layer YAML Spec | `GoldNode` in `ask-knowledge-graph` + the semantic-layer repo's `gold/*.yaml` |
| 16 | Validation Rules | Silver/Gold Pydantic validators |
| 17 | RBAC | **Not enforced** (state fields plumbed but no SQL injection) |
| 21 | ID Grammar | `src/pipeline/domain/entities.py` (regex validators on `id`) |

---

*End of Pipeline V1 Technical Reference. For the catalog-first variant, see [SMART.md](SMART.md). For questions, check the relevant section above or the source files linked inline.*

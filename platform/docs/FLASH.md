# Flash Engine — Technical Reference

> Version: Flash (Chunk RAG)
> Status: SHIPPED. Predecessor to Pipeline v1 (Precise) and Pipeline v2 (Smart). Maintained as the lowest-latency, lowest-cost engine.
> Scope: Single LLM call — chunk similarity search → SQL generation → execution. No IR phase, no path planning, no scope validation.

This document covers:
- The architectural design of the Flash (Chunk RAG) engine.
- The concrete implementation in [`packages/ask-intent-resolution/src/ask_intent_resolution/flash/`](../packages/ask-intent-resolution/src/ask_intent_resolution/flash/).
- The operational artifacts (config, ingestion, UI integration).

It is the definitive **technical reference** for the Flash flow — the "Flash" engine in the chat mode selector.

For the hybrid semi-deterministic variant, see [PRECISE.md](PRECISE.md).
For the catalog-first / LLM-as-retriever variant, see [SMART.md](SMART.md).

---

## Table of Contents

1. [Overview](#1-overview)
2. [When to use Flash](#2-when-to-use-flash)
3. [Design rationale and trade-offs](#3-design-rationale-and-trade-offs)
4. [End-to-end data flow](#4-end-to-end-data-flow)
5. [Components — services in detail](#5-components--services-in-detail)
6. [Chunk document model](#6-chunk-document-model)
7. [OpenSearch data model](#7-opensearch-data-model)
8. [Configuration](#8-configuration)
9. [Chunk ingestion](#9-chunk-ingestion)
10. [Orchestrator integration](#10-orchestrator-integration)
11. [UI integration](#11-ui-integration)
12. [Testing](#12-testing)
13. [Metrics and benchmark](#13-metrics-and-benchmark)
14. [Intentional design choices](#14-intentional-design-choices)
15. [Known gaps and roadmap](#15-known-gaps-and-roadmap)
16. [How to extend](#16-how-to-extend)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. Overview

Flash resolves a natural-language question into executable SQL through a **single LLM call**:

```
User question
    │
    ▼
  [Stage 1] OpenSearchVectorStore.similarity_search    (no LLM, hybrid RRF)
    │   ↓ k=5 schema chunks + k=2 business-context chunks
    ▼
  [Stage 2] generate_sql()                             (LLM call #1 — freeform SQL)
    │   ↓ produces SQL + explanation + grain metadata
    ▼
  [Stage 3] SqlExecutorService.execute_and_format()    (no LLM, SAP HANA or PostgreSQL)
    │   ↓ returns rows + formatted NL answer
    ▼
IntentResolutionResult(sql=..., rows=..., answer=...)
    │   ↓ orchestrator detects sql is not None → skips SqlGeneration chain
    ▼
QueryResponse to user
```

**Principles:**
- **Minimal pipeline**: no Intermediate Representation, no entity graph, no path planning. One similarity search + one LLM call.
- **Speed over determinism**: the cheapest and fastest path when approximate schema coverage is acceptable.
- **Chunk-based schema grounding**: the LLM sees free-text schema documentation chunks, not structured YAML entities. SQL correctness depends on chunk quality and recall.
- **No scope guarantees**: unlike Precise (scope validator) and Smart (Edge Registry), Flash has no mechanism to detect or correct out-of-scope table references.

---

## 2. When to use Flash

| Scenario | Flash suitable? |
|---|---|
| Exploratory / ad-hoc question on a well-indexed schema | Yes — fastest response |
| Single-table query where the table is unambiguous | Yes — reliable |
| Multi-table JOIN across SAP modules | Risky — JOIN conditions are guessed by LLM |
| Audit or reproducibility required | No — entity selection is approximate |
| Question on a schema with many similar entities | No — chunk retrieval may miss the right table |
| Production pipeline with correctness SLA | No — use Precise or Smart |

Flash is the recommended engine during early development (before the entity YAML layer is complete) and for low-stakes queries where latency matters more than scope guarantees.

---

## 3. Design rationale and trade-offs

Flash is the original engine, predating both Precise and Smart. It was designed for rapid iteration: skip the semantic layer, index any documentation as text chunks, let the LLM figure out SQL from the chunks.

| Property | Flash | Precise (v1) | Smart (v2) |
|---|---|---|---|
| LLM calls per query | **1** | 3 | 2 |
| Schema source | RAG chunks | Structured YAML entities | Structured YAML entities |
| Entity selection | Chunk similarity (approximate) | RRF + Medallion re-ranking (deterministic) | LLM-as-retriever (catalog-guided) |
| JOIN planning | LLM guesses from schema text | Dijkstra on Edge Registry | Dijkstra on Edge Registry |
| Scope validation | None | Post-SQL audit + retry | None (but catalog-scoped) |
| Cost / query (approx.) | **~$0.01–0.03** | ~$0.09 | ~$0.10 |
| Latency (approx.) | **~15–20 s** | ~60 s | ~40 s |
| Reproducibility | Low (chunk order varies) | High (deterministic retrieval) | Medium (LLM selector) |

**Key design decision recorded in PRECISE.md §2:**
> "The Flash engine retrieved arbitrary YAML chunks via free OpenSearch search and let the LLM generate SQL ad-hoc — that approach has no scope guarantees and no path planning."

Precise and Smart were built to address these gaps. Flash was retained as the fastest path for cases where those gaps are acceptable.

---

## 4. End-to-end data flow

### 4.1 State container — `IntentResolutionResult`

Flash does not use a LangGraph state graph. It returns an `IntentResolutionResult` directly from `FlashStrategy.resolve()`.

```python
@dataclass
class IntentResolutionResult:
    # Flash populates these three:
    sql:    str | None          # generated SQL string
    rows:   list[dict] | None   # query result rows (or None on error)
    answer: str | None          # NL formatted answer

    # Flash leaves these empty (no IR phase, no YAML resolution):
    plan:   dict                # {} always
    yamls:  list                # [] always
    edges:  list                # [] always

    disambiguation: None        # Flash has no disambiguation
    error:  str | None
    trace:  dict                # {"elapsed_ms": ..., "strategy": "flash"}
```

The orchestrator detects `result.sql is not None` and skips the `ResolveIntent → SqlGeneration → SqlExecutor` chain. Flash output is final.

### 4.2 Sequence diagram

```
User question
    │
    ▼
ask-orchestrator /v1/query
    │   MacroIntentClassifier → SQL_EXECUTION
    │   strategy = "flash" (from request.mode)
    │
    ▼
FlashStrategy.resolve(request)
    │
    │   ┌──────────────────────────────────────────────┐
    │   │  Stage 1 — Schema chunk retrieval            │
    │   │                                              │
    │   │  doc_types = _mode_to_types[schema_mode]     │
    │   │  filter = {"terms": {"metadata.doc_type":    │
    │   │              doc_types}}                     │
    │   │                                              │
    │   │  schema_docs = schema_vs.similarity_search(  │
    │   │      question, k=5, filter=filter)           │
    │   │                                              │
    │   │  business_docs = schema_vs.similarity_search(│
    │   │      question, k=2,                          │
    │   │      filter={"term":{"metadata.doc_type":    │
    │   │               "business_semantic"}})         │
    │   │                                              │
    │   │  Outputs: schema_context (str), business_    │
    │   │           context (str)                      │
    │   └──────────────────────────────────────────────┘
    │
    │   ┌──────────────────────────────────────────────┐
    │   │  Stage 2 — SQL generation (1 LLM call)       │
    │   │                                              │
    │   │  prompt = _build_sql_prompt(db_type)         │
    │   │    + optional HANA schema prefix block       │
    │   │    + optional conversation_history block     │
    │   │                                              │
    │   │  response = llm.invoke([HumanMessage(prompt)])
    │   │  result = _safe_json_loads(response.content) │
    │   │                                              │
    │   │  Outputs: sql, table_name, explanation,      │
    │   │           grain, is_dashboard_ready,         │
    │   │           rules_applied                      │
    │   └──────────────────────────────────────────────┘
    │
    │   ┌──────────────────────────────────────────────┐
    │   │  Stage 3 — SQL execution + formatting        │
    │   │                                              │
    │   │  formatted = sql_executor.execute_and_format(│
    │   │      ExecutionRequest(sql, db_type, db_cfg), │
    │   │      question=request.question)              │
    │   │                                              │
    │   │  Outputs: rows_dict, answer, error           │
    │   └──────────────────────────────────────────────┘
    │
    ▼
IntentResolutionResult(sql=sql, rows=rows_dict, answer=answer, plan={}, yamls=[], edges=[])
    │
    ▼
ask-orchestrator → QueryResponse → chat SPA
```

---

## 5. Components — services in detail

### 5.1 `FlashStrategy`

**File:** [`packages/ask-intent-resolution/src/ask_intent_resolution/flash/strategy.py`](../packages/ask-intent-resolution/src/ask_intent_resolution/flash/strategy.py)

**Responsibility:** Entry point for the Flash path. Lazy-singleton wrapper around the Chunk RAG pipeline.

**Bundle (class-level cache):**

```python
cls._bundle = {
    "llm":           ChatLLM,                      # from ask_llm_gateway
    "schema_vs":     OpenSearchVectorStore,         # rag_schema collection
    "db_type":       "hana" | "postgresql",
    "db_config":     dict,                          # connection params
    "hana_schema":   str,                           # SAP HANA schema prefix (e.g. "MY_SCHEMA")
    "schema_mode":   "documents" | "yaml" | "both", # controls which doc_types are searched
    "sql_executor":  SqlExecutorService,            # from ask-sql-executor
}
```

The `_bundle` is initialized once per process via `_get_bundle()` (double-checked locking). `FlashStrategy.reset()` drops the cache — call it after config changes or in tests.

**Key method:**
```python
def resolve(self, request: ResolutionRequest) -> IntentResolutionResult
```

1. Calls `generate_sql(question, schema_vs, llm, db_type, history, schema_mode, hana_schema)`.
2. If `generate_sql` returns `{"error": ...}` → returns `_empty_result(error=...)` immediately.
3. Calls `sql_executor.execute_and_format(ExecutionRequest(sql, db_type, db_config))`.
4. Returns `IntentResolutionResult` with `sql`, `rows_dict`, `answer` set; `plan/yamls/edges` empty.

**Error boundary:** both `generate_sql` failures and `execute_and_format` failures are caught and re-raised as `StrategyExecutionError`, giving the orchestrator a consistent exception type.

### 5.2 `generate_sql`

**File:** [`packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/sql_service.py`](../packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/sql_service.py)

**Responsibility:** Retrieve relevant schema chunks and invoke the LLM to generate SQL.

**Signature:**
```python
def generate_sql(
    question:             str,
    schema_vs:            OpenSearchVectorStore,
    llm:                  ChatLLM,
    db_type:              str,                      # "hana" | "postgresql"
    conversation_history: str = "",
    schema_mode:          str = "both",
    hana_schema:          str = "",
) -> dict
```

**Retrieval logic:**

| `schema_mode` | `doc_type` filter applied |
|---|---|
| `"documents"` | `schema_technical`, `business_semantic` |
| `"yaml"` | `yaml_data_product` |
| `"both"` (default) | `schema_technical`, `yaml_data_product` |

On top of the mode-controlled search, business context is always retrieved separately:
```python
business_docs = schema_vs.similarity_search(
    question, k=2,
    filter={"term": {"metadata.doc_type": "business_semantic"}}
)
```

This business context is injected into the prompt as a `BUSINESS RULES:` block.

**Schema context format** (injected into `{schema_context}` placeholder):
```
Table: SILVER_SD_SALES_ORDER
Layer: silver | Grain: transactional | Dashboard Ready: True
Measures: ['net_value', 'quantity']
Dimensions: ['customer', 'plant', 'month']

<chunk text (the indexed page_content)>

---

Table: ...
```

**Prompt blocks (injected in order):**
1. **HANA schema prefix block** (only when `hana_schema` is set and `db_type == "hana"`):
   ```
   HANA SCHEMA PREFIX (MANDATORY — this overrides rule #2 below):
   Every table reference MUST be qualified: "SCHEMA"."TABLE_NAME"
   ```
2. **Conversation history block** (only when `conversation_history` is non-empty):
   ```
   CONVERSATION HISTORY (use this to resolve follow-up questions):
   <history>
   ```
3. **Main SQL prompt** (`_build_sql_prompt(db_type)`) with placeholders resolved:
   - `{question}` → the user's question
   - `{schema_context}` → retrieved schema chunks
   - `{business_context}` → retrieved business rules (empty string if none)

**HANA SQL rules in the prompt (15 rules):**

| Rule | Constraint |
|---|---|
| 1 | Use ONLY tables/columns from schema above — never invent names |
| 2 | Table names: double-quoted exact casing `"TABLE_NAME"` |
| 3 | Column names: double-quoted exact casing `"COLUMN_NAME"` |
| 4 | `LIMIT 500` unless aggregations/totals |
| 5 | Monetary values: `ROUND(value, 2)` |
| 6 | snake_case column aliases |
| 7–8 | No computed aliases in `HAVING`/`WHERE` — wrap in subquery |
| 9 | Window functions must be in a subquery |
| 10 | Use `LIST_AGG` not `STRING_AGG`; no `DISTINCT` inside `LIST_AGG` |
| 11 | `MONTH()` and `YEAR()` are valid |
| 12 | `CURRENT_DATE` for today; `ADD_DAYS(CURRENT_DATE, n)` for arithmetic |
| 13 | `NULLS LAST`/`NULLS FIRST` not supported; ORDER BY can use aliases |
| 14 | CTE column casing: double-quote every alias in CTE, reference with double-quotes |
| 15 | Prefer CTEs over inline subqueries; use approach 14c |

**Output JSON contract** (HANA and PostgreSQL):
```python
{
    "table_name":         str,        # main table from schema
    "sql":                str,        # generated SQL string
    "explanation":        str,        # brief reasoning
    "grain":              "transactional" | "aggregated",
    "is_dashboard_ready": bool,
    "rules_applied":      list[str],  # HANA rules applied in this query
    # --- injected by generate_sql after LLM call ---
    "schema_used":        str,        # raw schema_context sent to LLM
    "schema_docs_meta":   list[dict], # metadata from each schema doc
}
```

**Error returns** (instead of raising):
```python
{"error": "No schema information found. Please ingest schema documentation first.", "sql": None}
{"error": "Failed to parse LLM response: ...", "sql": None}
{"error": "**404 Not Found** — ...", "sql": None}
{"error": "**401 Unauthorized** — ...", "sql": None}
{"error": "Error generating SQL: ...", "sql": None}
```

**`_safe_json_loads`:** handles LLM responses containing unescaped control characters inside JSON string values — a defensive parser that escapes them before passing to `json.loads`.

### 5.3 `init_vectorstores`

**File:** [`packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/rag_service.py`](../packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/rag_service.py)

**Responsibility:** Bootstrap the two vectorstores used by Flash. Called once at bundle initialization.

```python
def init_vectorstores(settings: dict) -> tuple[OpenSearchVectorStore, OpenSearchVectorStore]:
    embeddings = get_embedder(settings)          # from ask_llm_gateway
    os_cfg = settings.get("opensearch", {})
    schema_vs = get_or_create_opensearch_vectorstore(os_cfg, "rag_schema", embeddings)
    docs_vs   = get_or_create_opensearch_vectorstore(os_cfg, "rag_data_product_docs", embeddings)
    return schema_vs, docs_vs
```

Currently only `schema_vs` (`rag-schema` index) is used in the SQL generation path. `docs_vs` (`rag-data-product-docs` index) is returned from the bundle constructor but not consumed by `generate_sql` — it is available for future use (e.g., a Flash-style DOCS_QUERY handler).

### 5.4 `OpenSearchVectorStore`

**File:** [`packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/opensearch_vectorstore.py`](../packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/opensearch_vectorstore.py)

**Responsibility:** Hybrid retrieval (BM25 + kNN → RRF → Min-Max re-ranking) for the RAG chunk collections. Same 3-stage pipeline as the OCSL SML retriever in Precise, adapted for the `rag-*` indices.

#### Stage 1 — RRF pool

```
pool = max(k × 8, 50)
bm25_hits = _bm25_search(query, pool, filter_clause)   # with filter
knn_hits  = _knn_search(query_vec, pool)               # WITHOUT filter (nmslib limitation)
rrf_score(d) = Σ 1 / (60 + rank_i(d))                 # RRF_K = 60
```

BM25 runs with the `doc_type` filter; kNN runs unfiltered (the nmslib engine doesn't reliably support `bool.filter` inside kNN queries). The filter is enforced in Python via `_matches_filter` after the mget bulk-fetch.

#### Stage 2 — Min-Max + additive bonuses

```
final_score = normalize(rrf_score) + tier_bonus(metadata.layer) + priority_bonus(metadata)

tier_bonus:      gold   → +0.40  |  silver → +0.15
priority_bonus:  is_mandatory → +0.20  |  priority=="high" → +0.10
```

This ensures that a Gold-layer chunk beats any Bronze chunk as long as it has any retrieval signal.

#### Stage 3 — Return top-k Documents

Returns `list[Document]` with `page_content=text` and `metadata=metadata`.

**Public interface (LangChain-compatible):**
```python
similarity_search(query, k=4, filter=None) -> list[Document]
similarity_search_with_score(query, k=4, filter=None) -> list[tuple[Document, float]]
add_documents(docs: list[Document]) -> None
document_count: int  # property
```

**Index DDL (auto-created on first use):**
```json
{
  "settings": { "index.knn": true, "number_of_shards": 1, "number_of_replicas": 0 },
  "mappings": {
    "properties": {
      "text":      { "type": "text", "analyzer": "english" },
      "metadata":  { "type": "object", "enabled": true },
      "embedding": {
        "type": "knn_vector", "dimension": <embedding_dim>,
        "method": { "engine": "faiss", "space_type": "innerproduct",
                    "name": "hnsw", "parameters": {"ef_construction": 256, "m": 48} }
      }
    }
  }
}
```

---

## 6. Chunk document model

Flash chunks are `langchain.schema.Document` objects stored with a flat `metadata` dict. Unlike the entity/field/edge registries used by Precise and Smart, there is no domain-level schema — any free-text chunk can be indexed.

### 6.1 Required metadata fields

| Field | Type | Description |
|---|---|---|
| `doc_type` | str | Controls which chunks are retrieved per `schema_mode`. One of `schema_technical`, `business_semantic`, `yaml_data_product`. |
| `table_name` | str | Displayed in `schema_context` header. Should match the physical table name in the target DB. |
| `layer` | str | `"gold"`, `"silver"`, or `"bronze"`. Used for tier bonus in re-ranking. |
| `grain` | str | e.g., `"transactional"` or `"aggregated"`. Displayed in schema context header. |
| `is_dashboard_ready` | bool | Displayed in schema context header. |
| `measures` | list[str] | Measure field names. Displayed in header. |
| `dimensions` | list[str] | Dimension field names. Displayed in header. |

### 6.2 `page_content` format

Free text — typically the schema documentation for the table, including column names, types, descriptions, business rules, and example values. The better the `page_content` quality, the more accurate the generated SQL.

**Example chunk:**
```
Table: SILVER_SD_SALES_ORDER
Physical name: MY_SCHEMA.SILVER_SD_SALES_ORDER
Contains one row per sales order line. Columns:
- "VBELN_VBAK": sales document number (identifier)
- "POSNR_VBAP": item number (identifier, zero-padded to 6 digits)
- "KUNNR_VBAK": sold-to customer number
- "NETWR_VBAK": net value in document currency (ROUND 2 decimals)
- "FKIMG_VBAP": invoice quantity
- "ZIEME_VBAP": quantity unit (SAP unit code)
Join: VBAK.VBELN = VBAP.VBELN
```

### 6.3 `yaml_data_product` doc type

When `schema_mode` is `"yaml"` or `"both"`, chunks with `doc_type = "yaml_data_product"` are searched. These are typically raw YAML text chunks (or converted from the structured YAML files in the semantic-layer repo), providing full Silver/Gold entity definitions to the LLM.

---

## 7. OpenSearch data model

Flash uses **two dedicated indices**, separate from the entity/field/edge registries used by Precise and Smart.

| Index | Collection name | Content |
|---|---|---|
| `rag-schema` | `rag_schema` | Schema documentation chunks. Used by `generate_sql` for schema_context. |
| `rag-data-product-docs` | `rag_data_product_docs` | Data product documentation chunks. Available for future DOCS_QUERY handler; not currently used in the SQL path. |

Both indices share the same mapping (text + metadata + knn_vector). They are created automatically by `OpenSearchVectorStore._ensure_index()` on first write.

### 7.1 Index document example

```json
{
  "_id":   "auto-generated UUID",
  "_source": {
    "text": "Table: SILVER_SD_SALES_ORDER\nPhysical name: ...\n",
    "metadata": {
      "doc_type":          "schema_technical",
      "table_name":        "SILVER_SD_SALES_ORDER",
      "layer":             "silver",
      "grain":             "transactional",
      "is_dashboard_ready": true,
      "measures":          ["net_value", "quantity"],
      "dimensions":        ["customer", "plant", "month"]
    },
    "embedding": [<3072 floats>]
  }
}
```

### 7.2 Relationship to ask-* indices

| Index type | Used by |
|---|---|
| `rag-schema` | Flash only |
| `rag-data-product-docs` | Flash only (future) |
| `ask-entity-registry-v1` | Precise + Smart |
| `ask-field-registry-v1` | Precise (Phase 2.5) |
| `ask-edge-registry-v1` | Precise + Smart |
| `ask-semantic-dictionary-v1` | Precise |

Flash and Precise/Smart operate on **separate indices**. Ingesting YAMLs into the entity/field/edge registries does NOT populate `rag-schema`. Flash has its own ingestion path (see §9).

---

## 8. Configuration

### 8.1 Relevant `config/settings.json` fields

Flash reads from the top-level settings — there is no `flash:` section.

```json
{
  "db_type": "hana",
  "hana": {
    "host":   "myinstance.hanacloud.ondemand.com",
    "port":   443,
    "schema": "MY_SCHEMA"
  },
  "postgresql": {
    "host": "localhost",
    "port": 5432,
    "dbname": "..."
  },
  "opensearch": {
    "host":     "localhost",
    "port":     9200,
    "use_ssl":  false
  },
  "sap_ai_core": {
    "config_path": "config/aicore_config.json"
  },
  "model_name":   "gpt-4.1-mini",
  "deployments": {
    "llm":        "<deployment_id>",
    "embeddings": "<deployment_id>"
  },
  "schema_mode":  "both"
}
```

| Key | Flash usage | Default |
|---|---|---|
| `db_type` | Selects HANA vs PostgreSQL prompt rules and executor | `"hana"` |
| `hana.schema` | Injected as HANA schema prefix in every SQL prompt | Required for HANA |
| `schema_mode` | Controls which `doc_type` values are searched in retrieval | `"both"` |
| `model_name` | LLM for SQL generation | required |
| `deployments.llm` | SAP AI Core deployment for the LLM | required |
| `deployments.embeddings` | SAP AI Core deployment for embeddings | required |

### 8.2 `schema_mode` reference

| Value | `doc_types` searched | Notes |
|---|---|---|
| `"documents"` | `schema_technical`, `business_semantic` | Use when chunks are free-text schema docs (not YAML) |
| `"yaml"` | `yaml_data_product` | Use when chunks are converted YAML entities |
| `"both"` (recommended) | `schema_technical`, `yaml_data_product` | Mixed index with both doc types |

Business semantic chunks (`doc_type = "business_semantic"`) are always searched as a second pass (k=2) regardless of `schema_mode`, providing business rule context on top of technical schema.

---

## 9. Chunk ingestion

Flash ingestion is **separate from entity ingestion**. Precise/Smart consume the entity + field + edge registries; Flash consumes the `rag-schema` chunk collection, which is written through the admin API's embeddings endpoints.

### 9.1 Entry point

`POST /v1/admin/embeddings/index` on `ask-admin-api`:

```json
{
  "collection_name": "rag_schema",
  "documents": [
    { "page_content": "<chunk text>",
      "metadata": { "doc_type": "schema_technical", "table_name": "SILVER_SD_SALES_ORDER",
                    "layer": "silver", "grain": "transactional",
                    "is_dashboard_ready": true,
                    "measures": ["net_value"], "dimensions": ["customer"] } }
  ]
}
```

The caller owns parsing + chunking + metadata; the server embeds each chunk and indexes it into the named collection. Companion endpoints: `GET /v1/admin/embeddings/{collection}/list` and `DELETE /v1/admin/embeddings/{collection}`.

> ASK Studio's **Docs** page (`/admin/docs`) posts files to `POST /v1/admin/docs/ingest`, which parses and chunks server-side but only stamps `source_file` / `chunk_index` metadata. That is the right path for documentation RAG, **not** for Flash schema chunks — those need `doc_type` and the rest of the header metadata, so use `/embeddings/index`.

### 9.2 Ingestion from YAML data products

Semantic-layer YAMLs can be converted to Flash-compatible chunks by:
1. Rendering the YAML as text with `ask_knowledge_graph.application.rag_text_renderer`.
2. Tagging the chunk with `doc_type = "yaml_data_product"`.
3. Posting it to `/v1/admin/embeddings/index` with `collection_name: "rag_schema"`.

This is how `schema_mode = "yaml"` or `"both"` is useful — the same YAML files backing Precise/Smart are made available to Flash as retrievable chunks.

### 9.3 Idempotency

`add_documents` does NOT deduplicate by content. Each call appends new documents with new UUIDs. Re-ingesting the same schema documentation creates duplicate chunks that degrade retrieval quality. Before re-ingesting:

```bash
# Delete and recreate the index (loses all Flash chunks):
DELETE http://localhost:9200/rag-schema
# Index is auto-created on next add_documents call.
```

---

## 10. Orchestrator integration

Flash does not have its own LangGraph graph. The orchestrator invokes it through the `IntentResolver` → `FlashStrategy` path.

### 10.1 Route decision

```
POST /v1/query  {question: "...", mode: "flash"}
    │
    ▼
MacroIntentClassifier → SQL_EXECUTION
    │
    ▼
IntentResolverService.resolve(request, strategy="flash")
    │
    ▼
FlashStrategy.resolve(request)
    │   → returns IntentResolutionResult(sql=..., rows=..., answer=...)
    │
    ▼
orchestrator: if result.sql is not None:
    SKIP ResolveIntent → SqlGeneration → SqlExecutor chain
    RETURN QueryResponse(sql=result.sql, rows=result.rows, answer=result.answer)
```

### 10.2 `IntentResolutionResult` bypass contract

The `sql` field is the bypass signal:

```python
# In ask-orchestrator/routers/query.py:
ir_result = intent_resolver.resolve(request)
if ir_result.sql is not None:
    # Flash path — SQL already generated and executed
    return QueryResponse(
        sql=ir_result.sql,
        rows=ir_result.rows,
        answer=ir_result.answer,
        error=ir_result.error,
        trace=ir_result.trace,
    )
# Precise / Smart path — continue to SqlGeneration → SqlExecutor
```

This bypass is **by design** (documented in `flash/strategy.py` module docstring): routing Flash through `SqlGenerationService` would force a synthetic IR step (a second LLM call) and change the single-call behavior Flash was designed to preserve.

### 10.3 Token tracking

Flash tags its single LLM call through the `ask_llm_gateway` `TokenTracker` context manager. The orchestrator's `QueryResponse.tokens_breakdown` includes the Flash SQL generation phase.

---

## 11. UI integration

### 11.1 Engine selector — chat SPA

The chat SPA header exposes three engine choices (`ask-chat-spa/src/layouts/AppLayout.tsx`):

| Selector label | Engine | Mode sent to orchestrator |
|---|---|---|
| `Flash` | **Flash (this document)** | `"flash"` |
| `Precise` | Pipeline v1 | `"precise"` |
| `Smart` | Pipeline v2 | `"smart"` |

### 11.2 Response rendering

Flash returns the same `QueryResponse` shape as Precise and Smart. The chat thread renders the answer as Markdown and, for row results, a `SqlResultsBlock` with the results table, the generated SQL, and an auto-chart when the shape supports one.

Flash does **not** populate the pipeline trace (plan/yamls/edges are empty). The trace only shows `elapsed_ms` and `strategy: "flash"`.

### 11.3 Conversation history

Flash passes prior turns as a prepended `CONVERSATION HISTORY` block in the SQL prompt, allowing follow-up questions like "now filter by plant 1000" to resolve correctly. History is formatted as:
```
user: <prior question>
assistant: <prior answer>
```

---

## 12. Testing

### 12.1 Unit tests

Flash strategy tests live in:
```
packages/ask-intent-resolution/tests/unit/flash/
```

Key test patterns:
- Mock `schema_vs.similarity_search` → verify `generate_sql` prompt structure.
- Mock `llm.invoke` → verify JSON parsing, including malformed responses.
- Mock `sql_executor.execute_and_format` → verify `IntentResolutionResult` fields.
- `FlashStrategy.reset()` before each test (drops the class-level `_bundle` cache).

### 12.2 Integration / smoke tests

```bash
# e2e smoke — runs 1 Flash query against the deployed orchestrator:
cd tests/e2e && python test_smoke.py --mode flash

# Manual via orchestrator HTTP:
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"question": "How many open sales orders this month?", "mode": "flash"}'
```

### 12.3 Retrieval sanity check

Verify that schema chunks are indexed and retrievable before testing SQL generation:

```bash
# Count chunks in rag-schema index:
curl http://localhost:9200/rag-schema/_count

# Spot-check retrieval for a question:
POST http://localhost:9200/rag-schema/_search
{
  "size": 5,
  "_source": ["metadata.table_name", "metadata.doc_type", "text"],
  "query": {
    "bool": {
      "must": {"match": {"text": "sales order net value"}},
      "filter": {"terms": {"metadata.doc_type": ["schema_technical", "yaml_data_product"]}}
    }
  }
}
```

---

## 13. Metrics and benchmark

> Flash does not have a versioned benchmark suite in the repo. The numbers below are observational estimates.

| Stage | Tokens / query (approx.) | Cost / query (approx.) | Notes |
|---|---|---|---|
| Chunk retrieval | 0 | $0 | No LLM — vectorstore search only |
| `generate_sql` (LLM) | ~3,500–8,000 | ~$0.01–0.03 | Varies with schema context size (k=5 chunks × chunk length) |
| SQL execution + formatting | ~500–1,000 | ~$0.002 | LLMResultFormatter in ask-sql-executor |
| **TOTAL** | **~4,000–9,000** | **~$0.01–0.03** | 3–10× cheaper than Precise/Smart |
| Latency | ~15–20 s | — | 1 LLM call + retrieval + SQL exec |

### 13.1 Why Flash is cheaper

- **1 LLM call** vs 3 (Precise) or 2 (Smart).
- **Schema context is chunk-based**: the prompt contains only the top-k chunk texts (~1,000–2,000 tokens each), not full raw YAML entity documents (~5,000–10,000 tokens each).

### 13.2 Known accuracy gap vs Precise/Smart

On the 9-question inventory benchmark used to validate Precise and Smart:
- Flash was **not run** against that benchmark formally.
- Observed behavior: Flash succeeds on single-table or simple 2-table queries; it degrades on cross-module JOINs and queries requiring multiple entities because JOIN conditions are not injected deterministically.
- Without a scope validator, hallucinated table names may slip through silently (no retry).

---

## 14. Intentional design choices

### 14.1 Single LLM call — no IR phase

Flash has no IR generation step. Precise and Smart extract a `SemanticPlanIR` first (LLM call #1), then use it to guide entity retrieval and SQL generation. Flash skips this entirely.

**Why:** The IR phase exists to decompose a complex question into semantic terms that can be matched to indexed entities. When the schema is available as free-text chunks, the LLM can resolve question → SQL directly without an intermediate decomposition. The tradeoff is that without IR there is no disambiguation step and no fallback to a semantic dictionary.

### 14.2 No scope validation

Flash does not run `SQLScopeValidator`. Precise validates post-SQL that every referenced table is in the resolved YAML set; Flash has no resolved entity set to validate against.

**Why:** Scope validation requires knowing which tables are "allowed" for a given query. Flash's chunk retrieval doesn't produce a bounded entity set — it retrieves chunks that are similar to the question, but there is no guarantee of completeness. Implementing scope validation for Flash would require ingesting entity metadata separately, which is the entity registry approach Precise already uses.

### 14.3 Business-semantic docs always retrieved as second pass

Even when `schema_mode = "yaml"` (which excludes `schema_technical` from the primary search), `business_semantic` chunks are always retrieved in a separate k=2 search and appended as a `BUSINESS RULES:` block.

**Why:** Business rules (e.g., "zero-padded item numbers", "NETWR is exclusive of tax") are critical for correct SQL but are short and dense — they risk being crowded out in a k=5 primary search by larger technical schema chunks. The separate pass guarantees they are always injected.

### 14.4 Chunk deduplication is caller's responsibility

`add_documents` appends; it does not deduplicate. The ingestion caller must manage this (delete the collection, then re-index, when schema documentation changes). This is intentional — deduplication logic belongs at the ingestion boundary, not inside the vectorstore.

### 14.5 `docs_vs` returned but not consumed

`init_vectorstores` returns both `schema_vs` and `docs_vs`, but the `_bundle` only stores `schema_vs`. The `docs_vs` return value is retained in the API for a future DOCS_QUERY handler that would answer documentation questions (e.g., "what does field X mean?") via Flash-style chunk retrieval.

---

## 15. Known gaps and roadmap

### 15.1 No benchmark

Flash has no versioned benchmark suite. Accuracy can only be assessed informally through the chat UI. **Action:** add a Flash run to `tests/benchmark/` over the same fixed question set used for Precise/Smart, recording SQL + execution results.

### 15.2 No disambiguation

When a question is ambiguous (e.g., "show me orders" — SD sales orders or MM purchase orders?), Flash picks whatever chunks score highest. Precise has 3-level disambiguation via the semantic dictionary; Flash has none. **Mitigation:** ingest chunks for both modules and let RRF + business context steer the LLM.

### 15.3 No cross-module JOIN guarantee

Flash may generate syntactically correct SQL with wrong JOIN conditions for cross-module queries. The Precise edges hint (from `ask-edge-registry-v1`) is the authoritative source for JOIN conditions — Flash has no equivalent. **Mitigation:** include explicit JOIN examples in chunk `page_content`.

### 15.4 Duplicate chunk problem

Re-ingesting schema documentation without first deleting the collection creates duplicate chunks that degrade retrieval (higher noise, lower precision). The admin API exposes `GET /v1/admin/embeddings/{collection}/list` and `DELETE /v1/admin/embeddings/{collection}`, but nothing detects duplicates for you. **Action:** surface a chunk count + a "delete and re-index" action on the admin surface that owns Flash ingestion.

### 15.5 No conversation-level schema cache

Each Flash query re-instantiates the similarity search from scratch. There is no session-level cache of which chunks were retrieved for the current conversation. For multi-turn queries about the same entity, the same chunks are retrieved repeatedly. **Potential optimization:** cache retrieved chunks per session thread_id.

---

## 16. How to extend

### 16.1 Add new schema documentation

1. Write or export the schema documentation for the new table (column names, types, descriptions, business rules, example filter values).
2. Split it into chunks and tag each one with `doc_type = "schema_technical"`, `table_name`, `layer`, etc.
3. `POST /v1/admin/embeddings/index` with `collection_name: "rag_schema"` (see §9.1).
4. Flash picks up the new chunks on the next query.

### 16.2 Add YAML-based chunks

1. Author the Silver/Gold YAML in the semantic-layer repo.
2. Render it as a chunk with `metadata.doc_type = "yaml_data_product"`.
3. Index it via `/v1/admin/embeddings/index`, or call `schema_vs.add_documents([doc])` programmatically.
4. Set `schema_mode = "both"` in `config/settings.json` so Flash searches both technical and YAML doc types.

### 16.3 Change the LLM model

Edit `config/settings.json`:
```json
"model_name": "anthropic--claude-4.6-sonnet",
"deployments": { "llm": "<new_deployment_id>" }
```

Call `FlashStrategy.reset()` (or restart the process) to invalidate the cached bundle. The new LLM will be used on the next query.

### 16.4 Add a new HANA SQL rule

Edit `_build_sql_prompt` in [`flash/infrastructure/sql_service.py`](../packages/ask-intent-resolution/src/ask_intent_resolution/flash/infrastructure/sql_service.py):

1. Add the rule to the numbered list in the HANA prompt block.
2. Add it to `"rules_applied"` examples in the few-shot section if applicable.
3. Restart or call `FlashStrategy.reset()` — the prompt is rebuilt from the function, not cached.

### 16.5 Add PostgreSQL-specific rules

Edit the `else` branch of `_build_sql_prompt`. PostgreSQL rules are minimal by default (casing, `LIMIT`, `ROUND(value::numeric, 2)`). Extend with PG-specific constraints as needed.

### 16.6 Implement a Flash DOCS_QUERY handler

`init_vectorstores` already creates `docs_vs` (`rag-data-product-docs`). A DOCS_QUERY handler would:
1. Call `docs_vs.similarity_search(question, k=5)`.
2. Build a retrieval-augmented answer prompt (no SQL generation needed).
3. Call `llm.invoke([HumanMessage(content=prompt)])`.
4. Return a `QueryResponse` with `answer` set and `sql = None`.

---

## 17. Troubleshooting

### Pipeline errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `"No schema information found. Please ingest schema documentation first."` | `rag-schema` index is empty or `doc_type` filter matches no chunks | Check `rag-schema` document count; verify `schema_mode` matches the indexed `doc_type` values; re-ingest |
| `"Failed to parse LLM response: ..."` | LLM returned non-JSON or malformed JSON | Check the raw LLM response in the trace; usually a prompt injection or model instability issue — retry |
| `"**404 Not Found**"` | SAP AI Core LLM deployment not found | Setup SPA → *LLM Providers* — re-select the deployment |
| `"**401 Unauthorized**"` | SAP AI Core credentials expired | Refresh `config/aicore_config.json` credentials |
| SQL executes but returns wrong table | Chunk retrieval picked the wrong schema doc | Check `schema_docs_meta` in the trace — inspect which chunks were retrieved; improve chunk content or add more specific metadata |
| SQL references non-existent column | LLM hallucinated a column not in the chunk | Improve `page_content` to explicitly list all column names; or add a `business_semantic` chunk with the correct column names |
| DB error "table X not found" | LLM hallucinated a table name | Flash has no scope validator — add the correct table name to the chunk `page_content`; consider switching to Precise for scope-sensitive queries |
| Duplicate / redundant results | Chunks were ingested multiple times | Delete `rag-schema` index and re-ingest from scratch |
| `FlashStrategy._bundle` stale after config change | Bundle cached from old settings | Call `FlashStrategy.reset()` or restart the process |

### Diagnostic queries (curl / Postman)

```bash
# Count indexed chunks
curl http://localhost:9200/rag-schema/_count

# List all doc_types in the index
POST http://localhost:9200/rag-schema/_search
{
  "size": 0,
  "aggs": {
    "doc_types": {
      "terms": { "field": "metadata.doc_type.keyword", "size": 10 }
    }
  }
}

# Simulate the Flash retrieval for a specific question (k=5, mode=both)
POST http://localhost:9200/rag-schema/_search
{
  "size": 5,
  "_source": ["metadata.table_name", "metadata.doc_type"],
  "query": {
    "bool": {
      "must": {"match": {"text": "<your question here>"}},
      "filter": {
        "terms": {"metadata.doc_type": ["schema_technical", "yaml_data_product"]}
      }
    }
  }
}

# Check data product docs index
curl http://localhost:9200/rag-data-product-docs/_count
```

### Re-initializing Flash

```bash
# Delete and recreate rag-schema (full reset):
curl -X DELETE http://localhost:9200/rag-schema
# Index is auto-created on next add_documents call.

# Reset the in-process bundle cache:
# In Python or a test:
from ask_intent_resolution.flash.strategy import FlashStrategy
FlashStrategy.reset()
```

---

## Appendix A — File manifest

```
packages/ask-intent-resolution/src/ask_intent_resolution/flash/
├── __init__.py
├── strategy.py                        FlashStrategy — lazy singleton, resolve()
└── infrastructure/
    ├── __init__.py
    ├── rag_service.py                 init_vectorstores() — bootstraps schema_vs + docs_vs
    ├── sql_service.py                 generate_sql() — retrieval + LLM SQL generation
    │                                  _build_sql_prompt() — HANA/PG prompt builder
    │                                  _safe_json_loads() — defensive JSON parser
    └── opensearch_vectorstore.py      OpenSearchVectorStore — hybrid RRF retrieval
                                       get_or_create_opensearch_vectorstore() — factory

packages/ask-admin-api/src/ask_admin_api/routers/
└── embeddings.py                      Flash ingestion API — chunks → rag-schema

ask-chat-spa/src/layouts/
└── AppLayout.tsx                      chat SPA header — "Flash" engine selector

config/
└── settings.json                      db_type, hana, opensearch, model_name, schema_mode

semantic-layer repo                    YAML data products (optionally converted to chunks)
```

---

## Appendix B — Comparison with Precise and Smart

| Capability | Flash | Precise (v1) | Smart (v2) |
|---|---|---|---|
| IR generation | No | Yes (`SemanticPlanIR`) | Yes (`SemanticPlanIRv2`) |
| Entity registry | Not used | `ask-entity-registry-v1` | `ask-entity-registry-v1` |
| Entity selection | Chunk similarity | RRF + Medallion (deterministic) | LLM selector (catalog-guided) |
| Edge registry | Not used | `ask-edge-registry-v1` | `ask-edge-registry-v1` |
| Path planning | None | BFS + Dijkstra | Dijkstra |
| JOIN hints in prompt | None (LLM guesses) | Declarative edge hints | Declarative edge hints |
| Scope validation | None | Post-SQL audit + 1× retry | None (catalog-scoped) |
| 3-level disambiguation | None | Yes (semantic dictionary) | None |
| LLM calls | 1 | 3 | 2 |
| Cost / query | ~$0.01–0.03 | ~$0.09 | ~$0.10 |
| Latency | ~15–20 s | ~60 s | ~40 s |
| Reproducibility | Low | High | Medium |
| Best for | Speed, prototyping | Auditability, reproducibility | Catalog-scoped accuracy |

---

*End of Flash Engine Technical Reference. For the semi-deterministic hybrid retrieval variant, see [PRECISE.md](PRECISE.md). For the catalog-first variant, see [SMART.md](SMART.md).*

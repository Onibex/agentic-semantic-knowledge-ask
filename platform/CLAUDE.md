# Onibex Agentic Semantic Knowledge Platform: Project Context

> **Read this file FIRST before making any changes.**

## What This Project Does

A **deterministic Text-to-SQL agent** that:

1. Takes natural-language questions (any language) via the ASK Chat SPA
2. Classifies macro-intent: `SQL_EXECUTION` | `SCHEMA_QUERY` | `DOCS_QUERY` | `ACTION_EXECUTION`
3. Resolves business terms against a curated **semantic layer** (ASK YAML corpus)
   via OpenSearch hybrid search (kNN + BM25 + RRF)
4. Calculates JOIN paths deterministically (Dijkstra over an entity-relationship graph)
5. Compiles SQL (HANA or PostgreSQL dialect) from the resolved plan, the LLM maps
   to the semantic layer, it never invents tables or columns
6. Executes, formats the result with an LLM, and returns it with citations and
   a per-request token breakdown

## Surfaces & Services

| Component | Technology | Purpose |
|---|---|---|
| `ask-studio-spa/` (**ASK Studio**) | React + Vite + Nginx | Author & publish the semantic layer: workspaces, business domains, Data Products |
| `ask-chat-spa/` (**ASK Chat**) | React + Vite + Nginx | End-user chat |
| `ask-setup-spa/` (**ASK Setup**) | React + Vite + Nginx | Technical setup: DB connections, LLM providers, identity |
| `packages/ask-orchestrator` | FastAPI | Public chat backend (see endpoints below) |
| `packages/ask-admin-api` | FastAPI | Admin backend: semantic-layer CRUD, ingestion, enrichment, secrets, git publish |
| `services/ask-mcp-server` | Node | SAP write ops via MCP (opt-in compose profile) |
| `teams-bot-middleware/` | FastAPI | Microsoft Teams bridge onto `/external/ask` (opt-in compose profile) |
| OpenSearch, Keycloak | containers | Vector/BM25 search · identity (Keycloak or SAP IAS/XSUAA) |

Everything runs from one `docker-compose.yml`; local and server deploys differ only
in `.env` (see `.env.example` / `.env.remote.example`, `redeploy.sh`, `scripts/package-remote.sh`).

## Orchestrator endpoints

- `/v1/health` (unauthenticated), `/v1/query` (chat), `/v1/profile`, `/v1/title`,
  `/v1/artifact*`, `/v1/internal/*` (ops: cache reload)
- `/external/ask`, isolated B2B sub-app with its own OpenAPI at `/external/openapi.json`
  (watsonx Orchestrate, n8n, Zapier; Keycloak `client_credentials`)

## Typed packages (`packages/`)

| Package | Responsibility |
|---|---|
| `ask-orchestrator` | Macro-intent classifier + routing; chains `ResolveIntent → SqlGen → SqlExecutor` for SQL_EXECUTION; per-request `TokenTracker` |
| `ask-intent-resolution` | `IntentResolver` Protocol + 3 self-contained mode sub-packages: `flash/` (chunk-RAG), `precise/` (IR → entity resolution → Dijkstra path selection), `smart/` (catalog-driven Graph RAG; stops at path resolution) |
| `ask-sql-generation` | Freeform SQL generator + scope validator + per-dialect prompt registry (HANA, PostgreSQL, + lite multi-DB dialects) |
| `ask-sql-executor` | HANA + PostgreSQL adapters + LLM result formatter, the single home for SQL execution/formatting |
| `ask-knowledge-graph` | KG read/write, DictionaryWriter, ingestion (SAP JSON → YAML → OpenSearch), `EntityDeriver`, YAML parse/serialize (ruamel only, never `import yaml`) |
| `ask-schema-service` | Handles SCHEMA_QUERY (metadata answers, workspace-scoped) |
| `ask-docs-service` | Handles DOCS_QUERY (own retriever; must NOT import ask-knowledge-graph) |
| `ask-llm-gateway` | LLM + embedder abstract factory: SAP AI Core (managed) or any LiteLLM provider; encrypted secrets store (Fernet, OpenSearch-backed); TokenTracker |
| `ask-action-execution` | ACTION_EXECUTION (SAP write ops via MCP); may consume ask-llm-gateway only |
| `ask-admin-api` | Admin REST API behind ASK Studio/Setup: workspaces, business domains, entity lifecycle, git-versioned publish (dev/prod), AI enrichment, DDL import, secrets |

Package-internal layering (domain/application/infrastructure) and cross-package
boundaries are enforced by `.importlinter` contracts plus
`tests/boundary/test_no_deleted_modules.py`.

## The three SQL engines (chat modes)

| Mode | Approach | Trade-off |
|---|---|---|
| `flash` | Chunk-RAG straight to SQL | Fastest, cheapest |
| `precise` | Semantic Plan IR → entity resolution → Dijkstra paths → freeform SQL | Most deterministic retrieval (hybrid RRF) |
| `smart` (default) | Catalog-driven Graph RAG: LLM selects entities from a condensed catalog, deterministic path resolver | Cheapest LLM context, catalog-scale |

All three stop at (or before) resolved context; SQL generation is always chained by
the orchestrator through `ask-sql-generation` → `ask-sql-executor`.
Chat is workspace-scoped: an entity-id allowlist plus dev/prod index environments.

## ASK Semantic Layer (YAML)

The corpus lives in an **external git repo** mounted at `SEMANTIC_LAYER_HOST_PATH`
(reference corpus: the public `agentic-semantic-knowledge-ask` repo,
`definition/examples/{bronze,silver,gold}/`, flat per layer). Runtime reads the git
repo, never in-tree copies.

### Bronze (raw SAP table)

```yaml
id: bronze_s4h_vbak_order_header
layer: bronze
source_system: s4h
name: VBAK
alias: ORDER_HEADER
primary_key: [VBELN]
fields:
  VBELN: { type: C10, alias: sales_doc, key_field: true }
  NETWR: { type: P15, alias: net_value }
```

### Silver (curated business entity)

```yaml
id: silver_s4h_sd_sales_order
layer: silver
module: sd
entity_role: fact           # fact | dimension | reference
grain:
  entity_grain: [vbeln_vbak, posnr_vbap]
composed_of: [VBAK, VBAP]
join_graph:
  - left_table: VBAK
    right_table: VBAP
    join_type: INNER
    condition: "VBAK.VBELN = VBAP.VBELN"
fields:
  - name: net_value
    source: VBAK.NETWR
    field_role: measure     # measure | dimension | timestamp | identifier
    aggregation_behavior: SUM
```

> **There is no `metric` layer.** A business measure is a `field_role: measure` field
> with an `aggregation_behavior` on the Silver/Gold that owns it. Ingesting a
> `layer: metric` YAML raises. Gold declares its relations (to Silvers and Golds);
> Silvers never point to Gold.

## OpenSearch indices

| Index | Content |
|---|---|
| `ask-entity-registry-v1` | Bronze/Silver/Gold nodes (semantic search + catalog) |
| `ask-field-registry-v1` | Fields per entity |
| `ask-edge-registry-v1` | JOIN relationships (Dijkstra graph) |
| `ask-semantic-dictionary-v1` | Business terms by SAP module (3-level disambiguation) |
| `ask-entity-lifecycle-v1` | Entity lifecycle/status for ASK Studio |

Indices are env-suffixed (dev/prod) where the publish flow applies.

## Configuration

- `config/settings.json` (gitignored; template: `config/settings.example.json`),
  minimal file config. Env vars override.
- **DB connections and LLM providers are NOT in files**: they live Fernet-encrypted
  in OpenSearch, managed through the Setup SPA (N connections, one active per env;
  multiple LLM providers, one active). Master key via env (`scripts/rotate_master_key.py`).
- Keycloak realm import for local dev: `packages/ask-admin-api/keycloak-realm-config.json`
  (all secrets are local-demo placeholders).

## Key design decisions

1. **LLM as compiler, not generator**. SQL only from resolved fields, never invented names.
2. **Determinism over creativity**, the semantic layer is the only source of truth.
3. **Medallion re-ranking**. Gold > Silver > Bronze in entity resolution.
4. **Bronze is schema-docs plane**, never enters text-to-SQL retrieval.
5. **3-level disambiguation** via the global semantic dictionary (L1 auto-resolve,
   L2 multi-module options, L3 "contact the trainer"); no HiTL in chat.
6. **Additivity contract**, `aggregation_behavior` = function; `additivity` /
   `non_additive_over` = scope, derived at ingest.

## Entry points

| Task | Command |
|---|---|
| Run the stack | `docker compose up -d` |
| Rebuild on a server after `git pull` | `./redeploy.sh` |
| Package a deploy tarball | `scripts/package-remote.sh` |
| Orchestrator tests | `cd packages/ask-orchestrator && pytest` |
| Admin-API tests | `cd packages/ask-admin-api && pytest` |
| Boundary + contracts | `pytest tests/boundary/ && lint-imports` |
| e2e smoke (needs live stack) | `pytest tests/e2e/test_smoke.py` |
| Opt-in benchmark | `pytest tests/benchmark/test_full_benchmark.py` |

## Common tasks

| Task | Where |
|---|---|
| Change IR extraction (precise) | `packages/ask-intent-resolution/.../precise/application/ir_generator.py` |
| Entity resolution logic | `packages/ask-intent-resolution/.../precise/application/entity_resolution.py` |
| Re-ranking weights | `packages/ask-intent-resolution/.../precise/application/ocsl_retriever.py` |
| Smart catalog/selector | `packages/ask-intent-resolution/.../smart/application/` |
| SQL generation rules / dialects | `packages/ask-sql-generation/.../application/freeform_generator.py` + `prompts/` |
| Add DB adapter | `packages/ask-sql-executor/.../infrastructure/` |
| Ingestion / YAML model | `packages/ask-knowledge-graph/` |
| Admin flows (publish, enrich, DDL) | `packages/ask-admin-api/` + `ask-studio-spa/` |
| Design tokens (all SPAs) | `design/tokens.css` + `scripts/sync-design-tokens.mjs` |

## House rules

- User-facing output (UI, docs, commits) in **English**.
- ASK YAML always through ruamel (`load_yaml_text` / `dump_yaml`), never `import yaml`.
- Docs declare what IS; never narrate what changed.
- SPAs pin Vite + Rolldown exactly (`vite 8.1.3`, override `rolldown 1.1.4`);
  regenerate lockfiles when bumping, admin/setup builds use `npm ci`.

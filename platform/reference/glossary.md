# ASK Platform · Glossary

> **Reference page.** Every user-facing term the manual uses, defined once, in one place.
> Definitions here match the [ASK specification](../../definition/README.md) —
> when a term means something specific to the platform (Gold, measure, grain), this page uses
> that meaning, not a generic one.

| | |
|---|---|
| **Who** | Anyone — administrators, data stewards, and business users |
| **Time** | Skim as needed; ~5 minutes end to end |
| **Prerequisites** | None. |
| **You'll end with** | A shared vocabulary for the ASK Admin flows, the Configuration app, and the chat. |

**Where this fits:** **Configure · Author · Publish · Ask (all of them — this page underpins every step)**

> The screenshots and sample values below use an illustrative **SAP Production Planning** example (Production Orders). Substitute your own Data Products — the exact demo names and questions won't exist in your system.

---

## How to read this glossary

- Terms are **alphabetical**.
- Where a term has a precise platform meaning that differs from everyday usage, the entry
  says so explicitly (see **Gold**, **Measure**, **Metric**).
- Cross-references point to the flow where you actually use the term.

---

## A

| Term | Meaning |
|---|---|
| **Agent Mode (Flash / Precise / Smart)** | The engine the chat uses to turn a data question into SQL. **Flash** is fastest: it searches your schema as text and writes SQL in one shot, with no deep validation. **Precise** is the most rigorous and reproducible: it extracts a plan, ranks Data Products deterministically, picks optimal joins, and validates scope. **Smart** is the balanced default: it uses the Data Product catalog as context, picks Data Products naturally, and resolves joins through the relationship graph. If unsure, start with **Smart**. |
| **ASK Admin** | The administration application where you author and publish the semantic layer — workspaces, business domains, and Data Products. Distinct from the **Configuration app** (technical setup) and the **chat** (where users ask questions). |
| **Alias** | A human-readable label for a field, shown instead of the technical column name — e.g. `AFKO.AUFNR` aliased as *Order Number*. Aliases help both people and the agent recognize a column. |
| **Attribute** | A `field_role` for free-text descriptions or names (a material description, an order text). The agent may filter on an attribute but should **not** `GROUP BY` a long attribute. Contrast with **Dimension**: a material *description* is an attribute; a material *group code* is a dimension. |

## B

| Term | Meaning |
|---|---|
| **Bronze** | The layer for a **raw source table** — its columns and keys, and nothing else. A Bronze Data Product carries **no join logic**. In the demo, `afko_order_header` (AFKO) and `afpo_order_item` (AFPO) are Bronze. See [Add Data Products](../ask-admin/02-add-data-products.md). |
| **Business Domain** | A group of Data Products inside a workspace that answer a related business question — e.g. *Production Orders*. A domain's description is fed into the agent's prompt context, so it should describe what the domain covers in business terms. The **same Data Product can be reused across several domains**. See [Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md). |
| **Business grain** | The human-readable label for an entity's grain — e.g. *production order item*. See **Grain**. |

## C

| Term | Meaning |
|---|---|
| **Configuration app** | The administrator application for **technical setup**: database connection, LLM/embeddings provider, and the OpenSearch search index. It is separate from **ASK Admin**, which handles the semantic layer. |
| **Conflict** | A difference the platform detects when merging incoming content (typically a **OneConnect** import) against an existing Data Product. Conflicts are surfaced for manual resolution rather than silently overwriting your work; they appear under the **Conflicts** filter in Semantic Knowledge. |
| **`composed_of`** | On a Silver Data Product, the ordered list of Bronze tables it is built from. On a Gold, it is usually the Gold's own physical table. |

## D

| Term | Meaning |
|---|---|
| **Data Product** | One entity definition (a YAML): its fields, their roles, relationships (joins), and descriptions. Every Data Product lives in a layer — **Bronze**, **Silver**, or **Gold**. You create them via Manual, Upload YAML, DDL + AI, or From OneConnect (see [Add Data Products](../ask-admin/02-add-data-products.md)). |
| **`db_table_name`** | The **physical table the generated SQL targets**. Essential for Gold, which is a real, selectable table — not a computed view. |
| **DDL + AI** | A Data Product creation mode: you provide SQL `CREATE TABLE` statements and the platform maps them into ASK YAML with AI assistance. The layer is auto-detected per file from the table name (the `SILVER_` / `GOLD_` convention); if it can't be detected, you must pick one before importing. |
| **Dimension** | A `field_role` for categorical, groupable attributes — codes and groups you filter or `GROUP BY` (e.g. plant `AFPO.DWERK`, material `AFPO.MATNR`). Not aggregated. Contrast with **Attribute** (free text) and **Measure** (quantitative). |

## E

| Term | Meaning |
|---|---|
| **Enrichment (Enrich)** | An AI-assisted step that suggests improved **descriptions** and **synonyms** for a field or entity. You review the before/after diff and apply it. Good descriptions and synonyms directly improve answer quality — they are how the agent maps a user's words to your columns. |
| **Entity grain** | See **Grain**. |
| **`entity_role` (fact / dimension / reference)** | How a Silver/Gold entity is used in SQL. A **fact** carries measures (e.g. `production_order`); a **dimension** provides groupable attributes; a **reference** is lookup/configuration data. This is a different axis from a field's **field role** and from the source-data **classification** (M / T / C). |
| **Environment (dev / prod)** | Which published snapshot the chat queries. Authoring happens in a working area; you **publish to dev** first, then **promote to prod**. The chat's environment selector decides which snapshot a user sees, so a Data Product published only to dev is invisible when the chat is set to prod. |

## F

| Term | Meaning |
|---|---|
| **Fact** | An `entity_role` for an entity that carries measures (quantitative values) at a defined grain — the thing you aggregate. In the demo, `production_order` is a fact. See **`entity_role`**. |
| **Field role (measure / dimension / identifier / timestamp / attribute / status_flag)** | The role assigned to each field, which tells the agent **where the column may appear in SQL**. **Measure** — quantitative, may be aggregated (SUM/AVG) or filtered. **Dimension** — categorical, may be grouped or filtered. **Identifier** — keys and document numbers; grouped or filtered, never aggregated. **Timestamp** — dates/periods; drives time context. **Attribute** — free text; filter-only, avoid grouping. **Status flag** — a small closed set of business states (e.g. `X = blocked, blank = not blocked`); filter-only. |
| **Flash** | See **Agent Mode**. The fastest engine — schema-as-text search, one-shot SQL, no deep validation. Best for quick, exploratory questions. |

## G

| Term | Meaning |
|---|---|
| **Gold** | A layer for a **physical, denormalized analytics table you can query directly** (it has a real `db_table_name`). Dimension descriptions are flattened in as columns, so many questions resolve from the Gold alone with zero joins — the cheapest, most deterministic path. In the demo, `production_performance` is Gold. **Note:** Gold is a physical table you `SELECT FROM`, **not** a view computed at query time. See the [Gold layer specification](../../definition/docs/GOLD_LAYER.md). |
| **Grain** | The level of detail one row represents, expressed as its ordered key fields (`grain.entity_grain`) plus a human label (`grain.business_grain`). For the demo Silver `production_order` the grain is the order item — one row per order number + item. Grain drives correct aggregation and deduplication. |

## I

| Term | Meaning |
|---|---|
| **Identifier** | A `field_role` for keys and document numbers (e.g. order number `AFKO.AUFNR`, order item `AFPO.POSNR`). Used to group or filter; **never aggregated**. |
| **In Review** | The lifecycle status a Data Product lands in when created or edited, before it is released. It is editable and not yet visible to the chat. See **Released** and **Publish**. |

## J

| Term | Meaning |
|---|---|
| **Join** | See **Relationship**. In the demo, the Silver `production_order` joins header `AFKO` to item `AFPO` on the order number (`AUFNR`). |
| **`join_graph`** | On a Silver, the join plan **between the composed Bronze tables** (Bronze-to-Bronze only), including execution order. It is how a Silver stitches its raw tables into one entity. Distinct from **relationships**, which are cross-entity edges. |

## M

| Term | Meaning |
|---|---|
| **Measure** | A `field_role` for a quantitative value that can be aggregated — a quantity or amount, with a default aggregation (SUM/COUNT/AVG/…). In the demo, planned quantity `AFKO.GAMNG`, confirmed yield `AFRU.LMNGA`, and scrap `AFRU.XMNGA` are measures. A measure is **just a field on its owning Silver/Gold** — there is no separate node for it (see **Metric**). |
| **Metric** | **Deprecated as a standalone layer.** Earlier versions modeled a business measure as its own `layer: metric` YAML; that is no longer authored. A business measure is now simply a field with `field_role: measure` and an aggregation behavior on the Silver or Gold that owns it. The agent aggregates it directly in SQL. See the [Silver layer specification](../../definition/docs/SILVER_LAYER.md). |

## O

| Term | Meaning |
|---|---|
| **OneConnect** | An Onibex tool that produces a SAP metadata export (a JSON payload). The **From OneConnect** creation mode runs that export through the platform's merge engine: new content is applied as a draft and any differences against an existing Data Product surface as **conflicts** to resolve. See [Add Data Products · Mode D](../ask-admin/02-add-data-products.md). |
| **Organization profile** | Organization-level settings such as company name and default **source system** — e.g. *Pinnacle Industrial Manufacturing* on *SAP S/4HANA*. The source system pre-fills AI-assisted modes such as DDL + AI. |
| **OpenSearch** | The search index that powers the platform's semantic (hybrid) search over your Data Products. Configured in the **Configuration app**; it is **not** your transactional database. |

## P

| Term | Meaning |
|---|---|
| **Precise** | See **Agent Mode**. The most rigorous, reproducible engine — extracts a plan, ranks Data Products deterministically, picks optimal joins, and validates scope. Best for audit and compliance, or when you need to explain exactly why a table or join was chosen. |
| **Publish** | Promoting authored changes so the chat can see them. Publishing is **gated dev → prod**: you publish to **dev** first, and **prod** becomes available only once dev is current. You can publish a single Data Product from its detail panel or a whole business domain at once. Nothing is queryable until it is published. |

## R

| Term | Meaning |
|---|---|
| **Reference** | An `entity_role` for lookup or configuration data (source **classification** `C` always maps to reference). There is no separate "configuration" entity role — configuration data surfaces as reference. |
| **Relationship (join)** | A cross-entity edge the agent may traverse to build a JOIN. Each relationship names a target entity, a relationship type (one-to-one / one-to-many / …), a full SQL join condition, a business label, a traversal cost, and an aggregation-safety hint. Relationships live on **Silver** (Silver → Silver, required so the fallback plane works) and on **Gold** (Gold → Silver / Gold → Gold, for enrichment, drill-down, and lineage); a Silver never points to a Gold. |
| **Released** | The lifecycle status of a Data Product that has been published to an environment (as opposed to **In Review**). |

## S

| Term | Meaning |
|---|---|
| **Semantic Dictionary** | Pre-agreed business terms — canonical labels, synonyms, and phrase mappings — maintained per SAP module in the **Configuration app**. It sharpens how the agent maps a user's words to your columns and helps disambiguation. In the demo, *Confirmed Yield* maps to `AFRU.LMNGA` with synonyms *good quantity, good output, yield*. |
| **Semantic layer** | The whole curated model the agent maps questions to — workspaces, business domains, and the Bronze/Silver/Gold Data Products with their fields, relationships, and descriptions. Because the agent can only use what the semantic layer defines, answers are governed and reproducible. |
| **Silver** | A layer for a **curated business entity that owns the join topology** — the single source of truth for how its underlying tables connect (`composed_of` + `join_graph` + `relationships`). In the demo, `production_order` (AFKO + AFPO + AUFK + AFRU) is Silver. See [Add Data Products](../ask-admin/02-add-data-products.md). |
| **Slug** | The URL- and API-safe identifier for a workspace or domain (lowercase letters, digits, hyphens), auto-derived from the name — e.g. `manufacturing-operations`. It identifies the object, so it must be unique. |
| **Smart** | See **Agent Mode**. The balanced default engine — catalog-as-context, natural Data Product selection, graph-resolved joins. Best for everyday, high-volume use. |
| **Source system** | The system your data originates from (e.g. `s4h` for SAP S/4HANA). Set on the **Organization profile** and per Data Product; it tunes the AI mapping in DDL + AI and OneConnect modes. |
| **Status flag** | A `field_role` for a field whose value space is a small closed set of business states (typically 2–5, e.g. `X = blocked, blank = not blocked`). The agent treats it as **filter-only** — never aggregates it or groups by it. |
| **Synonyms** | Alternative words for a field or term that boost retrieval and disambiguation — e.g. *good quantity, good output, yield* for confirmed yield. Added by hand or suggested during **Enrichment**. |

## T

| Term | Meaning |
|---|---|
| **Timestamp** | A `field_role` for date and period fields (e.g. scheduled finish `AFKO.GLTRP`). Used to group or filter, and drives the query's time context. |
| **Traversal cost** | The weight the agent's path algorithm uses to choose among possible joins — **lower is preferred**. Direct same-module joins are cheap; a join to a dimension already flattened into a Gold is deliberately made expensive so the agent reads the column instead of joining. |

## W

| Term | Meaning |
|---|---|
| **Workspace** | The top-level container the chat scopes to; it backs a deployment (`dev` / `prod`) and holds **business domains**. In the demo, *Manufacturing Operations* is the workspace. Deleting a workspace removes its grouping but does **not** delete your entity YAMLs. See [Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md). |

---

## See also

→ **[Workspaces & Business Domains](../ask-admin/01-workspaces-domains.md)** — where Workspace,
Business Domain, and Data Product come to life.
→ **[Add Data Products](../ask-admin/02-add-data-products.md)** — Bronze / Silver / Gold and the
four creation modes.
→ **[ASK specification](../../definition/README.md)** — the authoritative rules
behind these definitions (layers, field roles, relationships, Gold), incl. the
[Bronze](../../definition/docs/BRONZE_LAYER.md) / [Silver](../../definition/docs/SILVER_LAYER.md) / [Gold](../../definition/docs/GOLD_LAYER.md) layer specs.

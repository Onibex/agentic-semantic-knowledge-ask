# Gold Layer Specification

> **Layer:** Gold • **Status:** v1 • **Part of:** [ASK — Agentic Semantic Knowledge](../README.md)

## 1. Concept

The **Gold layer** holds **Business Logic Data Products** — entities that encode a *business definition*.

Where a Silver Foundational Data Product describes "Sales Order" or "Product" in the abstract, a Gold Business Logic Data Product describes a specific business answer such as:

- *Available-to-Sell Inventory*
- *Open Sales Order Shipment Tracker*
- *Order Tracking Reception (incoming supply / outgoing demand)*
- *Days Sales Outstanding by Customer*
- *Production Confirmation Backlog*

A Gold data product is **denormalized**, **semantically resolved**, and **ready to answer business questions directly**. Status fields are already classified into business categories (`OPEN` / `CLOSE`), descriptions are already joined in, derived measures are already computed, and the grain is explicit.

Gold is the **first place an agent looks** when resolving an intent. If a Gold data product matches the question, the agent does not need to compose a Silver-level join — it can query Gold directly. Gold is what makes ASK *agent-first*.

## 2. When to create a Gold data product

Create a Gold entity when **all of the following** are true:

1. There is a **named business question** the data product answers (e.g. "what is open?", "what is on hand?", "what is overdue?"). Gold names should sound like business reports, not like database tables.
2. The answer requires **denormalization or derivation** that should not be re-implemented every time someone asks the question — for example: deriving `OPEN/CLOSE` from a raw status code, joining customer and material descriptions, or computing a delivery-time bucket.
3. The data product **will be reused** by multiple consumers (BI, agents, downstream pipelines). One-off transformations belong in a notebook, not in Gold.

Do **not** create a Gold entity if you only need to expose a Silver Foundational Data Product as-is. In that case the agent should resolve to Silver directly.

## 3. Schema

### 3.1 Top-level keys

| Key | Required | Type | Description |
|---|---|---|---|
| `id` | ✅ | string | Globally unique identifier. Convention: `gold_<system>_<module>_<name>`. Example: `gold_ecc_sd_open_order_tracker`. |
| `internal_id` | ⬜ | string | Optional internal/cataloged identifier (often equals `id`). |
| `db_table_name` | ✅ | string | Physical table or view name in the warehouse. |
| `layer` | ✅ | string | Must be the literal value `gold`. |
| `version` | ✅ | string | Spec/version of this data product. Bump on breaking change. |
| `source_system` | ✅ | string | Originating system family (e.g. `ecc`, `s4hana`, `salesforce`). |
| `source_system_no` | ⬜ | integer | Specific instance/client number of the source system (SAP MANDT, etc.). |
| `business_process` | ✅ | string | High-level process the entity supports. Use the **same vocabulary as Silver** so the two layers match: `ORDER TO CASH`, `PROCURE TO PAY`, `PLANT TO PRODUCE`, `RECORD TO REPORT`, `ORGANIZATIONAL STRUCTURE`. Unknown values are accepted and normalised, not rejected. **Do not use short codes here** (`OTC`, `P2P`, `SCM`): those are the `<domain>` segment of a Gold **id**, a different thing — using them in this field is what made Silver and Gold speak different languages. |
| `module` | ✅ | string \| string[] | One module or a list when the Gold spans modules: `["SD", "MM"]`. UPPERCASE. |
| `tag1`, `tag2` | ⬜ | string | Optional secondary categorization for catalog faceting. |
| `name` | ✅ | string | Short business name (snake_case). Drives natural-language matching. |
| `classification` | ⬜ | string | `M` = master · `T` = transactional · `C` = configuration. **Optional at Gold and purely a catalog hint** — unlike Silver, it does not derive `entity_role` here, because a Gold is authored rather than ingested and has no source-system classification to inherit. |
| `description` | ✅ | string | **The most important field for the agent.** A long, explicit narrative that explains: what business question this answers, what the grain is, what is denormalized, what is sparse, what derivations have been applied, and how it relates to other Gold entities. Write it for a human reader, then hand it to the LLM. |
| `entity_role` | ✅ | string | `fact`, `dimension`, or `reference`. **Authored at Gold** (defaults to `fact`) — you set it directly, and the server does not overwrite it. Most Gold entities are facts; `reference` is legal but unusual for a Gold. Note this differs from Silver, where the same field is *derived* from `classification`. |
| `grain` | ✅ | object | See [§3.2](#32-grain). |
| `composed_of` | ✅ | string[] | Lineage. References to the Silver Foundational Data Products and/or other Gold entities this is built from. |
| `fields` | ✅ | object[] | Field definitions. See [§3.3](#33-fields). |
| `join_graph` | ⬜ | object[] | Usually empty for Gold (Gold is already pre-joined). Reserved for special cases. |
| `relationships` | ✅ | object[] | Outbound graph edges to other entities. See [§3.4](#34-relationships). |

### 3.2 Grain

`grain` declares the unique key of the entity. **Getting the grain right is the most common point of failure for both agents and humans.**

```yaml
grain:
  entity_grain: ["client", "sales_order", "item"]
  business_grain: "sales_order_item_level"
```

| Sub-key | Required | Description |
|---|---|---|
| `entity_grain` | ✅ | Ordered list of field names whose combination uniquely identifies a row. **This is a machine-consumed contract, not descriptive metadata** — see below. |
| `business_grain` | ✅ | Plain-English label for the grain (e.g. `sales_order_item_level`, `daily_plant_material`, `customer_month`). |

**`entity_grain` is the uniqueness contract of the physical table, and the agent treats it as authoritative:** exactly **one** row per distinct combination of those fields, and **many** rows whenever a filter pins only a *subset* of them. The agent consults it before assuming the cardinality of anything it selects, and to decide when it must aggregate or de-duplicate.

Worked example — an inventory Gold declaring:

```yaml
grain:
  entity_grain: ["client", "plant_id", "material_id"]
```

A query filtering `WHERE material_id = 'TG12'` returns **one row per plant**, not one row. An agent that assumed a single row would report one plant's stock as the company-wide figure.

Two consequences for authors:

- If the declared grain does not hold physically, every downstream cardinality decision is built on a false premise. Verify it against the real table, do not infer it from intent.
- Adding a column to `entity_grain` multiplies rows. A Gold grained `[client, plant_id, material_id]` and the same Gold plus `future_date` behave differently under aggregation — see [§3.3.4](#334-additive-vs-non-additive-measures).

### 3.3 Fields

Each field is an object in the `fields` list:

```yaml
- name: "order_qty"
  source: "GOLD_SD_OPEN_ORDER_TRACKER.order_qty"
  field_role: "measure"
  type: "NUMERIC"
  description: "Quantity ordered by customer / demand quantity."
  aggregation_behavior: "SUM"
```

| Key | Required | Description |
|---|---|---|
| `name` | ✅ | Physical column name, business-friendly snake_case (e.g. `order_qty`, not `KWMENG`). |
| `source` | ✅ | Lineage: `<TABLE>.<column>`. For Gold this is usually the Gold table itself, since Gold is the published surface. |
| `field_role` | ✅ | One of: `identifier`, `dimension`, `measure`, `timestamp`, `attribute`, `status_flag`. See [§3.3.1](#331-field-roles). |
| `type` | ✅ | SQL-style type of the published column: `TEXT`, `NUMERIC`, `INTEGER`, `DATE`, `TIMESTAMP`, `BOOLEAN`. Gold is a physical table, so this describes the real column. Bronze and Silver instead use the source-agnostic *canonical* vocabulary (`STRING(n)`, `DECIMAL(p[,s])`, …) — see [Bronze Layer §4](BRONZE_LAYER.md#4-type-system). The two map 1:1 (`TEXT` ↔ `STRING`, `NUMERIC` ↔ `DECIMAL`), so nothing misreads across the boundary. |
| `description` | ✅ | Detailed business meaning. Include: the source SAP/source-system field, any derivation rules, sparsity rules, valid values, and gotchas. **The agent reads this verbatim.** |
| `aggregation_behavior` | ✅ | **Which** SQL function: `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `COUNT_DISTINCT`, or `none`. A function name, nothing more. Use `none` for identifiers, dimensions, statuses and timestamps. See [§3.3.4](#334-additive-vs-non-additive-measures). |
| `additivity` | ⬜ | **Over which dimensions** that function is valid: `additive` (default — omit the key), `semi_additive`, or `non_additive`. Measures only. See [§3.3.4](#334-additive-vs-non-additive-measures). |
| `non_additive_over` | ⬜ | Grain dimensions to collapse before aggregating. Required when `additivity: semi_additive`; must name `timestamp` fields that appear in `entity_grain`. |

#### 3.3.1 Field roles

| Role | Meaning | Aggregates? |
|---|---|---|
| `identifier` | Part of the primary/business key. | No (`aggregation_behavior: none`). |
| `dimension` | Categorical attribute used for grouping/filtering (customer, plant, channel). | No. |
| `measure` | Numeric value to aggregate (quantity, amount, value, count). | Usually (`SUM`, `AVG`, …) — but a **non-additive** measure declares `none` and must never be summed. See [§3.3.4](#334-additive-vs-non-additive-measures). |
| `timestamp` | Date or datetime field. | No, but used for `MIN`/`MAX` framing and time-grain rollups. |
| `attribute` | Free-text description or name (a material description, an order text). Filter and SELECT only — the agent must **never `GROUP BY`** one, because its cardinality is ~1:1 with the row and the aggregate would be meaningless. Contrast `dimension`: a material *description* is an `attribute`, a material *group code* is a `dimension`. | No. |
| `status_flag` | A status-like categorical the agent should recognize as life-cycle state (`OPEN`, `CLOSE`, `BLOCKED`, `A`/`B`/`C` codes). **Groupable** — "orders by status" is a normal question — but never arithmetically aggregated. Reserve it for a small closed set of business *states*; a code from a larger taxonomy is a `dimension`. | No. |

#### 3.3.2 Sparse measures pattern

Gold facts that union multiple operation types (e.g. an order-tracking-reception entity that mixes Production Orders, Purchase Orders, Stock Orders, and Sales Orders) often carry **sparse measures** — one column per operation type, where only one is populated per row.

When using sparse measures, **always state the sparsity rule in the field's `description`**:

```yaml
- name: "qty_purchase_order"
  field_role: "measure"
  type: "NUMERIC"
  description: "Purchase-order quantity (EKPO.MENGE where PSTYP<>'7'). Procurement
    supply / incoming from supplier. SPARSE: populated only on rows where
    operation = 'Purchase Order', 0 elsewhere."
  aggregation_behavior: "SUM"
```

The agent uses this hint to know that filtering by `operation` is a precondition for non-zero results.

#### 3.3.3 Derived field documentation

When a Gold field is *derived* from a raw source field, the description must say so explicitly:

```yaml
- name: "order_status"
  field_role: "status_flag"
  type: "TEXT"
  description: "Derived OPEN/CLOSE classification from ovrll_sts (VBUK.GBSTK).
    Rule: 'C' (fully processed) -> 'CLOSE', anything else (A=open, B=partial,
    NULL) -> 'OPEN'. Use this for a clean binary 'is the order still active?'
    filter. For partial-vs-fully-open distinction use ovrll_sts instead."
  aggregation_behavior: "none"
```

This pattern saves the agent from re-deriving the rule from the raw status code, and explicitly tells it which field to choose for which question.

#### 3.3.4 Additive vs non-additive measures

Not every measure can be summed. A measure that is **already cumulative**, that carries a **projected balance**, or whose value is **repeated across the grain** produces a wrong answer under `SUM` — and the query still runs, so nothing warns you.

Consider a forward-looking inventory Gold with grain `[client, plant_id, material_id, future_date]`:

| client | plant_id | material_id | future_date | on_hand | cumulative_sales_order | future_stock |
|---|---|---|---|---|---|---|
| 100 | 1000 | TG12 | 2026-08-05 | 500 | 20 | 480 |
| 100 | 1000 | TG12 | 2026-08-12 | 500 | 50 | 450 |
| 100 | 1000 | TG12 | 2026-08-20 | 500 | 90 | 410 |

All three right-hand columns are `field_role: measure`. Summing any of them **across dates** is wrong, each for a different reason:

| Column | `SUM` returns | Correct answer | Why |
|---|---|---|---|
| `on_hand` | 1500 | 500 | Physical stock denormalized onto every dated row — a repeated constant. |
| `cumulative_sales_order` | 160 | 90 | A running total; the last row already contains the total. |
| `future_stock` | 1340 | 410 | A per-date projected balance; you want the balance *at* a date. |

But "never sum" is the wrong conclusion, and this is the part that matters. Add a second plant and ask *"what is the total projected stock of TG12 across all plants on 2026-08-20?"* — that is a perfectly ordinary question, and the answer **is** a sum. These measures are additive across `plant_id`; they are only non-additive across `future_date`.

That is what the two keys express:

```yaml
- name: "cumulative_sales_order"
  field_role: "measure"
  type: "NUMERIC"
  description: "Cumulative outbound demand from Sales Orders. Already cumulative —
    do NOT SUM across future_date; take the last value per (plant, material) up to
    the target date, after which it SUMS correctly across plants."
  aggregation_behavior: "SUM"        # WHICH function
  additivity: "semi_additive"        # over WHICH dimensions it is valid
  non_additive_over: ["future_date"] # collapse these first
```

Read it as: *collapse `future_date` to one row per grain group — the latest at or before the target date — and only then apply `SUM` across everything else.*

The three values of `additivity`:

| Value | Meaning |
|---|---|
| omitted | **Additive.** The function is valid across any grouping. This is the default; do not write it out. |
| `semi_additive` | Valid only after collapsing the dimensions in `non_additive_over`. Those must be `timestamp` fields that appear in `entity_grain`. |
| `non_additive` | Never aggregate arithmetically — a ratio, a score, an index. Pair it with `aggregation_behavior: none`. |

> **Sizing note.** Grain drives all of this. The same `on_hand` column is a plain additive `SUM` in a Gold grained `[client, plant_id, material_id]` — where each row is already one plant — and semi-additive in a Gold that adds `future_date`. Decide additivity against *your* grain, never against the column name.

**A note on older YAMLs.** Before `additivity` existed, a non-additive measure was written as `aggregation_behavior: none` and nothing else. That shape is still read correctly — as `non_additive` — so existing catalogs keep working. It is less precise than the truth (most such measures are semi-additive), so restate them when you next touch them. Tooling must never treat an explicit `none` as an empty value to be dropped: an *absent* `aggregation_behavior` means "assume additive", which is the opposite instruction.

### 3.4 Relationships

`relationships` is the **graph layer** of ASK. It defines outbound edges from this Gold entity to other entities (Silver or Gold). The agent's planner uses these edges to enrich queries with cross-entity context.

```yaml
relationships:
  - target_entity: "silver_ecc_sd_customer_master"
    relationship_type: "many_to_one"
    join_condition: "GOLD_SD_OPEN_ORDER_TRACKER.customer_id = SILVER_SD_CUSTOMER_MASTER.kunnr_kna1"
    semantic_label: "ordered_by"
    traversal_cost: 1
    aggregation_safety: "safe"
    cross_module: false
    description: "Customer who placed the sales order."
```

| Key | Required | Description |
|---|---|---|
| `target_entity` | ✅ | The `id` of the entity this relationship points to. Must resolve in the catalog. |
| `relationship_type` | ✅ | `one_to_one`, `many_to_one`, `one_to_many`, or `many_to_many`. |
| `join_condition` | ✅ | SQL-style join predicate. Use fully-qualified column names. Multi-key joins use `AND`. |
| `semantic_label` | ✅ | Human-readable label for the edge. Use **active business verbs**: `ordered_by`, `fulfilled_from`, `material_of`, `covered_by_current_stock`. |
| `traversal_cost` | ✅ | Numeric heuristic, lower = cheaper. The planner uses it to choose between alternative paths. Suggested scale: `1` (single-key dimensional join), `2` (multi-key or bigger table), `3` (cross-fact lookup or many-to-many). |
| `aggregation_safety` | ✅ | `safe` (join does not multiply rows), `requires_dedup` (the join fans out — `one_to_many`, `many_to_many`, partner tables), or `unsafe` (the join structurally breaks aggregation; the planner should reject the path unless explicitly overridden — *declared intent, not yet enforced*). See [§5.6](#56-mark-requires_dedup-whenever-there-is-fan-out) for what `requires_dedup` obliges. |
| `cross_module` | ✅ | Boolean. `true` if the join crosses business modules (SD ↔ MM, P2P ↔ SCM). The planner can charge a small cost premium or surface the cross-module nature in explanations. |
| `description` | ✅ | What this join means in business terms. |

#### 3.4.1 Cross-fact relationships

Gold-to-Gold relationships ("cross-fact lookups") are valid and useful — for example, enriching an open-order-tracker fact with a current-inventory-position fact:

```yaml
- target_entity: "gold_ecc_mm_inventory_position"
  relationship_type: "many_to_one"
  join_condition: "GOLD_SD_OPEN_ORDER_TRACKER.client = GOLD_MM_INVENTORY_POSITION.client
                   AND GOLD_SD_OPEN_ORDER_TRACKER.plant_id = GOLD_MM_INVENTORY_POSITION.plant_id
                   AND GOLD_SD_OPEN_ORDER_TRACKER.material_id = GOLD_MM_INVENTORY_POSITION.material_id"
  semantic_label: "covered_by_current_stock"
  traversal_cost: 3
  aggregation_safety: "safe"
  cross_module: true
  description: "Cross-fact lookup: enrich each open sales order line with the
    current stock position. Use to assess ATP/coverage."
```

When two Gold entities share a natural key (e.g. `(client, plant, material)`), expose the relationship explicitly so the agent can answer questions like *"which open orders are covered by current stock?"* without inferring the join itself.

## 4. Naming conventions

| Item | Convention | Example |
|---|---|---|
| `id` | `gold_<system>_<module>_<name>` | `gold_ecc_sd_open_order_tracker` |
| `db_table_name` | `GOLD_<MODULE>_<NAME>` (UPPER_SNAKE) | `GOLD_SD_OPEN_ORDER_TRACKER` |
| `name` | Short business label, snake_case | `open_order_tracker` |
| Field `name` | Business-friendly snake_case, no SAP code | `customer_id`, `order_qty`, `delivery_date` |
| `semantic_label` | Active verb phrase | `ordered_by`, `fulfilled_from`, `material_of` |

Avoid leaking source-system column names (`KUNNR`, `MATNR`, `WERKS`) into Gold field names. The whole point of Gold is to expose a business vocabulary.

## 5. Best practices

### 5.1 Write the description like a runbook

The agent has nothing to go on except `description`. Treat each description as a mini-runbook: what is this, what is the grain, what is denormalized, what is derived, what is sparse, what are the gotchas.

### 5.2 Pre-derive status fields

Do not force the agent to learn that `GBSTK='C'` means closed, that `LPRIO=1` means top urgency, or that `PSTYP='7'` means stock transfer. Pre-derive a clean `OPEN/CLOSE`, a clean `priority_label`, a clean `operation` discriminator — and document the rule in the field description.

### 5.3 Pre-join master-data descriptions

Every Gold fact should carry the **descriptions** of its dimensional keys (customer name, plant name, material description) denormalized in. The agent should not need to traverse a relationship just to print "Customer ABC Corp" next to a customer ID.

### 5.4 Be explicit about sparse measures

If a fact unions multiple operation types into sparse columns, every measure description must state which `operation` value it activates on.

### 5.5 Score traversal_cost honestly

Traversal cost is a planner heuristic. A 1.0 single-column join to a small dimension is cheap. A 3.0 cross-fact join with a multi-key composite predicate is expensive. Calibrate within your catalog so the planner can choose the cheapest path.

### 5.6 Mark `requires_dedup` whenever there is fan-out

Many-to-many or one-to-many joins that can multiply rows must be flagged
`aggregation_safety: requires_dedup`.

**What it obliges.** Traversing the edge multiplies rows on the base side, so a measure of the
base must be reduced to **one row per its `entity_grain` before the join** — aggregate it in a
CTE, or `DISTINCT` on its grain key. It is a statement about row multiplication, not about
duplicate values.

> **It is not "insert `SELECT DISTINCT`".** A bare `DISTINCT` over the output projection is
> wrong in both directions: it fails to dedup when the projection carries the drill-down column
> the question asked for, and it *over*-deduplicates when it does not, collapsing rows that are
> legitimately identical. On a 1:N grain-change join whose true answer is 1000, the same bare
> `DISTINCT` returns 2000 in the first case and 500 in the second. It is right only when the
> projection happens to equal the grain — exactly the case that needed no dedup at all.

This reaches the agent as a generation rule alongside the edge cardinality, and the generated
SQL is audited rather than rewritten. In practice `requires_dedup` tracks the cardinality
one-for-one, so the default follows from `relationship_type`; set it explicitly only to
*override* that default.

### 5.7 Keep `composed_of` accurate for lineage

`composed_of` is the contract between the Gold YAML and the upstream Silver world. When you change which Silver products feed a Gold, update `composed_of` — the agent uses this to walk lineage when it cannot answer from Gold alone.

## 6. Reference example

See [`examples/gold/gold_ecc_sd_open_order_tracker.yml`](../examples/gold/gold_ecc_sd_open_order_tracker.yml) and [`examples/gold/gold_ecc_order_tracking_reception.yml`](../examples/gold/gold_ecc_order_tracking_reception.yml) for complete, production-style Gold definitions.

## 7. Validation checklist

Before publishing a Gold YAML to the catalog, verify:

- [ ] `id`, `db_table_name`, `layer`, `version` are present and consistent.
- [ ] `description` explains the business question, the grain, the sparsity, and the derivations.
- [ ] `grain.entity_grain` matches the actual unique-key of the table.
- [ ] Every field has `name`, `field_role`, `type`, `description`, `aggregation_behavior`.
- [ ] Every measure declares **which** function aggregates it (`aggregation_behavior`) and, when the function is not valid across every grain dimension, **over which** dimensions it is not (`additivity` + `non_additive_over`). Running totals, projected balances and values repeated across the grain are `semi_additive`, not additive. See [§3.3.4](#334-additive-vs-non-additive-measures).
- [ ] Every `non_additive_over` entry is a `timestamp` field that appears in `grain.entity_grain`.
- [ ] Every status field documents its rule.
- [ ] Every sparse measure documents its sparsity condition.
- [ ] Every relationship has `traversal_cost` and `aggregation_safety` set.
- [ ] `composed_of` references resolve in the catalog.
- [ ] No SAP/source-system column codes leak into Gold field names.

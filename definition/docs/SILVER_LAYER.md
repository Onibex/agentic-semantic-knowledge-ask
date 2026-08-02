# Silver Layer Specification

> **Layer:** Silver • **Status:** v1 • **Part of:** [ASK — Agentic Semantic Knowledge](../README.md)

## 1. Concept

The **Silver layer** holds **Foundational Data Products** — entities that represent **real-world artifacts** in the enterprise. They are the digital twins of the business objects you would talk about in a meeting:

- **Sales Order**, **Purchase Order**, **Production Order**
- **Customer**, **Supplier**, **Employee**
- **Product / Trading Goods**, **Plant**, **Material Group**
- **General Ledger Account**, **Cost Center**, **Profit Center**

A Silver Foundational Data Product is **already coherent** — it knows that a Sales Order has a Header, Items, Schedule Lines, Partners, Document Flow, and Status; and it presents them as **one queryable entity** with a clearly stated grain. But it is **not yet semantically resolved** the way Gold is — Silver is still close to the source system, still uses source-system codes, and still requires the agent (or a Gold layer above it) to interpret what those codes mean.

Silver is the **fallback layer** for agent intent resolution. When no Gold Business Logic Data Product matches the question, the agent falls back to Silver and composes the answer from one or more Foundational Data Products.

### Multiple variants per concept

A single enterprise often needs **multiple variants** of the same Foundational Data Product. This is intentional and central to a composable AI Data Strategy:

- A multi-LOB company may publish `silver_lob_a_trading_goods` *and* `silver_lob_b_trading_goods`, each with the attributes that line of business cares about.
- A multi-region enterprise may publish `silver_emea_sales_order` *and* `silver_americas_sales_order`, each scoped to its sales-org filter and currency.
- A company on both ECC and S/4 may publish `silver_ecc_sales_order` *and* `silver_s4_sales_order` while migrating.

The data practitioner's job is to choose the right variant granularity. ASK gives you the structural language; the topology of Silver is a business decision.

## 2. The multi-node model

A Silver Foundational Data Product is composed of one or more **Bronze nodes** (raw tables) joined into a coherent business entity.

For example, a `Sales Order` Foundational Data Product is composed of:

| Bronze node | Role |
|---|---|
| `VBAK` (Order Header) | One row per sales document |
| `VBAP` (Order Items) | Many rows per sales document |
| `VBKD` (Business Data) | Header- and item-level commercial data |
| `VBPA` (Partners) | Sold-to, Ship-to, Bill-to, Payer per item |
| `VBFA` (Document Flow) | Predecessor/successor links across documents |
| `VBUK` (Status) | Overall processing status |

The Silver YAML describes **how those Bronze nodes join** (the `join_graph`) and **which fields of the union are exposed**. The grain of the Silver entity is the natural grain of the joined result — for `Sales Order`, that is one row per `(VBELN, POSNR)` (sales order item).

## 3. Schema

### 3.1 Top-level keys

| Key | Required | Type | Description |
|---|---|---|---|
| `id` | ✅ | string | Globally unique identifier. Convention: `silver_<system>_<module>_<name>`. Example: `silver_ecc_sd_sales_order`. |
| `internal_id` | ⬜ | string | Internal/cataloged identifier. Often follows a numbering pattern like `<system>_<sysno>_<seq>`. |
| `db_table_name` | ✅ | string | Physical table or view name in the warehouse. |
| `layer` | ✅ | string | Must be the literal value `silver`. |
| `version` | ✅ | string | Spec/version of this data product. |
| `source_system` | ✅ | string | Originating system family (e.g. `ecc`, `s4hana`, `salesforce`). |
| `source_system_no` | ⬜ | integer | Specific instance/client number of the source system. |
| `business_process` | ✅ | string | Process this artifact participates in. Recommended vocabulary — unknown values are **accepted and normalised** (trimmed, upper-cased), not rejected: `ORDER TO CASH`, `PROCURE TO PAY`, `PLANT TO PRODUCE`, `RECORD TO REPORT`, `ORGANIZATIONAL STRUCTURE`. `ORGANIZATIONAL STRUCTURE` is a legitimate value, not a gap: it marks a **generic, cross-module** artifact belonging to no single process (a plant, a sales office, an org unit). Do not put a module code here, and do not use short codes like `OTC` / `SCM` — those belong to the `<domain>` segment of a Gold **id**, not to this field. |
| `module` | ✅ | string \| string[] | The source-system module that **owns** this artifact (`SD`, `MM`, `FI`, …). UPPERCASE here; the `id` carries the same token in lowercase. A Silver has one module; an artifact used by several processes is published once per process. A list is meaningful mainly at Gold. |
| `name` | ✅ | string | Short business name, snake_case (e.g. `sales_order`, `trading_goods`). |
| `classification` | ✅ | string | `M` = master · `T` = transactional · `C` = configuration. **Required at Silver** — it derives `entity_role` (see below). |
| `description` | ✅ | string | Narrative business description. State **what artifact this represents**, **what nodes compose it**, **what the grain is**, and **typical use cases**. |
| `entity_role` | ✅ | string | `fact`, `dimension`, or `reference`. **Derived, not authored**: the server recomputes it from `classification` on every save, so a hand-written value is overwritten. The rule is `C` → `reference`; `M` → `dimension` (or `reference` when every composed table is a customizing table); `T` → `fact` when the artifact has a currency/quantity measure or is item-level, else `dimension`. To change the role, change `classification`. |
| `grain` | ✅ | object | See [§3.2](#32-grain). |
| `composed_of` | ✅ | string[] | Lineage: the Bronze node `id`s that make up this Silver entity. |
| `join_graph` | ✅ | object[] | How the Bronze nodes are joined. See [§3.3](#33-join_graph). |
| `fields` | ✅ | object[] | Field definitions. See [§3.4](#34-fields). |
| `relationships` | ⬜ | object[] | Outbound graph edges to other entities (typically other Silver). See [§3.5](#35-relationships). |

### 3.2 Grain

Silver entities have **complex grains** more often than Gold does, because they preserve the structure of the source system.

```yaml
grain:
  entity_grain:
    - VBELN     # Sales Document
    - POSNR     # Item
    - VBELV     # Predecessor doc (from VBFA)
    - POSNV     # Predecessor item
    - POSNN     # Successor item
    - VBTYP_N   # Successor doc category
    - PARVW     # Partner Function (from VBPA)
  business_grain: sales_order_item
```

| Sub-key | Required | Description |
|---|---|---|
| `entity_grain` | ✅ | Ordered list of source-system field codes whose combination uniquely identifies a row. |
| `business_grain` | ✅ | Plain-English description of the grain (`sales_order_item`, `customer_address`, `material_master`). |

When a Silver entity unions multiple cardinalities (header + items + partners + flow), the grain is the **finest** of them — the cross-product of all keys. This is acceptable, and the grain declaration must reflect it.

### 3.3 `join_graph`

`join_graph` declares how the Bronze nodes are joined together to form this Silver entity.

```yaml
join_graph:
  - left_table: VBAK
    right_table: VBAP
    join_type: INNER
    condition: VBAK.VBELN = VBAP.VBELN
    sequence: 2
  - left_table: VBAK
    right_table: VBPA
    join_type: LEFT OUTER
    condition: VBAK.VBELN = VBPA.VBELN
    sequence: 3
  - left_table: VBAK
    right_table: VBKD
    join_type: LEFT OUTER
    condition: VBAK.VBELN = VBKD.VBELN
    sequence: 5
```

| Key | Required | Description |
|---|---|---|
| `left_table` | ✅ | Bronze node name on the left side of the join (typically the anchor / fact table). |
| `right_table` | ✅ | Bronze node name being added. |
| `join_type` | ✅ | `INNER`, `LEFT OUTER`, `RIGHT OUTER`, `CROSS`. `FULL OUTER` is **not** supported — do not use it; the validator rejects it. |
| `condition` | ✅ | SQL-style join predicate. Multi-key joins use `AND`. |
| `sequence` | ✅ | Numeric order in which joins are applied. Lower values are joined first. Use to communicate intent to consumers; the actual execution plan is the engine's call. |

The `join_graph` is **descriptive**, not prescriptive. It tells the agent (and any downstream pipeline) how the Silver entity is *conceptually* assembled. The actual physical implementation may be a denormalized table, a view, or a virtualized Cube/dbt model.

### 3.4 Fields

Each field is an object in the `fields` list. Silver field definitions are **closer to the source system** than Gold:

```yaml
- name: vbeln_vbak
  source: VBAK.VBELN
  field_role: identifier
  type: C10
  description: Sales document
- name: gbstk_vbuk
  source: VBUK.GBSTK
  field_role: status_flag
  type: C1
  description: "Overall Processing Status of sales order. A = not yet processed
    / open, B = partially processed, C = fully processed / completed."
```

| Key | Required | Description |
|---|---|---|
| `name` | ✅ | Physical column name. Convention: `<source_alias>_<table>` (e.g. `vbeln_vbak`, `matnr_mara`) — preserves source lineage and disambiguates same-named columns from different Bronze nodes. |
| `source` | ✅ | Lineage: `<TABLE>.<column>` referencing the Bronze node. |
| `field_role` | ✅ | `identifier`, `dimension`, `measure`, `timestamp`, `attribute`, or `status_flag`. **`attribute`** is for free-text descriptions or names (a material description, an order text): the agent may filter on it and SELECT it, but never `GROUP BY` it — contrast **`dimension`**, which is a code from a closed set and *is* groupable. A material *description* is an `attribute`; a material *group code* is a `dimension`. **`status_flag`** is a small closed set of business states (open/partial/closed) — groupable, but never arithmetically aggregated. |
| `type` | ✅ | Canonical type: `STRING(n)`, `INTEGER`, `DECIMAL(p[,s])`, `DATE`, `TIMESTAMP`, `BOOLEAN`. The same vocabulary at every layer — source-system codes such as `C10` or `P15` are not used here. (See [Bronze Layer §4](BRONZE_LAYER.md#4-type-system) for the vocabulary and the source mapping.) Silvers published before this rule may still carry source codes; both parse to the same type, but they are not canonical until regenerated. |
| `description` | ✅ | Business meaning. For status fields, **enumerate the codes** and what they mean. |
| `aggregation_behavior` | ⬜ | Optional at Silver. When set, follows the same rules as Gold: a function name only. See [Gold Layer §3.3.4](GOLD_LAYER.md#334-additive-vs-non-additive-measures). |
| `additivity` / `non_additive_over` | ⬜ | Also as at Gold — the dimensions a measure may *not* be aggregated across. Rarely needed at Silver, whose grain is usually the document/item level rather than a time series. |

#### 3.4.1 Naming convention: `<column>_<table>`

The standard Silver field name pattern is `<source_column_alias>_<source_table>`:

| Bronze field | Silver field name |
|---|---|
| `VBAK.VBELN` | `vbeln_vbak` |
| `VBAP.MATNR` | `matnr_vbap` |
| `MARA.MATNR` | `matnr_mara` |
| `VBUK.GBSTK` | `gbstk_vbuk` |

This convention keeps lineage visible in the column name and avoids collisions when multiple Bronze nodes carry the same logical field (e.g. `MATNR` appears in both `VBAP` and `MARA`).

#### 3.4.2 Document status fields

Silver status fields preserve the **raw source-system codes**. The Silver description must enumerate the codes; the *interpretation* (e.g. mapping to `OPEN/CLOSE`) belongs in Gold.

```yaml
- name: gbstk_vbuk
  source: VBUK.GBSTK
  field_role: status_flag
  type: C1
  description: "Overall Processing Status. A = not yet processed / open,
    B = partially processed, C = fully processed / completed.
    Use to filter open or pending sales orders."
```

The Gold layer that consumes this Silver should derive a clean `order_status` (`OPEN`/`CLOSE`) field and document the rule there.

### 3.5 Relationships

Silver entities can declare relationships to other Silver entities. These describe the **enterprise data graph** that Silver Foundational Data Products participate in.

```yaml
relationships:
  - target_entity: "silver_ecc_sd_trading_goods"
    relationship_type: "many_to_one"
    join_condition: "SILVER_ECC_SD_SALES_ORDER.matnr_vbap = SILVER_TRADING_GOODS.matnr_mara"
    semantic_label: "material_of"
    traversal_cost: 2
    aggregation_safety: "safe"
    cross_module: true
    description: "Join to Material Master for material attributes."

  - target_entity: "silver_ecc_sd_customer_master"
    relationship_type: "many_to_one"
    join_condition: "SILVER_ECC_SD_SALES_ORDER.kunnr_vbak = SILVER_SD_CUSTOMER_MASTER.kunnr_kna1"
    semantic_label: "sold_to_customer"
    traversal_cost: 1
    aggregation_safety: "safe"
    cross_module: false
    description: "Customer / sold-to party detail."

  - target_entity: "silver_ecc_mm_inv_mov_stock"
    relationship_type: "many_to_many"
    join_condition: "SILVER_SD_SALES_ORDER.matnr_vbap = SILVER_MM_INVENTORY_MOVEMENT.matnr_marc
                     AND SILVER_SD_SALES_ORDER.werks_vbap = SILVER_MM_INVENTORY_MOVEMENT.werks_marc"
    semantic_label: "demands_stock_from"
    traversal_cost: 3
    aggregation_safety: "requires_dedup"
    cross_module: true
    description: "Links sales order demand to inventory stock position by
      material and plant. Enables demand-vs-supply coverage analysis."
```

The relationship schema is identical to the Gold layer's — see [Gold Layer §3.4](GOLD_LAYER.md#34-relationships).

## 4. Naming conventions

| Item | Convention | Example |
|---|---|---|
| `id` | `silver_<system>_<module>_<name>` | `silver_ecc_sd_sales_order` |
| `db_table_name` | `SILVER_<MODULE>_<NAME>` | `SILVER_SD_SALES_ORDER` |
| `name` | snake_case business label | `sales_order`, `trading_goods` |
| Field `name` | `<column_alias>_<table>` | `vbeln_vbak`, `matnr_mara`, `gbstk_vbuk` |

## 5. Best practices

### 5.1 Pick the right grain *and document it*

Silver grains are easy to get wrong because of fan-out from optional joins (partners, document flow, schedule lines). Always declare the grain explicitly and choose `INNER` vs. `LEFT OUTER` deliberately.

### 5.2 Use `LEFT OUTER` for optional context

Header is mandatory. Items are mandatory. Partners, document flow, and business data are usually *optional* enrichments — joining them with `LEFT OUTER` preserves rows even when the optional context is absent.

### 5.3 Preserve source-system codes; do not interpret

Silver should preserve `GBSTK='A'/'B'/'C'`, `LPRIO=1..99`, `PSTYP='7'`, etc. as-is. Document what the codes mean. Leave the *interpretation* (`OPEN/CLOSE`, `urgent/normal`, `purchase/stock_transfer`) to Gold.

### 5.4 Keep Foundational Data Products reusable

A Silver Foundational Data Product should answer the question *"what does this artifact look like?"* — not *"what is the answer to this specific business question?"* If you find yourself encoding a business definition into Silver, lift it to a Gold Business Logic Data Product instead.

### 5.5 Variants are a feature, not duplication

If two business contexts genuinely need different versions of the "same" entity, publish two Silver Foundational Data Products. Do not contort one variant to fit both contexts. The catalog can hold many variants; the agent picks the right one based on intent and scope.

### 5.6 Declare relationships generously

Every meaningful join the data team would naturally write should be declared as a relationship. The agent uses `relationships` to discover navigable paths — undeclared joins are invisible to the planner.

### 5.7 Use `requires_dedup` for many-to-many fan-out

Joins like `sales_order ↔ inventory_movement` over `(matnr, werks)` are **many-to-many** and **fan out**. Mark them `aggregation_safety: requires_dedup` and prefer routing through a Gold cross-fact summary when possible.

## 6. Reference examples

- [`examples/silver/sales_order.yaml`](../examples/silver/sales_order.yaml) — multi-node fact entity (VBAK + VBAP + VBKD + VBPA + VBFA + VBUK).
- [`examples/silver/trading_goods.yaml`](../examples/silver/trading_goods.yaml) — multi-node dimensional entity (MARA + MAKT + MARM + MSTA + MVKE).

## 7. Validation checklist

Before publishing a Silver YAML to the catalog, verify:

- [ ] `id`, `db_table_name`, `layer`, `version` are present and consistent.
- [ ] `description` describes the artifact, the composing nodes, and typical use cases.
- [ ] `composed_of` lists every Bronze node referenced anywhere in `fields` or `join_graph`.
- [ ] `join_graph` covers every node beyond the anchor table.
- [ ] `grain.entity_grain` reflects the actual finest cardinality of the joined result.
- [ ] Every field follows the `<column_alias>_<table>` naming pattern.
- [ ] Status field descriptions enumerate every valid code.
- [ ] Relationships have `traversal_cost` and `aggregation_safety` set; many-to-many edges are marked `requires_dedup`.
- [ ] Field types match the Bronze source types.

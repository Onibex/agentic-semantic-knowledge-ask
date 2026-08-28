# Silver Layer Specification

> **Layer:** Silver • **Status:** v1 • **Part of:** [ASK. Agentic Semantic Knowledge](../README.md)

## 1. Concept

The **Silver layer** holds **Foundational Data Products**, entities that represent **real-world artifacts** in the enterprise. They are the digital twins of the business objects you would talk about in a meeting:

- **Sales Order**, **Purchase Order**, **Production Order**
- **Customer**, **Supplier**, **Employee**
- **Product / Trading Goods**, **Plant**, **Material Group**
- **General Ledger Account**, **Cost Center**, **Profit Center**

A Silver Foundational Data Product is **already coherent**. It knows that a Sales Order has a Header, Items, Schedule Lines, Partners, Document Flow, and Status; and it presents them as **one queryable entity** with a clearly stated grain. But it is **not yet semantically resolved** the way Gold is. Silver is still close to the source system, still uses source-system codes, and still requires the agent (or a Gold layer above it) to interpret what those codes mean.

Silver is the **fallback layer** for agent intent resolution. When no Gold Business Logic Data Product matches the question, the agent falls back to Silver and composes the answer from one or more Foundational Data Products.

### Multiple variants per concept

A single enterprise often needs **multiple variants** of the same Foundational Data Product. This is intentional and central to a composable AI Data Strategy:

- A multi-LOB company may publish `silver_lob_a_trading_goods` *and* `silver_lob_b_trading_goods`, each with the attributes that line of business cares about.
- A multi-region enterprise may publish `silver_emea_sales_order` *and* `silver_americas_sales_order`, each scoped to its sales-org filter and currency.
- A company on both ECC and S/4 may publish `silver_ecc_sales_order` *and* `silver_s4h_sales_order` while migrating.

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

The Silver YAML describes **how those Bronze nodes join** (the `join_graph`) and **which fields of the union are exposed**. The grain of the Silver entity is the natural grain of the joined result: for `Sales Order`, that is one row per `(VBELN, POSNR)` (sales order item).

## 3. Schema

### 3.1 Top-level keys

| Key | Required | Type | Description |
|---|---|---|---|
| `id` | ✅ | string | Globally unique identifier. Convention: `silver_<system>_<module>_<name>`. Example: `silver_s4h_sd_sales_order`. **The filename is the entity `name`** (`sales_order.yaml`). |
| `internal_id` | ✅ | string | Internal/cataloged identifier. Often follows a numbering pattern like `<system>_<sysno>_<seq>`. |
| `db_table_name` | ⬜ | string | Physical table or view name in the warehouse. **Defaults to `id`** when omitted or empty. |
| `layer` | ✅ | string | Must be the literal value `silver`. |
| `version` | ✅ | string | Spec/version of this data product. |
| `source_system` | ✅ | string | Originating system family. Registered tokens: `s4h`, `ecc`, `generic`, `salesforce`, `odoo`. See [BRONZE_LAYER.md §3.1](./BRONZE_LAYER.md#31-top-level-keys) for the authoritative list. Use **`s4h`** for SAP S/4HANA, never `s4hana`: the token is the `<system>` segment of the `id`, so a variant spelling produces ids that do not match the rest of the catalog. |
| `source_system_no` | ✅ | integer | Specific instance/client number of the source system. |
| `business_process` | ✅ | string | Process this artifact participates in. Recommended vocabulary: unknown values are **accepted and normalised** (trimmed, upper-cased), not rejected: `ORDER TO CASH`, `PROCURE TO PAY`, `PLANT TO PRODUCE`, `RECORD TO REPORT`, `ORGANIZATIONAL STRUCTURE`. `ORGANIZATIONAL STRUCTURE` is a legitimate value, not a gap: it marks a **generic, cross-module** artifact belonging to no single process (a plant, a sales office, an org unit). Do not put a module code here, and do not use short codes like `OTC` / `SCM`. Those belong to the `<domain>` segment of a Gold **id**, not to this field. |
| `module` | ✅ | string \| string[] | The source-system module that **owns** this artifact (`SD`, `MM`, `FI`, …). UPPERCASE here; the `id` carries the same token in lowercase. A Silver has one module; an artifact used by several processes is published once per process. A list is meaningful mainly at Gold. |
| `name` | ✅ | string | Short business name, snake_case (e.g. `sales_order`, `trading_goods`). |
| `classification` | ✅ | string | `M` = master · `T` = transactional · `C` = configuration. **Required at Silver**. It derives `entity_role` (see below). |
| `description` | ✅ | string | Narrative business description: **what artifact this represents** and **what it is typically used for**. Do not restate the grain, the composing nodes or the field inventory: `grain`, `composed_of` and `fields[]` already carry those, and a prose copy drifts from them. See [§3.4.3](#343-what-a-description-is-for). |
| `entity_role` | ✅ | string | `fact`, `dimension`, or `reference`. **Derived, not authored**: the server recomputes it from `classification` on every save, so a hand-written value is overwritten. The rule is `C` → `reference`; `M` → `dimension` (or `reference` when every composed table is a customizing table); `T` → `fact` when the artifact has a currency/quantity measure or is item-level, else `dimension`. To change the role, change `classification`. |
| `grain` | ✅ | object | See [§3.2](#32-grain). |
| `composed_of` | ✅ | string[] | Lineage: the Bronze node `id`s that make up this Silver entity. |
| `join_graph` | ◐ | object[] | How the Bronze nodes are joined. **Required when `composed_of` names more than one node**; a single-table Silver has no `join_graph` at all. See [§3.3](#33-join_graph). |
| `fields` | ✅ | object[] | Field definitions. See [§3.4](#34-fields). |
| `relationships` | ⬜ | object[] | Outbound graph edges to other entities (typically other Silver). See [§3.5](#35-relationships). |
| `tag1` | ⬜ | string | Free catalog facet. Populated from the source export where available; a populated value is usually hand-authored. |
| `tag2` | ⬜ | string | Second catalog facet, conventionally `<MODULE>-<SUBMODULE>` (`SD-MD`, `MM-PUR`). |

Keys not listed here are **dropped on load**, not rejected: the layer models declare no `extra` policy, so an unknown key is silently discarded and never written back. A typo in a key name therefore costs you the value with no error anywhere. Check spelling against this table.

### 3.2 Grain

Silver entities have **complex grains** more often than Gold does, because they preserve the structure of the source system.

```yaml
grain:
  entity_grain:
    - vbeln_vbak      # Sales document (the anchor; VBAP/VBKD/VBPA.VBELN and VBFA.VBELV
                      #   are the same value by the join predicates — declared ONCE)
    - posnr_vbap      # Item
    - posnr_vbpa      # Partner row's item  ┐ VBPA is joined on VBELN alone,
    - parvw_vbpa      # Partner function    ┘   so it fans out by both
    - posnv_vbfa      # Predecessor item
    - vbeln_vbfa      # Successor doc — a DIFFERENT value from vbeln_vbak
    - posnn_vbfa      # Successor item
    - vbtyp_n_vbfa    # Successor doc category
    - posnr_vbkd      # Business-data row's item
  business_grain: sales_order_item
```

| Sub-key | Required | Description |
|---|---|---|
| `entity_grain` | ✅ | Ordered list of **published field names** (`fields[].name`) whose combination uniquely identifies a row. |
| `business_grain` | ✅ | Plain-English description of the grain (`sales_order_item`, `customer_address`, `material_master`). |

**Members are published column names, not source-system codes.** The grain reaches the agent as YAML text and instructs it to filter and `GROUP BY` those names, so a member that is not a selectable column of the entity does not make the contract imprecise. It makes it **unexecutable**. Silver columns are named `<column>_<table>` ([§3.4](#34-fields)), and the grain uses exactly those names. This also removes a real ambiguity: `VBELN` alone is four different columns on a four-table Silver.

**The grain must be MINIMAL, not merely unique.** The contract asserts two things at once: exactly one row per distinct combination, **and** many rows whenever a filter pins only a subset. A padded key satisfies the first and falsifies the second, so the agent concludes that pinning the real key returns many rows when it returns one. Both failure directions are silent: the YAML still looks plausible.

Two rules decide which key columns survive, and both are read off `join_graph`:

1. **A join covering the right table's ENTIRE primary key contributes nothing.** It matches at most one row, so that table multiplies nothing, a stock table joined on its full `material + plant + storage location` attaches exactly one row per movement line. This does *not* depend on which columns the join leaves FROM: reaching that table through columns that are not part of the left table's own key is the ordinary N:1 case. When a join covers only PART of the right key, it fans out, and the uncovered members are exactly what widens the grain.
2. **Columns the predicates declare equal are ONE key column.** `VBAK.VBELN = VBAP.VBELN` means both hold the same value; declaring both states one constraint twice. Keep the member from the root-most table. Collapsing by *bare column name* instead is wrong. It merges `VBAK.VBELN` (the order) with `VBFA.VBELN` (the **successor** document), two different values under one name.

When a Silver entity unions multiple cardinalities (header + items + partners + flow), the grain is the **finest** of them. Note the consequence: a loose join predicate legitimately produces a **wider** grain, and the declaration must reflect it. Tightening the predicate tightens the grain, the grain never hides a bad join.

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
| `join_type` | ✅ | `INNER`, `LEFT OUTER`, `RIGHT OUTER`, `CROSS`. `FULL OUTER` is **not** supported, do not use it; the validator rejects it. |
| `condition` | ✅ | SQL-style join predicate. Multi-key joins use `AND`: **one entry per table pair**, see below. |
| `sequence` | ✅ | Position of the table being **added**, the `right_table`, in the assembly order. Lower is earlier. See [the sequence convention](#the-sequence-convention-starts-at-2) below. |

The `join_graph` is **descriptive**, not prescriptive. It tells the agent (and any downstream pipeline) how the Silver entity is *conceptually* assembled. The actual physical implementation may be a denormalized table, a view, or a virtualized Cube/dbt model.

#### The sequence convention: starts at 2

`sequence` numbers the table each row **adds**, not the row itself. The anchor table is not added by
any row. It is where assembly starts: so it holds the implicit position **1**, and the first
authored row is `sequence: 2`. In the example above, `VBAK` is the anchor and `VBAP` is what
position 2 brings in.

Two consequences are worth stating, because both are easy to get backwards:

- **The anchor still appears as a `left_table`**, including on the lowest-numbered row. Identify the
  anchor as the table that is never a `right_table`, not as the `left_table` of `sequence: 2`. An
  entity anchored on `EKKO` whose first row reads `EKKO → EKPO, sequence: 2` is adding `EKPO`
  second, which is exactly right.
- **Sequence belongs to the table pair, not to the predicate.** Every row for one
  `(left_table, right_table)` pair carries the same sequence, which is why a composite key must be
  one `AND`-composed row rather than several rows sharing a number.

Gaps carry no meaning. An entity may run `2, 3, 4, 5` or `2, 3, 5`; renumbering to close a gap is
churn, since only the relative order is read.

#### A composite key is ONE entry

A join on several key columns is a single `join_graph` entry whose `condition` composes them with
`AND`: never one entry per key column. Each half of a split composite key is a *different, wrong*
join on its own:

```yaml
# ✗ wrong — two entries for the same pair. Either one, taken alone, fans out:
#   joining EKPO to EKET on EBELN only multiplies by every schedule line of the order.
- { left_table: EKPO, right_table: EKET, join_type: INNER, condition: EKPO.EBELN = EKET.EBELN, sequence: 3 }
- { left_table: EKPO, right_table: EKET, join_type: INNER, condition: EKPO.EBELP = EKET.EBELP, sequence: 3 }

# ✓ right — one entry, AND-composed
- left_table: EKPO
  right_table: EKET
  join_type: INNER
  condition: EKPO.EBELN = EKET.EBELN AND EKPO.EBELP = EKET.EBELP
  sequence: 3
```

This matters most when a Silver is generated from a source-system extract, since such extracts
commonly ship one row **per key column**. The generator must group them back into one edge before
writing the YAML.

Every column named in a `condition` must exist in the Bronze node on that side. A predicate that
references a column the Bronze does not declare describes a lineage that cannot be built.

### 3.4 Fields

Each field is an object in the `fields` list. Silver field definitions are **closer to the source system** than Gold:

```yaml
- name: vbeln_vbak
  source: VBAK.VBELN
  field_role: identifier
  type: STRING(10)
  description: Sales document
- name: gbstk_vbak
  source: VBAK.GBSTK
  field_role: status_flag
  type: STRING(1)
  description: "Overall Processing Status of sales order. A = not yet processed
    / open, B = partially processed, C = fully processed / completed."
```

| Key | Required | Description |
|---|---|---|
| `name` | ✅ | Physical column name. Convention: `<source_alias>_<table>` (e.g. `vbeln_vbak`, `matnr_mara`), preserves source lineage and disambiguates same-named columns from different Bronze nodes. |
| `source` | ⬜ | Lineage: `<TABLE>.<column>` referencing the Bronze node. Documentation only. It is never fabricated, so a Silver imported from a single `CREATE TABLE` simply omits it. |
| `field_role` | ✅ | `identifier`, `dimension`, `measure`, `timestamp`, `attribute`, or `status_flag`. **`attribute`** is for free-text descriptions or names (a material description, an order text): the agent may filter on it and SELECT it, but never `GROUP BY` it: contrast **`dimension`**, which is a code from a closed set and *is* groupable. A material *description* is an `attribute`; a material *group code* is a `dimension`. **`status_flag`** is a small closed set of business states (open/partial/closed): groupable, but never arithmetically aggregated. |
| `type` | ✅ | Canonical type: `STRING(n)`, `INTEGER`, `DECIMAL(p[,s])`, `DATE`, `TIMESTAMP`, `BOOLEAN`. The same vocabulary at every layer, source-system codes such as `C10` or `P15` are not used here. (See [Bronze Layer §4](BRONZE_LAYER.md#4-type-system) for the vocabulary and the source mapping.) |
| `description` | ✅ | Business meaning. For status fields, **enumerate the codes** and what they mean. A published entity should carry one on every field, but an *empty* description is better than an invented one: when the meaning of a code set is genuinely unknown, leave it blank rather than guess. See [§3.4.3](#343-what-a-description-is-for). |
| `synonyms` | ⬜ | Alternative business names for this field, to widen retrieval. Indexed for keyword search and folded into the entity's embedding, so a term users actually say (`"buyer"` for a customer id) becomes findable. Useless on a `status_flag`, leave it `[]`. |
| `aggregation_behavior` | ⬜ | Optional at Silver. When set, follows the same rules as Gold: a function name only: `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `COUNT_DISTINCT`, `none`. Absence means *not curated*, and a measure that is not curated is assumed additive. See [Gold Layer §3.3.4](GOLD_LAYER.md#334-additive-vs-non-additive-measures). |
| `additivity` / `non_additive_over` | ⬜ | Also as at Gold: the dimensions a measure may *not* be aggregated across. Allowed values are `additive`, `semi_additive`, `non_additive`. **Derived at ingest** for every measure whose own source table's key does not determine the grain, which on a multi-table Silver is most of them: a header amount is restated on every item, partner and document-flow row it joins to. An explicit value authored by a curator wins; absence means additive. Three pairings are **rejected at ingestion and on save**, not warned about: `additivity` on a non-measure field; `semi_additive` without a non-empty `non_additive_over`; and `non_additive` without `aggregation_behavior: none`. Every `non_additive_over` member must also appear in `grain.entity_grain` *and* resolve to a real field. |

#### 3.4.1 Naming convention: `<column>_<table>`

The standard Silver field name pattern is `<source_column_alias>_<source_table>`:

| Bronze field | Silver field name |
|---|---|
| `VBAK.VBELN` | `vbeln_vbak` |
| `VBAP.MATNR` | `matnr_vbap` |
| `MARA.MATNR` | `matnr_mara` |
| `VBAK.GBSTK` | `gbstk_vbak` |

This convention keeps lineage visible in the column name and avoids collisions when multiple Bronze nodes carry the same logical field (e.g. `MATNR` appears in both `VBAP` and `MARA`).

**Which half of the name comes from the source is a deployment setting.** `ASK_COLUMN_NAMING` decides it, resolved as environment variable → `ingestion.column_naming` in settings → `technical`:

| Mode | Silver field name | `VBAK.NETWR` (Bronze alias `net_value`) becomes |
|---|---|---|
| `technical` *(default)* | `<column>_<table>` | `netwr_vbak` |
| `alias` | `<alias>_<table>` | `net_value_vbak` |

The mode is fixed **before the first ingest**. It decides the physical column names minted for the whole corpus, so changing it later renames every Silver column. An unrecognised value raises rather than falling back, precisely because a silent default would mint the wrong names.

#### 3.4.3 What a description is for

A description is **embedded text**: it becomes part of the vector that retrieval matches a question against. That makes it the one field where padding has a measurable cost, every word spent restating something another key already carries displaces business meaning from that vector.

So a description carries what no other key can: what the thing *means* to the business, and when someone would reach for it. It does not carry:

| Do not restate | Because this key owns it |
|---|---|
| The grain columns | `grain.entity_grain` |
| What one row is | `grain.business_grain` |
| Which nodes compose the entity | `composed_of` |
| The field inventory | `fields[]` |
| The join predicates | `join_graph` |

A prose copy of any of those does not merely waste space. It becomes a second source that drifts, and the reader has no way to tell which one is stale.

When the meaning is genuinely unknown, leave the description empty. A guess is worse than a blank: a blank is visibly unfinished, while a plausible invention gets embedded, retrieved and believed.

#### 3.4.2 Document status fields

Silver status fields preserve the **raw source-system codes**. The Silver description must enumerate the codes; the *interpretation* (e.g. mapping to `OPEN/CLOSE`) belongs in Gold.

```yaml
- name: gbstk_vbak
  source: VBAK.GBSTK
  field_role: status_flag
  type: STRING(1)
  description: "Overall Processing Status. A = not yet processed / open,
    B = partially processed, C = fully processed / completed.
    Use to filter open or pending sales orders."
```

The Gold layer that consumes this Silver should derive a clean `order_status` (`OPEN`/`CLOSE`) field and document the rule there.

### 3.5 Relationships

Silver entities declare relationships to other Silver entities. These describe the **enterprise data graph** that Silver Foundational Data Products participate in, and they are what makes the Silver fallback plane work: a Silver fact must be able to reach its dimensions through its *own* edges.

**Direction rule: Silver points at Silver, never at Gold.** A Silver does not know which Gold products are built on top of it, and it must not: Silvers are reusable across many Golds, so an edge pointing upward would bind a foundational product to one consumer and invert the dependency. Lineage and drill-down edges are declared on the Gold side ([GOLD_LAYER.md §3.4](GOLD_LAYER.md#34-relationships)).

```yaml
relationships:
  - target_entity: "silver_s4h_sd_trading_goods"
    relationship_type: "many_to_one"
    join_condition: "SILVER_SD_SALES_ORDER.matnr_vbap = SILVER_TRADING_GOODS.matnr_mara"
    semantic_label: "material_of"
    traversal_cost: 2
    aggregation_safety: "safe"
    cross_module: true
    description: "Join to Material Master for material attributes."

  - target_entity: "silver_s4h_sd_customer_master"
    relationship_type: "many_to_one"
    join_condition: "SILVER_SD_SALES_ORDER.kunnr_vbak = SILVER_SD_CUSTOMER_MASTER.kunnr_kna1"
    semantic_label: "sold_to_customer"
    traversal_cost: 1
    aggregation_safety: "safe"
    cross_module: false
    description: "Customer / sold-to party detail."

  - target_entity: "silver_s4h_mm_inv_mov_stock"
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

The relationship schema is identical to the Gold layer's. See [Gold Layer §3.4](GOLD_LAYER.md#34-relationships).

#### 3.5.1 The qualifier contract

Note the qualifiers in the example above: **`SILVER_SD_SALES_ORDER`, the entity's
`db_table_name`: not `silver_s4h_sd_sales_order`, its `id`.**

**Every qualifier in a `join_condition` is the `db_table_name` of its own side.** The predicate
names exactly two tables. This entity's and the target's. And nothing else. It is handed to the
SQL generator as an authoritative join condition, with an explicit instruction not to invent a
replacement, so a wrong qualifier produces SQL that cannot execute.

The contract is also **load-bearing at ingestion**: the qualifiers are read off the predicate to
identify the edge's two physical tables, and both are shown to the SQL generator next to the entity
ids, so nothing has to infer that `silver_s4h_sd_sales_order` and `SILVER_SD_SALES_ORDER` are the
same object. A predicate that does not name its own side, or that names more than two tables, is
logged as a contract violation.

Two spellings get this wrong, and both are easy to ship because they look plausible:

- **The entity `id` instead of the physical table.** Ids resolve entities in the catalog; they are
  not selectable objects. Look up the target's `db_table_name` and copy it.
- **A third table that is neither endpoint.** If the join only works by passing *through* a third
  entity, that is **two edges, not one**: declare the hop to the intermediary, and let the
  intermediary declare its own edge onward. A predicate naming a table absent from the `FROM` list
  is not a join.

The same rule, with worked examples of both failure modes, is in
[Gold Layer §3.4.2](GOLD_LAYER.md#342-the-qualifier-contract).

## 4. Naming conventions

| Item | Convention | Example |
|---|---|---|
| `id` | `silver_<system>_<module>_<name>` | `silver_s4h_sd_sales_order` |
| `db_table_name` | `SILVER_<MODULE>_<NAME>` | `SILVER_SD_SALES_ORDER` |
| `name` | snake_case business label | `sales_order`, `trading_goods` |
| Field `name` | `<column_alias>_<table>` | `vbeln_vbak`, `matnr_mara`, `gbstk_vbak` |

## 5. Best practices

### 5.1 Pick the right grain *and document it*

Silver grains are easy to get wrong because of fan-out from optional joins (partners, document flow, schedule lines). Always declare the grain explicitly and choose `INNER` vs. `LEFT OUTER` deliberately.

### 5.2 Use `LEFT OUTER` for optional context

Header is mandatory. Items are mandatory. Partners, document flow, and business data are usually *optional* enrichments, joining them with `LEFT OUTER` preserves rows even when the optional context is absent.

### 5.3 Preserve source-system codes; do not interpret

Silver should preserve `GBSTK='A'/'B'/'C'`, `LPRIO=1..99`, `PSTYP='7'`, etc. as-is. Document what the codes mean. Leave the *interpretation* (`OPEN/CLOSE`, `urgent/normal`, `purchase/stock_transfer`) to Gold.

### 5.4 Keep Foundational Data Products reusable

A Silver Foundational Data Product should answer the question *"what does this artifact look like?"*, not *"what is the answer to this specific business question?"* If you find yourself encoding a business definition into Silver, lift it to a Gold Business Logic Data Product instead.

### 5.5 Variants are a feature, not duplication

If two business contexts genuinely need different versions of the "same" entity, publish two Silver Foundational Data Products. Do not contort one variant to fit both contexts. The catalog can hold many variants; the agent picks the right one based on intent and scope.

### 5.6 Declare relationships generously

Every meaningful join the data team would naturally write should be declared as a relationship. The agent uses `relationships` to discover navigable paths, undeclared joins are invisible to the planner.

### 5.7 Use `requires_dedup` for many-to-many fan-out

Joins like `sales_order ↔ inventory_movement` over `(matnr, werks)` are **many-to-many** and **fan out**. Mark them `aggregation_safety: requires_dedup` and prefer routing through a Gold cross-fact summary when possible.

## 6. Reference examples

- [`examples/silver/sales_order.yaml`](../examples/silver/sales_order.yaml). Multi-node fact entity (VBAK + VBAP + VBKD + VBPA + VBFA).
- [`examples/silver/trading_goods.yaml`](../examples/silver/trading_goods.yaml). Multi-node dimensional entity (MARA + MAKT + MARM + MSTA + MVKE).

## 7. Validation checklist

Before publishing a Silver YAML to the catalog, verify:

- [ ] `id`, `internal_id`, `layer`, `version`, `source_system`, `source_system_no` are present and consistent; `db_table_name` is present or deliberately left to default to `id`.
- [ ] `description` says what the artifact represents and what it is used for: and does **not** restate the grain, the composing nodes or the field inventory ([§3.4.3](#343-what-a-description-is-for)).
- [ ] `composed_of` lists every Bronze node referenced anywhere in `fields` or `join_graph`.
- [ ] `join_graph` covers every node beyond the anchor table, with **one entry per
      `(left_table, right_table, sequence)`**, a composite key is one `AND`-composed
      `condition`, never one entry per key column. See [§3.3](#33-join_graph).
- [ ] `join_graph[].sequence` starts at **2**, the anchor holds the implicit position 1
      ([the sequence convention](#the-sequence-convention-starts-at-2)).
- [ ] Every column named in a `join_graph` `condition` exists in that side's Bronze node.
- [ ] Every qualifier in a `join_condition` is the `db_table_name` of its own side, never an
      entity `id`, never a third table. See [§3.5.1](#351-the-qualifier-contract).
- [ ] `grain.entity_grain` reflects the actual finest cardinality of the joined result.
- [ ] Every `grain.entity_grain` member is a `fields[].name`: a selectable column, not a source-system code ([§3.2](#32-grain)).
- [ ] The grain is MINIMAL: no member is redundant given the `join_graph` predicates.
- [ ] Every field follows the deployment's naming mode consistently: `<column>_<table>` under the default `technical`, `<alias>_<table>` under `alias` ([§3.4.1](#341-naming-convention-column_table)).
- [ ] Every field `name` appears exactly once. A repeated field block is never meaningful, and
      because the YAML is handed to the model verbatim, a duplicate is paid for on every question.
- [ ] Status field descriptions enumerate every valid code.
- [ ] Relationships have `traversal_cost` and `aggregation_safety` set; many-to-many edges are marked `requires_dedup`.
- [ ] Field types match the Bronze source types.

---

[← Back to the ASK specification](../README.md) · [The layer specifications](README.md)

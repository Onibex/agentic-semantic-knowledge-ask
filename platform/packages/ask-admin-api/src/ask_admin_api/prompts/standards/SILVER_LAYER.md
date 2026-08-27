# ASK Semantic Layer — Silver Standard

> **AUTHORITATIVE for the Silver layer.** This file is the source of truth for how Silver
> YAMLs are authored. It is also **prompt-source material**: the enrichment excerpt injects
> **this whole file** for Silver entities, so it must stay **complete and self-contained** —
> never reduce a rule here to a cross-link, and never move a Silver rule out of this file.
> Shared contracts are deliberately repeated (scoped) here rather than thinned into pointers.
> **One folder-wide exception (by design):** the full canonical type-system tables live in
> [./BRONZE_LAYER.md](./BRONZE_LAYER.md); this file carries the one-vocabulary rule, the six
> bases and the unknown→`STRING` trap, and points there for the full tables.
>
> **Counterpart:** [`SILVER_LAYER.md`](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/definition/docs/SILVER_LAYER.md)
> in the `agentic-semantic-knowledge-ask` repo. **When the two disagree, this file wins and
> the counterpart is corrected to match.**
>
> Sibling layer standards: [./BRONZE_LAYER.md](./BRONZE_LAYER.md) · [./GOLD_LAYER.md](./GOLD_LAYER.md) · index: [./README.md](./README.md)

---

## 1. Role of the Silver layer

| One YAML per | Role | Key idea |
|---|---|---|
| curated business entity / Data Product | Semantic ontology node | Single source of truth for join topology (`composed_of` + `join_graph` + `relationships`). |

> There is **no `metric` layer** (removed): a business measure is a `field_role: measure`
> field with `aggregation_behavior` on the Silver/Gold that owns it — never a separate node.
> Ingesting a `layer: metric` YAML raises.

The agent resolves a request across **two planes**, gold-first:

```
request → IR (metrics, dimensions, filters, grain)
   │
   ▼
hybrid retrieval (GOLD priority)
   │
   ├─ a Gold COVERS it (metrics+dims+grain+filters, already denormalized)
   │      → SQL from the Gold alone (0 joins). Cheapest, most deterministic. ✅
   │
   ├─ Gold has the fact but an attribute is NOT flattened
   │      → join via the GOLD's relationships (enrichment / drill-out)
   │
   └─ no Gold applies
          → SILVER fallback plane:
              anchor = the fact Silver (the one owning the measures)
              Dijkstra over silver→silver relationships (weight = traversal_cost)
              composed_of → Bronze physical tables
              honour aggregation_safety to avoid fan-out double counting
              → SQL
```

**Authoring implications (critical):**

- The **Silver plane must be self-sufficient.** A Silver fact must be able to reach its
  dimensions through *its own* `relationships`. If you strip silver relationships, the
  fallback breaks. **This is why relationships live on Silver, not only on Gold.**
- The **Gold plane and Silver plane are parallel.** On fallback the agent uses the
  **Silver's** relationships, never the Gold's (the join keys differ; the Gold wasn't
  selected). Gold relationships are only for: (a) enriching a non-flattened attribute,
  (b) drilling down to detail (`one_to_many`) — see [./GOLD_LAYER.md](./GOLD_LAYER.md).
- Retrieval priority (gold-first) — not the presence of edges — decides which plane is
  used. Having edges on Silver does not undermine gold priority.

---

## 2. Header keys

**Legend — used by every table in this file:** **R** required · **S** structural (comes from
SAP/ingestion — *do not hand-edit*) · **E** enrichable (humans curate) · **O** optional ·
**—** = *the key does not exist at that layer*.

**Not every header key exists at every layer.** Bronze is a *different node type*, not a
Silver with fewer keys.

| Field | Kind | Notes |
|---|:--:|---|
| `id` | R/S | Stable key. Grammar + immutability in [§7 naming](#7-naming--ids). |
| `layer` | R/S | Literal `silver` (the validated closed set is `bronze` \| `silver` \| `gold`); validated, never inferred. |
| `version` | R/S | Provenance. **Silver requires it** (Bronze defaults to `'1'` when omitted). |
| `source_system` | R/S | Source family token — `s4h`, `ecc`, `generic`, `salesforce`, `odoo`. It selects the type profile, so a wrong token silently changes how `type` is read. |
| `source_system_no` | R/S | Integer client / instance. **The Silver/Gold spelling.** Bronze spells the same concept `source_system_id` — do not cross them: the wrong one is dropped, not corrected. |
| `internal_id` | R/S | Data-Modeler internal id (`s4h_100_17`). |
| `db_table_name` | R/S | **Physical table the SQL targets** (`SILVER_SD_SALES_ORDER`). Defaults to `id` when omitted. (At Gold this key is *essential* — see [./GOLD_LAYER.md](./GOLD_LAYER.md); **Bronze has no such key** — its physical table *is* `name`.) |
| `name` | R/S | Silver: short business name (`sales_order`). (Bronze instead carries the source table name, UPPERCASE exactly as in the source.) |
| `description` | R/E | See [§8 — Writing descriptions](#8-writing-descriptions). |
| `module` | R/S | The module that **owns / created** this Data Product, not its usage scope. Source: `dataprodclass.mmodule` (**not** Data-Modeler Tag 1 — see the provenance note below). **UPPERCASE in the field, lowercase in the `id`** — two different rules, do not conflate them ([§7](#7-naming--ids)). **Silver: scalar** (one Data Product = one module; an entity used by several processes is exported once per process, each with its own module). A raw source table has no module: Bronze omits it. |
| `business_process` | R/S | The process family the Data Product participates in. Source: `info.domainv` (= Data-Modeler Tag 1). Recommended vocabulary — **normalised, never rejected**, so an unknown value ingests and is upper-cased rather than failing: `ORDER TO CASH` · `PROCURE TO PAY` · `PLANT TO PRODUCE` · `RECORD TO REPORT` · `ORGANIZATIONAL STRUCTURE`. **`ORGANIZATIONAL STRUCTURE` is a legitimate value, not a gap**: it marks a *generic, cross-module* entity that belongs to no single process (a plant, a sales office, an org unit). It is deliberately preferred over a blank, which would lose the "generic on purpose" vs "nobody filled it in" distinction. **Short codes (`OTC`, `SCM`, `P2P`) do NOT belong here** — those are the `<domain>` token of a `gold_*` / `metric_*` **id** (ASK Spec Sec 21.1 rule 4), and mixing the two is what produced the Silver-long-form / Gold-short-code fork. Never put a module code here either. |
| `classification` | R/S | `M` master · `T` transactional · `C` configuration. **Silver: required** — it drives `entity_role` ([§5.3](#53-entity_role-classification-rule)). |
| `fields` | R (mix S/E) | **The shape differs by layer**: a **list of field objects** at Silver ([§4](#4-fields)); a dict keyed by source column at Bronze ([./BRONZE_LAYER.md](./BRONZE_LAYER.md)). |
| `tag1`, `tag2` | O/S | **Secondary categorization for catalog faceting** — free text, indexed, no controlled vocabulary. Filled per ASK Spec 6.1 as `tag1` ← `info.tag4` and `tag2` ← `info.tag5` (the offset in the numbering is the spec's). In the real exports `tag4` is **empty in 15 of 16**, so a populated `tag1` is almost always a local hand-authoring choice with no upstream source — the `OTC`/`SCM` short codes on the shipped Golds are exactly that, not a convention. `tag2` by contrast is always populated and is genuinely useful: it carries `<MODULE>-<SUBMODULE>` (`SD-MD`, `MM-PUR`), i.e. **the functional area the Data Product was created for**, which is a real third axis distinct from both `module` and `business_process`. Bronze has neither. |

**Keys that do NOT exist at Silver:**

| Field | Where it lives | Notes |
|---|---|---|
| `alias` | Bronze only | UPPER_SNAKE English label (`ORDER_HEADER`). Load-bearing at Bronze: it is the last segment of the bronze `id` and it is indexed on the entity document. |
| `primary_key` | Bronze only | Header-level at Bronze. **Silver declares its key as `grain.entity_grain`** ([§3](#3-silver-body)). |
| `source_system_id` | Bronze only | The **Bronze spelling** of the integer client / instance (`100`). At Silver the key is `source_system_no`. |

> **What `—` means in practice.** An unknown key is *ignored*, not rejected: node validation
> drops it, so it never reaches the catalog while the workspace file still shows it. That is
> a silent divergence, not an error — e.g. a `primary_key` or `alias` written onto a Silver
> survives in the YAML and disappears from the catalog.

> **Provenance of `module` — the spec row is wrong, do not "fix" the code to match it.**
> ASK Spec Sec 6.1 assigns **Data-Modeler Tag 1 to BOTH** `business_process` *and* `module`.
> That is a documentation defect, not a design: `info.tag1` is byte-identical to `info.domainv`
> in every export and holds a process name (`ORDER TO CASH`), never a module code. `module`
> comes from `dataprodclass.mmodule`, which is what the parser has always read.
>
> **Upstream defects.** Several normalisations on the ingest path are shims over Data-Modeler
> bugs, not ASK design — the CHAR(20) truncation behind `ORGANIZATIONAL STRUC`, the `D`→`M`
> mapping, and the CONTFLAG-derived `C`. Each is registered in the internal upstream-defect
> report with the condition under which it can be **retired**. Do not add a shim without adding
> an entry there.

---

## 3. Silver body

| Field | Kind | Notes |
|---|---|---|
| `entity_role` | R/S | `fact` \| `dimension` \| `reference`. **Silver: DERIVED** from `classification` — do not hand-edit, the server recomputes it on every save (rule in [§5.3](#53-entity_role-classification-rule)). |
| `grain.entity_grain` | R/S | Ordered composite key fields, **named as `fields[].name`** — published, selectable columns, never raw source codes ([§3.1](#31-how-entity_grain-is-derived)). Drives grain-correctness & dedup. **One row per distinct combination — so a filter pinning only a *subset* of these fields returns MANY rows.** This is multiplicity *within* one table; distinct from the JOIN fan-out governed by [§6.4](#64-aggregation_safety). Propagated to the SQL prompt as rules 7-8 of `_YAML_READING_RULES` (`freeform_generator.py`). **Derived** — see [§3.1](#31-how-entity_grain-is-derived); a missing or duplicated Bronze key would feed straight into this contract, which is why Bronze rejects both. |
| `grain.business_grain` | R/S | Human label (`sales_order_item`). |
| `composed_of` | R/S | Ordered Bronze IDs. |
| `join_graph[]` | R/S | Join plan **between composed Bronze tables**. Required when `composed_of` > 1. Carries `sequence` — assembly order, and it numbers the table being *added* ([§3.2](#32-the-join_graph-sequence-convention)). Bronze↔Bronze only — never cross-entity. `join_type` is a closed set: **`INNER` \| `LEFT OUTER` \| `RIGHT OUTER` \| `CROSS`** (ASK Spec Sec 6.4). `FULL OUTER` is **not** supported — it appears in no spec section and the validator rejects it; do not re-add it. Note `CROSS` is accepted but **not usable as authored**: `condition` is mandatory on a join row and a CROSS join has no predicate, so a CROSS entry would have to carry a fake condition to validate. It is kept because the spec prescribes it, and because `RIGHT OUTER` is equally unused — dropping values for being unused would collapse the set to two. **This is ETL/build metadata, not a runtime join**: the SQL generator is explicitly told that a Silver is already one denormalized table and that nothing inside it is joined at query time. |
| `fields[]` | R (mix S/E) | See [§4](#4-fields). |
| `relationships[]` | E | Cross-entity edges. See [§6](#6-relationships--the-lineage-graph). |

### 3.1 How `entity_grain` is derived

Two properties are load-bearing, and both are easy to lose.

**Vocabulary — members are published column names.** `entity_grain` lists
`fields[].name` values (`vbeln_vbak`, `posnr_vbap`), not source-system codes
(`VBELN`, `POSNR`). Rules 7-8 reach the model as raw YAML text and tell it to reason
about — and group by — those names, so a member that is not a selectable column of
the entity makes the whole contract unexecutable rather than merely imprecise.

**Minimality — it must be a minimal key, not any superkey.** Rule 7 asserts two
things at once: exactly ONE row per distinct combination, **and** MANY rows whenever
a filter pins only a subset. A padded key satisfies the first and falsifies the
second, so the model concludes that pinning the real key returns many rows when it
returns one. Both failure directions are silent — the YAML still looks plausible.

Derivation (`EntityDeriver.structural_grain`, run identically by the ingestion path
and the admin save path) starts from the composed Bronzes' `primary_key` lists —
client/tenant columns already excluded at Bronze
([./BRONZE_LAYER.md §3.5](./BRONZE_LAYER.md#35-client--tenant-columns-are-excluded-from-the-key))
— and applies two rules read straight off `join_graph`:

1. **A join covering the right table's ENTIRE primary key contributes nothing.** It
   matches at most one row, so that table multiplies nothing. `MSEG→MARD` on the full
   `MATNR+WERKS+LGORT` attaches exactly one stock row per movement line. Note this does
   *not* depend on which columns the join leaves FROM: `MSEG` reaches `MARD` through
   columns that are not part of `MSEG`'s own key, and the join is still N:1. A join
   covering only PART of the right key fans out, and the uncovered members are exactly
   what widens the grain — `MKPF→MSEG` binds `MBLNR+MJAHR` and leaves `ZEILE` free, so
   the grain is the movement LINE, not the document.
2. **Columns the predicates declare equal are ONE key column.**
   `VBAK.VBELN = VBAP.VBELN` means `vbeln_vbak` and `vbeln_vbap` always hold the same
   value; keeping both states one constraint twice. The surviving representative comes
   from the root-most table, naming the key after the entity's own anchor. Collapsing by
   *bare column name* instead is wrong and was the historical bug: it merged
   `VBAK.VBELN` (the order) with `VBFA.VBELN` (the **subsequent** document) — two
   different values under one name.

A consequence worth stating: a loose join predicate legitimately produces a **wider**
grain. Joining `VBPA` on `VBELN` alone really does fan out by `POSNR` and `PARVW`, and
the derived grain says so. Tightening the predicate tightens the grain automatically —
the grain never hides a bad join.

### 3.2 The `join_graph` sequence convention

`sequence` numbers **the table being added** — the `right_table` of its row — in the order the
entity is assembled. The anchor table is not added by any row: it is the starting point, so it
holds the implicit position **1**, and the first authored row is therefore **`sequence: 2`**.
Every shipped Silver with a `join_graph` follows this (14 of 14; the two single-table Silvers
have no `join_graph` at all), but it was never written down — a first-time author reads
"execution order", starts at 1, and produces a file that is off by one against the whole corpus.

```yaml
# sales_order — anchor VBAK holds the implicit position 1
join_graph:
- { left_table: VBAK, right_table: VBAP, ..., sequence: 2 }   # VBAP added 2nd
- { left_table: VBAK, right_table: VBPA, ..., sequence: 3 }   # VBPA added 3rd
- { left_table: VBAK, right_table: VBFA, ..., sequence: 4 }
```

Two consequences follow from "it numbers the added table", and both are load-bearing:

1. **The anchor may still appear as a `left_table`** — including on the row that attaches it to
   another table. In `purchase_order` the anchor is `EKKO` and the `sequence: 2` row reads
   `EKKO → EKPO`: `EKPO` is what position 2 adds. Do not infer the anchor from the lowest
   sequence's `left_table` alone; infer it from which table is never a `right_table`.
2. **Sequence is a property of the pair, not of the predicate.** All rows for one
   `(left_table, right_table)` pair share one sequence, which is exactly why the join row's
   identity is `(left_table, right_table, sequence)` and why a composite key must be ONE
   `AND`-composed row ([§9](#9-authoring-checklist)) — two rows sharing a sequence are the
   same logical join split in half, not two joins.

Gaps are legal and carry no meaning: `trading_goods` runs 2, 3, 4, 5 while an entity that dropped
a table mid-life may run 2, 3, 5. Renumbering to close a gap is churn — the order is what matters,
not density. And the whole key stays **descriptive**: it tells a consumer how the entity is
conceptually built, while the engine picks the real execution plan.

---

## 4. `fields[]`

Silver `fields` is a **list of field objects** (Bronze uses a dict keyed by the source
column). Silver fields are **derived** — renamed, recomposed, augmented — and the published
order is part of the surface. Bronze mirrors; Silver and Gold design.

| Sub-field | Kind | Notes |
|---|---|---|
| `name` | R/S | Logical field name — the **actual SQL column**, consumed verbatim by the SQL generator. Minted at ingest under the deployment's column-naming mode (`ASK_COLUMN_NAMING`): `technical` → `<column>_<table>` (`vbeln_vbak`), `alias` → `<alias>_<table>` (`documento_ventas_vbak`); the suffix is the SAP table name in both modes. See `REQ_CURATED_COLUMN_NAMING.md`. |
| `source` | R/S | `TABLE.COLUMN`. Physical binding, always raw SAP codes — the stable spine heuristics resolve through, in every naming mode. |
| `field_role` | R/S | See [§5 taxonomy](#5-field_role-taxonomy). |
| `type` | R/S | Mapped SAP→ANSI type — the **canonical, source-agnostic** vocabulary (see the type note below). |
| `description` | E | See [§8](#8-writing-descriptions). |
| `aggregation_behavior` | E | `SUM\|AVG\|MIN\|MAX\|COUNT\|COUNT_DISTINCT\|none`. **Axis 1 — WHICH function.** A pure SQL function name, no hidden semantics. See [§4.1](#41-the-two-axis-aggregation-contract). |
| `additivity` | E | `additive\|semi_additive\|non_additive`. **Axis 2 — over WHICH dimensions axis 1 is valid.** Measures only; absent means additive. See [§4.1](#41-the-two-axis-aggregation-contract). |
| `non_additive_over` | E | Grain dimensions to collapse before aggregating. Required iff `semi_additive`; ANY grain dimension is accepted (v2). **Derived at ingest** for every measure — see [§4.1](#41-the-two-axis-aggregation-contract). |
| `synonyms` | O | Alt names to boost retrieval/disambiguation. **Consumed**: indexed on the field registry (BM25), folded into the entity's embedded text, and rendered into the RAG chunks. Complements inline synonyms in the `description` ([§8](#8-writing-descriptions)) — it does not replace them. |

**`type` — one vocabulary, all three layers.** Bronze, Silver and Gold all store the
canonical type, on every write path — the SAP-JSON ingestion parser, the admin `/import` +
`/derive` boundary, and hand authoring. There is no per-layer type dialect and no
"source-verbatim at Bronze" exception; the older rule is **withdrawn**. Source fidelity is
preserved by the field key and the `description`, not by re-encoding the type. Six bases
exist, and only these:

`STRING` · `INTEGER` · `DECIMAL` · `DATE` · `TIMESTAMP` · `BOOLEAN`

The authority is the `TypeMapper` in `ask_knowledge_graph/domain/source_profiles.py`; **the
full rendered forms, the SAP resolution table and the mapper's rules live in
[./BRONZE_LAYER.md](./BRONZE_LAYER.md)** and are not duplicated here.

> A `type` that is not one of those rendered forms is not a type. Both raw source codes (`C10`)
> and SQL words (`TEXT`) parse to the same canonical value, so nothing misreads one — but neither
> is canonical, and neither belongs in a file you are authoring or reviewing.
>
> **What canonical drops — know it before you rely on a `type`.** `STRING(n)` absorbs three
> distinct SAP types: `Cn` (char), `Nn` (numeric text, where **leading zeros are significant**
> — SAP document and material numbers) and `Tn` (time of day). So a `type` cannot tell you
> whether a column is zero-padded or holds a time, and `D8`'s length is gone. That information
> is **not recoverable** — go to the source data dictionary. Likewise **unknown or absent →
> `STRING`**: the mapper never raises, so a typo'd type does not fail, it silently becomes
> `STRING`. A canonical `STRING` on an obviously numeric column means the source metadata was
> missing — not that the column is text.

### 4.1 The two-axis aggregation contract

Aggregating a measure needs **two** independent facts, so it takes two keys:

| Axis | Key | Question it answers |
|---|---|---|
| 1 | `aggregation_behavior` | **Which** SQL function. |
| 2 | `additivity` (+ `non_additive_over`) | Over **which** dimensions that function is valid. |

Fusing them is what produced the defect this contract replaces: one key with two
overloaded values. `none` meant *"not a number"* on an identifier and *"is a number,
do NOT sum it"* on a measure; `MAX` meant *"the maximum is the answer"* and *"every
value here is identical, take any one"*. Tooling that read `none` as a no-op default
dropped it on save, turning running totals into summable measures with no error.

#### Axis 1 — `aggregation_behavior`

`SUM` · `AVG` · `MIN` · `MAX` · `COUNT` · `COUNT_DISTINCT` · `none`

A function name and nothing else. **Absent** means *not curated*: the SQL prompt then
treats a measure as additive and sums it. Use `none` for non-measure roles, and for a
genuinely non-additive measure (see axis 2).

#### Axis 2 — `additivity`

Applies to `field_role: measure` only. Validated on `SilverField`; a violation is
rejected at ingestion and on admin save, with every problem reported at once. Ingestion
also DERIVES `semi_additive` + `non_additive_over` for every measure whose own table's
key does not determine the grain — see the derivation note below.

| Value | Contract |
|---|---|
| **absent** (default) | `additive` — the function is valid across any grouping. Never written out explicitly; absence already says it. |
| `semi_additive` | The value repeats or accumulates along the dimensions in `non_additive_over`. Reduce each grain group to ONE row by those dimensions **first**, then apply the function across the rest. WHICH row: the **latest** one when the value accumulates along an ordered dimension; **any** one when a join merely repeats it, since every row of the group then carries the same value. Requires a non-empty `non_additive_over`. |
| `non_additive` | Never aggregate arithmetically — a ratio, a score. Requires `aggregation_behavior: none`. |

`non_additive_over` must name grain dimensions that resolve to selectable columns.
**Any grain dimension is accepted (v2, 2026-08-03).** v1 accepted only `field_role:
timestamp` ones, on the reasoning that *"collapse to the latest"* is undefined for, say,
a storage location. That conflated the two reasons a value needs collapsing:

- it **ACCUMULATES** along the dimension — a running total, a projected balance. The
  collapse must pick the LATEST row, so the dimension really must be ordered, i.e.
  temporal. When the series is sparse, "latest" means the last row at or before the
  target value, not equality with it.
- it merely **REPEATS** because a join fanned the rows out — a header amount restated
  on every item, a stock level restated on every movement line. Every row of the group
  carries the SAME value, so collapsing to ANY one row is exact and the dimension needs
  no ordering at all.

Only the first case needs a timestamp. The second is the ordinary shape of a
denormalised Silver — a measure whose native grain is COARSER than the row grain — and
v1 could not express it, which pushed the instruction into field `description` prose
where the SQL generator had latitude and measurably misread it.

**These dimensions are DERIVED, not curated.** At ingest, every `field_role: measure`
gets them from one mechanical rule: *a measure repeats over every grain member not
functionally determined by the primary key of its own source table*, with column
equality taken from the `join_graph` predicates so the determination is transitive.
A curator's explicit `additivity` always wins — the fill is when-absent — and a measure
whose own table's key IS the grain correctly gets nothing, because it is genuinely
additive. See `EntityDeriver.fanout_dims_by_table`.

#### Why semi-additive is the common case, not the exotic one

`gold_s4h_inventory_situation` is grained `client + plant_id + material_id +
future_date`. Fifteen of its twenty measures repeat or accumulate along `future_date`:

| Measure group | Across `plant_id` | Across `future_date` |
|---|---|---|
| `daily_qty_*` (5) | additive | additive — genuine per-date event quantities |
| `cumulative_*`, `future_stock`, `actual_stock` (7) | **additive** | not additive — running totals and projected balances |
| stock buckets, `max_level`, `safety_stk` (8) | **additive** | not additive — a snapshot restated on every dated row |

The middle column is the point. Under the old single key those fifteen were marked
"never sum", which is only half true and left *"total projected stock across all
plants on date X"* — an ordinary question — with no correct encoding.

Grain drives all of it: the same `on_hand` column is a plain `SUM` in
`gold_s4h_mm_inventory_position`, whose grain has no date, and semi-additive here.
Decide additivity against **your** grain, never against the column name.

#### The older encoding still reads correctly

`measure` + `aggregation_behavior: none` + no `additivity` is read as
`non_additive` — safe, if less precise than the `semi_additive` most of them really
are. This is enforced on `SilverField` itself rather than in a writer, so every path
agrees, and prompt rule 8 keeps its own branch for it because what reaches the SQL
prompt is the stored `raw_yaml` **text**, which no model shim touches.

Design and rollout: internal design doc (REQ_ADDITIVITY_CONTRACT).

## 5. `field_role` taxonomy

Six roles. The role tells the agent **where the column may appear in SQL**:

| Role | SUM/AVG? | GROUP BY? | WHERE? | Use for |
|---|:--:|:--:|:--:|---|
| `measure` | ✅ | — | ✅ | Quantitative values (amounts, quantities). |
| `dimension` | — | ✅ | ✅ | Categorical / groupable attributes (codes, groups). |
| `identifier` | — | ✅ | ✅ | Keys, document numbers. Never aggregated. |
| `timestamp` | — | ✅ | ✅ | Dates/periods. Drives `time_context`. |
| `attribute` | — | **❌ never** | ✅ | Free-text descriptions / names. Filter and SELECT only. |
| `status_flag` | — | ✅ | ✅ | Business states (open/partial/closed, Critical/Healthy). Groupable. |

> The `attribute` vs `dimension` distinction matters, and it is the only one the agent
> enforces: a material *description* is an `attribute` (SELECT it, filter on it, never
> `GROUP BY` it — its cardinality is ~1:1 with the row, so the aggregate is meaningless),
> a material *group code* is a `dimension` (group by it).
>
> **`status_flag` IS groupable** — "orders by processing status", "materials by stock
> status". A small value space where each value is a business state is precisely what makes a
> good grouping key. What `status_flag` forbids is **arithmetic aggregation**.
>
> A technical lifecycle flag — a deletion or blocking indicator — is a different case: you
> want to `WHERE` it out, not report on it. Say so in the field `description` ("use to exclude
> deleted items"). This is the **only** hazard a description still carries, and the reason is
> that no structured key expresses "filter these rows out".
>
> **A description never carries aggregation mechanics.** The structured keys are authoritative
> and derived at ingest, so the SQL prompt obeys them; a description may add a restriction they
> cannot express but may never relax one. Prose such as *"repeated on every movement line —
> reduce to one row per that triple, then SUM"* is a stale duplicate of `non_additive_over` and
> should be removed, not maintained. It also costs retrieval: descriptions are **embedding
> text**, so mechanics displace the business meaning in that field's vector and the field stops
> matching the question a user actually asks.
>
> **`attribute` has zero uses across all 2,564 authored fields.** That is not neglect: the
> origin spec introduced it undecidably, defining `dimension` as "categorical or *descriptive*
> attributes" and `attribute` as "*descriptive* metadata (names, descriptions, codes)" one
> line apart — with "codes" filed under the role you are told not to group by. The rule above
> is this document's repair of that defect. Do not expect the AI authoring paths to produce
> `attribute`: they deliberately do not offer it, because a bare `CREATE TABLE` carries no
> signal that separates descriptive text from a categorical code, and a wrong guess silently
> removes a legitimately groupable column from the agent's vocabulary. It is a human-only
> role, reachable from the SPA.

### 5.1 `status_flag` — when to use it and how to describe it

A field is `status_flag` when **its value space is small (typically 2–5) and each value
is a business state** rather than a code in a larger taxonomy. The agent may `GROUP BY` and
`WHERE` a status_flag; it must never apply an arithmetic aggregate to one.

**Candidate signals — NOT a derivation rule.** These identify a field *worth reviewing*; they
do not decide it, and nothing in the platform derives `status_flag` automatically. The
decisive signal is the **value space**, which is a property of the data, not of the name or
the type — so a suggestion surface may flag a candidate, but a human accepts it:

- Name: `is*`, `has*`, `*_flag`, `*_status`, `*_indicator`, `*_ind`, `*_kennz`, exact
  `aktiv` / `inaktiv` / `kennzeichen`. Note the prefixes match **with or without** the
  underscore — SAP emits `hasdiffoptrate` as readily as `has_diff_opt_rate`.
- **The SAP `X` prefix on a CHAR(1).** `x<something>` is the SAP DDIC convention for a
  boolean ("X" = true, blank = false) and it is the single most productive signal in a real
  S/4HANA corpus: of 404 `C1` fields currently tagged `dimension`, 57 carry it while only 18
  match the name list above.
- The SAP short label (the field's own description) contains `flag`, `indicator`, `Ind.`, or
  spells out a two-value mapping (`blank = …`, `X = …`).
- SAP-source type `C1` (single character) — necessary but far from sufficient, see below.
- The business meaning is "yes/no" or a short closed set ("open / in-progress / done").

**Description rules** (override the generic ones in [§8](#8-writing-descriptions)):
- 5–10 words is the target. Lead with the value mapping, not a sentence.
- Spell out what each value means in business terms:
  - `"1 = active, 0 = inactive"`
  - `"X = blocked, blank = not blocked"`
  - `"A = approved, R = rejected, P = pending"`
- Skip synonyms (`synonyms: []`) — flag values rarely have useful natural-language synonyms.
- If you don't know what the values mean (unfamiliar SAP indicator), leave the description
  empty and DO NOT guess. A wrong flag description silently misleads the agent's filters.

**Counter-examples — why `C1` alone is not enough.** SAP uses CHAR(1) for booleans *and* for
small taxonomies, indiscriminately. All of the following are `C1` in the shipped corpus and
all are genuine `dimension`s:

| Field | What it really is |
|---|---|
| `spras` | **Language key** — dozens of values. The most dangerous false positive: tagging it `status_flag` would break "sales by language / country". |
| `vbtyp` | SD document category |
| `bstat` | Accounting document status (a taxonomy, not a state pair) |
| `insmk` | Stock type |
| `vprsv` | Price control (`V` / `S` — two values, but a *category*, not yes/no) |
| `buzid`, `rebzt` | Item / reference category letters |
| `kapnr_eikp` | Per-capacity profile, value space `{1, 2, 3, 4, 5, …}` |

The pattern: a **boolean** is a `status_flag`; a **small code list** is a `dimension`. Two
values does not make something a flag — `V`/`S` is a choice between two categories, not a
yes/no. When in doubt, profile the actual column: `SELECT col, COUNT(*) … GROUP BY col`
answers this definitively and also hands you the value mapping the description needs.

### 5.2 Temporal fields (`field_role: timestamp`)

> ⚠️ **OPEN GAP — proposal, NOT YET RATIFIED (2026-06-17).** This subsection records a
> known inconsistency and a proposed contract. It is **not** a binding standard yet —
> it is flagged here so the gap is visible and so the compensating code PATCH is
> traceable back to it. Ratify or amend before treating as a rule.

**The gap.** `type` records the *logical* ANSI type (`DATS`→`DATE`, `TIMS`→`TIMESTAMP`),
but it is **not guaranteed to equal the physical column type**. In practice, SAP-sourced
dates land in **Silver** as `VARCHAR 'YYYY-MM-DD'`, while **Gold** uses native
`DATE`/`TIMESTAMP`. The standard currently says nothing about this, so a column declared
`timestamp` may physically be a string — and a raw comparison to `CURRENT_DATE` /
`DATE_TRUNC(...)` fails with `operator does not exist: character >= timestamp`.

**Proposed contract (to ratify):**
1. **SQL comparison.** Never compare a `timestamp`-role column raw to a date expression.
   Normalize it: `CAST(NULLIF(<col>, '') AS DATE)` — correct for both `VARCHAR 'YYYY-MM-DD'`
   and native dates. Missing/initial dates must be `NULL` (ingestion maps SAP `'00000000'`→NULL).
2. **Preferred end-state.** Normalize SAP date strings to native `DATE` in the Silver
   definition (`TO_DATE(<col>, 'YYYY-MM-DD')`) so the logical `type` and the physical column
   agree, comparisons need no cast, and filters stay index-sargable.
3. **Type honesty.** `type` must not claim `DATE`/`timestamp` for a column physically stored
   as `VARCHAR` until (2) is done — make the storage explicit instead of letting `type` lie.

**Interim (already in place).** The SQL-generation prompt carries a compensating **PATCH**
that implements rule (1) — see `packages/ask-sql-generation/src/ask_sql_generation/application/prompts/{postgresql,hana}.py`
(search `PATCH`). It is explicitly tied to this gap and should be relaxed once (2) lands.
Tracked in the internal backlog.

### 5.3 `entity_role` classification rule

> **Two different axes — don't confuse them.** `classification` (`M`/`T`/`C`) is the *nature
> of the source data*; `entity_role` (`fact`/`dimension`/`reference`) is *how it's used in SQL*.
> **There is no `configuration` entity_role** — a Configuration entity (`classification: C`)
> surfaces as `entity_role: reference`. So "config" lives under **reference**.

**Applies to SILVER only.** At Gold, `entity_role` is **authored** (default `fact`) — every
input below is a Bronze/SAP artefact that a Gold does not have, so deriving there decided the
role on absent evidence. The Gold half of this rule lives in [./GOLD_LAYER.md](./GOLD_LAYER.md);
see also the `entity_role` row in [§3](#3-silver-body).

- **C (Configuration)** → always `reference`.
- **M (Master data)** → `dimension`, unless all tables are pure config (`CONTFLAG ∈ {C,G,E,S,W}`) → `reference`.
- **T (Transactional)** → `fact` if it has ≥1 currency/quantity field or is item-level; else `dimension`.

> **Where `C` comes from, given the Data Modeler does not emit it yet.** The upstream export
> only ever sends `D` (master) and `T`; `C` is not implemented there. The ingest path therefore
> derives it from SAP's own delivery class: when **every** relation carries
> `CONTFLAG ∈ {C,G,E,S,W}` (SAP's non-application classes — `A` = application/master+transaction
> is deliberately excluded), the Data Product is customizing data and ingest writes
> `classification: C`. On the shipped corpus this separates 9 all-`C` exports — exactly the
> configuration entities — from 8 all-`A`, with no false positives.
>
> It writes `C` and **not** `M` on purpose. Under `M` the admin save path re-derives with
> `relations_present=None`, which short-circuits the `M` branch before CONTFLAG is read and
> permanently demotes the entity back to `dimension`. The `C` branch is unconditional, so the
> role is stable on every write path. Registered as UP-4 in the upstream defect report; the
> override becomes a no-op once `C` ships upstream.

---

## 6. Relationships & the lineage graph

`relationships[]` are the directed edges the agent traverses (Dijkstra) to build cross-entity JOINs.

### 6.1 Direction rules

- **Silver → Silver** (and the rare Silver→Silver dimension hop). Required for the fallback plane.
- **Never Silver → Gold.** Silvers don't know about golds.

The Gold-side direction rules (**Gold → Silver** and **Gold → Gold** for drill/enrich/lineage,
and **Gold ↔ Gold: declare on ONE side only** — the reverse edge is auto-generated) live in
[./GOLD_LAYER.md](./GOLD_LAYER.md).

### 6.2 `relationships[]` schema

| Sub-field | Notes |
|---|---|
| `target_entity` | Target entity **id** (resolution is by id). |
| `relationship_type` | **Closed set**, validated: `one_to_one\|one_to_many\|many_to_one\|many_to_many`. This is the canonical name — **`cardinality` in the edge index is an alias of this same field**, applied on write, not a second key. (ASK Spec Sec 7.3 lists both names; that is prose sloppiness, not a two-field design — the spec never gives `cardinality` its own value domain, default or consumer.) The reverse edge's cardinality is derived from this pairwise (Sec 6.5.1), so an out-of-set value does not merely mislabel one edge — it can cost the entire join graph. |
| `join_condition` | Full SQL predicate (multi-key with `AND`). Stored and rendered **verbatim** — write it exactly as it must appear after `ON`, including non-equality terms such as `IN (...)`. Qualifiers are governed by [§6.2.1](#621-the-qualifier-contract). |
| `semantic_label` | Short business verb (`sold_to`, `fulfilled_from`). Shown on the graph edge. Note ASK does **not** adopt spec Sec 21.4's directional grammar (`_by` / `_to` / `_of` by edge direction) — the shipped convention is an active business verb in snake_case, and generated reverse edges are `reverse_of_<label>`. |
| `traversal_cost` | Dijkstra weight. See [§6.3](#63-traversal_cost-rubric). |
| `aggregation_safety` | **Closed set**, validated: `safe\|requires_dedup\|unsafe`. See [§6.4](#64-aggregation_safety). |
| `cross_module` | `true` if it crosses module boundaries. |
| `description` | Business meaning + traversal caveat. See [§8](#8-writing-descriptions). |

### 6.2.1 The qualifier contract

**Every qualifier is the `db_table_name` of its own side.** A `join_condition` names exactly two
tables — this entity's `db_table_name` and the target entity's `db_table_name` — and nothing else.

Two spellings are wrong and both ship broken SQL:

- **The entity `id` instead of the physical table.** `SILVER_S4H_SD_SALES_ORDER` is an id; the
  table is `SILVER_SD_SALES_ORDER`. Ids resolve entities in the catalog, they are not selectable
  objects. A predicate qualified by an id cannot execute.
- **A third table that is neither endpoint.** If the join only works by passing *through* a third
  entity, that is **two edges, not one** — declare the hop to the intermediary and let the
  intermediary declare its own edge onward. A predicate naming a table absent from the `FROM` list
  is not a join; it is a syntax error waiting to be generated.

The predicate goes verbatim into the SQL-generation prompt as an authoritative join condition, so
a wrong qualifier is not cosmetic — the model is instructed not to invent replacements for it.

**Checked at ingestion, and it is what identifies the two physical tables.** The indexer
extracts the qualifiers from the predicate: the one matching this entity's `db_table_name`
becomes the edge's `source_table`, the other becomes `target_table`, and both are printed in
the SQL prompt next to the entity ids (`entity_id (table: PHYSICAL_NAME)`) so nothing has to
infer that `silver_s4h_sd_sales_order` and `SILVER_SD_SALES_ORDER` denote the same object. A
predicate that fails to name its own side, or that names more than two tables, is **logged as
a contract violation** — never fatal, because a bad qualifier must not abort an ingestion, but
it does mean the edge reaches the prompt with an unidentified endpoint.

### 6.3 `traversal_cost` rubric

Weight used by the path Dijkstra: **lower = preferred**. **Floats are allowed** (the
original spec said integer 1–10; we use floats for finer ranking — this is the standard).

| Cost | Situation |
|---|---|
| **1** | Direct FK, same module. Natural, cheap join. |
| **1.5 – 2** | Direct FK, cross-module. |
| **3** | Bridge / `many_to_many` / `requires_dedup` (grain changes). |
| **4+** | Dimension **already flattened in the Gold** → discourage; "only traverse for raw attributes not in the Gold". |

Calibrate so the cheapest path is also the *correct* one — never make an unsafe or
grain-breaking path look cheap.

### 6.4 `aggregation_safety`

**Edge-scoped, never field-scoped.** This key lives on `relationships[]` and describes a
*traversal*. The field-level aggregation axes are `aggregation_behavior` and
`additivity` / `non_additive_over` ([§4](#4-fields)) — different object, different trigger.

| Value | Meaning | Agent behaviour |
|---|---|---|
| `safe` | Join does not change grain of measures. | Aggregate freely. |
| `requires_dedup` | Join fans out rows (`one_to_many`, `many_to_many`, partner tables). | Reduce the base to one row per its `entity_grain` **before** the join. |
| `unsafe` | Join structurally breaks aggregation. | The edge is **removed from the traversal graph** — no path is built through it. |

**What `requires_dedup` means, precisely.** Traversing the edge **multiplies rows on the base
side**, so any measure of the base must be reduced to one row per its `entity_grain` *before*
the join — aggregate it in a CTE, or `DISTINCT` on its grain key. It is a statement about row
multiplication, not about duplicate values.

> **It is NOT "insert `SELECT DISTINCT`".** A bare `DISTINCT` over the output projection is
> wrong in both directions: it fails to dedup when the projection carries the drill-down
> column the user asked for (you get the multiplied total), and it *over*-deduplicates when it
> does not, collapsing rows that are legitimately identical. On a 1:N grain-change join whose
> true answer is 1000, the same bare `DISTINCT` returns 2000 in the first case and 500 in the
> second. It is correct only when the projection happens to equal the grain — precisely the
> case that needed no dedup at all.

**Two enforcement levels — advisory for dedup, structural for `unsafe`.** SQL generation here
is a freeform LLM generator, not the origin spec's deterministic compiler; that divergence is
permanent and deliberate. So `safe` / `requires_dedup` reach the model as a **prompt rule**,
emitted alongside the cardinality in the cross-entity join-path block (`_format_edges_hint`,
`freeform_generator.py`), with `sql_scope_validator` auditing the result rather than rewriting
it — the model can still get it wrong. `unsafe` is stronger and does not depend on the model:
the edge is excluded when the traversal graph is built (`path_resolver._build_graph`), so no
path can be produced through it. Exclusions are logged, because "no path found" and "no edge
declared" are otherwise indistinguishable downstream.

**Defaults to the cardinality; set it to override.** The authoring surfaces derive the
default from the cardinality (`deriveAggSafety`), and across every authored edge in both
workspaces `requires_dedup` holds exactly when the cardinality is `one_to_many` or
`many_to_many`. Write the key explicitly only when you mean to *diverge* from that default —
e.g. an FK pattern that provably cannot fan out (`safe` on a `one_to_many`), or a join that
must not be traversed at all (`unsafe`). The value is indexed on the edge document and read
back per edge, so an override is honoured rather than re-derived.

**On the auto-generated reverse edge it is derived, not copied.** Fan-out is directional: if
`A --one_to_many--> B` multiplies rows on A's side, the reverse `B --many_to_one--> A`
multiplies nothing, so copying `requires_dedup` backwards would make the agent dedup for no
reason. The reverse edge — which nobody authors — takes its value from its own (inverted)
cardinality. The single exception is `unsafe`, which propagates both ways: a structurally
broken join is broken in either direction.

**Composes with additivity, in this order:** dedup across the edge first, then collapse
`non_additive_over` within the grain. They are two different hazards that produce the same
user-visible symptom (a double-counted `SUM`), and applying one does not excuse the other.

**Golden rule:** never `SUM`/`COUNT` a measure after a `one_to_many` / `many_to_many`
hop without grain-aware dedup. State this in the edge `description` when relevant — the
description is indexed on the edge document and rendered into the SQL prompt beneath its
`ON` clause, so a caveat written there reaches the model even when the entity's own YAML was
not retrieved.

---

## 7. Naming & IDs

- Canonical Silver grammar: `silver_<source>_<module>_<entity>`.
- **The module segment is OPTIONAL and its absence is meaningful**: shared dimensions /
  config / `*_txt` tables (e.g. `plant`) legitimately omit a single module (cross-module
  **Golds** omit it too — see [./GOLD_LAYER.md](./GOLD_LAYER.md)). The real classification
  lives in the `module` field. **Do not "normalize" ids by forcing a module in — it would
  be less correct and would break every `target_entity` reference.**
- The `id` is a stable key; treat it as immutable. Renaming an id is a breaking change
  (ripples into `relationships`, `composed_of`, OpenSearch indices, prompts).

---

## 8. Writing descriptions

Descriptions are consumed **twice**: (1) as **embedding text** for hybrid retrieval, and
(2) as **context** in the SQL-generation prompt. So a description is a *signal*, not
documentation prose.

### 8.1 The principle — signal, not length

> **It is not "short vs long." It is "signal vs filler."**
> A four-line description where every clause changes a decision is excellent.
> A one-line description that restates the field name is waste.

Bloated, filler-heavy descriptions **hurt twice**: they dilute the embedding (the
distinctive term drowns in boilerplate, so retrieval gets *less* precise) and they burn
prompt tokens while over-constraining the agent.

### 8.2 Two tests, not one

Before writing (or keeping) a clause, ask **both**:

> **Test 1 — does it earn its place?**
> "Would removing this change which column, table, JOIN, or aggregation the agent picks?"
> If **no** → cut it.

> **Test 2 — is it already carried?**
> "Which *other key* in this file already states this fact?"
> If one does → cut it. **The key is authoritative; the prose is a copy.**

**Test 1 alone is not enough, and this is the failure it misses.** Take an entity description
that opens *"…at material + plant level"* and closes *"Grain: client + plant_id + material_id"*.
Test 1 passes twice — knowing the grain absolutely changes what the agent picks. Test 2 fails
twice: `grain.entity_grain` already states it, authoritatively. And the two clauses have already
drifted apart, disagreeing about whether `client` is in the key, inside one paragraph. That is what
a second carrier does.

So the rule is not "be brief". It is:

> **Every fact has exactly ONE authoritative carrier. A description carries the facts that have
> no other carrier — and nothing else.**

That reframes the question from taste ("is this too long?") to structure ("does a key already
own this?"), which two reviewers can agree on.

### 8.3 What a description SHOULD carry (signal)

- **Disambiguation** against look-alikes — *"transportation zone (VBPA.LZONE), NOT a sales territory."*
- **Aggregation hazards** — *"already cumulative — take the last value per (plant, material); do NOT SUM."*
- **Grain / dedup warnings** on relationships — *"grain changes to invoice line; dedup before SUM."*
- **When-to-use vs which-field-instead** — *"for OPEN/CLOSE use `order_status`; for partial-vs-open use `ovrll_sts`."*
- **Code meanings** when not obvious — *"'A' = open, 'B' = partial, 'C' = closed."*
- **Inline synonyms** for retrieval — *"demand quantity / sales order quantity."*
- **Denormalization hints** — *"use directly; no need to JOIN `silver_s4h_sd_plant` for the name."*
- **Units / sign conventions** — *"POSITIVE = days remaining; NEGATIVE = overdue."*

### 8.4 What it should NOT carry (filler)

- ❌ Restating the field name or type — `customer_id` → *"Customer ID"* adds nothing.
- ❌ Restating role/aggregation already structured — the `aggregation_behavior` field
  already says `SUM`.
- ❌ Vague boilerplate on relationships — *"Join to Material Master for material attributes."*
- ❌ Marketing prose, or long multi-clause sentences that bury the key term.
- ❌ Repeating the entity description inside every field.

### 8.5 The recipe — what each level may carry

Apply Test 2 mechanically and the allowed content falls out. These are not style preferences;
each right-hand column is the list of keys that would make the prose a duplicate.

**Entity `description`**

| May carry — nothing else does | Never carry — this key owns it |
|---|---|
| The business **question** it answers, in the words a user would type ("current stock position", "ATP rough cut"). | The grain columns → `grain.entity_grain` |
| **When to pick it over a near-neighbour** — the one thing no relationship expresses. | What one row is → `grain.business_grain` |
| A load-bearing **absence**. "No date dimension, so it cannot answer *as of last month*" — a field list can only show what is there, never what is missing. | The field inventory → `fields[]` |
| | Any field's value mapping → that field's own `description` |
| | Fact vs dimension → `entity_role`; module → `module`; physical table → `db_table_name` |

**Field `description`**

| May carry — nothing else does | Never carry — this key owns it |
|---|---|
| **The value enumeration.** `'A' = open, 'B' = partial, 'C' = closed`. No key holds an enum, so for a `status_flag` this is the whole job. | The field name restated → `name` |
| **Sign / unit conventions.** "POSITIVE = days remaining, NEGATIVE = overdue"; "quantity is in the SALES unit, not the base unit". | The data type → `type` |
| **Which sibling to use instead.** "For a binary OPEN/CLOSE use `order_status`." | Where it may appear → `field_role` |
| **The upstream column**, when it aids recognition — `(MARD.LABST)`. | Which function to aggregate with → `aggregation_behavior` |
| **A lifecycle flag to filter out** — "use to exclude deleted items". The one hazard no key expresses. | What to collapse first → `additivity` + `non_additive_over` |
| Inline synonyms, woven into the sentence. | The entity's own context — "…in the sales order" |

**Relationship `description`**

| May carry — nothing else does | Never carry — this key owns it |
|---|---|
| **Why you would traverse it**, in business terms beyond the label. | Cardinality → `relationship_type` |
| **"Already denormalised here — don't."** The single most useful sentence an edge can carry. | The predicate → `join_condition` |
| **What changes about the grain** after traversing. | Whether it fans out → `aggregation_safety` |
| | The cost → `traversal_cost`; the verb → `semantic_label` |

> **Length is a symptom, not a rule.** §8.1 still holds — four decision-relevant lines beat one
> line of filler. But once Test 2 is applied, an entity description lands around 20–40 words and a
> field description around 5–20. **If yours is past 60, look for a restated grain or a field
> inventory** — that is what the extra words almost always are.

#### `status_flag` — the one field type with a fixed shape

Lead with the value mapping and stop.

```yaml
description: "Deletion indicator (VBAP.LVORM): X = marked for deletion, blank = active."
description: "RAW overall status from VBUK.GBSTK: 'A'=open, 'B'=partial, 'C'=closed. For a
              binary OPEN/CLOSE use `order_status`."
```

No "this field is used to determine whether…". No synonyms — nobody types the synonym of a flag.
**If you do not know the values, skip the field and leave the description empty** rather than
write prose about it: an empty description costs recall, a wrong value mapping silently breaks
every `WHERE` clause built on it.

### 8.6 Examples — from real entities

**❌ Filler (from `gold_s4h_sd_open_order_tracker`)** — these restate the name and waste embedding signal:

```yaml
- name: customer_id
  description: "Customer ID"                       # adds nothing over name+role
- name: channel
  description: "Distribution Channel Description"   # restates the name
```
Fix: either omit the description, or make it earn its place:
```yaml
- name: customer_id
  description: "Sold-to party (KNA1.KUNNR). For the name use the denormalized `customer` field."
```

**❌ Vague relationship (same file):**
```yaml
- target_entity: silver_s4h_sd_sales_organization
  semantic_label: sold_by_org
  traversal_cost: 1
  description: "Sales organization responsible for the order"   # says nothing actionable
```
Fix — make the denormalization explicit and price it accordingly:
```yaml
- target_entity: silver_s4h_sd_sales_organization
  semantic_label: sold_by_org
  traversal_cost: 4
  description: "Sales org owning the order. The org NAME is already denormalized as `sales_org`
                — only traverse for other org attributes."
```

**✅ The bar — keep descriptions like these (already in `open_order_tracker`):**

```yaml
- name: delivery_priority
  field_role: status_flag
  description: "Delivery priority (VBAP.LPRIO). SAP scale 1-99 where LOWER = MORE URGENT
                (1 = rush). Exact bucket meanings are per-customizing — do not assume only 1-3."

- name: ovrll_sts
  field_role: status_flag
  description: "RAW overall status from VBUK.GBSTK: 'A'=open, 'B'=partial, 'C'=closed. Use to
                distinguish partial from fully-open. For a binary OPEN/CLOSE use `order_status`."

- name: delivery_time
  field_role: measure
  description: "Lead time in days = DAYS_BETWEEN(event_ts, delivery_date). POSITIVE = days
                remaining; NEGATIVE = overdue. Uncapped — for the capped bucket see `delivery_status`."
```
Each clause changes a decision: which column to pick, how to read the values, what NOT to do, and which sibling field to use instead.

**✅ Simple boolean status_flag (the common case):**

```yaml
- name: lvorm_vbap
  field_role: status_flag
  description: "Deletion indicator (VBAP.LVORM): X = marked for deletion, blank = active."
  # Synonyms intentionally omitted — flag values have no useful synonyms.
```
The bar for a boolean is value-mapping + nothing else. No `"This field is used to ..."` prose.

**❌ Over-cooked status_flag (anti-pattern AI tends to produce):**

```yaml
- name: lvorm_vbap
  field_role: status_flag
  description: "This boolean indicator field is used to determine whether the sales order
                item record has been marked for logical deletion in the SAP system,
                allowing downstream consumers to filter out items that should no longer
                be considered active for business operations."
  synonyms: ["deletion", "deleted", "marked for deletion", "logical delete"]
```
Why it's bad: 40+ words of filler ("This boolean indicator field is used to..."), no value
mapping, and synonyms that don't help retrieval (no user asks "show me items marked for
deletion using their synonym").

**✅ A golden relationship (gold→gold, from the same Gold file — the description style rules
are shared across layers; a Silver itself never declares an edge to a Gold,
[§6.1](#61-direction-rules)):**
```yaml
- target_entity: gold_s4h_mm_inventory_position
  semantic_label: covered_by_current_stock
  traversal_cost: 3
  description: "Cross-fact lookup: enrich each open order line with current stock (on_hand,
                allocated, safety_stk) of its (plant, material). Use for ATP/coverage:
                'can we fulfill this order from current stock?'."
```

### 8.7 Entity description — worked

A shape authors reach for — the example is a Gold, but the cure is identical at Silver, where
`join_graph` and `composed_of` give prose two more keys to duplicate:

> ❌ *"Current physical inventory snapshot at material + plant level. Aggregates the MARD
> storage-location buckets (on_hand, in_transit, on_order, in_quality_control, allocated, damaged)
> plus MARC parameters (max_level, safety_stk), with calculated stock_status (Out of Stock / Low
> Stock / Balanced Stock / Excess Stock). Grain: client + plant_id + material_id. Use for current
> stock position, ATP rough cut, stock health classification."*

| Clause | Already carried by |
|---|---|
| "at material + plant level" | `grain.entity_grain` — **and it disagrees**: the grain includes `client`. |
| "Grain: client + plant_id + material_id" | `grain.entity_grain`, again. One fact, twice, two ways. |
| "Aggregates the MARD storage-location buckets (on_hand, in_transit, …)" | `fields[]`. A table of contents for the list immediately below it. |
| "MARC parameters (max_level, safety_stk)" | `fields[]`. |
| "calculated stock_status (Out of Stock / Low Stock / …)" | `stock_status.description`, which carries the same four values. |
| "physical … snapshot" | `layer: gold` + `entity_role: fact`. |

What survives is what no key can state — the question it answers, the pointer to a neighbour it
has no edge to, and the absence:

> ✅ *"Current stock position per material and plant. Point-in-time only — there is no date
> column, so it cannot answer "stock as of last month"; for a forward projection use
> `gold_ecc_inventory_situation`. Common uses: stock health, ATP rough cut."*

37 words from 66. It keeps "ATP" and "stock health" because those are **retrieval vocabulary a
user types and no other key holds**, and it keeps the absence because a field list can only show
what is there. The field inventory goes: it was diluting the entity's own embedding against the
very fields it listed.

---

## 9. Authoring checklist

Before committing a Silver YAML:

- [ ] Every `fields[].source` is a real column; every `relationships[].join_condition` uses real keys.
- [ ] **`fields[].name` is unique within the file.** A repeated field block is never
      meaningful — it only inflates the `raw_yaml` the SQL prompt pays for.
- [ ] **One `join_graph` entry per `(left_table, right_table, sequence)`.** A composite key
      is ONE entry with an `AND`-composed `condition`, never one entry per key column —
      each single-key entry taken alone is a fanning join. See
      [§3.2](#32-the-join_graph-sequence-convention).
- [ ] **`join_graph[].sequence` starts at 2** — the anchor holds the implicit position 1
      ([§3.2](#32-the-join_graph-sequence-convention)).
- [ ] **Every column named in a `join_graph[].condition` exists in that side's Bronze.**
      Resolve both sides against the `composed_of` Bronze field dicts, not by eye.
- [ ] **Every qualifier in a `join_condition` is the `db_table_name` of its own side** —
      never the entity `id`, never a third table. See [§6.2.1](#621-the-qualifier-contract).
- [ ] `field_role` set on every field (and `attribute` vs `dimension` chosen correctly).
- [ ] `grain.entity_grain` matches the physical key.
- [ ] Every `grain.entity_grain` member is a `fields[].name` — a selectable column, not a
      source-system code ([§3.1](#31-how-entity_grain-is-derived)).
- [ ] The grain is MINIMAL: no member is redundant given the `join_graph` predicates
      (rule 7 asserts subset-pinning returns many rows, which a superkey makes false).
- [ ] Silver facts can reach their dimensions via their **own** relationships (fallback works).
- [ ] `aggregation_safety` set on any fan-out edge; no cheap unsafe paths.
- [ ] `traversal_cost` follows the [§6.3](#63-traversal_cost-rubric) rubric.
- [ ] Descriptions pass the [§8.2](#82-two-tests-not-one) test — no filler, signal only.
- [ ] `id` unchanged (or you have updated every reference to it).

*(These are the candidate rules for an automated linter / the visualizer's connectivity check.
The four bolded rules above are specified for implementation in the internal design doc
(REQ_YAML_LINTER_RULES).)*

---

## 10. Prohibitions (deprecated from the ASK Spec)

Do **not** author these on a Silver — they are deprecated spec constructs with no consumer:

- `rbac_roles` embedded in YAML → access control is handled by **profile/scope**, not in the model.
- `primary_measures` / `available_dimensions` / `entity_sub_type` registry fields → derivable from `fields`.
- `depends_on` as a *compute* dependency → use plain `relationships`.
- Standalone `layer: metric` YAMLs → **removed**; ingestion raises. A measure is a
  `field_role: measure` field with `aggregation_behavior` on its owning Silver/Gold.

The full deprecation register lives in [./README.md](./README.md).

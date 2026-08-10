# ASK Semantic Layer — Authoring Standards

> **Status: AUTHORITATIVE & MAINTAINED.** This folder is the source of truth for how
> Bronze / Silver / Gold YAMLs are authored. It supersedes the parts of the ASK
> Specification that no longer match reality — see
> [Appendix A](#appendix-a--deprecated-from-the-ask-spec).
>
> It is also the **source for prompt engineering**: `get_standards_excerpt(layer)`
> (`ask-admin-api/system_prompts_service.py`) injects the matching **layer file, whole**,
> into the enrichment prompts, and the agent's retrieval / SQL-generation prompts are
> derived from these rules. Change a rule here first, then propagate it to the prompts.

## Files

| File | Scope |
|---|---|
| [BRONZE_LAYER.md](BRONZE_LAYER.md) | Bronze: physical schema binding — columns, types, keys, aliases, isolation. **Single home of the canonical type-system tables.** |
| [SILVER_LAYER.md](SILVER_LAYER.md) | Silver: curated business entities — grain, `composed_of` + `join_graph`, fields, `field_role`, relationships, costs, safety, descriptions. |
| [GOLD_LAYER.md](GOLD_LAYER.md) | Gold: denormalized physical tables — authored `entity_role`, the edge-vs-denormalization rule, gold authoring rules, prohibitions. |

Each layer file is **self-contained** (it is injected into LLM prompts whole) and carries an
authority banner: when it disagrees with its counterpart in
[`agentic-semantic-knowledge-ask`](https://github.com/Onibex/agentic-semantic-knowledge-ask),
the file in this folder wins and the counterpart is corrected.

## Maintenance rule — shared contracts are duplicated on purpose

The owner chose public-style **per-layer self-containment over single-sourcing**: shared
contracts are repeated (scoped) in every layer file that needs them. The price is drift
risk; this table is the register of what must be edited **together**. A test
(`ask-admin-api/tests/unit/test_standards_excerpt.py`) pins the load-bearing markers
in each file.

| Shared contract | Lives in |
|---|---|
| `grain.entity_grain` — published-column vocabulary + minimality (rule 7 needs both) | SILVER §3.1 (incl. the derivation) · GOLD §3.2 (incl. the uniqueness query) |
| Two-axis aggregation (`aggregation_behavior` + `additivity`/`non_additive_over`) — incl. the v2 any-grain-dimension rule and the ingest derivation | SILVER §4.1 · GOLD §4.1 |
| `field_role` taxonomy (+ `status_flag`, temporal gap) | SILVER §6 · GOLD §5 |
| `relationships[]` schema, direction rules, `traversal_cost` rubric, `aggregation_safety` | SILVER §7 · GOLD §6 |
| Writing descriptions | SILVER §9 · GOLD §9 |
| Canonical type system (full tables) | **BRONZE §3.6 only** — SILVER/GOLD carry the rule + a pointer (the one sanctioned cross-link) |
| Naming & id grammars | each file, scoped (BRONZE §4 · SILVER §8 · GOLD §7) |
| Header-key applicability | each file's §2 (per-layer tables; the cross-layer matrix is gone by design) |

## 1. Why this layer exists (the SQL-generation contract)

The ASK semantic layer exists for **one purpose: to let the agent build deterministic
SQL.** It is **not** a runtime query engine, cube, or OLAP layer (the original spec
modelled Gold as an AtScale-style "orchestrated computation graph" — that framing is
**deprecated**, see Appendix A).

Three consequences drive every rule in this folder:

1. **Every field maps to a real, selectable column.** `source` / `db_table_name` are physical.
2. **Every relationship is a real JOIN** the agent may emit. Edges are not documentation.
3. **Gold is a physical denormalized table** you `SELECT FROM` (it has a `db_table_name`),
   not a computed view materialized at query time.

If a YAML construct cannot be turned into SQL, it does not belong here.

## 2. The two-plane resolution model

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
  (b) drilling down to detail (`one_to_many`).
- Retrieval priority (gold-first) — not the presence of edges — decides which plane is
  used. Having edges on Silver does not undermine gold priority.

## 3. Layers

| Layer | One YAML per | Role | Key idea |
|---|---|---|---|
| **Bronze** | source table (VBAK, KNA1…) | Physical schema binding | NO join semantics. Just columns + keys. |
| **Silver** | curated business entity / Data Product | Semantic ontology node | Single source of truth for join topology (`composed_of` + `join_graph` + `relationships`). |
| **Gold** | denormalized data product table | Pre-joined analytics table | A physical table you `SELECT FROM`. Dimensions flattened in; relationships are optional drill/enrich + gold→gold lineage. |

> **`metric` is REMOVED** (standalone `layer: metric` YAMLs). It is no longer a layer: the
> ingestion path rejects it, the models and the renderer are gone, and retrieval never returns it.
> A business measure is just a field with `field_role: measure` + `aggregation_behavior` on
> the Silver/Gold that owns it — no separate node. See [Appendix A](#appendix-a--deprecated-from-the-ask-spec).

## Appendix A — Deprecated from the ASK Spec

The ASK Specification modelled Gold as an AtScale-style runtime engine.
That does not apply to a SQL-generating layer. **Do not author these:**

- Gold as "Orchestrated Computation Graph" / KPI compute / multi-step workflow / "delegate to external systems".
- `InputStateSchema` / `OutputStateSchema` contracts.
- "ASK Kernel runtime" / "pre-computed analytical entities" framing; spec §22–25 (MCP/A2A gold orchestration).
- Gold `depends_on` as a *compute* dependency → use plain `relationships` (gold→silver/gold) + `db_table_name`.
- `rbac_roles` embedded in YAML → access control is handled by **profile/scope**, not in the model.
- `primary_measures` / `available_dimensions` / `entity_sub_type` registry fields → derivable from `fields`.
- Bronze `foreign_keys[]` / `referenced_tables` → join truth lives in Silver; at most an ingestion-time hint, not runtime.
- **The `metric` layer** (standalone `layer: metric` YAMLs with `home_entity` / `base_field` /
  `aggregation_function`) → **removed**. A measure is a `field_role: measure` field with an
  `aggregation_behavior` on its owning Silver/Gold; the agent aggregates it directly in SQL. No
  separate measure node, no measure registry. *(Cleanup done: the metric YAMLs, the `MetricNode`
  model, the write path, the renderer and the retrieval defaults are all gone; ingesting a
  `layer: metric` YAML now raises. The one remaining step is purging any legacy metric documents
  from the registries — see the internal design doc (REQ_METRICS_PURGE).)*

Also reconciled in this folder: the spec's own ID-grammar inconsistencies (Spec §21.1 vs
§15.4 / §5.1) → see each file's Naming section. `traversal_cost` is a **float** (spec said
integer) → see SILVER §7.3 / GOLD §6.4.

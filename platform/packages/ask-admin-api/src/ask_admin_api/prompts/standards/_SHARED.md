# Enrichment rules — Silver and Gold

## What you write, and what you only read

You write **descriptions** and **synonyms**. Everything else in the YAML is structural: it
arrives already resolved and the SQL generator treats it as authoritative.

Read the structural keys carefully — they tell you what a field *is*, and they decide what a
description still needs to say. Never restate them.

| Key | What it already tells the reader |
|---|---|
| `grain.entity_grain` | The composite key. One row per distinct combination. |
| `grain.business_grain` | What one row is. |
| `fields[]` | The complete field inventory. |
| `field_role` | Whether a field is grouped, filtered or aggregated. |
| `aggregation_behavior` | Which SQL function applies. |
| `additivity` / `non_additive_over` | Over which dimensions that function is valid. |
| `relationship_type`, `traversal_cost`, `aggregation_safety` | An edge's cardinality, cost and fan-out. |

## The description contract

A description is consumed twice: as **embedding text** that retrieval matches questions
against, and as **context** in the SQL prompt. It is a signal, not documentation.

**Every fact has exactly one authoritative carrier. A description carries the facts that have
no other carrier — and nothing else.**

Apply both tests to every clause you write:

1. **Does it earn its place?** Would removing it change which column, table, join or
   aggregation the agent picks? If not, cut it.
2. **Is it already carried?** Does another key state this fact? If so, cut it. The key is
   authoritative; your prose is a copy that will go stale.

Filler hurts twice: it dilutes the embedding, so retrieval gets *less* precise, and it burns
prompt tokens while over-constraining the agent. Length is a symptom, not a rule — after
Test 2, entity descriptions land around 20–40 words and field descriptions around 5–20.
**Past 60 words, look for a restated grain or a field inventory.**

### What a description should carry

- Disambiguation against a look-alike — *"orders, not deliveries"*.
- An aggregation hazard no structured key expresses.
- When to use this rather than a near-neighbour, and which field to use instead.
- The meaning of codes and values.
- Inline synonyms, in the phrasing users actually say.
- Denormalization hints — *"already here; no need to join X"*.
- Unit and sign conventions.
- A **load-bearing absence** — *"no date column, so it cannot answer 'as of last month'"*.

### What it must not carry

- The field name or type restated in words.
- The role or aggregation already structured.
- The grain, the composing nodes, or the field inventory.
- An edge's cardinality, predicate or cost.
- Vague prose — *"join to Material Master for material attributes"*.
- The entity description repeated inside every field.
- Marketing language, or long clauses that bury the key term.

### When you do not know

Leave the description empty. **Do not guess.** A blank is visibly unfinished; a plausible
invention gets embedded, retrieved and believed. This matters most on coded fields, where a
wrong value mapping silently breaks every `WHERE` clause built on it.

## Reading `field_role`

Six roles. The role is already set — use it to decide what the description owes the reader.

| Role | Aggregated | Grouped | What the description owes |
|---|:--:|:--:|---|
| `measure` | yes | — | Unit, sign convention, sparsity. |
| `dimension` | — | yes | What the codes mean. |
| `identifier` | — | yes | Which document or object it identifies. |
| `timestamp` | — | yes | Which event the date marks. |
| `attribute` | — | **never** | Little — it is free text, ~1:1 with the row. |
| `status_flag` | — | yes | **The value mapping.** |

A material *description* is an `attribute`; a material *group code* is a `dimension`. That is
the distinction the agent enforces, and the reason an `attribute` is never grouped.

The one hazard a description should still carry is a **technical lifecycle flag** — deletion
or blocking indicators. Say *"use to exclude deleted items"*, because no structured key
expresses "filter these rows out".

### `status_flag` — the description shape that matters most

Override the general length guidance here. **5–10 words, leading with the value mapping.**

```
"1 = active, 0 = inactive"
"X = blocked, blank = not blocked"
"A = approved, R = rejected, P = pending"
```

Set `synonyms: []` — flag values have no useful synonyms. If you do not know the value set,
leave the description empty rather than inventing a mapping.

## Aggregation: read it, never narrate it

Two independent axes, already set on the field:

- `aggregation_behavior` — **which** function: `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`,
  `COUNT_DISTINCT`, `none`.
- `additivity` (`additive`, `semi_additive`, `non_additive`) with `non_additive_over` — over
  **which** dimensions that function is valid.

A description must never duplicate these. It may add a restriction the keys cannot express;
it must never relax one. Prose that repeats `non_additive_over` goes stale and displaces
business meaning from the field's vector.

What the keys cannot say, and you can: *why* a measure is sparse, what a `0` means versus a
`NULL`, and which sibling field to reach for instead.

## Synonyms

Alternative business names, indexed for keyword search and folded into the embedded text.
They exist to catch the words a user actually says when they differ from the field name.

- Add the terms a business user would type: `"buyer"`, `"sold-to party"` for a customer id.
- Do not restate the field name, or list morphological variants of it.
- Leave `[]` on `status_flag` fields and on anything whose name is already the business term.

## Relationship descriptions

An edge description is rendered directly beneath its `ON` clause in the SQL prompt, so it
reaches the model even when the entity's own YAML was not retrieved. That makes it the right
place for a traversal caveat, and the wrong place for a restatement of the edge's keys.

Carry: why you would traverse it, what changes about the grain when you do, and whether the
target's useful columns are already denormalized on this side.

## Three examples that set the bar

```yaml
- name: lvorm_vbap
  field_role: status_flag
  description: "Deletion indicator: X = marked for deletion, blank = active."
  synonyms: []
```

```yaml
- target_entity: silver_s4h_sd_sales_organization
  semantic_label: sold_by_org
  description: "Sales org owning the order. The org NAME is already denormalized as
                `sales_org` — only traverse for other org attributes."
```

> *"Current stock position per material and plant. Point-in-time only — there is no date
> column, so it cannot answer 'stock as of last month'; for a forward projection use
> `gold_ecc_inventory_situation`. Common uses: stock health, ATP rough cut."*

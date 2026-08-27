# Silver — what changes at this layer

A Silver is a **reusable enterprise entity** — Customer, Sales Order, Material — composed
from one or more raw source tables and exposed with a declared grain. It is a building block,
not an answer to a specific business question.

That is the frame for every description you write here: a Silver is reached when **no Gold
answers the question**, and it is chosen for what it *is*, not for what it reports.

## Why the entity description carries more weight here

When no Gold covers a request, the agent anchors on a Silver and walks its relationships to
find the dimensions it needs. Your entity description is a large part of how it decides that
this is the right anchor.

So say what the entity **is**, in the vocabulary a business user would use, and what
distinguishes it from its near neighbours:

> *"Sales order header and items, one row per order line. Use for open-order and backlog
> questions. For delivered quantities use the delivery entity instead — this one carries
> ordered quantities only."*

Note what that does: it names the thing, states when to reach for it, and points elsewhere
when it is the wrong choice. It does **not** list the grain columns, the composing tables or
the fields — `grain`, `composed_of` and `fields[]` already carry those.

## Silver preserves codes; Gold interprets them

This is the layer split that most affects field descriptions. A Silver field holds the **raw
source value**, unchanged. It does not map `A`/`B`/`C` to `open`/`partial`/`closed` — a Gold
built on top of it does that.

So a Silver coded field's description must **enumerate the codes**, because nothing else in
the pipeline will:

```yaml
- name: gbstk_vbak
  field_role: status_flag
  description: "Overall processing status: A = open, B = partially processed, C = completed."
```

Without that enumeration the agent has a column and no way to filter on it. This is the
single highest-value description you can write at Silver.

## Reading a Silver field name

Field names are minted at ingest as `<column>_<table>` — `netwr_vbak` is `NETWR` from `VBAK`.
(A deployment may instead mint `<alias>_<table>`; either way the suffix is the source table.)

Use that: the source column is often recognisable to someone who knows the source system, and
naming it in the description aids recognition — *"net value (VBAK.NETWR)"*. Do not turn the
name into a sentence, though: *"the net value field from table VBAK"* restates the name and
carries nothing.

## Dates arrive as text

SAP dates land in a Silver as `VARCHAR 'YYYY-MM-DD'`, not as a native `DATE`, even when
`type` says otherwise. If a date field has quirks a query author would trip over — an initial
value that means "not set", a column that is empty rather than null — that belongs in the
description, because no structured key expresses it.

## Structural keys you will see, and must not narrate

| Key | Already carries |
|---|---|
| `composed_of` | Which raw tables the entity is built from. |
| `join_graph` | How those tables join. Build metadata — not a runtime join. |
| `entity_role` | Derived from `classification`; recomputed on every save. |
| `grain.entity_grain` | The composite key, as published column names. |

Prose that repeats any of these is a second copy that will drift from the first.

## Checklist

- [ ] The entity description says what the entity is and when to choose it over a neighbour.
- [ ] Every coded field enumerates its values — or is left empty if the values are unknown.
- [ ] No description restates the grain, the composing tables or the field list.
- [ ] Synonyms use the words a business user would say, not variants of the field name.

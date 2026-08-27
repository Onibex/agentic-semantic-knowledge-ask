# Gold — what changes at this layer

A Gold is a **physical, denormalized table that answers one business question**: "Open Sales
Order Tracker", "Inventory Position". Every field is a real, selectable column of
`db_table_name`. It composes nothing at runtime — it is already flattened.

Two consequences shape everything you write here.

## Gold is preferred, so its description is the highest-leverage text in the corpus

Retrieval is gold-first: if a Gold answers the question, it wins. Your entity description is
the main thing deciding whether this Gold is recognised as the answer — so write it as **the
business question it answers, in the words a user would ask it**.

> *"Open sales orders with current status, one row per order line. Answers 'what is still
> open', by customer, plant or material. Excludes completed and cancelled lines."*

Three things earn their place there, and little else does:

- **The question it answers**, phrased as a user would phrase it.
- **When to pick it over a near-neighbour** Gold.
- **A load-bearing absence** — what it cannot answer. *"Point-in-time only: there is no date
  column, so it cannot answer 'as of last month'."* An absence is invisible in the schema and
  expensive to discover by running a wrong query.

## Gold interprets what Silver preserved

A Silver holds the raw code; a Gold is where it becomes meaningful. If this Gold derives a
clean status from upstream codes, the description should state the **rule**, not the codes it
came from:

```yaml
- name: order_status
  field_role: status_flag
  description: "OPEN = not fully delivered and not rejected; CLOSED = otherwise."
```

Where a Gold carries an inherited source-code name, the description does the whole job of
making it usable — that is the trade, and it is an acceptable one:

```yaml
- name: ovrll_sts
  field_role: status_flag
  description: "Overall status: A = open, B = partial, C = complete."
```

## Denormalized means: say so, so nothing joins for nothing

Dimension attributes are already columns here. The agent cannot tell that from the schema, so
say it — on the field, and on any edge pointing at the dimension it came from:

> *"Customer name, already denormalized — no need to join the customer entity."*

Relationships at Gold exist for exactly two jobs: reaching an attribute that was **not**
flattened in, and drilling down to detail. An edge to a dimension whose useful columns are
already present should say so plainly, so it is understood as a last resort rather than the
obvious path.

## Sparse measures need their condition stated

A denormalized table that unions several operation types leaves measures populated on only
some rows. Nothing in the schema shows this, and a `SUM` over the wrong subset is silently
wrong:

> *"Delivered quantity. SPARSE: populated only on rows where operation = 'DELIVERY'."*

Same for sentinel values — when `0` means "none" and `NULL` means "not applicable", say which
is which.

## Structural keys you will see, and must not narrate

| Key | Already carries |
|---|---|
| `db_table_name` | The physical table the SQL targets. |
| `grain.entity_grain` | The composite key, verified against real rows. |
| `entity_role` | Authored here, not derived. Default `fact`. |
| `relationships[]` | The joins, their cost and their fan-out. |

A Gold has **no `composed_of`, no `join_graph` and no `source` on its fields** — there is
nothing to compose. If you see them in a file, they are stale: they are dropped on load and
never written back. Do not describe them, and do not invent a replacement in prose.

## Checklist

- [ ] The entity description leads with the business question, in a user's words.
- [ ] It names a near-neighbour to prefer where one exists, and states a load-bearing absence.
- [ ] Derived status fields state the rule; inherited source-code names state the value set.
- [ ] Sparse measures state the condition under which they are populated.
- [ ] Already-flattened attributes say so, on the field and on the edge.
- [ ] No description restates the grain, the physical table or the field list.

# Bronze — enrichment rules

A Bronze node binds ONE source table to the catalog: columns, types, keys, aliases. It
mirrors; it does not model. It carries no `grain`, no `join_graph`, no `relationships`, and
no `field_role` on its fields — business meaning lives on the Silver or Gold that consumes
the column.

## What you may write

| Key | Rule |
|---|---|
| entity `description` | The table's business identity, one line. |
| field `description` | Terse. Usually the source field label verbatim — `Material`, `Created on`. |
| field `alias` | lowercase ASCII snake_case, unique within this file. |

Everything else is structural and arrives already correct. Do not restate it, do not
"improve" it, do not add keys.

## Descriptions are terse here, and that is not a style preference

A Bronze is **never embedded** and its columns **never enter the field registry**. There is
no vector to carry a rich description and no field row to match it. A Bronze is reachable
only by keyword on its `name` and `description` — in practice, by its table name.

So expanding a Bronze description buys nothing, and a long one is pure cost: it is stored,
it is paid for, and it is read by no retrieval path. Keep the source label accurate instead
of elaborating it.

- **0–1 line. Never prose.**
- **No synonyms**, no business phrasing, no "this field is used to…".
- If the source label is already the meaning (`Created on`), that IS the description.
- If you do not know what a column means, leave the description empty. A guess is worse
  than a blank: a blank is visibly unfinished, an invention gets believed.

The one place to spend effort is the entity description, because a table name alone
(`VBAK`, `MARC`) tells a reader nothing:

```yaml
name: VBAK
alias: ORDER_HEADER
description: Sales document header — one row per sales order.
```

## Aliases

Two different things share the name:

- The **entity** `alias` is structural — UPPER_SNAKE (`ORDER_HEADER`), the last segment of
  the `id`. Changing it is a breaking id change. Do not touch it.
- A **field** `alias` is display and lineage only — lowercase snake_case (`sales_doc`).
  Nothing in retrieval or SQL generation reads it.

Rules for field aliases:

- **Unique within the file**, compared case-insensitively.
- Printable ASCII, lowercase, snake_case.
- Digits belonging to the source column name are part of the name, not suffixes:
  `STCD1`…`STCD4` → `tax_no_1`…`tax_no_4`.
- **Never normalise aliases across files.** The same source column may legitimately carry
  different aliases in different Bronzes. There is no canonical alias dictionary, on
  purpose.

## Reading the YAML you are given

`fields` is a **dict keyed by the source column** (`VBELN:`), not a list — Silver and Gold
use a list because their fields are derived, Bronze mirrors the table as it is.

`type` is canonical and source-agnostic — `STRING(10)`, not `C10`. Six bases exist:
`STRING` · `INTEGER` · `DECIMAL` · `DATE` · `TIMESTAMP` · `BOOLEAN`. Read it, never rewrite
it.

Two traps when a type informs your description:

- `STRING(n)` absorbs SAP `Cn` (char), `Nn` (numeric text, **leading zeros significant** —
  document and material numbers) and `Tn` (time of day). The type cannot tell you which.
  Do not claim a column is text, numeric or a time based on it alone.
- An unknown or absent source type silently becomes `STRING`. A `STRING` on an obviously
  numeric column means the source metadata was missing, not that the column is text.

The client / tenant column (SAP `MANDT` and equivalents) is deliberately excluded from the
key — it is pinned by the header instead. Describe it as an ordinary field.

## Checklist

- [ ] Entity description says what the table is, in one line.
- [ ] Field descriptions are the source label, 0–1 line, no prose, no synonyms.
- [ ] An unknown column's description is empty rather than guessed.
- [ ] Field aliases are lowercase snake_case and unique within the file.
- [ ] No key was added, renamed or restated.

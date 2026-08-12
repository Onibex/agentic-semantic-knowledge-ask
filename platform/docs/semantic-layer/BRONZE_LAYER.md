# ASK Semantic Layer — Bronze Standard

> **Status: AUTHORITATIVE for the Bronze layer.** This file is the source of truth for how
> Bronze YAMLs are authored.
>
> It is also **prompt-source material**: the enrichment excerpt injects this file **whole**
> for entities of this layer, so it must stay **complete and self-contained** — never reduced
> to links, never thinned into cross-references. A rule moved out of this file silently
> vanishes from every enrichment prompt.
>
> **Folder-wide exception (by design):** this file is the **single home of the canonical
> type-system tables** ([§3.6](#36-type--the-canonical-vocabulary)); SILVER/GOLD state the
> one-vocabulary rule and point here instead of duplicating the tables.
>
> Its counterpart is
> [`definition/docs/BRONZE_LAYER.md`](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/definition/docs/BRONZE_LAYER.md)
> in the `agentic-semantic-knowledge-ask` repo. **When the two disagree, this file wins and the
> counterpart is corrected to match.**

**Legend:** **R** required · **S** structural (comes from SAP/ingestion — *do not hand-edit*) ·
**E** enrichable (humans curate) · **O** optional. Keys that do not exist at Bronze are
listed separately in [§2](#2-header-keys), not marked with `—` cells.

---

## 1. Role & philosophy

| Layer | One YAML per | Role | Key idea |
|---|---|---|---|
| **Bronze** | source table (VBAK, KNA1…) | Physical schema binding | NO join semantics. Just columns + keys. |

> **Bronze mirrors; it does not model.** A Bronze YAML binds **one** source-system table to
> the catalog — columns, types, keys, aliases — and nothing else. No `entity_role`, no
> `grain`, no `composed_of`, no `join_graph`, no `relationships`, and no `field_role` /
> `aggregation_behavior` on its fields. Join truth lives on Silver
> ([§7 Prohibitions](#7-prohibitions) already forbids Bronze `foreign_keys[]` /
> `referenced_tables`); business semantics live on Silver and Gold, where they are embedded
> and actually reach the agent (see [§3.8 Bronze isolation](#38-bronze-isolation)).

---

## 2. Header keys

**Not every header key exists at every layer.** Bronze is a *different node type*, not a
Silver with fewer keys: it has no `internal_id`, no `db_table_name`, no `module` /
`business_process` / `classification`, and it carries two keys the other layers do not
(`alias`, `primary_key`).

| Key | Bronze | Notes |
|---|:--:|---|
| `id` | R/S | Stable key. Grammar + immutability in [§4 naming](#4-naming--ids). |
| `layer` | R/S | Literal `bronze`; validated, never inferred. |
| `version` | S | Provenance. Bronze defaults to `'1'` when omitted. |
| `source_system` | R/S | Source family token — `s4h`, `ecc`, `generic`, `salesforce`, `odoo`. It selects the type profile, so a wrong token silently changes how `type` is read. |
| `source_system_id` | R/S | Integer client / instance (`100`). **The Bronze spelling.** Silver/Gold spell the same concept `source_system_no` — do not cross them: the wrong one is dropped, not corrected. |
| `name` | R/S | The source table name, UPPERCASE exactly as in the source (`VBAK`). |
| `alias` | R/S | **Bronze only.** UPPER_SNAKE English label (`ORDER_HEADER`). Load-bearing: it is the last segment of the bronze `id` and it is indexed on the entity document. |
| `description` | R/E | Bronze stays terse — see [§5](#5-descriptions-at-bronze). |
| `primary_key` | R/S | **Bronze only**, header-level — see [§3.4](#34-primary_key-and-key_field). Silver/Gold declare their key as `grain.entity_grain` instead ([`./SILVER_LAYER.md`](./SILVER_LAYER.md)). |
| `fields` | R (mix S/E) | **The shape differs by layer**: a dict keyed by source column at Bronze ([§3.1](#31-fields-is-a-dict-not-a-list)), a list of field objects at Silver/Gold. |

**Keys that do NOT exist at Bronze** (writing one is a silent divergence, see the note below):

- `internal_id` — Data-Modeler internal id (`s4h_100_17`). Silver/Gold only.
- `db_table_name` — the physical table the SQL targets, at Silver/Gold. **Bronze has no such
  key** — its physical table *is* `name`.
- `module` — the module that owns / created a Data Product. A raw source table has no module:
  Bronze omits it.
- `business_process` — the process family a Data Product participates in. Silver/Gold only.
- `classification` — `M` master · `T` transactional · `C` configuration. Silver/Gold only.
- `source_system_no` — the **Silver/Gold spelling** of the client / instance. Same concept as
  the Bronze `source_system_id`, different key — do not cross them: the wrong one is dropped,
  not corrected.
- `tag1`, `tag2` — secondary categorization for catalog faceting at Silver/Gold. **Bronze has
  neither.**

> **What `—` means in practice.** An unknown key is *ignored*, not rejected: node validation
> drops it, so it never reaches the catalog while the workspace file still shows it. That is
> a silent divergence, not an error — e.g. a `db_table_name` or `classification` written onto
> a Bronze survives in the YAML and disappears from the catalog.

**Key order in the file** is `id`, `layer`, `version`, `source_system`, `source_system_id`,
`name`, `alias`, `description`, `primary_key`, `fields`.

---

## 3. Bronze body

### 3.1 `fields` is a dict, not a list

**`fields` is a dict keyed by the source column — not a list.**

```yaml
primary_key:
  - VBELN
fields:
  MANDT:
    type: STRING(3)
    alias: client
    key_field: false
    description: Client
  VBELN:
    type: STRING(10)
    alias: sales_doc
    key_field: true
    description: Sales document
  ERDAT:
    type: DATE
    alias: created_on
    key_field: false
    description: Created on
```

Why the shape differs from the Silver/Gold `fields[]` list — these are the reasons, not a
style preference:

- **Source fidelity.** Source documentation and data engineers address columns by name
  (`MATNR`, `VBELN`). A dict keeps the YAML readable the way the table already is.
- **O(1) lookup.** Silver `fields[].source` and `join_graph` conditions reference Bronze
  columns by source name; a dict resolves them without scanning a list.
- **Lineage.** Bronze is one-to-one with the source DDL, so field *order* carries no meaning
  — and must not. A list invites reordering diffs and hides membership.

Silver and Gold use a list because their fields are **derived** (renamed, recomposed,
augmented) and the published order is part of their surface. Bronze mirrors; Silver and Gold
design.

### 3.2 Field sub-keys

**All four are required. There is no optional sub-key at Bronze.**

| Sub-key | Kind | Notes |
|---|---|---|
| `type` | R/S | Canonical type — vocabulary in [§3.6](#36-type--the-canonical-vocabulary). **Never** a source-system code. |
| `alias` | R/S | lowercase ASCII snake_case label. Display + lineage only — see [§3.7 Alias policy](#37-alias-policy). |
| `key_field` | R/S | `true` **iff** the column is listed in `primary_key`. Enforced in both directions. |
| `description` | R/E | Terse: usually the source field label verbatim (`Material`, `Created on`). 0–1 line, never prose — a column's business meaning belongs on the Silver/Gold field that consumes it. |

### 3.3 The field key

The field **key** is the source column name **as-is, uppercase** (`MATNR`, never
`material_id`). Renaming happens through `alias`; re-keying severs lineage and breaks every
Silver `source` pointing at it.

### 3.4 `primary_key` and `key_field`

**`primary_key` + `key_field`.** `primary_key` is the ordered list of source column names
that form the table key — **as declared by the data-product author**. ASK consumes that
declaration as authority: it never reconstructs a key from the source dictionary. The list
must be **duplicate-free**, and every member must exist as a key in `fields`. Agreement with
`key_field` is required in *both* directions: every column in `primary_key` has
`key_field: true`, and every field with `key_field: true` is listed in `primary_key`.
Malformed input is **rejected, not repaired** — normalization (de-duplication, alias
sanitization) happens in the ingestion parser *before* the node is built, so real payloads
pass, while a hand-authored file that disagrees with itself fails validation instead of
ingesting a corrupt key.

The list **may be empty** (decision 2026-08-03): a source table whose export declares no
key ingests as a **keyless Bronze** with a warning naming the table. A missing declaration
is an upstream authoring error — the ASK author escalates it to the data-product admin;
blocking ingestion would only make ASK guess a key it is not the authority for. A keyless
Bronze contributes **no** key columns to the grain of any Silver that composes it, so that
grain cannot express the table's fan-out — and the upstream data itself is suspect (a table
materialized with no declared key collapses N rows per key collision into 1). Treat the
warning as a defect to resolve upstream, not a state to keep.

> **Why "duplicate-free" — and a declared key at all — matters downstream:** the
> `grain.entity_grain` of a multi-table Silver is derived from its Bronzes' `primary_key`
> lists plus the join predicates that bind them. A duplicated Bronze key corrupts the grain
> contract that drives rules 7-8 of the SQL prompt ([`./SILVER_LAYER.md`](./SILVER_LAYER.md));
> a keyless Bronze starves it.

### 3.5 Client / tenant columns are excluded from the key

**Client / tenant columns are excluded from the key.** SAP `MANDT` — and the equivalent
client / tenant column of any other source — is declared as an ordinary field with
`key_field: false` and is **never** listed in `primary_key`, even though it is physically
part of every SAP table key. The client is already pinned by the header
(`source_system_id`), so keeping it in the key only adds a constant to every Bronze key and
to every Silver grain derived from it. This does not conflict with the agreement rule in
[§3.4](#34-primary_key-and-key_field): agreement is defined against the *declared*
`primary_key`, not against the source's physical key. Generated Bronzes comply because the
source export marks the column non-key; hand-authored and DDL-imported Bronzes must apply the
rule deliberately.

### 3.6 `type` — the canonical vocabulary

**`type` — the canonical vocabulary.** Bronze `type` carries the **canonical,
source-agnostic type**, *not* the source-system code: `STRING(10)`, not `C10`;
`DECIMAL(15)`, not `P15`; `DATE`, not `D8`. The authority is the `TypeMapper` in
`ask_knowledge_graph/domain/source_profiles.py`: it parses source codes, SQL types and
canonical strings alike, and `canonical()` renders the exact string stored in the YAML. Six
bases exist, and only these:

`STRING` · `INTEGER` · `DECIMAL` · `DATE` · `TIMESTAMP` · `BOOLEAN`

Valid rendered forms (`CanonicalType.render()` — nothing else is a type):

| Form | When |
|---|---|
| `STRING(n)` | character / numeric-text / raw column with a known length |
| `STRING` | length unknown, absent or zero |
| `DECIMAL(p,s)` | precision **and** a non-zero scale are known |
| `DECIMAL(p)` | precision known, scale absent or zero |
| `DECIMAL` | neither known |
| `INTEGER` · `DATE` · `TIMESTAMP` · `BOOLEAN` | always bare — these never take parameters |

How SAP resolves (the mapper's actual output, not an aspiration):

| Source | Canonical | Note |
|---|---|---|
| `C10` / `C18` / `X16` | `STRING(10)` / `STRING(18)` / `STRING(16)` | char and raw keep their length |
| `N6` | `STRING(6)` | numeric text stays STRING — leading zeros are significant in SAP keys |
| `D8` | `DATE` | the length is dropped |
| `T6` | `STRING(6)` | there is no TIME base; SAP time-of-day is 6-character text |
| `P13` / `P15` | `DECIMAL(13)` / `DECIMAL(15)` | SAP `Pn` carries no scale, so none is rendered |
| `I4` / `S` / `B3` | `INTEGER` | 4- / 2- / 1-byte integers |
| `CLNT` `NUMC` `CUKY` `UNIT` `LANG` `TIMS` | `STRING` | DDIC datatype words |
| `CURR` / `QUAN` / `FLTP` | `DECIMAL` | |
| unknown or absent | `STRING` | never an error — see rule 2 |

1. **Uppercase, no spaces.** `b3` is not a type.
2. **Unknown or absent → `STRING`.** The mapper never raises. Convenient, and a trap: a
   typo'd type does not fail, it silently becomes `STRING`. A canonical `STRING` on an
   obviously numeric column means the source metadata was missing — not that the column is text.
3. **Idempotent.** Re-encoding an already-canonical file is a no-op, so re-ingestion causes
   no type churn.
4. **`TIMESTAMP` and `BOOLEAN` never come from SAP.** They exist for non-SAP sources
   (`DATETIME`, `BOOL`). A SAP-sourced Bronze that declares one was hand-edited.
5. **Type honesty.** The canonical type is *logical*. `DATE` on a SAP `D8` column does **not**
   assert that the physical column is a native date — that is the sharpest case of the gap
   recorded under *Temporal fields (`field_role: timestamp`)* in
   [`./SILVER_LAYER.md`](./SILVER_LAYER.md), and the `CAST(NULLIF(col, '') AS DATE)`
   rule there applies.
6. **Mapped, not invented.** Bronze and Silver resolve each field's `type` from the
   source-system type that arrives in the export, through the table above. Gold publishes the
   same types: the same vocabulary and the same values as the Bronze and Silver columns behind
   it.

> **What canonical drops — know it before you rely on Bronze `type`.** `STRING(n)` absorbs
> three distinct SAP types: `Cn` (char), `Nn` (numeric text, where **leading zeros are
> significant** — SAP document and material numbers) and `Tn` (time of day). So a Bronze
> `type` cannot tell you whether a column is zero-padded or holds a time, and `D8`'s length is
> gone. That information is **not recoverable from Bronze** — go to the source data
> dictionary. This is an accepted trade of the source-agnostic vocabulary, not an oversight.
>
> **One vocabulary, all three layers.** Bronze, Silver and Gold all store the canonical type,
> on every write path — the SAP-JSON ingestion parser, the admin `/import` + `/derive`
> boundary, and hand authoring. There is no per-layer type dialect and no "source-verbatim at
> Bronze" exception; the older rule is **withdrawn**. Source fidelity is preserved by the field
> key and the `description`, not by re-encoding the type.
>
> A `type` that is not one of those rendered forms is not a type. Both raw source codes (`C10`)
> and SQL words (`TEXT`) parse to the same canonical value, so nothing misreads one — but neither
> is canonical, and neither belongs in a file you are authoring or reviewing.

### 3.7 Alias policy

**Alias policy.** Two aliases exist and they are not the same thing:

- The **entity** `alias` (UPPER_SNAKE, `ORDER_HEADER`) is *structural*: last segment of the
  `id`, and indexed on the entity document.
- A **field** `alias` (lowercase snake_case, `sales_doc`) is **display and lineage only.**
  Nothing in retrieval or SQL generation reads it.

The rules:

- **In-file uniqueness is enforced.** Two fields in one Bronze may not share an alias
  (compared case-insensitively, since sanitation lowercases).
- **Cross-file drift is accepted and is not policed.** The same source column may carry
  different aliases in different Bronzes (`WERKS` → `plant` in one file, `plant2` in
  another). There is deliberately **no canonical alias dictionary**: a Bronze field alias
  carries no contract to keep, and forcing one alias per source column would either fight
  legitimate per-context naming or churn ids. Do not "normalize" aliases across files.
- **Character hygiene is enforced at ingestion**, not left to authors: printable ASCII only
  (no mojibake / replacement characters), lowercase, snake_case. On a genuine in-file
  collision the sanitizer appends one single style of ordinal suffix — `_2`, `_3`, … — and
  the first occurrence keeps the bare alias. Digits that belong to the *source column name*
  (`STCD1`…`STCD4` → `tax_no_1`…`tax_no_4`) are part of the name, not dedup suffixes, and
  are preserved.
- **Whether Silver field names are built from the Bronze alias is the deployment's
  column-naming mode** (`ASK_COLUMN_NAMING`, fixed before the first ingest — see
  `REQ_CURATED_COLUMN_NAMING.md`). Under `technical` (the default) a Silver field is named
  `<column>_<table>`, lowercased — `VBAK.NETWR` → `netwr_vbak` (`sap_json_parser.py`); an
  ugly Bronze alias never leaks into a Silver field name, and improving a Bronze alias never
  renames a Silver field or invalidates a `join_graph`. Under `alias` the Silver field is
  `<alias>_<table>` — `VBAK.NETWR` with alias `net_value` → `net_value_vbak` — byte-identical
  to the persisted Bronze alias, which is why the alias is minted once at ingest and editing
  it afterwards does NOT rename the Silver field (minted names are persisted, never
  re-derived). The suffix is the SAP table name in both modes.

### 3.8 Bronze isolation

**Bronze isolation.** What the catalog does with a Bronze is an index-time **guarantee**,
not a runtime recommendation:

- **No field-registry rows and no edges.** Ingesting a Bronze reports
  `{"entities": 1, "fields": 0, "edges": 0}` — its columns are deliberately kept out of the
  field registry so they cannot pollute the agent's semantic field search.
- **No embedding.** Silver and Gold entities get one; Bronze does not.
- **A terse 8-key manifest.** The entity document stores exactly `id`, `layer`,
  `source_system`, `name`, `alias`, `description`, `primary_keys`, `raw_yaml`
  (`save_bronze_node`, `opensearch_repository.py`). `version` and `source_system_id` are not
  indexed; the whole file is preserved in `raw_yaml`, so a Bronze stays auditable and
  reconstructible.
- **Lexical-only reachability.** With no embedding a Bronze can only be hit by the BM25 half
  of hybrid retrieval, matching `name` / `description` — i.e. by its table name — and it
  earns a `0.00` layer bonus in re-ranking (Silver `0.15`, Gold `0.40`). It is *not*
  hard-excluded from the entity index: the gold-first retrieval priority of the two-plane
  resolution model ([`./README.md`](./README.md)) is what keeps Bronze out of answers.

> **Suppression by ranking is weaker than the published contract, deliberately, for now.** The
> spec says Bronze is *skipped* on the agent surface, and Smart enforces exactly that
> (`ALLOWED_LAYERS = ("silver","gold")`), but Precise and Flash apply no layer filter — so a
> question phrased in raw table codes can still surface a Bronze when no Silver or Gold matched.
> The contract is the target and stays as published; the enforcement is specified in the
> internal design doc (REQ_BRONZE_RETRIEVAL_SCOPE).
> Bronze keeps its place in the index on purpose — it is the authoritative answer for
> `SCHEMA_QUERY`. Do not "fix" this paragraph by deleting the caveat, and do not fix the gap by
> dropping Bronze from the registry.

Authoring consequences: rich descriptions, synonyms or business phrasing on a Bronze buy
**nothing** — there is no embedding to carry them and no field rows to match them; that
effort belongs on the Silver/Gold field that consumes the column. And a Bronze must never be
handed to the agent as primary context: a raw table cannot say that `GBSTK = 'C'` means
closed, so the model will guess confidently and emit SQL that runs and answers the wrong
question.

---

## 4. Naming & IDs

- Canonical Bronze grammar: `bronze_<source>_<table>_<alias>`, lowercase.
- That last segment is why `alias` is required at Bronze and why changing one is a breaking
  id change.
- The `id` is a stable key; treat it as immutable. Renaming an id is a breaking change
  (ripples into `relationships`, `composed_of`, OpenSearch indices, prompts).

---

## 5. Descriptions at Bronze

Bronze descriptions stay **terse**: usually the source field label verbatim (`Material`,
`Created on`). **0–1 line, never prose** — a column's business meaning belongs on the
Silver/Gold field that consumes it.

This is not a style preference, it follows from [§3.8](#38-bronze-isolation): rich
descriptions, synonyms or business phrasing on a Bronze buy **nothing** — there is no
embedding to carry them and no field rows to match them. With no embedding, a Bronze is
reachable only through the BM25 half of hybrid retrieval on `name` / `description` — i.e. by
its table name ([§3.8](#38-bronze-isolation)) — so keep the source label accurate rather than
expanding it.

---

## 6. Authoring checklist

Before committing a Bronze YAML:

- [ ] Header keys are exactly the Bronze set, in order: `id`, `layer`, `version`,
      `source_system`, `source_system_id`, `name`, `alias`, `description`, `primary_key`,
      `fields` ([§2](#2-header-keys)). No `db_table_name`, `module`, `business_process`,
      `classification`, `internal_id`, `source_system_no`, `tag1`/`tag2` — they are dropped
      silently, not rejected.
- [ ] `id` follows `bronze_<source>_<table>_<alias>`, lowercase — and is unchanged (or you
      have updated every reference to it) ([§4](#4-naming--ids)).
- [ ] `name` is the source table name, UPPERCASE exactly as in the source; field keys are the
      source column names as-is, uppercase, never renamed ([§3.3](#33-the-field-key)).
- [ ] Every field carries all four sub-keys — `type`, `alias`, `key_field`, `description`.
      There is no optional sub-key at Bronze ([§3.2](#32-field-sub-keys)).
- [ ] `primary_key` is duplicate-free and every member exists as a key in `fields`;
      `key_field` agrees with it in **both** directions. Empty is valid but means a
      **keyless Bronze** — warned at ingestion, contributes nothing to any Silver grain;
      escalate the missing declaration to the data-product admin
      ([§3.4](#34-primary_key-and-key_field)).
- [ ] The client / tenant column (SAP `MANDT` and its equivalents) is declared
      `key_field: false` and is **not** in `primary_key`
      ([§3.5](#35-client--tenant-columns-are-excluded-from-the-key)).
- [ ] Every `type` is a canonical form — `STRING(n)`, `DECIMAL(p[,s])`, `INTEGER`, `DATE`,
      `TIMESTAMP`, `BOOLEAN` — never a source-system code
      ([§3.6](#36-type--the-canonical-vocabulary)).
- [ ] Aliases are unique within the file (case-insensitively), lowercase ASCII snake_case;
      no cross-file "normalization" ([§3.7](#37-alias-policy)).
- [ ] Descriptions are terse — source label, 0–1 line, no prose, no synonyms
      ([§5](#5-descriptions-at-bronze), [§3.8](#38-bronze-isolation)).
- [ ] No join semantics and no business semantics: no `entity_role`, `grain`, `composed_of`,
      `join_graph`, `relationships`, `field_role` or `aggregation_behavior`
      ([§1](#1-role--philosophy), [§7](#7-prohibitions)).

*(These are the candidate rules for an automated linter.)*

---

## 7. Prohibitions

The ASK Specification carries constructs that do not apply to a
SQL-generating layer. **Do not author these:**

- Bronze `foreign_keys[]` / `referenced_tables` → join truth lives in Silver; at most an
  ingestion-time hint, not runtime.

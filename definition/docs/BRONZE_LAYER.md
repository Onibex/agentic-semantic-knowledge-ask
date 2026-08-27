# Bronze Layer Specification

> **Layer:** Bronze • **Status:** v1 • **Part of:** [ASK — Agentic Semantic Knowledge](../README.md)

## 1. Concept

The **Bronze layer** is a **faithful, mostly-uninterpreted representation of source-system tables and nodes**. A Bronze YAML describes a single table (e.g. SAP `MARA`, `VBAK`, `EKKO`) — its columns, types, primary key, and human-readable aliases — and nothing more.

Bronze is the **lineage substrate** of ASK: the raw building blocks that Silver Foundational Data Products are composed from, which in turn feed Gold Business Logic Data Products.

> Although the Bronze layer is most often used to describe **tables**, the spec is not table-only. A "Bronze node" is any leaf-level structural unit that participates in a Silver entity — a table, a sub-document, an API response shape, or a flat file schema. The YAML structure is the same regardless.

**Bronze mirrors; it does not model.** It carries no `entity_role`, no `grain`, no `composed_of`, no `join_graph`, no `relationships`, and no `field_role` or `aggregation_behavior` on its fields. Join truth lives in Silver; business semantics live in Silver and Gold.

## 2. ⚠️ Bronze is not for business agents, USE ONLY for Technical Agents

**Do not give Bronze YAMLs to your business agent as primary context.**

A raw `VBAK` table has no notion that:

- `GBSTK='C'` means the order is closed;
- `VDATU` is the *requested* delivery date, not the actual delivery date;
- `VBELN` joins to `VBAP.VBELN` (one-to-many on items);
- the same column appears under different SAP "areas" with different semantics.

Pointed at Bronze, an LLM will hallucinate — confidently — and produce SQL that runs but answers the wrong question. **The intent resolver must skip Bronze.** Bronze exists so the catalog has lineage, so Silver and Gold definitions are reproducible, and so data engineers can audit upstream sources. It is *not* the agent's reading material.

The ASK intent-resolution priority is:

```
1. GOLD    → primary
2. SILVER  → fallback
3. BRONZE  → skipped (lineage only)
```

A Bronze is never embedded, never given field-registry rows and never chunked into the retrieval collections, so most of that isolation is structural rather than a rule someone has to remember — see [§6.6](#66-what-isolates-bronze-and-how) for the part that is still a filter.

## 3. Schema

Unlike Silver and Gold (which use a list of field objects), **Bronze fields are a dictionary keyed by the source-system column name**. This intentionally mirrors the source-system DDL.

```yaml
id: bronze_s4h_mara_master_material
layer: bronze
version: '1'
source_system: s4h
source_system_id: 100
name: MARA
alias: MASTER_MATERIAL
description: General Material Data
primary_key:
  - MATNR
fields:
  MANDT:
    type: STRING(3)
    alias: client
    key_field: false
    description: Client
  MATNR:
    type: STRING(40)
    alias: material
    key_field: true
    description: Material
  ERSDA:
    type: DATE
    alias: created_on
    key_field: false
    description: Created on
  # ... etc.
```

Note two things in that snippet, both covered below: `type` carries the **canonical** type and not the source-system code ([§4](#4-type-system)), and `MANDT` — physically part of every SAP table key — is deliberately **not** in `primary_key` ([§6.7](#67-clienttenant-columns-are-excluded-from-the-key)).

### 3.1 Top-level keys

Exactly these ten keys, in this order. Anything else is dropped by catalog validation rather than rejected, so an unrecognised key survives in the file and silently never reaches the catalog.

| Key | Required | Type | Description |
|---|---|---|---|
| `id` | ✅ | string | Globally unique identifier, **lowercase**. Convention: `bronze_<system>_<table>_<alias>` — see [§5](#5-naming-conventions). Example: `bronze_s4h_mara_master_material`. Validated against that grammar; a non-conforming id is rejected. Treat it as immutable — renaming one is a breaking change. |
| `layer` | ✅ | string | Must be the literal value `bronze`. Tooling defaults it to `bronze` when omitted. |
| `version` | ⬜ | string | Spec/version of this definition. **Defaults to `'1'`** when omitted — unlike Silver and Gold, where it is required. |
| `source_system` | ✅ | string | Source-system family. Registered tokens: `s4h`, `ecc`, `generic`, `salesforce`, `odoo`. **Load-bearing:** it selects the type profile, so a wrong token changes how `type` is read. Use `s4h` for SAP S/4HANA — not `s4hana`, which would produce ids that do not match the rest of the catalog. |
| `source_system_id` | ✅ | integer | Specific instance/client number (e.g. `100`). **This is the Bronze spelling**; Silver and Gold use `source_system_no`. They are *not* interchangeable — the wrong one is dropped, not translated. Tooling defaults it to `0` when omitted. |
| `name` | ✅ | string | Source-system table or node name, **uppercase as it appears in the source** (e.g. `MARA`, `VBAK`, `EKKO`). |
| `alias` | ✅ | string | Human-readable alias, UPPER_SNAKE (e.g. `MASTER_MATERIAL`, `ORDER_HEADER`). **Load-bearing:** it is the last segment of the `id` and it is indexed on the entity document, so changing it changes the id. Tooling defaults it to `name` when omitted. |
| `description` | ✅ | string | Description of the table. Brief is correct here — Bronze descriptions are usually the source-system table label. See [§6.2](#62-keep-descriptions-short). Tooling defaults it to an empty string, which is a placeholder to fill, not an acceptable end state: `description` is one of the few fields indexed for a Bronze and the only text by which one is findable. |
| `primary_key` | ✅ | string[] | Ordered list of source-system column names that form the primary key, **as declared by the data-product author** — ASK consumes that declaration as authority and never reconstructs a key. **Duplicate-free**; every member must exist in `fields`. May be empty: that is a keyless Bronze, warned and ingested — see [§6.3](#63-primary_key-and-key_field-must-agree). Excludes the client/tenant column — see [§6.7](#67-clienttenant-columns-are-excluded-from-the-key). |
| `fields` | ✅ | object | Dictionary of fields keyed by source-system column name. See [§3.2](#32-field-dictionary). |

### 3.2 Field dictionary

Each entry in `fields` is keyed by the **source-system column name** (e.g. `MATNR`, `VBELN`, `GBSTK`), and the value is a metadata object:

```yaml
MATNR:
  type: STRING(40)
  alias: material
  key_field: true
  description: Material
```

All four sub-keys are required. There is no optional sub-key at Bronze.

| Sub-key | Required | Type | Description |
|---|---|---|---|
| `type` | ✅ | string | The **canonical** type — never a source-system code. See [§4](#4-type-system). Tooling defaults it to `STRING` when omitted. |
| `alias` | ✅ | string | Human-readable lowercase snake_case label, for **display and lineage only**. Tooling defaults it to the lowercased column name. Nothing in retrieval or SQL generation reads it — see [§6.5](#65-aliases-are-display-labels-not-a-contract). |
| `key_field` | ✅ | boolean | `true` if and only if the column is listed in `primary_key`. Agreement is enforced in both directions — see [§6.3](#63-primary_key-and-key_field-must-agree). |
| `description` | ✅ | string | Business description. Often the source-system field label verbatim. Tooling defaults it to an empty string. |

### 3.3 Why a dictionary instead of a list?

The dict keying decision is deliberate:

- **Source fidelity.** Source-system documentation references columns by name (`MATNR`, `VBELN`). A dict keeps the YAML aligned with the way data engineers and SAP analysts already read the table.
- **Lookup speed.** A Silver `join_graph` references fields by source name. A dict gives O(1) access without filtering a list.
- **Lineage.** Bronze is a one-to-one mirror of the source DDL. Modeling it as a list invites reordering and obscures the mapping. A dict makes the ordering irrelevant and the membership obvious.

Silver and Gold use a list of field objects because their fields are **derived** (renamed, recomposed, augmented) — the order in the list is part of the published surface. Bronze is **mirroring**, not designing.

## 4. Type system

Bronze `type` carries the **canonical, source-agnostic type** — `STRING(10)`, not `C10`; `DECIMAL(15)`, not `P15`; `DATE`, not `D8`.

**One vocabulary, all three layers.** Bronze, Silver and Gold all store the canonical type, so a column reads identically from the raw table through the curated entity to the published surface and no consumer has to know which source produced it. There is no per-layer type dialect. Fidelity to the source is preserved by the field *key* (the column name, unchanged) and by `description` — not by re-encoding the type.

### 4.1 The canonical vocabulary

Six bases exist, and only these:

`STRING` · `INTEGER` · `DECIMAL` · `DATE` · `TIMESTAMP` · `BOOLEAN`

Valid rendered forms — nothing else is a type:

| Form | When |
|---|---|
| `STRING(n)` | character / numeric-text / raw column with a known length |
| `STRING` | length unknown, absent, or zero |
| `DECIMAL(p,s)` | precision **and** a non-zero scale are known |
| `DECIMAL(p)` | precision known, scale absent or zero |
| `DECIMAL` | neither known |
| `INTEGER` · `DATE` · `TIMESTAMP` · `BOOLEAN` | always bare — these never take parameters |

Rules:

1. **Uppercase, no spaces.** `string(10)` and `b3` are not types.
2. **Unknown or absent → `STRING`.** The mapper never raises. Convenient, and a trap: a typo'd type does not fail, it silently becomes `STRING`. A canonical `STRING` on an obviously numeric column means the source metadata was missing — not that the column is text.
3. **Idempotent.** Re-encoding an already-canonical file is a no-op, so re-ingestion causes no type churn.
4. **The type is logical, not physical.** `DATE` on a SAP `D8` column does **not** assert that the stored column is a native date — SAP stores it as 8-character text. Consumers that compare it to a real date must cast.
5. **Mapped, not invented.** Bronze and Silver resolve each field's `type` from the source-system type that arrives in the export, through the table above. Gold publishes the same types: the same vocabulary and the same values as the Bronze and Silver columns behind it.

### 4.2 How SAP resolves

This is the mapper's actual output, not an aspiration.

| Source code | Canonical | Note |
|---|---|---|
| `C10` / `C18` | `STRING(10)` / `STRING(18)` | character, length preserved |
| `N6` | `STRING(6)` | numeric text stays STRING — leading zeros are significant in SAP keys |
| `D8` | `DATE` | the length is dropped |
| `T6` | `STRING(6)` | there is no `TIME` base; SAP time-of-day is 6-character text |
| `P13` / `P15` | `DECIMAL(13)` / `DECIMAL(15)` | SAP `Pn` carries no scale, so none is rendered |
| `X16` | `STRING(16)` | raw / hex |
| `I4` / `S` / `B3` | `INTEGER` | 4- / 2- / 1-byte integers |
| `F16` | `DECIMAL(16)` | floating point |
| `CLNT` `NUMC` `CUKY` `UNIT` `LANG` `TIMS` `RAW` `SSTRING` | `STRING` | DDIC datatype words |
| `CURR` / `QUAN` / `FLTP` | `DECIMAL` | |
| `DATS` | `DATE` | |
| unknown or absent | `STRING` | never an error — see rule 2 |

The ABAP internal-type letters the mapper recognises are `C N G X Y D T P F A E I S B`. Anything else falls through to `STRING`.

**What canonical drops — know this before relying on a Bronze `type`.** `STRING(n)` absorbs three distinct SAP types: `Cn` (character), `Nn` (numeric text, where **leading zeros are significant** — SAP document and material numbers) and `Tn` (time of day). A Bronze `type` therefore cannot tell you whether a column is zero-padded or holds a time, and `D8`'s length is gone. That information is **not recoverable from Bronze** — consult the source data dictionary. This is an accepted trade of a source-agnostic vocabulary, not an oversight.

### 4.3 Non-SAP source systems

The canonical vocabulary is the target for every source, not just SAP. The mapper reads the source's own types and re-encodes them:

- PostgreSQL / MySQL: `VARCHAR(n)` → `STRING(n)`, `NUMERIC(p,s)` → `DECIMAL(p,s)`, `TIMESTAMPTZ` → `TIMESTAMP`, `BOOL` → `BOOLEAN`.
- Oracle: `VARCHAR2(n)` → `STRING(n)`, `NUMBER(p,s)` → `DECIMAL(p,s)`.
- Salesforce: `ID` / `REFERENCE` / `PICKLIST` → `STRING`, `CURRENCY` → `DECIMAL`, `DATETIME` → `TIMESTAMP`.
- REST APIs: JSON Schema `string` → `STRING`, `number` → `DECIMAL`, `boolean` → `BOOLEAN`.

The principle: **mirror the source faithfully at Bronze in the column names and descriptions; harmonize the type vocabulary from Bronze through Silver.**

## 5. Naming conventions

| Item | Convention | Example |
|---|---|---|
| `id` | `bronze_<system>_<table_lower>_<alias_lower>` | `bronze_s4h_mara_master_material`, `bronze_s4h_mvke_material_sales_data` |
| `name` | Source-system table name, **UPPERCASE** as in the source | `MARA`, `VBAK`, `EKKO` |
| `alias` | Human-readable English label, UPPER_SNAKE | `MASTER_MATERIAL`, `ORDER_HEADER`, `PURCHASING_DOC_HEADER` |
| Field key | Source-system column name **as-is** | `MATNR`, `VBELN`, `GBSTK`, `KUNNR` |
| Field `alias` | lowercase short label (snake_case) | `material`, `sales_doc`, `created_on` |

The `id` is built from `source_system` + `name` + `alias`, lowercased — which is why `alias` is required and why changing it is a breaking change. Ingestion enforces printable-ASCII snake_case on both aliases, so a stray non-ASCII character in a source label cannot corrupt an id.

## 6. Best practices

### 6.1 Mirror the source — do not edit it

Bronze should be a faithful mirror. Do not rename `MATNR` to `material_id` at the field key level — the *key* must stay `MATNR`. Use `alias` to provide the friendly name. Re-keying severs lineage and breaks every Silver `source` pointing at the column.

### 6.2 Keep descriptions short

Unlike Silver and Gold, Bronze descriptions are terse — often just the source-system field label ("Material", "Created on", "Sales document"). Detailed business meaning belongs in Silver and Gold, where it is embedded and actually reaches the agent. Zero to one line; never prose.

### 6.3 `primary_key` and `key_field` must agree

If `primary_key: [MATNR]`, then exactly the field `MATNR` has `key_field: true`. Agreement is required in **both** directions: every column in `primary_key` has `key_field: true`, and every field with `key_field: true` is listed in `primary_key`.

Catalog validation **rejects** mismatches rather than repairing them, and reports every violation at once so a corrupt file can be fixed in a single pass. Normalization that *is* safe — de-duplicating a key, sanitizing an alias — happens in the ingestion parser before validation, so machine-generated payloads pass while a hand-authored file that disagrees with itself fails.

A source table whose export declares **no** key at all ingests as a **keyless Bronze**, with a warning naming the table. The key declaration belongs to the data-product author — ASK consumes it as authority and never reconstructs a key from the source dictionary — so a missing declaration is an upstream authoring error to fix at the source, not something ingestion should guess around. Until it is fixed, a keyless Bronze contributes no key columns to the grain of any Silver that composes it (the grain cannot express that table's fan-out), and the table's upstream data itself is suspect: materialized with no declared key, N rows per key collision collapse into 1. Treat the warning as a defect to escalate, not a state to keep.

### 6.4 One Bronze per source-system node

Do not collapse two source-system tables into one Bronze YAML. If you need them together, that is what Silver is for. Bronze is one-to-one with the source.

### 6.5 Aliases are display labels, not a contract

A good `alias` is a stable English noun that survives translation: `material`, `customer`, `plant`, `created_on`, `net_value`. Avoid jargon and abbreviations.

Three things to be clear about:

- **In-file uniqueness is enforced**, compared case-insensitively. Two fields in one Bronze may not share an alias: an authored or imported YAML that does is **rejected**. The one exception is the SAP metadata path, where the parser repairs a collision before the node is built — it appends an ordinal suffix (`_2`, `_3`, …; the first occurrence keeps the bare alias) and records a naming warning. Under `ColumnNamingMode.ALIAS` that repair is load-bearing rather than cosmetic, because the published Silver column takes its name from the alias: the client's physical table must carry the same suffix.
- **Cross-file drift is not policed, and that is deliberate.** The same source column may carry different aliases in different Bronzes (`KUNNR` as `customer` on a sales table and `competitor` on a competitor table is *correct*). There is no canonical alias dictionary; do not "normalize" aliases across files.
- **Silver field names are not built from the Bronze alias.** A Silver field is named `<column>_<table>`, lowercased — `VBAK.NETWR` becomes `netwr_vbak`. So an unhelpful Bronze alias never leaks into a Silver field name, and improving one never renames a Silver field or invalidates a `join_graph`.

### 6.6 What isolates Bronze, and how

Bronze YAMLs are catalog metadata, not agent-facing context. Most of that isolation is structural — a Bronze is never given the representations retrieval needs:

- **No field-registry rows and no edges.** Ingesting a Bronze reports `{"entities": 1, "fields": 0, "edges": 0}` — its columns are kept out of the field registry so they cannot pollute the agent's semantic field search.
- **No embedding.** Silver and Gold entities get one; Bronze does not.
- **A terse manifest.** The entity document stores `id`, `layer`, `source_system`, `name`, `alias`, `description`, `primary_keys` and the full `raw_yaml` — nothing else. The whole file is preserved, so a Bronze stays auditable and reconstructible.
- **No RAG chunks.** The publish cascade skips Bronze outright, so the chunk collection the Flash engine searches never contains one.
- **Lexical-only reachability.** With no embedding, a Bronze can only be matched by the keyword half of hybrid retrieval, on `name` and `description` — in practice, by its table name — and it earns no layer bonus in re-ranking.

**A Bronze does stay in the entity registry**, though, so the last step is a filter rather than an absence, and it differs by engine:

| Engine | How Bronze is kept out |
|---|---|
| Flash | Structural — Bronze is never indexed into the chunk collection it searches. |
| Smart | The catalog query itself restricts `layer` to `silver` and `gold`. |
| Precise | Resolution and path selection filter to `silver` and `gold`, with an explicit opt-in that admits Bronze for schema questions. |

The distinction matters when you change retrieval: the structural half cannot be undone by accident, the filtering half can. Answering a question **from** a Bronze is a `SCHEMA_QUERY` — "what columns does VBAK have" — not a data question, and that is the one path meant to reach it.

The authoring consequence: rich descriptions, synonyms or business phrasing on a Bronze buy **nothing** for data questions. There is no embedding to carry them and no field rows to match them. That effort belongs on the Silver or Gold field that consumes the column.

### 6.7 Client/tenant columns are excluded from the key

SAP `MANDT` — and the equivalent client or tenant column of any other source — is declared as an ordinary field with `key_field: false` and is **never** listed in `primary_key`, even though it is physically part of every SAP table key.

The client is already pinned by the header (`source_system_id`), so keeping it in the key would only add a constant to every Bronze key and to every Silver grain derived from it. This does not conflict with [§6.3](#63-primary_key-and-key_field-must-agree): agreement is defined against the *declared* `primary_key`, not against the source's physical key. Generated Bronzes comply because the source export marks the column non-key; hand-authored and DDL-imported Bronzes must apply the rule deliberately.

### 6.8 Same-named columns may legitimately differ between tables

Two Bronzes can declare the same column name with different types, and that is usually correct rather than drift: the source data dictionary defines them as different elements that happen to share a name. In SAP, `AFRU.GRUND` is a 4-character code while `MSEG.GRUND` is 4-digit numeric text; `MARA.NTGEW` and `EBKN.NETWR` differ in precision from their namesakes elsewhere. Mirror what the source declares per table and do not harmonize across files — harmonization is Silver's job.

## 7. Reference examples

- [`examples/bronze/mara.yaml`](../examples/bronze/mara.yaml) — SAP MARA (Material Master). Single-column key, shows the client-column convention.
- [`examples/bronze/mvke.yaml`](../examples/bronze/mvke.yaml) — SAP MVKE (Material Sales Data). Composite three-column key.

Both are generated output, not hand-written illustrations: they are what the ingestion pipeline actually emits.

## 8. Validation checklist

Before publishing a Bronze YAML to the catalog, verify:

- [ ] All ten required keys are present: `id`, `layer`, `version`, `source_system`, `source_system_id`, `name`, `alias`, `description`, `primary_key`, `fields`.
- [ ] `id` follows `bronze_<system>_<table_lower>_<alias_lower>`, lowercase, and is reconstructible from `source_system` + `name` + `alias`.
- [ ] `name` matches the source-system table name **exactly** (case-sensitive).
- [ ] `source_system` is a registered token (`s4h`, `ecc`, `generic`, `salesforce`, `odoo`).
- [ ] `primary_key` is a **duplicate-free** list of column names that exist in `fields`. Empty is valid but means a keyless Bronze — warned at ingestion, contributes nothing to any Silver grain; escalate the missing key declaration to the data-product author.
- [ ] For every column in `primary_key`, the corresponding field has `key_field: true`.
- [ ] For every field with `key_field: true`, the column is listed in `primary_key`.
- [ ] The client/tenant column is **not** in `primary_key`.
- [ ] Every field has `type`, `alias`, `key_field`, `description`.
- [ ] Every `type` is a canonical form (`STRING(n)`, `DECIMAL(p[,s])`, `INTEGER`, `DATE`, `TIMESTAMP`, `BOOLEAN`) — no source-system codes.
- [ ] Source-system column names are preserved as field keys (not renamed).
- [ ] Aliases are unique within the file (case-insensitively) and contain only lowercase ASCII, digits and underscores.
- [ ] `description` is filled on the table and on every field — an empty string is a placeholder, not a valid end state.
- [ ] No business logic, derivations, or status interpretations are encoded here — those belong in Silver and Gold.

---

[← Back to the ASK specification](../README.md) · [The layer specifications](README.md)

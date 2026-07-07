# Bronze Layer Specification

> **Layer:** Bronze • **Status:** v1 • **Part of:** [ASK — Agentic Semantic Knowledge](../README.md)

## 1. Concept

The **Bronze layer** is a **faithful, mostly-uninterpreted representation of source-system tables and nodes**. A Bronze YAML describes a single table (e.g. SAP `MARA`, `VBAK`, `EKKO`) — its columns, types, primary key, and human-readable aliases — and nothing more.

Bronze is the **lineage substrate** of ASK: the raw building blocks that Silver Foundational Data Products are composed from, which in turn feed Gold Business Logic Data Products.

> Although the Bronze layer is most often used to describe **tables**, the spec is not table-only. A "Bronze node" is any leaf-level structural unit that participates in a Silver entity — a table, a sub-document, an API response shape, or a flat file schema. The YAML structure is the same regardless.

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

## 3. Schema

Unlike Silver and Gold (which use a list of field objects), **Bronze fields are a dictionary keyed by the source-system column name**. This intentionally mirrors the source-system DDL.

```yaml
id: bronze_ecc_mara_master_material
layer: bronze
version: '1'
source_system: ecc
source_system_id: 100
name: MARA
alias: MASTER_MATERIAL
description: SAP Table MARA
primary_key:
  - MATNR
fields:
  MANDT:
    type: C3
    alias: client
    key_field: false
    description: Client
  MATNR:
    type: C18
    alias: material
    key_field: true
    description: Material
  ERSDA:
    type: D8
    alias: created_on
    key_field: false
    description: Created On
  # ... etc.
```

### 3.1 Top-level keys

| Key | Required | Type | Description |
|---|---|---|---|
| `id` | ✅ | string | Globally unique identifier. Convention: `bronze_<system>_<table>_<name>`. Example: `bronze_ecc_mara_master_material`. |
| `layer` | ✅ | string | Must be the literal value `bronze`. |
| `version` | ✅ | string | Spec/version of this definition. |
| `source_system` | ✅ | string | Source-system family (`ecc`, `s4hana`, `salesforce`). |
| `source_system_id` | ⬜ | integer | Specific instance/client number. (Note: Bronze typically uses `source_system_id`; Silver/Gold use `source_system_no`. Both are accepted but consistency within a catalog is recommended.) |
| `name` | ✅ | string | Source-system table or node name, **uppercase as it appears in the source** (e.g. `MARA`, `VBAK`, `EKKO`). |
| `alias` | ⬜ | string | Human-readable alias (e.g. `MASTER_MATERIAL`, `ORDER_HEADER`). Used for display and search. |
| `description` | ✅ | string | Description of the table. Brief is acceptable here — Bronze descriptions are usually a one-liner pointing to the source-system documentation. |
| `primary_key` | ✅ | string[] | Ordered list of source-system column names that form the primary key. |
| `fields` | ✅ | object | Dictionary of fields keyed by source-system column name. See [§3.2](#32-field-dictionary). |

### 3.2 Field dictionary

Each entry in `fields` is keyed by the **source-system column name** (e.g. `MATNR`, `VBELN`, `GBSTK`), and the value is a metadata object:

```yaml
MATNR:
  type: C18
  alias: material
  key_field: true
  description: Material
```

| Sub-key | Required | Type | Description |
|---|---|---|---|
| `type` | ✅ | string | Source-system data type (e.g. `C18` = 18-character text, `D8` = 8-digit date, `P15` = 15-digit packed decimal). See [§4](#4-source-system-type-system). |
| `alias` | ⬜ | string | Human-readable lowercase alias used as a display name and as a building block for Silver field names. |
| `key_field` | ✅ | boolean | `true` if the field is part of the primary key, `false` otherwise. Must be consistent with the `primary_key` list. |
| `description` | ✅ | string | Business description. Often the source-system field label verbatim. |

### 3.3 Why a dictionary instead of a list?

The dict keying decision is deliberate:

- **Source fidelity.** Source-system documentation references columns by name (`MATNR`, `VBELN`). A dict keeps the YAML aligned with the way data engineers and SAP analysts already read the table.
- **Lookup speed.** A Silver `join_graph` references fields by source name. A dict gives O(1) access without filtering a list.
- **Lineage.** Bronze is a one-to-one mirror of the source DDL. Modeling it as a list invites reordering and obscures the mapping. A dict makes the ordering irrelevant and the membership obvious.

Silver and Gold use a list of field objects because their fields are **derived** (renamed, recomposed, augmented) — the order in the list is part of the published surface. Bronze is **mirroring**, not designing.

## 4. Source-system type system

Bronze YAMLs use **source-system types** verbatim (rather than SQL-style types like `TEXT`/`INTEGER`). This preserves fidelity with the source schema and avoids premature lossy conversion.

### 4.1 SAP common type codes

| Code | Meaning |
|---|---|
| `Cn` | `n`-character text (e.g. `C3` = client/MANDT, `C10` = sales doc number, `C18` = material number) |
| `Nn` | `n`-digit numeric character (e.g. `N6` = item number) |
| `Dn` | `n`-digit date (`D8` = `YYYYMMDD`) |
| `Tn` | `n`-digit time (`T6` = `HHMMSS`) |
| `Pn` | `n`-digit packed decimal (`P13`, `P15` = SAP DEC currency/quantity) |
| `In` | `n`-byte integer |
| `Fn` | floating point |
| `Xn` | `n`-byte raw / hex |

The Silver layer that consumes Bronze translates these to SQL-style types when it publishes its surface. The Gold layer always uses SQL-style types (`TEXT`, `NUMERIC`, `INTEGER`, `DATE`, `TIMESTAMP`, `BOOLEAN`).

### 4.2 Non-SAP source systems

For non-SAP sources, use the type system the source actually exposes:

- Salesforce: `STRING`, `ID`, `REFERENCE`, `DATETIME`, `CURRENCY`, `PICKLIST`, etc.
- PostgreSQL/MySQL: native SQL types.
- REST APIs: JSON Schema-style types (`string`, `number`, `boolean`, `object`, `array`).

The principle is the same: **mirror the source faithfully at Bronze; harmonize at Silver and Gold.**

## 5. Naming conventions

| Item | Convention | Example |
|---|---|---|
| `id` | `bronze_<system>_<table_lower>_<alias_or_name>` | `bronze_ecc_mara_master_material`, `bronze_ecc_vbak_order_header` |
| `name` | Source-system table name, **UPPERCASE** as in the source | `MARA`, `VBAK`, `EKKO` |
| `alias` | Human-readable English label, UPPER_SNAKE | `MASTER_MATERIAL`, `ORDER_HEADER`, `PURCHASING_DOC_HEADER` |
| Field key | Source-system column name **as-is** | `MATNR`, `VBELN`, `GBSTK`, `KUNNR` |
| Field `alias` | lowercase short label (snake_case) | `material`, `sales_doc`, `created_on` |

## 6. Best practices

### 6.1 Mirror the source — do not edit it

Bronze should be a faithful mirror. Do not rename `MATNR` to `material_id` at the field key level — the *key* must stay `MATNR`. Use `alias` to provide the friendly name. This preserves traceability when source-system documentation is the ground truth.

### 6.2 Keep descriptions short

Unlike Silver and Gold, Bronze descriptions can be terse — often just the source-system field label ("Material", "Created On", "Sales Document"). Detailed business meaning belongs in Silver and Gold.

### 6.3 `primary_key` and `key_field` must agree

If `primary_key: [MATNR]`, then exactly the field `MATNR` must have `key_field: true`. Catalog validators should reject mismatches.

### 6.4 One Bronze per source-system node

Do not collapse two source-system tables into one Bronze YAML. If you need them together, that is what Silver is for. Bronze is one-to-one with the source.

### 6.5 Aliases should be stable English nouns

A good `alias` is a stable English noun that survives translation: `material`, `customer`, `plant`, `created_on`, `net_value`. Avoid jargon, abbreviations, or terms specific to one ERP module.

### 6.6 Do not lift Bronze to the agent context

Bronze YAMLs are catalog metadata, not agent-facing context. Catalog UIs may display Bronze for data engineers; agent runtimes should filter it out by `layer == "bronze"`.

## 7. Reference examples

- [`examples/bronze/mara.yaml`](../examples/bronze/mara.yaml) — SAP MARA (Material Master).
- [`examples/bronze/vbak.yaml`](../examples/bronze/vbak.yaml) — SAP VBAK (Sales Order Header).

## 8. Validation checklist

Before publishing a Bronze YAML to the catalog, verify:

- [ ] `id`, `layer`, `version`, `source_system`, `name` are present.
- [ ] `name` matches the source-system table name **exactly** (case-sensitive).
- [ ] `primary_key` is a non-empty list of column names that exist in `fields`.
- [ ] For every column in `primary_key`, the corresponding field has `key_field: true`.
- [ ] For every field with `key_field: true`, the column is listed in `primary_key`.
- [ ] Every field has `type`, `key_field`, `description`.
- [ ] Source-system column names are preserved as field keys (not renamed).
- [ ] Aliases are unique within the file.
- [ ] No business logic, derivations, or status interpretations are encoded here — those belong in Silver and Gold.

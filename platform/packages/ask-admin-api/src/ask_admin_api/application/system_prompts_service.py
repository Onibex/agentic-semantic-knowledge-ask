# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Editable system prompts + Semantic Layer Standards loader.

Two responsibilities packed in a small surface:

  1. ``get_prompt(key)`` returns the active body for a named prompt
     (e.g. ``"enrichment"``). Falls back to ``DEFAULT_PROMPTS[key]`` when no
     doc is stored in OpenSearch.

  2. ``get_standards_excerpt(layer)`` returns the cached authoring standard
     for one layer: the matching file under ``prompts/standards/``
     (``BRONZE_LAYER.md`` / ``SILVER_LAYER.md`` / ``GOLD_LAYER.md``), injected
     WHOLE — each file is written scoped to what an enricher of that layer
     needs. ``None`` / unknown returns the three files concatenated. These are
     package data resolved from this module, so they travel inside the wheel;
     they are prompt payload, not user documentation.

Cache strategy: load the standards files once at module-init time. Reloading
requires a process restart OR ``POST /v1/internal/reload``.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from .system_prompts_repository import SystemPromptRecord, SystemPromptsRepository

logger = logging.getLogger(__name__)


# ── Built-in defaults ───────────────────────────────────────────────────────


_DEFAULT_ENRICHMENT_PROMPT = """\
ROLE
====
You are a senior SAP + data-engineering consultant enriching a semantic layer
that an AI text-to-SQL agent uses to answer natural-language questions over SAP
tables (HANA / Postgres; medallion: bronze = raw mirror, silver = curated
entities, gold = analytics facts).

Your only job: write enrichment text for the entity and fields below so
(a) a non-technical user's question retrieves the right field, and (b) the
agent picks the right column. Descriptions are used as embedding text AND as
prompt context — they are SIGNAL, not documentation.

THE ONE PRINCIPLE — signal, not filler
======================================
Before keeping any clause, ask:
   "Would removing it change which column / table / join / aggregation the agent picks?"
If no → cut it.

GLOBAL RULES (apply to EVERY target below)
==========================================
1. If the current value is already clear, return NO change for that key.
2. Lead with the noun the value IS. Never write "This field represents…",
   "used for tracking…", "stored in…".
3. NEVER repeat the entity context inside a field description. The entity
   is already "sales order" — do NOT end each description with "in the sales
   document".
4. NEVER echo `(TABLE.FIELD)` or `from TABLE.FIELD` in the description
   text you produce. The `sap_origin` we ship in the input is for YOUR
   internal anchoring only — the reader of the description NEVER sees it
   spelled out. If a description you write ends with `(VBAK.VBELN)`,
   `(VBAK.AUART)`, `(VBUK.GBSTK)` etc. — that is a bug, remove it.

      bad:  "Unique sales document number (VBAK.VBELN)"
      good: "Unique sales document number"

      bad:  "Order reason (VBAK.AUGRU)"
      good: "Order reason"

   The PRESERVATION RULE (rule 6 below) is the ONE exception: when the
   CURRENT description already contains a TABLE.FIELD citation, keep it
   verbatim (removing it would lose info). But you do NOT ADD citations
   that aren't already in the input.

5. ANTI-REPHRASING — cosmetic changes are NOT improvements.
   Before proposing a description change, run this test:
      "Does my new description add information the old one didn't have,
       or am I just rephrasing / fixing capitalisation / changing word order?"
   If it's only rephrasing → return NO change for that field. Cosmetic
   edits waste tokens AND will be silently rejected by the backend.

      Skip these (cosmetic only, return no change):
        "Order Reason" → "Order reason"             (capitalisation)
        "Sales document" → "Sales document number"  (minor word add, marginal)
        "Customer" → "The customer"                 (article only)
        "Net Value" → "Net value"                   (capitalisation)

      Accept these (add real information):
        ""       → "Unique sales document number"   (empty → filled)
        "Code"   → "SAP standard order type code"   (vague → specific)
        "Amount" → "Net value before tax in document currency"  (adds business detail)
        "Flag"   → "1 = active, 0 = inactive"       (prose → value mapping)

6. PRESERVATION RULE (hard — applies to ALL field_roles)
   If the CURRENT description contains any of:
     - Value-to-meaning mapping: `'C' = CLOSED`, `1 = active`, `X -> BLOCKED`
     - A source-column citation: `(VBUK.GBSTK)`, `from VBAK.NETWR`
     - A specific business rule: "anything except 'C' counts as OPEN"
     - A caveat pointing to a related field: "for partial detail use ovrll_sts"
   → PRESERVE THOSE TOKENS VERBATIM in your rewrite. You may shorten the
     surrounding prose, but NEVER strip value tokens, source citations, or
     alternative-field hints. The agent downstream depends on those EXACT
     tokens to write correct WHERE clauses and JOINs. Losing them silently
     breaks SQL generation.

   If you cannot keep all the value information while staying inside the
   length budget for the field_role → SKIP the field (return no change for
   that key). Better verbose-but-correct than concise-but-broken. The
   backend ENFORCES this rule and will silently cancel any rewrite that
   drops critical tokens — you save tokens by not even proposing such a
   rewrite.

   NOT protected — aggregation mechanics. A clause that merely restates
   `aggregation_behavior` / `additivity` / `non_additive_over` ("repeated on
   every movement line", "reduce to one row per (a, b, c) then SUM", "never
   total it", "requires dedup") is NOT a value token. Those keys are derived
   at ingest and the SQL agent reads them directly, so the prose is a stale
   duplicate. REMOVE it and keep the business meaning. This is the one case
   where shortening IS an improvement rather than a cosmetic edit.

7. NEVER write aggregation mechanics into a description. You are shown
   `aggregation_behavior`, `additivity` and `non_additive_over` so your wording
   does not CONTRADICT them — never so you restate them. A description is what
   the value MEANS to a business reader; how to aggregate it is already
   configured. Two costs to restating: prose and keys drift apart, and the
   description is embedding text, so mechanics push the business meaning out of
   the field's vector and the field stops being retrievable by the question a
   user actually asks.

      bad:  "Unrestricted stock. One value per (matnr, werks, lgort), repeated
             on every movement line; reduce to one row per that triple first."
      good: "Unrestricted (available) stock on hand"

   A genuine business caveat no key can express still belongs here — a
   lifecycle flag to filter out ("use to exclude deleted items"), a sign
   convention (credits are negative), a KPI definition.

ENRICHABLE TARGETS
==================
The blocks below define every enrichable concept. Each block is a contract:
{ what it is · length / style · when to omit · example }.

Adding a new enrichable in the future = adding ONE new TARGET block. Nothing
else in this prompt changes.

────────────────────────────────────────────────────────────────────────────
TARGET: entity.description
────────────────────────────────────────────────────────────────────────────
WHAT     : one short sentence stating what this entity represents.
LENGTH   : 10-20 words.
STYLE    : business-friendly. Lead with the noun ("Sales order…", not
           "This entity stores…").
OMIT WHEN: current description is already concrete + at the entity grain.
EXAMPLE  : "Sales document headers with customer, pricing, plant and delivery
           context — one row per VBELN."

────────────────────────────────────────────────────────────────────────────
TARGET: entity.alias
────────────────────────────────────────────────────────────────────────────
WHAT     : short business-friendly display name for the entity.
LENGTH   : 1-5 words (≤ 40 chars).
STYLE    : Title Case. No SAP table codes.
OMIT WHEN: current alias is already a meaningful business term.
EXAMPLE  : "Sales Order Header" (NOT "VBAK Mirror" or "sales_order").

────────────────────────────────────────────────────────────────────────────
TARGET: entity.business_process
────────────────────────────────────────────────────────────────────────────
WHAT     : the SAP business process this entity participates in.
STYLE    : EXACTLY one of the canonical values, UPPERCASE with spaces:
             ORDER TO CASH
             PROCURE TO PAY
             PLANT TO PRODUCE
             RECORD TO REPORT
             ORGANIZATIONAL STRUCTURE   <- generic / cross-module entity that
                                           belongs to no single process (an org
                                           unit, a plant, a sales office). This
                                           is a legitimate value, not a gap.
           Do NOT hyphenate ("Order-to-Cash"), do NOT title-case, do NOT invent
           a new value, and do NOT put a MODULE code (SD, MM) here — the module
           is a separate key.
OMIT WHEN: the current value is NON-EMPTY. This key comes from the upstream SAP
           export and the export wins; propose one ONLY to fill a blank.
EXAMPLE  : "ORDER TO CASH".

────────────────────────────────────────────────────────────────────────────
TARGET: fields[*].description
────────────────────────────────────────────────────────────────────────────
WHAT     : a tight noun phrase identifying the column's business meaning.
LENGTH   : keyed on `field_role` (canonical six-role taxonomy from
           the standards excerpt below):

             identifier   4-10 words   "Unique sales doc id"
             dimension    8-15 words   one short clause
             measure      10-20 words  business meaning ONLY — the aggregation
                                       is configured, see global rule 7
             timestamp    5-10 words   "Document creation date"
             attribute    8-15 words   free-text name / long-description column
             status_flag  5-10 words   LEAD WITH VALUE MAPPING, never prose:
                                         "X = blocked, blank = not blocked"
                                         "1 = active, 0 = inactive"
                                       If you don't know the values → SKIP
                                       the field. A wrong flag description
                                       silently breaks WHERE clauses.

           Hard cap 25 words, unless a real gotcha earns more — KPI
           definition, sign convention, a lifecycle flag to filter out. A
           dedup / fan-out hazard does NOT earn more: it is a structured key.
STYLE    : Lead with the noun. Do NOT echo "(TABLE.FIELD)" in the text.
OMIT WHEN: current description is already clear and at the right length.
EDGE CASE: a field named `is_*` / `*_kennz` / `*_flag` / `*_status` whose
           `field_role` is NOT `status_flag` is almost certainly mis-classified.
           Treat as `status_flag` regardless. Same logic for `*_at` fields
           lacking `field_role: timestamp`.
EXAMPLE  :
   bad  (filler + redundant TABLE.FIELD):
     "Partner VAT registration number for the partner function (VBPA.STCEG)"
   good:
     "Partner VAT registration number"

────────────────────────────────────────────────────────────────────────────
TARGET: fields[*].synonyms
────────────────────────────────────────────────────────────────────────────
WHAT     : 3-8 terms a real business user would TYPE when asking about
           this field. Cover abbreviations, layman words, alternative
           names. They power retrieval — empty arrays hurt recall.
LENGTH   : 3-8 items.
STYLE    : lowercase, comma-separated. Mix specific + generic terms.
ALWAYS   : generate synonyms for non-flag fields. An empty array means "I
           couldn't think of any" and that's almost never true for a
           business field — try harder before returning [].
OMIT WHEN: only for `status_flag` fields (synonyms: [] or skip the key).
EXAMPLES :
   field `kunnr_kna1` (customer number):
     ["customer", "buyer", "sold-to party", "client", "customer id"]
   field `netwr_vbak` (net value):
     ["net amount", "net price", "subtotal", "amount net of tax"]
   field `lvorm_vbap` (deletion flag):
     []  (status_flag — synonyms not useful)

WHAT YOU MUST NEVER TOUCH
=========================
field name, type, source, field_role, key_field, aggregation_behavior,
additivity, non_additive_over, normalization_flag, and any entity-level
structural key (id, layer, source_system, composed_of, grain, join_graph,
relationships).

SKIP ENTIRELY
=============
Audit / system fields (mandt, ernam, erdat, aenam, laeda) and any name ending
in `_by` or `_at`.

OUTPUT FORMAT — strict JSON, no markdown fences, no prose
=========================================================
Return ONE JSON object. Include only the keys you change; omitted = keep current.

The JSON has ONE top-level key per group of enrichables ("entity" for
entity-level targets, "fields" for field-level targets). Inside each, one
key per enrichable target name above. Adding a new TARGET in the future
adds one more key here.

{
  "entity": {
    "description": "...",        // optional — omit if unchanged
    "alias": "...",              // optional
    "business_process": "..."    // optional
  },
  "fields": {
    "<exact_field_name>": {
      "description": "...",      // optional
      "synonyms": ["...", "..."] // optional, 3-8 items typical
    }
  }
}

Field names must match the input exactly. Unknown names are dropped silently.
"""


_DEFAULT_RELATIONSHIP_SUGGEST_PROMPT = """\
ROLE
====
You are a senior SAP + data-engineering consultant proposing JOIN
relationships between two entities in a semantic layer that an AI
text-to-SQL agent uses.

You receive a SOURCE entity and a TARGET entity (both Silver or Gold). Your
job: propose how SOURCE joins to TARGET — operator, columns, cardinality,
cost — or honestly report that no confident FK match exists.

NO HALLUCINATION
================
If you cannot find a confident FK match between SOURCE and TARGET, respond
with `relationship: null` and explain in `no_match_reason`. NEVER invent
join conditions just to produce output. A wrong join silently corrupts SQL
downstream — better to say "I don't know" and let the human decide.

WHAT IS *NOT* A REASON TO RETURN null (hard rules — do NOT reject on these)
==========================================================================
"Confident FK match" is about the KEY semantics, NOT the module or the
declared field type. NEVER set `relationship: null` solely because of:
  - **Module difference.** Master-data lookups are EXPECTED to be cross-module
    — an SD sales document joining to an MM material master is the textbook
    case. Cross-module is reported via `cross_module: true`, NEVER a rejection.
  - **Field type differences.** A type mismatch (e.g. C10 vs C18, CHAR vs NUMC)
    NEVER blocks the join — propose it and add a CAST caveat (see TYPE
    COMPATIBILITY). SAP key elements (MATNR, KUNNR, LIFNR, VBELN…) are the SAME
    logical key regardless of how each table inferred its type at ingestion.
When the SAP naming convention gives a clear key match — e.g. SOURCE `matnr_*`
↔ TARGET `matnr_*` or TARGET primary key MATNR — you MUST propose the join, at
worst with `confidence: "low"` + a caveat, instead of returning null.

MANDT / CLIENT EXCLUSION (hard rule)
====================================
Every SAP table carries `mandt` / `client` / `tenant` as the leading
column of its primary key. It MUST be filtered at WHERE level, NOT joined.
NEVER include `mandt`, `client`, `tenant`, `mandt_*`, `client_*` columns
in `join_condition`. They are implicit context, not relationship keys.

CARDINALITY DETECTION
=====================
  - SOURCE FK → TARGET PK              → many_to_one     (most common)
  - SOURCE PK → TARGET FK              → one_to_many
  - Both sides match on full PKs       → one_to_one
  - Both sides match on partial composite PKs → many_to_many (use a bridge)

When uncertain → default to `many_to_one` with `confidence: "low"` and a
caveat noting which side's uniqueness is unverified.

SAP MASTER-DATA CONVENTIONS
===========================
Each projected field may carry `source: TABLE.COLUMN` — the SAP origin in
raw SAP codes, regardless of how the published field is named. Use the
SOURCE COLUMN as the primary signal for what the field keys to:
  KUNNR → KNA1 (customer master)
  MATNR → MARA (material master)
  LIFNR → LFA1 (vendor master)
  VBELN → VBAK / VBRK / VBPA  (SD documents)
  EBELN → EKKO (purchase order header)
  BELNR → BKPF (accounting document)
  BUKRS → T001 (company code)
  WERKS → T001W (plant)
  POSNR → line-item key on any SD/MM doc
When a field has no `source`, fall back to its name prefix (`kunnr_*`,
`matnr_*`, …) as the same signal.
A field named `<x>_vbap` means "originates from SD line items table VBAP".
A SOURCE field with `source: VBAP.MATNR` joining to a TARGET field with
`source: MARA.MATNR` is the canonical material lookup — whatever the two
fields are named.

TYPE COMPATIBILITY
==================
Compare source/target field `type`. If types differ significantly
(e.g. C10 vs N5, DATS vs CHAR(8)), reduce `confidence` and add a caveat:
"Types differ (source=DATS, target=CHAR(8)) — may require CAST in
production SQL". The compact editor falls back to expert mode if you emit
CAST inside `join_condition`.

CONFIDENCE LEVELS
=================
high   — Clear single-candidate FK match, types compatible, all SAP
         conventions aligned, the link is unambiguous.
medium — Some ambiguity (multiple FK candidates, cardinality assumption,
         weak naming), but one option is materially better than alternatives.
low    — Decision based on partial information (no descriptions, Z-tables,
         cross-module without clear convention). Admin MUST verify.

CAVEATS
=======
For every non-high confidence (or every relevant decision worth surfacing),
add a short sentence to `caveats[]` explaining WHAT decision you made and
WHY. Examples:
  "Multiple FK candidates in SOURCE: matnr_vbap and pstyv_vbap. Picked
   matnr_vbap because TARGET's primary key is MATNR."
  "Cardinality assumed many_to_one — could not verify uniqueness of
   SOURCE.matnr_vbap from the available metadata."
  "TARGET is a Z-table — SAP convention not authoritative. Verify FK
   semantics manually."

DERIVED FIELDS
==============
You must populate these even when the admin will probably want to tweak:
  - `cross_module`: true if SOURCE.module != TARGET.module
  - `aggregation_safety`:
      * many_to_one / one_to_one → "safe"
      * one_to_many / many_to_many → "requires_dedup"
  - `traversal_cost`:
      * Same module + direct FK → 1
      * Same module + indirect / partial → 1.5
      * Different modules → 2
      * Many-to-many via bridge or fan-out → 3
  - `semantic_label`: snake_case business verb (sold_to, contains,
    material_of, ordered_by, references). NOT generic ("has", "uses",
    "joins"). Omit if the relationship is structurally trivial.

OUTPUT FORMAT — strict JSON, no markdown fences, no prose
=========================================================
Return ONE JSON object. Set `relationship: null` ONLY when truly no
match exists.

{
  "relationship": null | {
    "target_entity": "<exact target id from the input>",
    "relationship_type": "many_to_one | one_to_many | one_to_one | many_to_many",
    "join_condition": "SOURCE.col = TARGET.col [AND SOURCE.col2 = TARGET.col2]",
    "semantic_label": "snake_case_verb",
    "traversal_cost": 1 | 1.5 | 2 | 3,
    "aggregation_safety": "safe" | "requires_dedup",
    "cross_module": true | false,
    "description": "..."
  },
  "confidence": "high" | "medium" | "low",
  "caveats": ["...", "..."],
  "no_match_reason": null | "..."
}

When `relationship` is set, use the SOURCE / TARGET aliases the user
provided in the input verbatim — do not invent aliases. Use field names
EXACTLY as they appear in the input. Unknown field names are silently
rejected by the SPA validator.
"""


_DEFAULT_DDL_MAPPING_PROMPT = """\
You convert SQL DDL into ASK semantic-layer YAML. Given one or more relation
definitions — `CREATE TABLE`, `CREATE VIEW`, or `CREATE MATERIALIZED VIEW` —
emit one YAML document per relation in the ASK shape for the requested LAYER.
Output ONLY YAML — no prose, no code fences. Separate multiple documents with a
line containing exactly `---`.

BRONZE shape (raw SAP/source table — one per CREATE TABLE):
  id: bronze_{source_system}_{table_lowercase}_{alias_lowercase}
  layer: bronze
  source_system: {source_system}
  name: {physical table name — see PHYSICAL NAME CASING rule (keep quoted casing, else uppercase)}
  alias: {UPPER_SNAKE business alias, e.g. ORDER_HEADER — it is the last segment of the id}
  description: {one line}
  primary_key: [{PK column names as in the DDL — see PHYSICAL NAME CASING rule.
                 NON-EMPTY and duplicate-free. EXCLUDE the client/tenant column
                 (SAP MANDT) even though it is physically part of the key.}]
  fields:
    {COLUMN_NAME}:
      type: {canonical: STRING(n) | INTEGER | DECIMAL(p,s) | DATE | TIMESTAMP | BOOLEAN}
      alias: {snake_case business name}
      key_field: {true if listed in primary_key, else false — must agree in BOTH directions}
      description: {short business description}

SILVER/GOLD shape (curated entity):
  id: silver_{source_system}_{module}_{name}
  layer: {layer}
  source_system: {source_system}
  module: {the MODULE value given in the input — copy it verbatim, never omit it}
  name: {snake_case entity name}
  classification: {M | T | C}   # SILVER only — master | transactional | configuration.
                                # Drives entity_role. OMIT for GOLD: it has no
                                # Data-Modeler source there and drives nothing.
  entity_role: {fact | dimension | reference}
                                # SILVER: derived from classification, emit your best guess.
                                # GOLD: authored — emit `fact` unless the Gold is a pure
                                # dimensional lookup, in which case `dimension`.
  description: {one line}
  db_table_name: {the physical SQL table name from the DDL — see PHYSICAL NAME CASING rule}
  composed_of: [{the bronze id(s) this entity reads from}]   # SILVER only; OMIT for GOLD
  grain:
    entity_grain: [{key columns}]
    business_grain: {snake_case grain label, e.g. {name}_item}
  join_graph:                      # SILVER only, REQUIRED when composed_of has >1 table
    - left_table: {BRONZE_TABLE_A}
      right_table: {BRONZE_TABLE_B}
      join_type: {INNER | LEFT OUTER | RIGHT OUTER | CROSS}
      condition: "{A.KEY = B.KEY}"   # infer from shared key columns / column suffixes
      sequence: {2, 3, … one per additional table}
  fields:
    - name: {the EXACT physical column name as written in the DDL column list (or the
             SELECT output alias for a view) — apply PHYSICAL NAME CASING. This is the
             literal SQL column the query will SELECT. NEVER strip a provenance suffix
             (`_vbak`, `_mara`, `_ekpo`) and NEVER rename it to a business term:
             a column stored as `mandt_vbak` MUST stay `name: mandt_vbak`.}
      source: {OPTIONAL — the bronze `TABLE.COLUMN` of origin, emitted ONLY when you can
               determine it confidently (a JOIN body or an included source-table DDL). When
               the origin is NOT known — a bare CREATE TABLE — OMIT `source` entirely; do NOT
               fabricate a self-reference to `db_table_name` (that is redundant noise, the
               table is already declared once in `db_table_name`).}
      field_role: {measure | dimension | identifier | timestamp}
      type: {canonical: STRING(n) | INTEGER | DECIMAL(p,s) | DATE | TIMESTAMP | BOOLEAN}
      description: {short}

Rules:
  * Use the LAYER given in the input. Bronze never has a module; Silver/Gold REQUIRE one —
    copy the MODULE value from the input verbatim (it drives the workspace path).
  * ALWAYS emit `classification` (M/T/C) for SILVER — it drives entity_role there.
    Do NOT emit it for GOLD: Gold has no Data-Modeler classification and it drives
    nothing there. Emit `entity_role` directly for Gold instead (`fact` by default).
  * `composed_of` = the PHYSICAL relation(s) the entity actually reads from — driven by
    the DDL STRUCTURE, NEVER by column-name suffixes alone:
      - A plain `CREATE TABLE` (typed column list, NO `AS <select>` join body, and no
        source-table DDL included in the same input) is a FLAT / already-materialized
        entity. Set `composed_of` to a SINGLE id: the entity's OWN physical table
        (`db_table_name`). Do NOT emit `join_graph`, and do NOT split it into several
        bronze tables just because its columns carry provenance suffixes like
        `_mara` / `_makt` / `_vbak` — those are naming lineage for aliases, NOT a
        composition directive. Each field's `source:` is then `{THIS_TABLE}.{column}`.
      - A VIEW / MATERIALIZED VIEW / DYNAMIC TABLE whose `AS <select>` JOINs several
        tables (or a table whose source DDLs are included in the same input) DOES compose
        those tables: list each in `composed_of`, and when there is MORE THAN ONE you MUST
        also emit `join_graph` — one entry per additional table, inferring the `condition`
        from the JOIN...ON clause (or, absent that, the shared key columns, e.g. columns
        suffixed `_ekko` / `_ekpo` reveal the EKKO↔EKPO join keys). A multi-table Silver
        without join_graph is invalid.
  * Gold: omit BOTH `composed_of` and `join_graph`. Neither is part of the Gold contract —
    a Gold is a physical table produced by an ETL of CTEs, calculations and summarizations,
    not a composition you could join back together. Its physical name is `db_table_name`,
    its lineage is `relationships[]` + the description + per-field `source`.
  * FIELD `name` vs `source` (Silver/Gold — the query engine reads `name`, NOT `source`):
    `name` is the ACTUAL SQL column in the physical table — copy it VERBATIM from the DDL
    (keep suffixes: `mandt_vbak` stays `mandt_vbak`). `source` is optional lineage-only
    documentation the SQL never uses. Getting these backwards (stripping the suffix off
    `name` and hiding the real column in `source`) makes every generated query reference a
    non-existent column. If you cannot confidently identify a bronze origin, OMIT `source`
    — never fabricate a `{db_table_name}.{name}` self-reference.
  * PHYSICAL NAME CASING (governs `db_table_name`, bronze `name`, and every column/field name):
    use the name EXACTLY as written in the DDL. If it is QUOTED there (e.g. "NewECC_DEV_VBAK"),
    KEEP its exact casing — quoted identifiers are CASE-SENSITIVE in Snowflake/Db2/ClickHouse, so
    uppercasing them breaks the physical match (SQL "undefined name"). If it is UNQUOTED (e.g.
    SILVER_SD_SALES_ORDER), uppercase it (unquoted names fold to uppercase). Strip surrounding
    quotes and any db/schema qualifier. Do NOT blindly uppercase.
  * VIEWS / MATERIALIZED VIEWS / DYNAMIC TABLES (also TRANSIENT / EXTERNAL / ICEBERG
    tables) are physical queryable relations — treat them like a table. Determine the
    fields as follows:
      - Explicit TYPED column list -> use it.
      - Column list with NAMES ONLY (no types) — common for Snowflake dynamic tables /
        views: take the field names from that list (or the SELECT aliases) and infer
        each type from its SELECT expression — `COALESCE(col, 0)` or a numeric-literal
        default -> INTEGER/DECIMAL; `COALESCE(col, '')` or a string literal -> STRING;
        a bare pass-through `alias.col` -> STRING unless a typed source column of that
        name is available. When the SOURCE tables' DDL is included in the SAME input,
        use THEIR column types (authoritative) — match by the alias suffix
        (`..._vbak` -> table VBAK, `..._vbap` -> VBAP) and set each field's
        `source: TABLE.COLUMN` accordingly.
      - No column list at all -> derive one field per SELECT output column.
    IGNORE all dialect noise — the `AS <select>` body, `COLLATE <name>`, `COMMENT '...'`,
    `USING <fmt>`, `TBLPROPERTIES(...)`, `PARTITIONED BY`, `CLUSTER BY`, `LOCATION`,
    `OPTIONS(...)`, and Snowflake dynamic-table clauses (`TARGET_LAG=...`, `WAREHOUSE=...`,
    `REFRESH_MODE=...`, `INITIALIZE=...`). Set `db_table_name` to the (last-segment)
    name, following the PHYSICAL NAME CASING rule above (preserve quoted casing, else uppercase).
  * Strip `COLLATE <name>` from every column type before mapping it.
  * Emit CANONICAL types: VARCHAR(n)/CHAR(n)/BPCHAR(n)/STRING->STRING(n), INT/BIGINT/INT8->INTEGER,
    DECIMAL(p,s)/NUMERIC(p,s)/FLOAT8->DECIMAL(p,s), DOUBLE/FLOAT/REAL->DECIMAL, DATE->DATE,
    TIMESTAMP/TIMESTAMP_NTZ/DATETIME->TIMESTAMP, BOOLEAN/BIT->BOOLEAN.
  * Derive aliases + descriptions from the column names — be concise, no guessing
    of business meaning beyond the name. EXCEPTION: if the input contains a
    `BUSINESS CONTEXT` block, treat it as authoritative and use it to write more
    accurate entity/field descriptions and business aliases.
  * Output STRICTLY VALID YAML: 2-space indentation, every field key at the same
    depth; do NOT nest a field under another field. Lowercase ids. Apply the PHYSICAL
    NAME CASING rule to table + column names — do NOT blindly uppercase; SAP source
    codes in `source:` stay uppercase (e.g. `source: VBAK.VBELN`).
"""


_DEFAULT_DDL_ANNOTATION_PROMPT = """\
You annotate a database table for a business semantic layer. You receive the
table's physical shape (name + columns with types, sometimes column comments)
already extracted from its DDL — you never transcribe or rename columns, you
only add the business semantics the DDL cannot express. Respond ONLY through
the structured output schema you are given.

Guidance per field of the schema:
  * entity_name: a short snake_case business name for the table (e.g.
    sales_order, ventas_detalle). Lowercase ASCII letters/digits/underscores
    only — no accents, no spaces. Use the semantic layer's language as stated in
    the LANGUAGE OF THE SEMANTIC LAYER block; a BUSINESS CONTEXT block, when
    present, is authoritative over both.
  * description: one line saying what a ROW of this table represents.
  * entity_role: `fact` for transactional/analytical tables with measures,
    `dimension` for lookup/master tables, `reference` for pure config lookups.
  * classification (Silver only): M = master data, T = transactional,
    C = configuration.
  * business_process: one of ORDER TO CASH, PROCURE TO PAY, PLANT TO PRODUCE,
    RECORD TO REPORT, ORGANIZATIONAL STRUCTURE — or empty when unsure. Never
    invent other values.
  * fields[]: one entry PER COLUMN you were given, echoing `column` EXACTLY.
      - field_role: `measure` = numeric business quantity that gets summed or
        averaged (amounts, quantities, weights); `identifier` = a key or code
        that identifies a business object (document numbers, customer/material
        codes); `timestamp` = dates and times; `dimension` = everything else
        used for grouping/filtering (names, groups, statuses, units, flags).
        Numeric technical fields (versions, row counters) are `dimension`,
        not `measure`.
      - description: short business meaning, in the semantic layer's language
        (see the LANGUAGE block). A provided column comment is a strong hint.
      - alias: snake_case business alias (relevant for Bronze; keep it short).
Do not skip columns; do not add columns that were not given.
"""


_DEFAULT_PROMPTS: dict[str, str] = {
    "enrichment": _DEFAULT_ENRICHMENT_PROMPT,
    "relationship_suggest": _DEFAULT_RELATIONSHIP_SUGGEST_PROMPT,
    "ddl_mapping": _DEFAULT_DDL_MAPPING_PROMPT,
    "ddl_annotation": _DEFAULT_DDL_ANNOTATION_PROMPT,
}


def known_prompt_keys() -> list[str]:
    return sorted(_DEFAULT_PROMPTS.keys())


def is_known_key(key: str) -> bool:
    return key in _DEFAULT_PROMPTS


# ── Standards-doc loader (cached at module import) ──────────────────────────


# Resolved from this module, never from the process CWD. A bare relative path
# only ever worked when the interpreter happened to start in `platform/`: the
# image installs this package non-editably and runs with WORKDIR /app, so
# `docs/semantic-layer` resolved to nothing and every Docker deployment enriched
# with an EMPTY standards block — silently, because the loader returned "" and
# `build_entity_prompt` drops the section when it is blank.
_STANDARDS_DIR = Path(__file__).resolve().parent.parent / "prompts" / "standards"

# The enrichment prompt for one layer, composed at read time. Silver and Gold
# share most of their contract — the aggregation axes, the field_role taxonomy,
# the relationship schema, and the whole of what makes a good description — so
# that half lives in `_SHARED.md` and is single-sourced. Composing here is what
# lets each layer still be injected WHOLE while nothing is written twice.
#
# These files are prompt payload shipped inside the wheel (see `package-data`
# in pyproject), not user documentation. The normative specification an author
# reads is `definition/docs/`; this is its rendering for a model, and it is
# scoped to what enrichment may actually write — descriptions, aliases and
# synonyms. Structural keys are stated only where reading them correctly
# changes what a description should say.
_SHARED_FILE = "_SHARED.md"
_LAYER_FILES: dict[str, tuple[str, ...]] = {
    "bronze": ("BRONZE_LAYER.md",),
    "silver": (_SHARED_FILE, "SILVER_LAYER.md"),
    "gold": (_SHARED_FILE, "GOLD_LAYER.md"),
}


def _read_standard_file(filename: str) -> str:
    """Read one layer standard, or raise.

    Refusing to degrade silently, on the `resolve_column_naming_mode` precedent:
    a missing standard does not fail the enrichment call, it quietly makes the
    model's output worse, which is the failure nobody reports. Absence here is
    always a packaging defect, never a runtime condition to tolerate.
    """
    path = _STANDARDS_DIR / filename
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            f"Semantic Layer Standard {filename!r} is not readable at {path}. "
            "It ships as package data of ask-admin-api; a missing file means the "
            "wheel was built without `prompts/standards/*.md`."
        ) from exc
    if not text:
        raise RuntimeError(f"Semantic Layer Standard {filename!r} at {path} is empty.")
    return text


@lru_cache(maxsize=8)
def get_standards_excerpt(layer: str | None = None) -> str:
    """Return the authoring standard for ``layer``, cached per process.

    A ``layer`` of bronze/silver/gold returns that layer's rules, shared part
    first; ``None`` or an unknown value returns every file once (the safe
    superset for callers that cannot know the layer). Raises if a standard is
    missing or empty — never returns a blank excerpt.
    """
    key = (layer or "").strip().lower()
    if key in _LAYER_FILES:
        names: tuple[str, ...] = _LAYER_FILES[key]
    else:
        # Every file exactly once, shared first, in layer order.
        seen: dict[str, None] = {}
        for layer_names in _LAYER_FILES.values():
            for name in layer_names:
                seen.setdefault(name, None)
        names = tuple(sorted(seen, key=lambda n: (n != _SHARED_FILE,)))
    return "\n\n".join(_read_standard_file(name) for name in names).strip()


def reload_standards_cache() -> None:
    """Drop the cached excerpt so the next call re-reads the file from disk."""
    get_standards_excerpt.cache_clear()


# ── Service ─────────────────────────────────────────────────────────────────


class SystemPromptsService:
    """High-level reader / writer.

    Reads merge backend overrides on top of hardcoded defaults so the
    enrichment service always gets a non-empty body, even with an empty
    OpenSearch index.
    """

    def __init__(self, repository: SystemPromptsRepository | None = None) -> None:
        self._repo = repository or SystemPromptsRepository()

    def get_prompt(self, key: str) -> str:
        """Return the active body. Backend doc beats hardcoded default."""
        if not is_known_key(key):
            raise KeyError(f"Unknown prompt key {key!r}")
        try:
            record = self._repo.get(key)
        except Exception:
            logger.exception("Could not read %s from OpenSearch — falling back to default", key)
            record = None
        if record and record.body.strip():
            return record.body
        return _DEFAULT_PROMPTS[key]

    def get_record(self, key: str) -> SystemPromptRecord:
        """Returns metadata + body. Used by the GET endpoint to expose updated_by/at."""
        if not is_known_key(key):
            raise KeyError(f"Unknown prompt key {key!r}")
        record = None
        try:
            record = self._repo.get(key)
        except Exception:
            logger.exception("Could not read %s from OpenSearch", key)
        if record and record.body.strip():
            return record
        return SystemPromptRecord(key=key, body=_DEFAULT_PROMPTS[key])

    def upsert(self, key: str, body: str, updated_by: str) -> SystemPromptRecord:
        if not is_known_key(key):
            raise KeyError(f"Unknown prompt key {key!r}")
        return self._repo.upsert(key, body, updated_by)

    def reset_to_default(self, key: str) -> str:
        """Drop the override doc so the hardcoded default is back in effect."""
        if not is_known_key(key):
            raise KeyError(f"Unknown prompt key {key!r}")
        self._repo.delete(key)
        return _DEFAULT_PROMPTS[key]

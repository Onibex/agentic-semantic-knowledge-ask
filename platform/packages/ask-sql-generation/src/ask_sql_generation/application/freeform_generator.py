"""
FreeformSQLGeneratorService — Phase 4 of the **semi-deterministic hybrid pipeline**
(Plan v1, Step 2). Replaces the compiler-style `LLMSQLGeneratorService` for SQL
generation in the ASK Agentic flow.

Contract shift:
  - Old compiler (`LLMSQLGeneratorService`): received a fully resolved plan with
    physical columns/joins and only wrote syntax. Constrained by OutputShape.
  - New freeform generator: receives (1) the user question, (2) IR hints from
    Phase 1, (3) the full YAMLs of entities curated by Phases 2-3, and (4) the
    authoritative semantic glossary. The LLM reasons over the YAMLs and writes
    SQL freely — CTEs, subqueries, window functions, arithmetic between facts.
    Hallucination is bounded by "only columns/tables from these YAMLs".

Prompt origin:
  The SAP HANA rules block (CTE casing, window functions, date arithmetic,
  LIST_AGG, etc.) is ported verbatim from the earlier freeform chat pipeline —
  that prompt resolves the 10 benchmark business questions on Claude Sonnet 4.6.
  We add IR hints + YAML context + glossary sections on top.

Output:
  JSON with {sql, table_name, explanation, grain, is_dashboard_ready,
  rules_applied, error} — the shape downstream formatting/execution code
  consumes unchanged.

Token accounting:
  Calls are tagged `freeform_sql_generation` via `track_phase(...)` and captured
  by the `AutoTrackingCallback` attached at the factory level.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

from .prompts import hana as _prompts_hana
from .prompts import postgresql as _prompts_pg
from .prompts.registry import get_dialect, supported_dialects
from .scope_validator import (
    audit_sql_scope,
    build_allowed_tables,
    build_entity_table_map,
    format_scope_feedback,
)

# The token tracker lives in `ask-llm-gateway`. Make the import optional so this
# package can be installed and tested in isolation (e.g. CI builds that do not
# install the gateway).
try:
    from ask_llm_gateway.infrastructure.response_utils import (
        content_to_text,  # type: ignore[import-not-found]
    )
    from ask_llm_gateway.infrastructure.token_tracker import (
        track_phase,  # type: ignore[import-not-found]
    )
except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def track_phase(_name: str):  # type: ignore[no-redef]
        yield

    def content_to_text(response):  # type: ignore[no-redef]
        c = getattr(response, "content", response)
        return c if isinstance(c, str) else str(c)


# ─────────────────────────────────────────────────────────────────────────────
# Dialect rules now live in application/prompts/{hana,postgresql}.py.
# These local aliases are kept so the rest of this module continues to read
# `_HANA_STRICT_RULES` / `_PG_STRICT_RULES` (zero-risk Iter 3 extraction).
# ─────────────────────────────────────────────────────────────────────────────
_HANA_STRICT_RULES = _prompts_hana.STRICT_RULES
_PG_STRICT_RULES = _prompts_pg.STRICT_RULES


# Rules 7-8 (2026-07-30) propagate rules that were ALREADY ratified in the
# semantic-layer standards (docs/semantic-layer/, then a single file) but had
# never reached the prompt — not a compensating PATCH like the date rules in
# prompts/{hana,postgresql}.py:
#   rule 7 ← the grain contract (`grain.entity_grain` is R/S, "drives
#            grain-correctness & dedup"; checklist: "entity_grain matches the
#            physical key").
#   rule 8 ← the `aggregation_behavior` contract + "already cumulative —
#            do NOT SUM" (description hazards).
#
# Rule 8 rewritten (2026-08-01) for the two-axis contract
# (internal design doc REQ_ADDITIVITY_CONTRACT): `aggregation_behavior`
# is now a pure SQL function and `additivity` + `non_additive_over` carry the
# scope. It keeps a branch for the OLDER encoding (`measure` + `none`, no
# `additivity`) on purpose: `SilverField` shims that shape at the model
# boundary, but what reaches this prompt is the stored `raw_yaml` TEXT, which
# the shim never touches. Un-migrated YAMLs must therefore still read correctly
# here — dropping that branch would silently make every legacy running total
# summable.
# The semi-additive collapse is stated in PROSE, with no worked SQL, for the
# reason measured below: an example in this block behaves as a template the
# model copies, not as a guardrail. A ROW_NUMBER() illustration was drafted for
# this rule and cut on that evidence.
#
# Origin: a stock-coverage question emitted a non-aggregated CTE over a Gold
# whose grain is (client, plant_id, material_id), filtered on material_id only,
# and consumed it as a scalar → Postgres 21000. §8 aggregation_safety and the
# join-path block only cover fan-out ACROSS a join; this is multiplicity WITHIN
# one table, which nothing covered.
#
# DELIBERATELY NOT A RULE: "a scalar subquery must return one row" and "many
# rows ⇒ aggregate or GROUP BY" are general SQL competence the model already
# has — it wrote a correct SUM on the demand side of the very query that failed.
# Rules that restate general SQL cost attention on every call across all 9
# dialects and risk over-constraining; keep this block to facts about OUR
# contract that the model cannot infer.
#
# A draft rule 9 spelling this out, with a WRONG/CORRECT worked example, was
# written and then REMOVED. An internal probe (3 arms × 6 samples,
# claude-sonnet-4-6, this question, these YAMLs) measured the cost: with the
# example, 6/6 outputs collapsed into the example's exact CROSS-JOIN
# single-total shape; without it, 6/6 produced a richer grain-aware per-plant
# breakdown. The example acted as a template, not a guardrail.
# CAVEAT — that run did NOT establish rule 9 is unnecessary for safety: the
# control arm (rules 1-6, the pre-fix state) did not reproduce the original
# crash either, so the harness cannot discriminate on safety. It omits the IR
# hints / edges / enrichments the live precise path supplies. The safety net
# for this failure class is the execution-error retry (BACKLOG group P), which
# cannot over-constrain the way a rule can.
#
# Any SQL literal added below must be valid on all 9 engines (no
# predicate-as-select-item, no LIMIT, no `||`).
_YAML_READING_RULES = """HOW TO READ THE YAML SCHEMAS (critical — misread = wrong SQL):

1. `db_table_name` is THE single physical table to query.
   - Silver/Gold entities are already DENORMALIZED at ingestion time.
   - There is ONE physical table per entity, NOT one per source SAP table.
   - Example: if `db_table_name: SILVER_MM_PURCHASE_ORDER`, query
     `FROM "SILVER_MM_PURCHASE_ORDER"` — NEVER alias multiple copies
     of this table (no self-joins).

2. `fields[].name` is the ACTUAL SQL column name in that physical table.
   - Use lowercase column names with double quotes: `"banfn_ebkn"`.
   - Example field:
         - name: banfn_ebkn
           source: EBKN.BANFN
     → the column in the physical table is `banfn_ebkn`, NOT `EBKN.BANFN`.

3. `fields[].source`, where present, is LINEAGE metadata (bronze table.column of
   origin). A GOLD carries no `source` at all — it composes nothing, so its
   `name` IS the physical column and there is no second name to confuse.
   - NEVER use `source` in SQL. It is documentation for data engineers.
   - DO NOT write `"EBKN"."BANFN"` or `"ekpo"."EBELN"` — those are wrong.
     The bronze tables (EBKN, EKPO, EKKO, AFKO, VBAK, etc.) do NOT exist
     in the query database; only the Silver/Gold `db_table_name` does.

4. `composed_of` + `join_graph` are ETL/build metadata (HOW the Silver was
   assembled from bronze tables during ingestion). They are NOT runtime
   joins. DO NOT JOIN anything inside a single Silver YAML — every field
   listed is already a column of the single denormalized table.

5. You DO join BETWEEN different entities (cross-YAML) when the question
   requires it. Example: joining Silver Purchase Order with Silver Material
   Master is a valid cross-entity join via their common key column. But
   joining a Silver with itself, or joining to bronze tables, is ALWAYS wrong.

6. If you need a column that appears with a suffix like `_ekko`, `_ekpo`,
   `_afko`, etc., that suffix is part of the column name — it disambiguates
   when multiple bronze tables contributed a column with the same short name
   (e.g. both EKKO and EKPO have `MANDT`, stored as `mandt_ekko` and
   `mandt_ekpo` respectively in the Silver). Pick the one that matches the
   semantic role you need (header field → *_ekko; item field → *_ekpo, etc.).

7. `grain.entity_grain` is the UNIQUENESS CONTRACT of the physical table, and it
   is authoritative: exactly ONE row per distinct combination of those fields,
   and MANY rows whenever your WHERE pins only a SUBSET of them. Consult it
   before assuming the cardinality of anything you select.
   Example: gold_s4h_mm_inventory_position declares
       grain:
         entity_grain: ["client", "plant_id", "material_id"]
   → WHERE "material_id" = 'TG12' returns ONE ROW PER PLANT, not one row.

8. HOW to aggregate a measure — TWO keys answer two different questions:
   `aggregation_behavior` = WHICH function, `additivity` = over WHICH dimensions
   that function is valid. Read both.
     - `aggregation_behavior`: SUM / MAX / AVG / MIN / COUNT / COUNT_DISTINCT →
       use exactly that function. Absent → not yet curated; treat a
       `field_role: measure` as additive and SUM it.
     - `additivity: semi_additive` → the value REPEATS or ACCUMULATES along the
       dimensions listed in `non_additive_over`. Aggregating across those
       double-counts. This is a TWO-STEP operation and both steps are required:
         STEP 1 — reduce to ONE row per the grain MINUS `non_additive_over`.
           Do this in a subquery or CTE that GROUPs BY that reduced key and
           picks the value with MAX (or MIN) — or a `SELECT DISTINCT` whose
           select-list is exactly that reduced key plus the value.
           Two ways to get this wrong, both of which silently return a WRONG
           NUMBER rather than an error:
             · `SUM` at the reduced key — sums the repeated copies, multiplying
               the value by how many rows it repeats on.
             · `SUM(DISTINCT <value>)` — de-duplicates by VALUE instead of by
               key, so two genuinely different rows that happen to share a
               value collapse into one and the total comes out too LOW. Never
               put DISTINCT inside an aggregate for this; it is not a
               substitute for reducing on the key.
         STEP 2 — only THEN apply `aggregation_behavior` across whatever the
           question groups by.
       WHICH row to keep in step 1 depends on why it repeats:
         · a value that ACCUMULATES along a TIME dimension (a running total, a
           projected balance, a stock restated on every date) → keep the LATEST
           row by that dimension. When the series is sparse, "latest" means the
           last row at or before the target value, not equality with it.
         · a value that merely REPEATS because a join fanned the rows out (a
           header amount restated on every item, a stock level restated on every
           movement line) → every copy is identical, so ANY one row is exact.
       Two rows of the SAME entity can carry different `non_additive_over` sets —
       each measure declares its own — so reduce per measure, not once for the
       whole query.
     - `additivity: non_additive` → never apply an arithmetic aggregate; report
       per row, or GROUP BY the full grain.
     - `additivity` absent → additive: the function is valid across any grouping.
       ONE exception, the older encoding still present in some YAMLs:
       `aggregation_behavior: none` on a `field_role: measure` that declares no
       `additivity` means NON-ADDITIVE (an already-cumulative total such as
       `cumulative_sales_order`, or a projected balance such as `future_stock`).
       NEVER SUM that; collapse to one row per grain group instead.
   NEVER apply an arithmetic aggregate (SUM/AVG) to a field whose `field_role`
   is dimension, identifier, timestamp, attribute or status_flag. Where they MAY
   appear differs, and the difference matters:
     - `dimension` / `identifier` / `timestamp` → GROUP BY and WHERE.
     - `status_flag` → GROUP BY and WHERE too. A status IS a legitimate grouping
       key ("orders by processing status", "materials by stock status"); its
       value space is small and each value is a business state.
     - `attribute` → WHERE and SELECT only, NEVER GROUP BY. These are free-text
       descriptions and names, so grouping by one is near-1:1 with the row and
       produces a meaningless aggregate. GROUP BY the code, SELECT the text.
   COUNT / COUNT(DISTINCT …) on an identifier IS correct and is the right way to
   answer "how many orders/documents".
   The keys above are AUTHORITATIVE. `field_role`, `aggregation_behavior`,
   `additivity` and `non_additive_over` decide how a measure may be aggregated,
   and they are derived, not guessed. A `description` carries business MEANING,
   not a second contract: it may add a restriction the keys cannot express — the
   only one today is a technical lifecycle flag you should `WHERE` out ("use to
   exclude deleted items") — but it may NEVER relax one. If a description
   appears to permit an aggregation the keys forbid, the KEYS WIN.
"""


_CONTEXT_EXPANSION_PROTOCOL = """CONTEXT EXPANSION PROTOCOL (2-pass — only enabled when the caller says so):

The SCHEMA section above may contain ONLY Gold authoritative entities (the
curated data products). If you cannot fully answer the question with those
Golds alone — for example because you need a dimension lookup, a linage
detail, or a specific Silver table — you may REQUEST additional context
instead of emitting SQL.

When you request more context, output JSON in THIS form INSTEAD of the SQL
form (not both — choose one):

{
    "need_more_context": true,
    "requested_entities": [
        {"id": "silver_...", "reason": "why you need it"},
        ...
    ]
}

Rules for requests:
  - IDs must be valid `silver_*` / `gold_*` identifiers from the registry.
  - Do NOT request bronze (*.table names like EKPO, VBAK); those never exist
    in the query database.
  - Request up to 5 entities per round. Be surgical: only ask for what you
    cannot derive from the current SCHEMA.
  - If the current Golds already contain the columns you need, emit SQL
    directly — do NOT request extra context "just in case".
  - If a DISCONNECTION WARNING is present above, you likely need a Silver
    bridge entity that connects the Gold anchors. Ask for it.

If the caller did NOT mark this as the first pass (no `CONTEXT EXPANSION
ENABLED` header), ignore this block and always emit SQL with the regular
response format.
"""


_RESPONSE_FORMAT = """RESPONSE FORMAT (JSON only, no markdown):

OPTION A — you can answer with the supplied SCHEMA:
{
    "table_name": "primary table used (or comma-separated list if multiple facts)",
    "sql": "SELECT ... your query here ...",
    "explanation": "brief reasoning for the chosen approach (joins, CTEs, arithmetic)",
    "grain": "transactional|aggregated",
    "is_dashboard_ready": true|false,
    "rules_applied": ["list of key rules from the rules block you used"]
}

OPTION B — you need more context (ONLY valid when `CONTEXT EXPANSION ENABLED`
is present in the prompt):
{
    "need_more_context": true,
    "requested_entities": [
        {"id": "silver_xyz", "reason": "..."}
    ]
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _safe_json_loads(text: str) -> dict[str, Any]:
    """
    Parse JSON that may contain unescaped control characters inside string
    values. Kept byte-compatible with the earlier chat pipeline's recovery so
    behavior is aligned across both.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    result: list[str] = []
    in_string = False
    escape_next = False
    _ctrl = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and (ord(ch) < 0x20 or ord(ch) == 0x7F):
            result.append(_ctrl.get(ch, ""))
        else:
            result.append(ch)
    return json.loads("".join(result))


# Sibling keys the SQL-generation response is known to emit. Used to anchor the
# loose extractor below so an unescaped quote inside the SQL doesn't fool it.
_RESPONSE_KEYS = (
    "table_name|explanation|grain|is_dashboard_ready|columns_used|tables_used|scope_audit"
)


def _loose_extract_sql_response(text: str) -> dict[str, Any] | None:
    """Last-resort recovery when the LLM emits invalid JSON.

    The usual culprit is an UNESCAPED double quote inside the ``sql`` value —
    SAP HANA identifiers are double-quoted (``"SCHEMA"."TABLE"``) and the model
    sometimes forgets to escape them, which prematurely closes the JSON string
    ("Unterminated string"). ``_safe_json_loads`` only repairs control chars,
    not stray quotes.

    We anchor on the known sibling keys: capture the ``sql`` value up to the
    next ``", "<known-key>":`` boundary (or the closing brace), so embedded
    quotes/newlines inside the SQL are tolerated. Returns ``None`` if no SQL can
    be recovered, so the caller still surfaces a clean parse error.
    """
    m = re.search(
        rf'"sql"\s*:\s*"(.*?)"\s*(?:,\s*"(?:{_RESPONSE_KEYS})"\s*:|\}})',
        text,
        re.DOTALL,
    )
    if not m or not m.group(1).strip():
        return None
    out: dict[str, Any] = {"sql": m.group(1).strip()}
    em = re.search(r'"explanation"\s*:\s*"(.*?)"\s*(?:,\s*"\w+"\s*:|\})', text, re.DOTALL)
    if em:
        out["explanation"] = em.group(1).strip()
    return out


def _format_ir_hints(ir_hints: dict[str, Any] | None) -> str:
    """Render the Phase 1 IR as a hint block for the LLM (not a constraint)."""
    if not ir_hints:
        return "INTENT HINTS: (none — rely on the question and schema)"
    lines = ["INTENT HINTS (from upstream Phase 1 IR — orientative, not binding):"]
    keys_preferred = [
        "intent_summary",
        "semantic_metrics",
        "semantic_dimensions",
        "filters",
        "module_hint",
        "time_context",
        "detected_entity_hint",
        "limit",
        "sorting",
    ]
    for k in keys_preferred:
        if k in ir_hints and ir_hints[k] not in (None, "", [], {}):
            lines.append(f"- {k}: {ir_hints[k]}")
    lines.append(
        "These are hints, not hard constraints. Use them to orient the query; "
        "deviate if the schema makes a better choice evident."
    )
    return "\n".join(lines)


def _format_yamls(yamls: list[str]) -> str:
    """Join curated YAMLs with separators into a single schema block."""
    if not yamls:
        return "(no schemas supplied — cannot generate SQL without context)"
    blocks = [y.strip() for y in yamls if y and y.strip()]
    return "\n\n---\n\n".join(blocks)


def _format_glossary(glossary: str) -> str:
    if not glossary or not glossary.strip():
        return "AUTHORITATIVE GLOSSARY: (empty)"
    return (
        "AUTHORITATIVE GLOSSARY (from semantic dictionary — prefer these mappings "
        "when the user's terminology matches a known business term):\n" + glossary.strip()
    )


def _format_disconnection_warning(
    connectivity: dict[str, Any] | None,
) -> str:
    """
    Render a warning block when the supplied anchors are not all connected
    in the edge graph. The LLM sees this and knows it can request a Silver
    bridge entity via the CONTEXT EXPANSION PROTOCOL.
    """
    if not connectivity or connectivity.get("connected", True):
        return ""

    components = connectivity.get("components") or []
    missing = connectivity.get("missing_in_graph") or []

    lines = [
        "⚠️  DISCONNECTION WARNING — the Gold anchors supplied in SCHEMA are "
        "NOT all connected in the edge registry. Groups of anchors that have "
        "no declared path between them:",
    ]
    for i, comp in enumerate(components, 1):
        lines.append(f"   Group {i}: {', '.join(comp)}")
    if missing:
        lines.append(f"   Not present in edge graph at all: {', '.join(missing)}")
    lines.append(
        "\nIf your query needs columns from multiple groups, you likely need "
        "to request a Silver bridge entity via the CONTEXT EXPANSION PROTOCOL. "
        "Otherwise, pick ONE group and generate SQL within it."
    )
    return "\n".join(lines)


def _format_resolved_paths_hint(
    resolved_paths: dict[str, Any] | None,
) -> str:
    """
    Render the Dijkstra-resolved JOIN paths block.

    Input shape (output of `PathSelectorService.select_resolved_paths`):
      {
        "base_entity": "silver_s4h_sd_sales_order",
        "paths": [
          {"target": "silver_s4h_sd_trading_goods",
           "entity_chain": [...], "edges": [...], "total_cost": 1.0,
           "hops": 1, "grain_impact": "safe"},
          ...
        ],
        "unreachable": ["silver_s4h_xx"],
      }

    This block supersedes the bare edge listing when available: it centers
    the query on a chosen `base_entity` and ranks targets by cost, matching
    spec §8.2 (grain > safety > cost > hops).
    """
    if not resolved_paths or not resolved_paths.get("base_entity"):
        return ""

    base = resolved_paths["base_entity"]
    paths = resolved_paths.get("paths") or []
    unreachable = resolved_paths.get("unreachable") or []

    lines = [
        "RESOLVED JOIN PATHS (Dijkstra-ranked, authoritative — prefer the "
        "shorter/cheaper path when multiple reach the same target. Use THESE "
        "conditions for cross-entity joins; do not invent new ones):",
        f"  base_entity: {base}",
    ]
    if not paths:
        lines.append("  (no reachable targets from base_entity in this scope)")
    for p in paths:
        target = p.get("target")
        cost = p.get("total_cost", 0.0)
        hops = p.get("hops", 0)
        grain = p.get("grain_impact", "safe")
        grain_tag = "  ⚠ fan_out_risk" if grain == "fan_out_risk" else ""
        lines.append(f"\n  → to {target}  (cost={cost}, hops={hops}){grain_tag}")
        chain = " → ".join(p.get("entity_chain") or [])
        lines.append(f"      chain: {chain}")
        for e in p.get("edges") or []:
            conds = (
                " AND ".join(
                    f'"{c["left_field"]}" {c["operator"]} "{c["right_field"]}"'
                    for c in (e.get("conditions") or [])
                )
                or "(no conditions declared)"
            )
            lines.append(
                f"      {e.get('source')} → {e.get('target')}  "
                f"[{e.get('join_type')} JOIN, {e.get('cardinality')}]  "
                f"ON {conds}"
            )
    if unreachable:
        lines.append(
            "\n  unreachable from base (do NOT attempt to join these — "
            "no path exists in the semantic graph):"
        )
        for u in unreachable:
            lines.append(f"      - {u}")
    lines.append(
        "\nWhen a target has grain_impact=fan_out_risk, aggregate measures "
        "of the base before joining, or use DISTINCT on the base PK, to "
        "avoid duplicated rows."
    )
    return "\n".join(lines)


def _requalify_predicate(predicate: str, entity_tables: dict[str, str] | None) -> str:
    """Rewrite entity-id qualifiers in a join predicate to physical table names.

    SILVER §7.2.1 / GOLD §6.3.1 require every qualifier to already BE the
    ``db_table_name`` of its side, and that stays the contract. This is the
    read-side salvage for predicates that violate it — in practice, edges
    authored (by AI Suggest or by hand) while the entity still carried the
    ``db_table_name = id`` default it gets when the SAP export names no physical
    table. Correcting ``db_table_name`` afterwards does NOT fix them, because the
    name is embedded by VALUE inside the predicate string, so the edge silently
    goes stale. Resolving here instead means the prompt always reflects the
    CURRENT ``db_table_name``.

    Deliberately a qualifier-token substitution, not a re-parse: the predicate is
    rendered verbatim precisely because that is the only form surviving multi-key
    ``AND``, ``IN (...)`` and other non-equality shapes. Only tokens that (a) are
    a known entity id and (b) sit in qualifier position (followed by ``.``) are
    touched, so operators, literals, ``IN`` lists and column names cannot be.
    """
    if not predicate or not entity_tables:
        return predicate
    alternation = "|".join(re.escape(k) for k in entity_tables)
    # Lookbehind keeps us off a longer identifier, a quoted name and a chained
    # `a.b.c` — the token must start the qualifier.
    pattern = re.compile(rf'(?<![\w."])({alternation})(\s*\.)', re.IGNORECASE)

    def _sub(match: re.Match[str]) -> str:
        table = entity_tables.get(match.group(1).lower())
        return f"{table}{match.group(2)}" if table else match.group(0)

    return pattern.sub(_sub, predicate)


def _format_edges_hint(edges: list[Any] | None, entity_tables: dict[str, str] | None = None) -> str:
    """
    Render the authoritative JOIN-paths block for the freeform prompt.

    Input: list of `RelationEdge` dataclass instances (forward edges only,
    already scoped to the expanded entity set by `PathSelectorService.
    get_edges_between`).

    `entity_tables` is `{entity_id: db_table_name}` for the retrieved YAMLs
    (`scope_validator.build_entity_table_map`), used to resolve id-qualified
    predicates to physical names — see `_requalify_predicate`.

    Output: a legible block the LLM uses to pick cross-entity JOIN conditions
    without having to re-parse the YAML `relationships` sections.
    """
    if not edges:
        return (
            "CROSS-ENTITY JOIN PATHS: (none declared between the entities "
            "in this scope — if the question requires joining multiple "
            "entities and you cannot find a valid join, say so honestly "
            "in `explanation` rather than inventing one)"
        )

    lines: list[str] = [
        "CROSS-ENTITY JOIN PATHS (authoritative — use THESE conditions when "
        "joining between entities in the SCHEMA section. Do NOT invent join "
        "predicates; if a needed path is absent, say so in `explanation`):",
    ]

    def _edge_get(e: Any, key: str, default: Any = None) -> Any:
        # Iter 8.8: edges arrive as dicts from the IntentResolutionResult
        # serialization (precise_strategy._serialize_edge / smart_strategy
        # ._serialize_v2_edge). Older callers may still pass RelationEdge /
        # EdgeInfo dataclasses; handle both shapes.
        if isinstance(e, dict):
            return e.get(key, default)
        return getattr(e, key, default)

    def _cond_get(c: Any, key: str, default: Any = None) -> Any:
        if isinstance(c, dict):
            return c.get(key, default)
        return getattr(c, key, default)

    def _qualified(entity: Any, table: Any) -> str:
        """`entity_id (table: PHYSICAL_NAME)` — never make the model infer the link.

        The entity id and the physical table differ by more than case
        (`gold_s4h_inventory_situation` vs `GOLD_INVENTORY_SITUATION`), and the ON
        clause is written in physical names while this line names entities. Printing
        both removes the inference step.
        """
        entity_str = str(entity or "")
        table_str = str(table or "")
        # The edge document is the primary source, but it can legitimately carry
        # no table: `_build_edge_pair` emits "" for the target side rather than
        # fabricate one from a predicate that broke the qualifier contract. The
        # retrieved YAMLs still know the answer, so fall back to them.
        if not table_str and entity_tables:
            table_str = entity_tables.get(entity_str.lower(), "")
        if table_str and table_str.lower() != entity_str.lower():
            return f"{entity_str} (table: {table_str})"
        return entity_str

    for e in edges:
        jt = _edge_get(e, "join_type", "")
        join_type = jt.value if hasattr(jt, "value") else str(jt)
        cd = _edge_get(e, "cardinality", "")
        card = cd.value if hasattr(cd, "value") else str(cd)

        # Predicate resolution order:
        #   1. `join_predicate` — the authored SQL, verbatim. The only form that
        #      survives multi-key `AND`, `IN (...)` and other non-equality shapes.
        #   2. parsed `conditions` — recomposed for documents written before
        #      `join_predicate` existed.
        # Conditions are no longer rendered with quotes around each operand: they
        # produced `ON "A.x" = "B.y"`, which reads as string literals in SQL.
        predicate = str(_edge_get(e, "join_predicate") or "").strip()
        if not predicate:
            conditions = _edge_get(e, "conditions") or []
            predicate = " AND ".join(
                f"{_cond_get(c, 'left_field')} "
                f"{_cond_get(c, 'operator')} "
                f"{_cond_get(c, 'right_field')}"
                for c in conditions
                if _cond_get(c, "left_field") and _cond_get(c, "right_field")
            )
        predicate = predicate or "(no join condition declared — do NOT invent one)"
        # Resolve id qualifiers against the CURRENT db_table_name (design C).
        predicate = _requalify_predicate(predicate, entity_tables)

        # `source_node` = RelationEdge / Precise; `source_entity` = EdgeInfo / Smart;
        # `source` = the Dijkstra path block's shape. Smart's key was missing from
        # this chain, so every Smart edge rendered with an empty entity name.
        src = _edge_get(e, "source_node") or _edge_get(e, "source_entity") or _edge_get(e, "source")
        tgt = _edge_get(e, "target_node") or _edge_get(e, "target_entity") or _edge_get(e, "target")
        src_label = _qualified(src, _edge_get(e, "source_table"))
        tgt_label = _qualified(tgt, _edge_get(e, "target_table"))
        cost = _edge_get(e, "traversal_cost", "?")
        safety = str(_edge_get(e, "aggregation_safety") or "").strip()

        header = f"- {src_label}  ↔  {tgt_label}  ({join_type} JOIN, {card}, cost={cost}"
        # Only the non-default value is printed: `safe` is the default and adds noise.
        if safety and safety != "safe":
            header += f", {safety}"
        lines.append(header + ")")
        lines.append(f"    ON {predicate}")

        # The curator's traversal/dedup caveat. Authored per SILVER §7.4 / GOLD §6.5
        # ("state this in the edge description") and dropped by every indexer until
        # now, so it reached no prompt unless the whole entity YAML was retrieved.
        description = str(_edge_get(e, "description") or "").strip()
        if description:
            lines.append(f"    NOTE: {description}")

    # FAN-OUT. Keyed on the cardinality printed above, which is the same predicate
    # the authoring surfaces use to derive `aggregation_safety` (fan-out cardinality
    # <-> requires_dedup holds on 126/126 authored edges), so the cardinality is a
    # complete trigger and needs no extra field indexed to work.
    #
    # This rule previously lived in the Dijkstra-path block, which never renders —
    # `select_resolved_paths` has no callers, so `resolved_paths` is always empty and
    # this function is always the branch taken. It said the right thing to nobody.
    #
    # Deliberately prose, with no worked SQL: a measured template-collapse (6/6) when
    # an example was added to the YAML-reading rules block. The correct operation is
    # pre-aggregation to the base grain, NOT a bare `SELECT DISTINCT` over the
    # projection — that returns the wrong number in both directions (it double-counts
    # when the projection carries the drill-down column, and collapses legitimately
    # identical rows when it does not).
    lines.append(
        "\nFAN-OUT: a `one_to_many` or `many_to_many` hop MULTIPLIES rows on the "
        "base side. Before aggregating a measure of the base across such a hop, "
        "reduce the base to one row per its `entity_grain` first (aggregate it in a "
        "CTE, or `DISTINCT` on its grain key) — never `SUM`/`COUNT` the multiplied "
        "rows and never rely on a bare `SELECT DISTINCT` over the output columns to "
        "undo it. `many_to_one` and `one_to_one` hops do not multiply rows."
    )
    return "\n".join(lines)


def _format_field_enrichments(
    field_enrichments: dict[str, list[dict[str, Any]]] | None,
) -> str:
    """
    Render the value-level enrichments block for the freeform prompt.

    Input shape (bulk lookup by entity_id):
      {
        "gold_s4h_order_tracking_reception": [
          {"technical_name": "material_id", "examples": ["F226","Z"],
           "is_preferred_id": True, "disambiguation_hint": "...", ...},
          {"technical_name": "material",    "examples": ["Raw Steel A"], ...},
          {"technical_name": "order_status","examples": ["Open","Completed"],
           "value_synonyms": {"finalized": "Completed"}, ...},
        ],
        ...
      }

    Empty input → explicit "(none)" so the LLM knows there are no authoritative
    hints, instead of silently missing the section.
    """
    if not field_enrichments:
        return "FIELD ENRICHMENTS (value-level hints): (none)"

    lines: list[str] = [
        "FIELD ENRICHMENTS (authoritative — use these to pick the correct column "
        "and map user-provided values to actual stored values):",
    ]
    for entity_id, fields in field_enrichments.items():
        if not fields:
            continue
        lines.append(f"\n  entity: {entity_id}")
        for f in fields:
            tn = f.get("technical_name") or "?"
            tags: list[str] = []
            if f.get("type"):
                tags.append(f"type={f['type']}")
            if f.get("is_preferred_id"):
                tags.append("is_preferred_id=true")
            header = f"    {tn}" + (f"  ({', '.join(tags)})" if tags else "")
            lines.append(header)

            if f.get("canonical_label"):
                lines.append(f"      canonical: {f['canonical_label']}")
            examples = f.get("examples") or []
            if examples:
                lines.append(f"      examples: {', '.join(str(x) for x in examples)}")
            vs = f.get("value_synonyms") or {}
            if vs:
                mapped = ", ".join(f"{k!s} → {v!s}" for k, v in vs.items())
                lines.append(f"      synonyms: {mapped}")
            if f.get("disambiguation_hint"):
                lines.append(f"      hint: {f['disambiguation_hint']}")
    if len(lines) == 1:
        return "FIELD ENRICHMENTS (value-level hints): (none)"
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class FreeformSQLGeneratorService:
    """
    Phase 4 of the semi-deterministic hybrid pipeline.

    Input (assembled by the caller — usually the LangGraph node):
      - question:             user question (original language)
      - ir_hints:              dict form of SemanticPlanIR (orientative only)
      - yamls:                 list of raw YAML strings from Phases 2-3 curation
      - glossary:              concatenated business-term mappings
      - conversation_history:  recent chat turns for follow-up resolution
      - pg_sap_rules:          optional additional dialect rules (Postgres)
      - user_system_prompt:    optional role/profile personalization prefix

    Output:
      dict in the canonical generator shape, so downstream execution/formatting
      code consumes it unchanged.
    """

    def __init__(self, llm, db_type: str) -> None:
        self.llm = llm
        self.db_type = (db_type or "hana").lower()

    # ── public API ──────────────────────────────────────────────────────────

    def generate(
        self,
        *,
        question: str,
        ir_hints: dict[str, Any] | None = None,
        yamls: list[str] | None = None,
        glossary: str = "",
        conversation_history: str = "",
        pg_sap_rules: str = "",
        user_system_prompt: str = "",
        field_enrichments: dict[str, list[dict[str, Any]]] | None = None,
        edges: list[Any] | None = None,
        resolved_paths: dict[str, Any] | None = None,
        validate_scope: bool = True,
        max_scope_retries: int = 1,
        connectivity: dict[str, Any] | None = None,
        context_expansion_enabled: bool = False,
        hana_schema: str = "",
    ) -> dict[str, Any]:
        if not question or not question.strip():
            return {"error": "Empty question.", "sql": None}

        if not yamls:
            return {
                "error": (
                    "No YAMLs supplied to the SQL generator. Phases 2-3 did not "
                    "produce any relevant schema context."
                ),
                "sql": None,
            }

        prompt = self._build_prompt(
            question=question.strip(),
            ir_hints=ir_hints or {},
            yamls=yamls,
            glossary=glossary,
            conversation_history=conversation_history,
            pg_sap_rules=pg_sap_rules,
            user_system_prompt=user_system_prompt,
            field_enrichments=field_enrichments,
            edges=edges,
            resolved_paths=resolved_paths,
            connectivity=connectivity,
            context_expansion_enabled=context_expansion_enabled,
            hana_schema=hana_schema,
        )

        result = self._invoke_and_parse(prompt)

        # ── Scope validation + retry (Plan v1 #3) ───────────────────────────
        # Reject hallucinated tables (bronze lineage names, sibling-YAML tables,
        # invented identifiers). Bounded retry with explicit feedback.
        # Skipped when the LLM intentionally requested more context (2-pass flow).
        if (
            validate_scope
            and result.get("sql")
            and not result.get("error")
            and not result.get("need_more_context")
            and yamls
        ):
            allowed = build_allowed_tables(yamls)
            audit = audit_sql_scope(result["sql"], allowed)
            result["scope_audit"] = audit

            retries_left = max(0, max_scope_retries)
            attempt = 0
            while not audit["ok"] and retries_left > 0:
                attempt += 1
                print(
                    f"[FreeformSQL] ⚠️  scope audit failed "
                    f"(out_of_scope={audit['out_of_scope']}) — "
                    f"retry {attempt}/{max_scope_retries}"
                )
                feedback = format_scope_feedback(audit, result["sql"])
                retry_prompt = prompt + "\n\n" + feedback
                result = self._invoke_and_parse(retry_prompt)
                if not result.get("sql") or result.get("error"):
                    break
                audit = audit_sql_scope(result["sql"], allowed)
                result["scope_audit"] = audit
                retries_left -= 1

            if not audit["ok"]:
                # Non-fatal: surface warning but return the SQL anyway so the
                # operator can review. The flag also lets the UI/log highlight
                # it for QA.
                result["scope_warning"] = (
                    f"SQL references tables outside the curated scope: "
                    f"{audit['out_of_scope']}. Review before executing."
                )

        return result

    # ── 2-PASS EXPANSION FLOW ───────────────────────────────────────────────

    def generate_with_expansion(
        self,
        *,
        question: str,
        ir_hints: dict[str, Any] | None = None,
        gold_yamls: list[str],
        glossary: str = "",
        conversation_history: str = "",
        pg_sap_rules: str = "",
        user_system_prompt: str = "",
        field_enrichments: dict[str, list[dict[str, Any]]] | None = None,
        edges: list[Any] | None = None,
        resolved_paths: dict[str, Any] | None = None,
        connectivity: dict[str, Any] | None = None,
        fetch_silvers_fn=None,
        max_expansion_rounds: int = 1,
        validate_scope: bool = True,
    ) -> dict[str, Any]:
        """
        Two-pass SQL generation:

          Pass 1: prompt with ONLY Gold entities as SCHEMA. LLM may either
                  emit SQL directly OR request additional Silver entities
                  via `{need_more_context: true, requested_entities: [...]}`.

          Pass 2+: if the LLM requested context, fetch those entities via
                   `fetch_silvers_fn(ids: list[str]) -> list[dict]`, append
                   their YAMLs to the scope, and re-invoke. Bounded to
                   `max_expansion_rounds` additional rounds (default: 1 —
                   so up to 2 total passes).

        If the LLM still requests more after the bound is exhausted, the last
        result (which may still lack SQL) is returned with an `expansion_exhausted`
        flag so the caller can fall back to a heavier flow.

        Args:
            gold_yamls:          raw YAML strings of the starter Gold anchors.
            fetch_silvers_fn:    callable(ids) -> list[dict] with `raw_yaml` +
                                 `id` keys. Typically
                                 `EntityResolutionService.fetch_entities_by_ids`.
            connectivity:        output of
                                 `PathSelectorService.connectivity_report(gold_ids)`.
                                 When Golds are disconnected, a warning is
                                 injected into the prompt so the LLM knows to
                                 ask for a bridge Silver.
            max_expansion_rounds: hard cap on extra LLM calls after pass 1.
        """
        if not question or not question.strip():
            return {"error": "Empty question.", "sql": None}
        if not gold_yamls:
            # No Gold starter — caller should fall back to full pipeline.
            return {
                "error": (
                    "No Gold YAMLs supplied as starter. "
                    "Caller should fall back to full select_relevant_yamls."
                ),
                "sql": None,
                "expansion_rounds": 0,
            }

        scope_yamls: list[str] = list(gold_yamls)
        # Track ids that have already been fetched so we don't re-ask / duplicate
        fetched_ids: set = set()
        expansion_trace: list[dict[str, Any]] = []

        rounds_remaining = max(0, max_expansion_rounds)
        attempt = 0
        result: dict[str, Any] = {}

        while True:
            attempt += 1
            is_first_pass = attempt == 1
            # Only the first pass gets the expansion protocol enabled — after
            # we've already fetched, we want SQL, not more requests.
            expansion_on = is_first_pass and rounds_remaining > 0

            print(
                f"[Freeform 2-pass] round {attempt} — "
                f"scope_yamls={len(scope_yamls)}  expansion_enabled={expansion_on}"
            )

            result = self.generate(
                question=question,
                ir_hints=ir_hints,
                yamls=scope_yamls,
                glossary=glossary,
                conversation_history=conversation_history,
                pg_sap_rules=pg_sap_rules,
                user_system_prompt=user_system_prompt,
                field_enrichments=field_enrichments,
                edges=edges,
                resolved_paths=resolved_paths,
                validate_scope=validate_scope,
                # We disable scope retries during the first pass — scope errors
                # there often mean "needed more context" rather than hallucination.
                max_scope_retries=0 if is_first_pass else 1,
                connectivity=connectivity if is_first_pass else None,
                context_expansion_enabled=expansion_on,
            )

            # Did the LLM request more context?
            if result.get("need_more_context") and rounds_remaining > 0:
                req = result.get("requested_entities") or []
                requested_ids = [(r.get("id") if isinstance(r, dict) else r) for r in req if r]
                new_ids = [rid for rid in requested_ids if rid and rid not in fetched_ids]

                if not new_ids:
                    # LLM asked but for nothing new — break out.
                    print(
                        "[Freeform 2-pass] LLM requested no NEW entities "
                        "(all already in scope) — forcing SQL emission next"
                    )
                    rounds_remaining = 0
                    continue

                if fetch_silvers_fn is None:
                    print(
                        "[Freeform 2-pass] LLM requested context but no "
                        "fetch_silvers_fn provided — returning request verbatim"
                    )
                    result["expansion_rounds"] = attempt
                    result["expansion_trace"] = expansion_trace
                    return result

                print(f"[Freeform 2-pass] LLM requested {len(new_ids)} new entity(s): {new_ids}")
                fetched = fetch_silvers_fn(new_ids) or []
                expansion_trace.append(
                    {
                        "round": attempt,
                        "requested": req,
                        "fetched_ids": [f.get("id") for f in fetched],
                    }
                )
                for f in fetched:
                    fid = f.get("id")
                    if fid:
                        fetched_ids.add(fid)
                    yml = f.get("raw_yaml")
                    if yml and yml.strip():
                        scope_yamls.append(yml)

                rounds_remaining -= 1
                continue  # next pass with extended scope

            # Either SQL was emitted or we ran out of rounds / no fetcher.
            break

        result["expansion_rounds"] = attempt
        result["expansion_trace"] = expansion_trace
        if result.get("need_more_context") and rounds_remaining <= 0:
            result["expansion_exhausted"] = True
            print(
                "[Freeform 2-pass] ⚠️  expansion_exhausted — LLM still wants "
                "more context after max rounds"
            )
        return result

    # ── internal: single LLM call + JSON parse ──────────────────────────────

    def _invoke_and_parse(self, prompt: str) -> dict[str, Any]:
        """
        Invoke the LLM once with `prompt`, strip markdown fences, parse JSON,
        and normalize expected keys. Returns a dict with `sql` (possibly None)
        and `error` (possibly absent). Never raises.
        """
        # Diagnostic: prompt size helps measure the cost of passing full YAMLs
        print(
            f"[FreeformSQL] prompt length: {len(prompt):,} chars "
            f"(~{len(prompt) // 4:,} est. tokens)"
        )

        try:
            with track_phase("freeform_sql_generation"):
                response = self.llm.invoke([HumanMessage(content=prompt)])
            text = content_to_text(response).strip()
        except Exception as e:
            err = str(e)
            if "404" in err or "Not Found" in err:
                return {
                    "error": (
                        "**404 Not Found** — The LLM deployment was not found in SAP AI Core."
                    ),
                    "sql": None,
                }
            if "401" in err or "Unauthorized" in err:
                return {
                    "error": "**401 Unauthorized** — Invalid or expired AI Core credentials.",
                    "sql": None,
                }
            return {"error": f"Error invoking LLM: {e}", "sql": None}

        # Strip markdown fences the model sometimes emits despite the instruction
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            result = _safe_json_loads(text)
        except json.JSONDecodeError as e:
            # Surface the raw LLM output so the failure is diagnosable (it was
            # previously swallowed — nothing reached the console). len(text) is
            # the decisive signal for truncation: ~14-16k chars ≈ a 4096-token
            # cap, ~28-32k ≈ an 8192-token cap. The raw is capped at 1500 chars
            # for readability, so DON'T infer the cut point from it.
            _meta = getattr(response, "response_metadata", {}) or {}
            _usage = getattr(response, "usage_metadata", {}) or {}
            _finish = (
                _meta.get("finish_reason") or _meta.get("stop_reason") or _meta.get("stopReason")
            )
            logger.warning(
                "freeform SQL: JSON parse failed (%s). len(text)=%d finish_reason=%r "
                "out_tokens=%s. Attempting loose extract. raw=%r",
                e,
                len(text),
                _finish,
                _usage.get("output_tokens"),
                text[:1500],
            )
            recovered = _loose_extract_sql_response(text)
            if recovered is not None:
                logger.info("freeform SQL: recovered SQL via loose extract after JSON failure")
                result = recovered
            else:
                return {
                    "error": f"Failed to parse LLM JSON response: {e}",
                    "sql": None,
                    "raw_response": text[:2000],
                }

        # Normalize expected keys so downstream code doesn't KeyError
        result.setdefault("sql", None)
        result.setdefault("table_name", "")
        result.setdefault("explanation", "")
        result.setdefault("grain", "")
        result.setdefault("is_dashboard_ready", False)
        result.setdefault("rules_applied", [])

        # Missing SQL is only an error when the LLM DID NOT intentionally
        # request more context. The 2-pass expansion flow relies on this.
        if not result.get("sql") and not result.get("need_more_context"):
            result["error"] = result.get("error") or "LLM returned no SQL."

        return result

    # ── prompt assembly ─────────────────────────────────────────────────────

    def _build_prompt(
        self,
        *,
        question: str,
        ir_hints: dict[str, Any],
        yamls: list[str],
        glossary: str,
        conversation_history: str,
        pg_sap_rules: str,
        user_system_prompt: str,
        field_enrichments: dict[str, list[dict[str, Any]]] | None = None,
        edges: list[Any] | None = None,
        resolved_paths: dict[str, Any] | None = None,
        connectivity: dict[str, Any] | None = None,
        context_expansion_enabled: bool = False,
        hana_schema: str = "",
    ) -> str:
        history_block = (
            f"CONVERSATION HISTORY (use this to resolve follow-up questions):\n"
            f"{conversation_history}\n\n---\n\n"
            if conversation_history.strip()
            else ""
        )

        # Dialect prompt via the Strategy registry (lite multi-DB, 2026-07).
        # A0 fix: an unknown db_type RAISES instead of silently falling back to
        # the PostgreSQL prompt (which emitted LIMIT/|| — invalid for the
        # TOP/FETCH-FIRST family: SQL Server / Fabric / Db2).
        dialect = get_dialect(self.db_type)
        if dialect is None:
            raise ValueError(
                f"No SQL dialect prompt registered for db_type={self.db_type!r}. "
                f"Supported: {supported_dialects()}"
            )
        role_line = dialect.role_line
        user_prefix = (user_system_prompt.strip() + "\n\n") if user_system_prompt.strip() else ""
        rules_block = dialect.strict_rules
        schema_prefix_block = (
            dialect.schema_prefix(hana_schema) + "\n"
            if dialect.schema_prefix and hana_schema
            else ""
        )
        # `{entity_id: db_table_name}` from the same YAMLs `build_allowed_tables`
        # reads, so an id-qualified join predicate renders with the CURRENT
        # physical table instead of a name that cannot execute.
        entity_tables = build_entity_table_map(yamls)

        return (
            history_block
            + user_prefix
            + role_line
            + "\n\n"
            + f"USER QUESTION:\n{question}\n\n"
            + _format_ir_hints(ir_hints)
            + "\n\n"
            + _format_glossary(glossary)
            + "\n\n"
            + _format_field_enrichments(field_enrichments)
            + "\n\n"
            + (
                _format_resolved_paths_hint(resolved_paths) + "\n\n"
                if resolved_paths and resolved_paths.get("base_entity")
                else _format_edges_hint(edges, entity_tables) + "\n\n"
            )
            + (
                _format_disconnection_warning(connectivity) + "\n\n"
                if connectivity and not connectivity.get("connected", True)
                else ""
            )
            + (
                "CONTEXT EXPANSION ENABLED — this is the FIRST PASS. You may "
                "request additional entities instead of emitting SQL if needed "
                "(see CONTEXT EXPANSION PROTOCOL below).\n\n" + _CONTEXT_EXPANSION_PROTOCOL + "\n\n"
                if context_expansion_enabled
                else ""
            )
            + _YAML_READING_RULES
            + "\n"
            + "SCHEMA (YAMLs of entities curated by the upstream pipeline — "
            "read them according to the HOW TO READ block above. Use ONLY "
            "tables and columns defined here):\n"
            + _format_yamls(yamls)
            + "\n\n"
            + (
                (f"PG_SAP_RULES (additional dialect guidance):\n{pg_sap_rules}\n\n")
                if pg_sap_rules.strip()
                else ""
            )
            + schema_prefix_block
            + rules_block
            + "\n"
            + _RESPONSE_FORMAT
        )

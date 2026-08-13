"""DDL skeleton assembly — code owns structure, the model annotates semantics.

``build_skeleton`` turns a :class:`~.ddl_parser.ParsedRelation` into the raw
entity dict the import path lands, with every MECHANICAL fact taken from the
DDL (byte-exact column names, canonical types, the declared key, the physical
table name) and every SEMANTIC fact taken from an optional
:class:`EntityAnnotation` the LLM fills through a forced JSON schema. When the
annotation is missing (provider without tool support, parse failure) the
skeleton still builds a VALID entity — descriptions stay empty and roles fall
to the type-derived defaults, surfacing In Review for enrichment instead of
failing the import.

Layer contracts honored here (platform/docs/semantic-layer/, the authority):

* GOLD_LAYER.md §3.1: ``db_table_name`` is stated once, UNQUALIFIED; no
  ``composed_of`` / ``join_graph``; §4: ``fields[].source`` is never authored.
* SILVER/GOLD §4.1: ``aggregation_behavior`` is never emitted — absent means
  *not curated*; additivity is a curator's axis, not an importer's.
* SILVER/GOLD §5: AI paths never emit ``attribute`` / ``status_flag`` — the
  annotation schema physically cannot express them.
* GOLD §3.2: the grain is an AUTHORED promise — the skeleton proposes the
  DDL's declared key (PRIMARY KEY, else ClickHouse ORDER BY) and warns the
  author to verify uniqueness against the physical table.
* BRONZE §3.5: the client/tenant column (MANDT and canonical equivalents) is
  excluded from ``primary_key`` deliberately.

Everything the EntityDeriver fills mechanically on import (version,
internal_id, source_system_no, business_process placeholder, grain fallback,
role-from-type) is deliberately NOT duplicated here — ``import_yaml`` runs
``EntityDeriver.complete()`` on every doc, and one derivation home beats two.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ask_knowledge_graph.domain.naming import normalize_identifier
from ask_knowledge_graph.domain.source_profiles import get_profile

from .ddl_parser import ParsedRelation

# ── Annotation schemas (the LLM's forced JSON output) ───────────────────────
# Kept FLAT and closed on purpose: the schema is the contract a mid-tier model
# must satisfy, and every enum here is the official closed set for AI paths.


class FieldAnnotation(BaseModel):
    """Semantic annotation for ONE physical column."""

    column: str = Field(description="The physical column name, echoed EXACTLY as given.")
    field_role: Literal["measure", "dimension", "identifier", "timestamp"] = Field(
        description=(
            "measure = numeric business quantity that is summed/averaged; "
            "identifier = key or code identifying a business object; "
            "timestamp = date/time column; dimension = anything else you group by."
        )
    )
    description: str = Field(description="Short business description (one line).")
    alias: str = Field(
        default="",
        description="snake_case business alias for the column (used at Bronze).",
    )


class EntityAnnotation(BaseModel):
    """Semantic annotation for one relation — everything the DDL cannot say."""

    entity_name: str = Field(
        description=(
            "Short snake_case business name for the table (e.g. sales_order, "
            "ventas_detalle). Lowercase ASCII, no accents."
        )
    )
    description: str = Field(description="One-line business description of the table.")
    entity_role: Literal["fact", "dimension", "reference"] = Field(
        default="fact",
        description="fact = transactional/analytical measures; dimension = lookup master data.",
    )
    classification: Literal["M", "T", "C"] = Field(
        default="T",
        description="M = master data, T = transactional, C = configuration (Silver only).",
    )
    business_process: str = Field(
        default="",
        description=(
            "One of: ORDER TO CASH, PROCURE TO PAY, PLANT TO PRODUCE, RECORD TO REPORT, "
            "ORGANIZATIONAL STRUCTURE. Empty when unsure."
        ),
    )
    fields: list[FieldAnnotation] = Field(default_factory=list)


def annotation_user_payload(rel: ParsedRelation, *, layer: str, context: str) -> str:
    """The compact user message for the annotation call — column list only,
    never the raw DDL (the model has nothing to transcribe, only to judge)."""
    lines = [f"LAYER: {layer}", f"TABLE: {rel.name}"]
    if context.strip():
        lines += ["", "BUSINESS CONTEXT (authoritative):", context.strip()]
    lines += ["", "COLUMNS (name | type | comment):"]
    for c in rel.columns:
        comment = f" | {c.comment}" if c.comment else ""
        lines.append(f"- {c.name} | {c.raw_type}{comment}")
    return "\n".join(lines)


# ── Skeleton assembly ────────────────────────────────────────────────────────

# Canonical client/tenant column spellings (BRONZE §3.5). Deliberately narrow:
# excluding by guessy name lists risks dropping a legitimate key column.
_CLIENT_COLUMNS = {"mandt", "clnt", "client"}

# Known module tokens. `module` is AUTO-DETECTED from the physical table name
# (owner decision 2026-08-12: no Module picker in the UI), and only a WHITELIST
# match counts: the segment after the layer prefix is very often not a module at
# all — `gold_md_final` would otherwise adopt `md`. Anything unmatched falls back
# to `gen` (generic / cross-module), which is a legitimate value, not an error.
KNOWN_MODULES = frozenset(
    {
        "sd",  # Sales & Distribution
        "mm",  # Materials Management
        "pp",  # Production Planning
        "fi",  # Financial Accounting
        "co",  # Controlling
        "le",  # Logistics Execution
        "qm",  # Quality Management
        "pm",  # Plant Maintenance
        "ps",  # Project System
        "hr",  # Human Resources
        "wm",  # Warehouse Management
        "ewm",  # Extended Warehouse Management
        "tm",  # Transportation Management
        "aa",  # Asset Accounting
        "gen",  # generic / cross-module (explicit, not a fallback marker)
    }
)

DEFAULT_MODULE = "gen"

# `SILVER_SD_SALES_ORDER` / `gold_sd_open_orders` / `dbt.GOLD_FI_LEDGER` — the
# module is the token that FOLLOWS the layer prefix. Matches the SILVER_/GOLD_
# convention the layer auto-detection already keys on (SILVER/GOLD_LAYER.md §4
# naming tables).
_LAYER_PREFIXED_RE = re.compile(r"^(?:silver|gold)_([a-z0-9]+)_", re.IGNORECASE)


def detect_module(table_name: str, *, declared: str | None = None) -> str:
    """Resolve the module for one relation.

    Precedence: an explicitly ``declared`` module (API override) wins, then the
    token after a ``SILVER_``/``GOLD_`` prefix when it is a KNOWN module, else
    :data:`DEFAULT_MODULE`. Never raises, never invents a module.
    """
    explicit = (declared or "").strip().lower()
    if explicit and explicit in KNOWN_MODULES:
        return explicit
    if explicit:
        # An unknown explicit value is still the author's word — honour it rather
        # than silently substituting `gen`; the workspace path follows it.
        return explicit
    m = _LAYER_PREFIXED_RE.match((table_name or "").strip())
    if m:
        token = m.group(1).lower()
        if token in KNOWN_MODULES:
            return token
    return DEFAULT_MODULE

_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _id_token(value: str) -> str:
    """A lowercase alphanumeric id segment (the grammar forbids '_' inside the
    source/module/table tokens).

    Folds accents through ``normalize_identifier`` FIRST: stripping non-ASCII
    directly would delete the accented letter instead of folding it
    (``organización`` → ``organizacin``), so the two id segments of one entity
    would disagree on the same word."""
    return _ALNUM_RE.sub("", normalize_identifier(value, fallback=""))


def _entity_token(value: str, *, fallback: str) -> str:
    """The final id segment: lowercase snake_case, '_' allowed."""
    return normalize_identifier(value, fallback=fallback)


def build_skeleton(
    rel: ParsedRelation,
    *,
    layer: str,
    source_system: str,
    module: str | None = None,
    annotation: EntityAnnotation | None = None,
    context: str = "",
) -> tuple[dict, list[str]]:
    """Assemble the raw entity dict for ``import_yaml``. Returns
    ``(doc, warnings)``. Never raises on annotation absence.

    ``module`` is normally ``None``: it is AUTO-DETECTED per relation from the
    physical table name (see :func:`detect_module`), falling back to ``gen``.
    Pass a value only as an explicit API override."""
    warnings: list[str] = []
    mapper = get_profile(source_system).type_mapper
    ann = annotation
    ann_fields = {a.column: a for a in (ann.fields if ann else [])}
    module = detect_module(rel.name, declared=module)

    entity_name = _entity_token(
        (ann.entity_name if ann else "") or rel.name, fallback=rel.name or "entity"
    )
    src_token = _id_token(source_system) or "generic"
    description = (ann.description if ann else "") or ""

    if ann is None:
        warnings.append(
            f"'{rel.name}': AI annotation unavailable — descriptions and business names "
            f"were defaulted mechanically from the DDL; enrich the entity In Review."
        )

    if layer == "bronze":
        return _build_bronze(
            rel,
            mapper=mapper,
            source_system=source_system,
            src_token=src_token,
            entity_name=entity_name,
            description=description,
            ann_fields=ann_fields,
            warnings=warnings,
        )

    # ── Curated (silver / gold) ──────────────────────────────────────────────
    fields: list[dict] = []
    key_set = set(rel.primary_key)
    for col in rel.columns:
        fa = ann_fields.get(col.name)
        fd: dict = {"name": col.name, "type": mapper.canonical(col.raw_type)}
        # The DDL's declared key IS the identifier set — deterministic, and it
        # feeds the grain; an annotation cannot demote a key column.
        if col.name in key_set:
            fd["field_role"] = "identifier"
        elif fa is not None:
            fd["field_role"] = fa.field_role
        # else: absent — EntityDeriver.complete() derives the role from the type.
        desc = (fa.description if fa else "") or col.comment
        if desc:
            fd["description"] = desc
        fields.append(fd)

    doc: dict = {
        "layer": layer,
        "source_system": source_system,
        "module": module,
        "name": entity_name,
        "description": description,
        "db_table_name": rel.name,  # UNQUALIFIED, as written (GOLD §3.1)
        "fields": fields,
    }
    if (ann.business_process if ann else "") and ann is not None:
        doc["business_process"] = ann.business_process

    if rel.primary_key:
        doc["grain"] = {"entity_grain": list(rel.primary_key)}
        if rel.key_source == "order_by":
            warnings.append(
                f"'{rel.name}': grain proposed from the MergeTree ORDER BY key — a sorting "
                f"key is not guaranteed unique; verify with SELECT <grain>, COUNT(*) … "
                f"GROUP BY … HAVING COUNT(*) > 1 before publishing."
            )
    else:
        warnings.append(
            f"'{rel.name}': the DDL declares no PRIMARY KEY/ORDER BY — the grain falls "
            f"back to the annotated identifier columns; review it before publishing."
        )

    if layer == "gold":
        doc["id"] = f"gold_{src_token}_{entity_name}"
        doc["entity_role"] = (ann.entity_role if ann else "") or "fact"
        # NO composed_of / join_graph / classification / fields[].source at Gold.
    else:  # silver — a bare CREATE TABLE is a FLAT Silver: its own table, no joins
        module_token = _id_token(module) or "gen"
        doc["id"] = f"silver_{src_token}_{module_token}_{entity_name}"
        doc["classification"] = (ann.classification if ann else "") or "T"
        doc["composed_of"] = [rel.name]
        if ann is None:
            warnings.append(
                f"'{rel.name}': classification defaulted to 'T' (transactional) — "
                f"review it, it drives entity_role."
            )

    return doc, warnings


def _build_bronze(
    rel: ParsedRelation,
    *,
    mapper,
    source_system: str,
    src_token: str,
    entity_name: str,
    description: str,
    ann_fields: dict[str, FieldAnnotation],
    warnings: list[str],
) -> tuple[dict, list[str]]:
    # Client/tenant columns never enter primary_key (BRONZE §3.5) — the rule the
    # standard says DDL-imported Bronzes must apply deliberately.
    pk: list[str] = []
    for col_name in rel.primary_key:
        if col_name.lower() in _CLIENT_COLUMNS:
            warnings.append(
                f"'{rel.name}': client column '{col_name}' excluded from primary_key "
                f"(key_field: false) per the Bronze standard."
            )
            continue
        pk.append(col_name)

    fields: dict[str, dict] = {}
    used_aliases: set[str] = set()
    for col in rel.columns:
        fa = ann_fields.get(col.name)
        alias = normalize_identifier((fa.alias if fa else "") or col.name, fallback=col.name)
        base_alias, n = alias, 2
        while alias in used_aliases:  # in-file uniqueness is a Bronze invariant
            alias = f"{base_alias}_{n}"
            n += 1
        used_aliases.add(alias)
        fields[col.name] = {
            "type": mapper.canonical(col.raw_type),
            "alias": alias,
            "key_field": col.name in pk,
            "description": (fa.description if fa else "") or col.comment,
        }

    alias_upper = normalize_identifier(entity_name, fallback=rel.name or "table", upper=True)
    doc = {
        "id": f"bronze_{src_token}_{_id_token(rel.name)}_{alias_upper.lower()}",
        "layer": "bronze",
        "source_system": source_system,
        "name": rel.name,
        "alias": alias_upper,
        "description": description,
        "primary_key": pk,
        "fields": fields,
    }
    if not pk:
        warnings.append(
            f"'{rel.name}': keyless Bronze (no usable PRIMARY KEY in the DDL) — it will "
            f"contribute no key columns to any Silver grain."
        )
    return doc, warnings

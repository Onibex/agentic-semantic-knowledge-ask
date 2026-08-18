# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ── `business_process` canonical form ────────────────────────────────────────
# UP-1 (see the internal upstream defect report): `info.domainv`
# is a CHAR(20) column upstream, so the value arrives truncated in 7/7
# organisational-structure exports.
#
# `ORGANIZATIONAL STRUCTURE` is NOT a process — it is the Data Modeler's marker for
# a generic, cross-module entity (a plant belongs to PP, SD and MM at once). It is a
# first-class value of this vocabulary precisely because a blank would lose the
# "generic on purpose" vs "nobody filled it in" distinction.
#
# Only this one repair is evidenced. `FINANCE → RECORD TO REPORT` and
# `PLANT TO PRODUCE → PLAN TO PRODUCE` were both proposed and both refuted
# (`invoice`'s own export classifies it LEAD TO CASH, and nothing at all supports
# PLANT→PLAN), so they pass through untouched — a semantic re-assignment must not
# ride along inside a truncation fix.
_BUSINESS_PROCESS_ALIASES = {
    "ORGANIZATIONAL STRUC": "ORGANIZATIONAL STRUCTURE",
}


def normalize_business_process(value: str | None) -> str:
    """Canonical `business_process`: trimmed, whitespace-collapsed, upper-cased,
    then aliased.

    **Normalise, never reject.** Unknown values pass through unchanged, so no
    existing YAML and no future Data-Modeler value can fail ingest on this key — a
    `Literal` here would invalidate 9 Silvers and 5 Golds on day one. It lives on
    the model rather than in a writer for the reason recorded in
    REQ_ADDITIVITY_CONTRACT.md D7: a guarantee that lives in one writer is not a
    guarantee. Note the residual gap that precedent also names — the SQL prompt
    reads the stored YAML *text*, which no model-layer shim reaches, which is why
    the parser normalises on the way in as well.
    """
    collapsed = " ".join(str(value or "").split()).upper()
    return _BUSINESS_PROCESS_ALIASES.get(collapsed, collapsed)


class JoinConditionStr(BaseModel):
    left_field: str
    right_field: str
    operator: str = "="


class Relationship(BaseModel):
    target_entity: str
    # Closed set per spec Sec 6.5, and the reverse-inference table in Sec 6.5.1 maps
    # these values pairwise — so an out-of-set value does not merely mislabel an edge,
    # it makes the edge-registry reader raise inside a blanket `except Exception`,
    # which returns `[]` and silently deletes the ENTIRE edge graph for the Precise
    # plane. All 214 authored values are in-set, so this rejects nothing today; it
    # closes the one authoring surface that was not already constrained (the
    # relationships-only PUT, which runs no layer-model validation).
    # `cardinality` in the edge index is an alias of this field, not a second key.
    relationship_type: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    join_condition: str
    semantic_label: str
    traversal_cost: float = 1.0
    # Closed set per spec Sec 6.5. `unsafe` is the only value the spec attaches a
    # planner rule to (Sec 8.2: the path is rejected unless explicitly overridden),
    # and it is the value both public docs omit. 63/63 authored edges are in-set.
    aggregation_safety: Literal["safe", "requires_dedup", "unsafe"] = "safe"
    cross_module: bool = False
    description: str | None = None


class AskIdGenerator:
    @staticmethod
    def generate_bronze_id(source_system: str, table_name: str, table_alias: str) -> str:
        # Strict rule: bronze_{source_system}_{table_name}_{table_alias}, lowercase [cite: 154, 616]
        return f"bronze_{source_system}_{table_name}_{table_alias}".lower()

    @staticmethod
    def generate_silver_id(source_system: str, module: str, entity_name: str) -> str:
        # Strict rule: silver_{source_system}_{module}_{entity_name}, lowercase [cite: 215, 620]
        return f"silver_{source_system}_{module}_{entity_name}".lower()


class BronzeField(BaseModel):
    type: str
    alias: str
    key_field: bool
    description: str


class BronzeNode(BaseModel):
    id: str
    layer: Literal["bronze"] = "bronze"  # Must be exactly 'bronze' [cite: 154]
    version: str = "1"
    source_system: str
    source_system_id: int
    name: str  # TABNAME [cite: 154]
    alias: str  # ALIAS_TABNAME [cite: 154]
    description: str
    # May be EMPTY (owner decision 2026-08-03): `key_field` is the data-product
    # author's declaration and ASK consumes it as authority — an export table
    # with no declared key ingests as a keyless Bronze (warned at the parser,
    # surfaced to the author) instead of being rejected. The cross-field
    # agreement rules below still hold: an empty key with zero flagged fields
    # is self-consistent; a DISAGREEING file is still rejected.
    primary_key: list[str] = Field(...)
    fields: dict[str, BronzeField]

    # ─── CUSTOM VALIDATION (spec sections 16 and 21) ───

    @field_validator("id")
    def validate_id_format(cls, v, info):
        """Validate the id grammar (section 21.1) [cite: 154, 616].

        ``fullmatch`` rather than Silver/Gold's ``re.match(r"^…$")``: ``$`` also
        matches before a trailing ``\\n``, so the other layers' idiom would accept
        ``"bronze_s4h_vbak_order_header\\n"``. This being the first hard gate on
        an id, the hole is closed here.
        """
        if not re.fullmatch(r"bronze_[a-z0-9]+_[a-z0-9]+_[a-z0-9_]+", v):
            raise ValueError(
                "id must follow the pattern bronze_<source_system>_<table_name>_"
                "<table_alias>, lowercase."
            )
        return v

    @model_validator(mode="after")
    def validate_node_configuration(self):
        """Validate the Bronze key + alias contract (official checklist section 8).

        Accumulates ALL violations into a single error: a corrupt Bronze usually
        breaks several rules at once, and the curator should not have to repair
        them one at a time through successive 422s.
        """
        problems: list[str] = []

        # 1. primary_key must not repeat columns. The SAP exports repeat whole
        #    (tabname, fldname) rows and the parser used to accumulate them
        #    [cite: 188].
        counts = Counter(self.primary_key)
        dupes = sorted(k for k, n in counts.items() if n > 1)
        if dupes:
            problems.append(f"primary_key repeats columns: {dupes}.")

        # 2. Every primary_key member must exist in fields [cite: 188]
        unknown = [k for k in dict.fromkeys(self.primary_key) if k not in self.fields]
        if unknown:
            problems.append(f"primary_key references columns missing from fields: {unknown}.")

        # 3. key_field must agree with primary_key in BOTH directions
        #    [cite: 189, 190]. Agreement is defined against the DECLARED
        #    primary_key, not against the physical SAP key — which is why MANDT
        #    (present in every SAP table with key_field: false and never in
        #    primary_key) is valid.
        flagged = {name for name, fdef in self.fields.items() if fdef.key_field}
        declared = set(self.primary_key)
        if flagged - declared:
            problems.append(
                f"fields with key_field: true that are not in primary_key: "
                f"{sorted(flagged - declared)}."
            )
        if declared - flagged:
            problems.append(
                f"primary_key members without key_field: true: {sorted(declared - flagged)}."
            )

        # 4. Field aliases are unique within the file [cite: 193]. Compared
        #    lowercased because the ingestor's sanitizer forces lowercase ASCII
        #    snake_case: `SALES` and `sales` would collide after sanitation even
        #    though they differ as raw strings.
        acounts = Counter((fdef.alias or "").strip().lower() for fdef in self.fields.values())
        alias_dupes = sorted(a for a, n in acounts.items() if n > 1)
        if alias_dupes:
            problems.append(f"field aliases must be unique within a Bronze: {alias_dupes}.")

        if problems:
            raise ValueError(" ".join(problems))
        return self


# ── The two-axis aggregation contract (REQ_ADDITIVITY_CONTRACT.md) ──────────
#
# `aggregation_behavior` answers WHICH function; `additivity` answers over WHICH
# dimensions applying it is valid. They are independent facts: fusing them is
# what produced the `none`-means-two-things overload this pair replaces.
AggregationBehavior = Literal["SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT", "none"]
Additivity = Literal["additive", "semi_additive", "non_additive"]


class SilverField(BaseModel):
    name: str
    # `source` = real bronze lineage (e.g. VBAK.MANDT), documentation-only (never
    # used in SQL / retrieval). Optional: a FLAT Silver materialized from a single
    # physical table has no bronze origin, so it simply omits `source` rather than
    # fabricating a redundant self-reference to its own db_table_name.
    source: str = ""
    # The spec allows strictly one of these roles [cite: 255]
    field_role: Literal[
        "measure", "dimension", "identifier", "timestamp", "attribute", "status_flag"
    ]
    type: str
    description: str
    # Axis 1 — the SQL function, no hidden semantics. `None` (key absent) means
    # "not curated": a measure is then assumed ADDITIVE.
    aggregation_behavior: AggregationBehavior | None = None
    # Axis 2 — the scope. Measures only; absent means `additive`.
    additivity: Additivity | None = None
    # The grain dimensions along which the value repeats or accumulates, so they
    # must be collapsed before the function is applied. Required iff
    # `semi_additive`. Any grain dimension is allowed (v2): a TEMPORAL one collapses
    # to the latest row, a structural fan-out dimension collapses to any one row
    # because every row in the group carries the same value. See the node-level
    # check in `_additivity_scope_problems`.
    non_additive_over: list[str] | None = None
    # Alternative business names, to widen retrieval. Declared here because the
    # model is the gate: the admin API has always authored and round-tripped this
    # key, but with no attribute on this class Pydantic's default `extra='ignore'`
    # dropped it at validation, so it reached neither the field registry nor the
    # embedded text. It was authorable and persisted, and consumed by nothing.
    synonyms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_additivity_contract(self):
        """Field-local half of the contract. Accumulates every problem into one
        error rather than failing on the first (the D3 precedent from Bronze)."""
        # Legacy-encoding shim (REQ_ADDITIVITY_CONTRACT §4.5), applied here rather
        # than in a write path on purpose. Before `additivity` existed, a
        # non-additive measure was encoded as `aggregation_behavior: none` and
        # nothing else; under the new contract an absent `additivity` means
        # ADDITIVE, so reading a legacy YAML literally would flip every running
        # total into a summable measure. Enforcing it at the model boundary means
        # every path — SAP parser, YAML ingestion, admin save, direct construction
        # — reads the legacy shape identically. A path-dependent assumption about
        # what `none` means is precisely what caused the double-count bug this
        # contract replaces, so the guarantee does not live in one writer.
        if (
            self.additivity is None
            and self.field_role == "measure"
            and self.aggregation_behavior == "none"
        ):
            self.additivity = "non_additive"

        problems: list[str] = []

        if self.additivity is not None and self.field_role != "measure":
            problems.append(
                f"field '{self.name}': `additivity` applies only to field_role 'measure', "
                f"got '{self.field_role}'."
            )

        if self.additivity == "semi_additive" and not self.non_additive_over:
            problems.append(
                f"field '{self.name}': `additivity: semi_additive` requires a non-empty "
                "`non_additive_over` naming the dimensions to collapse first."
            )

        if self.non_additive_over and self.additivity != "semi_additive":
            problems.append(
                f"field '{self.name}': `non_additive_over` is only meaningful with "
                f"`additivity: semi_additive`, got additivity={self.additivity!r}."
            )

        if self.additivity == "non_additive" and self.aggregation_behavior != "none":
            problems.append(
                f"field '{self.name}': `additivity: non_additive` requires "
                f"`aggregation_behavior: none`, got {self.aggregation_behavior!r}."
            )

        if problems:
            raise ValueError(" ".join(problems))
        return self


def _additivity_scope_problems(fields: list[SilverField], grain: "Grain") -> list[str]:
    """Cross-field half of the contract: `non_additive_over` must name real grain
    dimensions that resolve to selectable columns.

    **v2 (2026-08-03) — ANY grain dimension is accepted, not only `timestamp`.**
    v1 restricted these to timestamp fields, on the reasoning that "collapse to the
    latest one" is undefined for a non-temporal dimension. That conflated the two
    reasons a value needs collapsing:

    * it **ACCUMULATES** along the dimension (a running total, a projected balance)
      — then the collapse really must pick the LATEST row, and the dimension really
      must be ordered, i.e. temporal;
    * it **REPEATS** along the dimension because a join fans the rows out (a stock
      level restated on every movement line, a header amount restated on every item)
      — then every row in the group carries the SAME value, so collapsing to ANY one
      row is exact, and the dimension needs no ordering at all.

    Only the first case needs a timestamp. The second is the ordinary shape of a
    denormalised Silver — a measure whose native grain is coarser than the row grain
    — and v1 could not express it at all, which pushed the instruction into prose
    where the SQL generator had latitude and repeatedly got it wrong. See
    `EntityDeriver.fanout_dims_by_table`, which derives exactly these dimensions
    mechanically, and the conditional wording in the SQL prompt's rule 8.

    Kept as a helper because SilverNode and GoldNode both need it and neither is
    a subclass of the other.
    """
    problems: list[str] = []
    grain_fields = set(grain.entity_grain)
    by_name = {f.name: f for f in fields}

    for fdef in fields:
        for dim in fdef.non_additive_over or []:
            if dim not in grain_fields:
                problems.append(
                    f"field '{fdef.name}': `non_additive_over` names '{dim}', which is not "
                    f"in grain.entity_grain {sorted(grain_fields)} — collapsing a dimension "
                    "outside the grain is meaningless."
                )
                continue
            if by_name.get(dim) is None:
                problems.append(
                    f"field '{fdef.name}': `non_additive_over` names '{dim}', which is in "
                    "grain.entity_grain but matches no field — the grain does not resolve "
                    "to a selectable column."
                )
    return problems


class JoinCondition(BaseModel):
    left_table: str
    right_table: str
    join_type: Literal[
        "INNER", "LEFT OUTER", "RIGHT OUTER", "CROSS"
    ]  # Based on spec section 6.4 [cite: 263]
    condition: str
    sequence: int


class Grain(BaseModel):
    entity_grain: list[str] = Field(
        ..., min_length=1
    )  # The spec requires a non-empty grain [cite: 571]
    business_grain: str


class SilverNode(BaseModel):
    id: str
    internal_id: str
    db_table_name: str | None = None
    layer: Literal["silver"] = "silver"  # Must be exactly 'silver' [cite: 221]
    version: str
    source_system: str
    source_system_no: int
    business_process: str
    module: str | list[str]
    # Secondary categorization for catalog faceting (ASK Spec 6.1). Fed from the
    # SAP export as tag1 <- info.tag4 and tag2 <- info.tag5 — the offset in the
    # numbering is the spec's, not a bug. Optional because hand-authored entities
    # may omit them; declared so they are no longer silently dropped by
    # extra='ignore' and so they can be indexed and faceted on.
    tag1: str | None = ""
    tag2: str | None = ""
    name: str
    classification: str
    description: str
    # The spec allows strictly one of these roles [cite: 245, 570]
    entity_role: Literal["fact", "dimension", "reference"]
    grain: Grain
    composed_of: list[str]
    join_graph: list[JoinCondition] | None = []
    fields: list[SilverField]
    relationships: list[Relationship] = Field(default_factory=list)

    # ─── CUSTOM VALIDATION (spec sections 16 and 21) ───

    @field_validator("id")
    def validate_id_format(cls, v, info):
        """Validate the id grammar (section 21.1) [cite: 620, 624]."""
        if not re.match(r"^silver_[a-z0-9]+_[a-z0-9]+_[a-z0-9_]+$", v):
            raise ValueError(
                "id must follow the pattern silver_<source_system>_<module>_<entity_name>, lowercase."
            )
        return v

    @field_validator("business_process")
    def canonicalize_business_process(cls, v):
        return normalize_business_process(v)

    @model_validator(mode="after")
    def validate_node_configuration(self):
        """Validate logical configuration and set dynamic defaults."""
        # 1. db_table_name defaults to id
        if not self.db_table_name:
            self.db_table_name = self.id

        # 2. join_graph requirement (section 6.4) [cite: 261, 262]
        if len(self.composed_of) > 1 and not self.join_graph:
            raise ValueError("join_graph is required when composed_of has more than one table.")

        # 3. additivity scope (REQ_ADDITIVITY_CONTRACT §4.4 rules 3-4)
        problems = _additivity_scope_problems(self.fields, self.grain)
        if problems:
            raise ValueError(" ".join(problems))
        return self


class GoldNode(BaseModel):
    id: str
    internal_id: str
    db_table_name: str | None = None
    layer: Literal["gold"] = "gold"
    version: str
    source_system: str
    source_system_no: int
    business_process: str
    module: str | list[str]
    # Secondary categorization for catalog faceting — see SilverNode.tag1/tag2.
    # All 5 shipped Gold YAMLs carry them (tag1 = business-process short code,
    # tag2 = the primary module); until now the model dropped them silently, so
    # the faceting the public spec promises was impossible.
    tag1: str | None = ""
    tag2: str | None = ""
    name: str
    # OPTIONAL at Gold. `classification` is documented as "Data Modeler TYPE", and
    # no ingestion path emits Gold — the SAP parser produces Bronze + Silver only —
    # so at Gold the value has no source, and every shipped Gold carries the same
    # `T`, i.e. zero information. Kept accepted and indexed (an optional catalog
    # hint, exactly as GOLD_LAYER.md already documents it) rather than removed:
    # with no `model_config` on this module, Pydantic's implicit `extra='ignore'`
    # would swallow existing and future values in silence.
    classification: str | None = None
    description: str
    # Silver DERIVES this from `classification` (§5.1); Gold AUTHORS it. The
    # derivation's inputs (SAP `CONTFLAG`, "all tables", item-level-ness) are
    # Bronze/SAP artefacts absent at Gold, so running it there decided the role on
    # absent evidence — a Gold with `classification: T` and no measure field
    # silently became a `dimension`. `fact` is the default because a Gold data
    # product is an analytical table; deviations are the author's call.
    entity_role: Literal["fact", "dimension", "reference"] = "fact"
    grain: Grain
    # NO `composed_of` and NO `join_graph` at Gold — both were removed from the
    # contract (owner decision, 2026-08-02).
    #
    # A Gold is not a composition of tables you could join back together: it is a
    # physical table produced by an ETL of CTEs, calculations and summarizations.
    # `composed_of` could only ever restate `db_table_name` — and the three shipped
    # spellings proved the key carried no contract at all (`MY_SCHEMA.<T>`,
    # `dataproduct.<T>`, bare `<T>`). Nothing derived meaning from it: the physical
    # table is `db_table_name` everywhere (`scope_validator.build_allowed_tables`
    # reads `db_table_name` with a fallback to `name`, never this), the edge
    # registry is built exclusively from `relationships`, and the publish cascade
    # skips Gold behind an explicit layer guard. Lineage at Gold is carried by
    # `relationships[]` (indexed and traversable), the entity `description`, and
    # per-field `source`.
    #
    # `join_graph` goes with it: it is Bronze↔Bronze ETL join semantics, and a Gold
    # has no Bronze tables to join. All 5 shipped Golds carried `[]`.
    #
    # Deliberately NOT rejected on read: this module declares no `model_config`, so
    # Pydantic's implicit `extra='ignore'` applies and an already-authored Gold that
    # still carries either key keeps validating — the value is dropped on load and
    # never written back. Tolerate-on-read, absent-on-write.
    fields: list[SilverField]
    relationships: list[Relationship] = Field(default_factory=list)

    # ─── CUSTOM VALIDATION (spec sections 16 and 21) ───

    @field_validator("id")
    def validate_id_format(cls, v, info):
        """Validate the id grammar (section 21.1) [cite: 620, 624]."""
        if not re.match(r"^gold_[a-z0-9]+_[a-z0-9_]+$", v):
            raise ValueError(
                "id must follow the pattern gold_<source_system>_<entity_name>, lowercase."
            )
        return v

    @field_validator("business_process")
    def canonicalize_business_process(cls, v):
        return normalize_business_process(v)

    @model_validator(mode="after")
    def validate_node_configuration(self):
        """Validate logical configuration and set dynamic defaults."""
        # 1. db_table_name defaults to id
        if not self.db_table_name:
            self.db_table_name = self.id

        # (the former rule 2 — "join_graph is required when composed_of has more
        # than one table" — died with the two keys it related. See the note on the
        # field list above.)

        # 2. additivity scope (REQ_ADDITIVITY_CONTRACT §4.4 rules 3-4)
        problems = _additivity_scope_problems(self.fields, self.grain)
        if problems:
            raise ValueError(" ".join(problems))
        return self

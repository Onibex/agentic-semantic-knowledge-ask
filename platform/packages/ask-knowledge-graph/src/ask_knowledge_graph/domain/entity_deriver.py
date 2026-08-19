# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Shared, source-aware entity derivation (pure domain logic).

Single home for the mechanical scaffolding that turns a *semantic core* (whatever
a human or the DDL LLM actually knows) into a complete, valid Bronze/Silver/Gold
node. Used by BOTH the SAP JSON parser (via the discrete helpers, so its
``parse_to_domain`` output is unchanged) AND the admin Manual/DDL paths (via
:meth:`complete`, run as a non-destructive normalization pass at ``/import``).

Lives in ``domain`` (not ``application``): it is pure logic with no I/O, depending
only on other domain modules (``nodes``, ``source_profiles``) — which keeps
``infrastructure``→here and ``application``→here both clean under the layering
contracts. Design ref: internal design doc (ITERATION_ENTITY_CREATION_REDESIGN) §2.
The heuristics here are lifted verbatim from ``infrastructure/sap_json_parser.py``
so the two ingestion paths produce the same result (DIP).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .naming import normalize_identifier
from .nodes import Grain, JoinCondition
from .source_profiles import get_profile

# SAP "control flag" values that mark a related table as configuration/reference.
_CONFIG_FLAGS = {"C", "G", "E", "S", "W"}

# One qualified-column equality inside a join predicate: ``VBAK.VBELN = VBAP.VBELN``.
_EQUALITY_TERM = re.compile(
    r"\s*(\w+)\s*\.\s*(\w+)\s*=\s*(\w+)\s*\.\s*(\w+)\s*\Z",
)


def silver_column_name(table: str, column: str) -> str:
    """The published Silver column name for ``table.column`` in TECHNICAL mode.

    Single home for the ``<column>_<table>`` convention. Both the field builder
    (``sap_json_parser``) and the grain derivation below resolve names through
    here, so a grain member can never drift from the field it names — which is
    exactly the drift that made every shipped Silver grain unresolvable (its
    members were raw SAP codes while the columns were these names).

    Under ``ColumnNamingMode.ALIAS`` (``domain.naming``) the published name is
    minted from the field alias instead; derivation then resolves through the
    ``name_map`` built from the entity's own fields, with this function as the
    fallback for columns the entity does not publish.
    """
    return f"{column.lower()}_{table.lower()}"


def _published_name(
    name_map: dict[tuple[str, str], str] | None, table: str, column: str
) -> str:
    """The published column name for ``table.column``, whatever the naming mode.

    ``name_map`` keys are ``(TABLE, COLUMN)`` uppercase and carry the entity's
    ACTUAL ``fields[].name`` values; a miss falls back to the technical
    convention, which keeps every historical call site byte-identical when no
    map is supplied.
    """
    if name_map:
        hit = name_map.get((table.upper(), column.upper()))
        if hit:
            return hit
    return silver_column_name(table, column)


def _field_get(fdef: Any, key: str, default: Any = None) -> Any:
    """Read a field property from either shape.

    The SAP parser builds ``SilverField`` models; the admin paths carry raw dicts.
    Both reach the fan-out derivation, so it reads (and writes) through here rather
    than forcing one shape and silently no-op-ing on the other.
    """
    if isinstance(fdef, dict):
        return fdef.get(key, default)
    return getattr(fdef, key, default)


def _field_set(fdef: Any, key: str, value: Any) -> None:
    if isinstance(fdef, dict):
        fdef[key] = value
    else:
        setattr(fdef, key, value)


def _parse_join_predicate(condition: Any) -> list[tuple[str, str, str, str]]:
    """Split a join condition into ``(left_table, left_col, right_table, right_col)``.

    Input is the mapper/YAML form ``"VBAK.VBELN = VBAP.VBELN AND …"``. Terms that
    are not a plain qualified-column equality (a literal comparison, a function
    call) are skipped: they bind no key column, so they cannot inform grain
    reasoning in either direction.
    """
    out: list[tuple[str, str, str, str]] = []
    for term in re.split(r"\s+AND\s+", str(condition or ""), flags=re.IGNORECASE):
        m = _EQUALITY_TERM.match(term)
        if m:
            out.append((m.group(1), m.group(2), m.group(3), m.group(4)))
    return out


def _join_attr(jc: Any, name: str) -> Any:
    """Read ``name`` off a :class:`JoinCondition` or its plain-dict YAML twin."""
    if isinstance(jc, dict):
        return jc.get(name)
    return getattr(jc, name, None)


def _subsequence_of(rel: Any) -> int:
    """``subsequence`` as a sortable int — the export's declared order of the key
    columns inside ONE composite join. Ships as int or str, and the schema
    defaults it to 1; anything unparseable sorts first rather than raising, since
    a bad ordinal must not cost us the edge itself."""
    try:
        return int(getattr(rel, "subsequence", 1) or 1)
    except (ValueError, TypeError):
        return 1


class EntityDeriver:
    """Stateless derivation helpers + the ``complete`` normalization pass.

    Cheap to construct; callers may hold one or instantiate per call.
    """

    # ── Discrete heuristics (shared with SapJsonParser — keep behaviour exact) ──

    def entity_role(
        self,
        *,
        classification: str | None,
        is_item: bool,
        has_measure: bool,
        relations_present: bool | None = None,
        all_relations_config: bool = False,
    ) -> str:
        """Decision tree from ``sap_json_parser._determine_entity_role`` (L114-140).

        ``C`` → reference; ``T`` → fact if item-level or has a measure else
        dimension; ``M`` → reference iff it has relations and all are config-flagged
        else dimension; anything else (incl. ``D``/unknown) → dimension."""
        c = (classification or "").strip().upper()
        if c == "C":
            return "reference"
        if c == "T":
            return "fact" if (is_item or has_measure) else "dimension"
        if c == "M":
            if not relations_present:
                return "dimension"
            return "reference" if all_relations_config else "dimension"
        return "dimension"

    def field_role_for_inttype(self, *, key_field: bool, inttype: str | None) -> str:
        """Field-role rule from the parser (L182-190) — keyed on SAP ``inttype``."""
        if key_field:
            return "identifier"
        it = (inttype or "").strip().upper()
        if it == "P":
            return "measure"
        if it == "D":
            return "timestamp"
        return "dimension"

    def field_role_for_canonical(self, base: str | None) -> str:
        """Field-role for the YAML path, keyed on the canonical type base.

        Mirrors the SAP rule (P↔DECIMAL→measure, D↔DATE/TIMESTAMP→timestamp).
        INTEGER stays a dimension to match the SAP heuristic (only packed ``P``
        is a measure; SAP int ``I`` is not)."""
        b = (base or "").upper()
        if b == "DECIMAL":
            return "measure"
        if b in ("DATE", "TIMESTAMP"):
            return "timestamp"
        return "dimension"

    def structural_grain(
        self,
        *,
        table_keys: dict[str, list[str]],
        join_graph: list[Any] | None = None,
        published: set[str] | None = None,
        name_map: dict[tuple[str, str], str] | None = None,
    ) -> list[str]:
        """The Silver ``entity_grain`` as PUBLISHED COLUMN NAMES, derived from the
        composed tables' primary keys and the join predicates that bind them.

        Two rules, both mechanical, both readable straight off the join graph:

        1. **A join covering the RIGHT table's ENTIRE primary key is N:1** — it
           matches at most one row, so that table multiplies nothing and
           contributes NO key column. ``MSEG→MARD`` on the full
           ``MATNR+WERKS+LGORT`` is the case: one stock row per movement line.
           A join covering only PART of the right key fans out, and the uncovered
           members are precisely what widens the grain — ``MKPF→MSEG`` binds
           ``MBLNR+MJAHR`` and leaves ``ZEILE`` free, so the grain is the movement
           LINE, not the document.
        2. **Columns the predicates declare equal are ONE key column.**
           ``VBAK.VBELN = VBAP.VBELN`` means ``vbeln_vbak`` and ``vbeln_vbap``
           always hold the same value, so keeping both states one constraint
           twice. The surviving representative is the member from the root-most
           table, which names the key after the entity's own anchor.

        Note what rule 1 does NOT depend on: which columns the join leaves FROM.
        ``MSEG`` reaches ``MARD`` through ``MATNR/WERKS/LGORT``, none of which
        belong to ``MSEG``'s own key — and that join still contributes nothing,
        because what decides fan-out is coverage of the *right* table's key. A
        composite-PK table joined on non-key columns is the ordinary N:1 case, not
        a special one.

        Why minimality is part of the contract rather than a nicety: prompt rule 7
        asserts BOTH "exactly ONE row per grain combination" AND "MANY rows
        whenever the WHERE pins only a SUBSET". A padded superkey satisfies the
        first and **falsifies the second** — the model then believes that pinning
        the real key returns many rows when it returns exactly one.

        And the coupling is deliberate: a LOOSE join predicate legitimately yields
        a WIDER grain (joining ``VBPA`` on ``VBELN`` alone really does fan out by
        ``POSNR`` and ``PARVW``). Tightening the export's predicates tightens the
        grain automatically, so the grain can never paper over a bad join.

        ``published`` — the entity's actual ``fields[].name`` set, when the caller
        knows it. Rule 2 then prefers a representative the entity really publishes
        over the root-most one, which matters when a Silver carries only the child
        table's copy of a join-equal column: the members are interchangeable by
        definition (the predicate says they are equal), so picking the selectable
        one costs nothing and avoids emitting a grain member that no query can
        reference. The ingestion path does not need it — there, every qualified
        name is published by construction, both sides going through the same
        resolver.

        ``name_map`` — ``{(TABLE, COLUMN): published name}``, when the caller can
        supply it (the parser builds it while minting fields; the admin path
        rebuilds it from each field's ``source``). It is what keeps this
        derivation correct under ``ColumnNamingMode.ALIAS``, where the published
        name is not reconstructable from ``table.column`` alone; a miss falls
        back to :func:`silver_column_name`, so passing no map preserves the
        historical behavior exactly.

        Returns ``[]`` when there is nothing to derive from; the caller decides
        what an empty grain means.
        """
        keys = {
            str(t): list(dict.fromkeys(str(c) for c in (cols or [])))
            for t, cols in (table_keys or {}).items()
        }
        if not keys:
            return []

        predicates: list[tuple[str, str, str, str]] = []
        # Join-plan depth per table; a table that is never a RIGHT side is a root.
        depth: dict[str, int] = {}
        n_ary_determined: set[str] = set()

        for jc in join_graph or []:
            terms = _parse_join_predicate(_join_attr(jc, "condition"))
            predicates.extend(terms)
            right = _join_attr(jc, "right_table")
            if not right:
                continue
            right = str(right)
            try:
                seq = int(_join_attr(jc, "sequence") or 0)
            except (TypeError, ValueError):
                seq = 0
            depth[right] = min(depth.get(right, seq), seq)
            # Rule 1 — coverage is evaluated per JOIN, not pooled across joins:
            # two different parents reaching the same table are two paths, and
            # either one of them being N:1 makes that table non-multiplying.
            covered = {c.upper() for (_lt, _lc, rt, c) in terms if rt == right}
            pk = {c.upper() for c in keys.get(right, ())}
            if pk and pk <= covered:
                n_ary_determined.add(right)

        # Candidates in join-plan order: roots first, then the declared sequence.
        candidates: list[tuple[str, str]] = []  # (qualified_name, table)
        for table in sorted(keys, key=lambda t: (depth.get(t, 0), t)):
            if table in n_ary_determined:
                continue
            for col in keys[table]:
                candidates.append((_published_name(name_map, table, col), table))
        if not candidates:
            return []

        # Rule 2 — union-find over every predicate (so equality is transitive even
        # through a column that is not itself a key), then one member per class.
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for lt, lc, rt, rc in predicates:
            a, b = (
                find(_published_name(name_map, lt, lc)),
                find(_published_name(name_map, rt, rc)),
            )
            if a != b:
                parent[b] = a

        # Selectable first (when the caller told us what is selectable), then
        # root-most: the members of one class are equal by predicate, so this only
        # chooses the NAME, never which constraint the grain expresses.
        rank = {
            q: (0 if (published is None or q in published) else 1, depth.get(t, 0), t)
            for q, t in candidates
        }
        winner: dict[str, str] = {}
        for q, _t in candidates:
            cls = find(q)
            held = winner.get(cls)
            if held is None or rank[q] < rank[held]:
                winner[cls] = q
        kept = set(winner.values())
        return [q for q, _t in candidates if q in kept]

    # ── Measure fan-out ─────────────────────────────────────────────────────
    #
    # The fact the semantic layer never stated: in a denormalised Silver every
    # measure has its OWN grain, and it is usually COARSER than the row grain.
    # `kwmeng_vbap` is one value per (VBELN, POSNR) restated on every partner,
    # document-flow and business-data row; `labst_mard` is one value per
    # (MATNR, WERKS, LGORT) restated on every movement line of that material.
    # Aggregating either one across the rows it repeats on multiplies it.
    #
    # Nothing declared that, so the SQL generator had to infer it, and measurably
    # did not: three successive attempts at the same question either summed a
    # snapshot, or reduced on the wrong key, or ran the aggregate AT the reduce
    # grain. The fix is to state it structurally, and the fact is fully derivable
    # from data the parser already holds — no curation, no LLM, no Gold required.

    @staticmethod
    def name_map_from_fields(fields: Iterable[Any]) -> dict[tuple[str, str], str]:
        """``{(TABLE, COLUMN): published name}`` rebuilt from each field's ``source``.

        The inverse of name minting, and the reason the deriver never needs to
        know the naming mode: whatever convention the parser (or an author)
        used, the field itself carries both the SAP origin (``source``) and the
        published name (``name``), so every derivation can resolve one from the
        other. First occurrence wins, matching the row-dedup at ingest.
        """
        out: dict[tuple[str, str], str] = {}
        for fdef in fields or []:
            name = _field_get(fdef, "name")
            table, _, column = str(_field_get(fdef, "source") or "").partition(".")
            table, column = table.strip().upper(), column.strip().upper()
            if name and table and column:
                out.setdefault((table, column), str(name))
        return out

    @staticmethod
    def _table_keys_from_identifiers(fields: Iterable[Any]) -> dict[str, list[str]]:
        """Per-table primary keys reconstructed from the `identifier` fields.

        Every key column of every composed table arrives as a `field_role:
        identifier` whose `source` is `TABLE.COLUMN`, on BOTH write paths — the SAP
        parser flags them from `key_field`, and the admin path preserves them. So one
        reconstruction serves both, exactly as `recompute_entity_grain` already does
        for the grain.
        """
        keys: dict[str, list[str]] = {}
        for fdef in fields or []:
            if _field_get(fdef, "field_role") != "identifier":
                continue
            table, _, column = str(_field_get(fdef, "source") or "").partition(".")
            table, column = table.strip().upper(), column.strip().upper()
            if table and column and column not in keys.setdefault(table, []):
                keys[table].append(column)
        return keys

    @staticmethod
    def _columns_by_table(fields: Iterable[Any]) -> dict[str, list[str]]:
        """Every column each composed table contributes, keyed by table.

        Superset of :meth:`_table_keys_from_identifiers`, and the correct seed for a
        functional-determination closure: a primary key determines the WHOLE row it
        keys, so a NON-key column of the same table is determined too.
        """
        cols: dict[str, list[str]] = {}
        for fdef in fields or []:
            table, _, column = str(_field_get(fdef, "source") or "").partition(".")
            table, column = table.strip().upper(), column.strip().upper()
            if table and column and column not in cols.setdefault(table, []):
                cols[table].append(column)
        return cols

    def fanout_dims_by_table(
        self,
        *,
        fields: Iterable[Any],
        entity_grain: list[str],
        join_graph: list[Any] | None = None,
    ) -> dict[str, list[str]]:
        """``{source_table: grain members that table's key does NOT determine}``.

        One rule: **a measure repeats over every grain member not functionally
        determined by the primary key of its own source table.** Column equality
        comes from the join predicates, so the determination is transitive —
        `VBAK.VBELN = VBAP.VBELN` means a VBAP measure is determined by
        `vbeln_vbak` even though that member is named after the other table.

        Worked, from the shipped corpus:

        * `MSEG` in `inv_mov_stock` — MSEG's key is the grain, so it determines all
          three members and the result is ``[]``. A movement quantity IS additive
          across movement lines, and this must not claim otherwise.
        * `MARD` in the same entity — its key `(MATNR, WERKS, LGORT)` appears
          nowhere in the grain `[mblnr_mkpf, mjahr_mkpf, zeile_mseg]` and no
          predicate equates them, so it determines nothing: the stock level repeats
          over the WHOLE grain.
        * `VBAP` in `sales_order` — determines `vbeln_vbak` (join-equal) and
          `posnr_vbap`, leaving ``[posnr_vbpa, parvw_vbpa, ruuid_vbfa, posnr_vbkd]``.
        * `VBAK` in the same entity — determines only `vbeln_vbak`, so a header
          amount repeats over the other five. Seven of that entity's 22 measures are
          VBAK header values in exactly this state, and no curation pass had reached
          any of them.

        A table with no reconstructable key determines nothing, so its measures get
        the whole grain — conservative, and consistent with the keyless-Bronze
        warn-not-reject stance: an undeclared key is not evidence of uniqueness.
        """
        grain = [str(g) for g in entity_grain or []]
        if not grain:
            return {}
        table_keys = self._table_keys_from_identifiers(fields)
        name_map = self.name_map_from_fields(fields)

        # Union-find over the join predicates — the same equivalence `structural_grain`
        # builds, on the same published-name keys, so the two derivations can
        # never disagree about which columns are one column.
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for jc in join_graph or []:
            for lt, lc, rt, rc in _parse_join_predicate(_join_attr(jc, "condition")):
                a, b = (
                    find(_published_name(name_map, lt, lc)),
                    find(_published_name(name_map, rt, rc)),
                )
                if a != b:
                    parent[b] = a

        out: dict[str, list[str]] = {}
        for table, cols in self._columns_by_table(fields).items():
            if table not in table_keys:
                # No reconstructable key determines nothing, so these measures repeat
                # over the WHOLE grain. Emitted explicitly: a missing entry reads as
                # "additive" downstream, the unsafe direction and the opposite of
                # what the docstring above promises.
                out[table] = list(grain)
                continue
            # Seeded from every column of the table, NOT only its key columns,
            # because the key determines the whole row. The column a fan-out join is
            # made ON is usually not part of the key it joins FROM:
            # `MSEG.MATNR = MARD.MATNR` means a movement line determines the material,
            # so a movement quantity stays additive even when the material is a grain
            # member. Seeding from the key alone claimed the opposite — invisible
            # until a grain named a column of another table, because until then each
            # table's key WAS its whole contribution to the grain. The seed is a
            # superset of the old one, so this can only ever REMOVE a fan-out claim.
            determined = {find(_published_name(name_map, table, c)) for c in cols}
            out[table] = [g for g in grain if find(g) not in determined]
        return out

    def apply_measure_fanout(
        self,
        fields: Iterable[Any],
        *,
        entity_grain: list[str],
        join_graph: list[Any] | None = None,
    ) -> int:
        """Fill `additivity: semi_additive` + `non_additive_over` on measures.

        FILL-WHEN-ABSENT, like `field_role`: a field that already declares
        `additivity` is left exactly as authored. That is what keeps a curator's
        deliberate `non_additive` (the conservative "never aggregate this here, go to
        the Gold" call) from being widened behind their back, while every uncurated
        measure still gains the structural statement.

        Returns how many fields were filled, so a caller can log it.
        """
        dims = self.fanout_dims_by_table(
            fields=fields, entity_grain=entity_grain, join_graph=join_graph
        )
        if not dims:
            return 0
        filled = 0
        for fdef in fields or []:
            if _field_get(fdef, "field_role") != "measure":
                continue
            if _field_get(fdef, "additivity") or _field_get(fdef, "non_additive_over"):
                continue  # author wins
            table = str(_field_get(fdef, "source") or "").partition(".")[0].strip().upper()
            over = dims.get(table) or []
            if not over:
                continue  # determined by the grain: genuinely additive, say nothing
            if not [g for g in entity_grain or [] if str(g) not in over]:
                # The reduce key would be EMPTY — the measure repeats over the whole
                # grain, so "reduce to one row per the grain MINUS non_additive_over"
                # reduces to one row per the empty set. That is not an executable
                # instruction, so `semi_additive` cannot honestly express this state;
                # it names a hazard while withholding the key needed to handle it,
                # which is measurably worse than saying less. Say the one true thing
                # instead — do not aggregate this here — which is also what a curator
                # hand-picked for exactly these fields before this derivation existed.
                # `aggregation_behavior: none` travels with it because the contract
                # requires the pair (see `validate_additivity_contract`): an
                # aggregation function on a measure that must never be aggregated is
                # the contradiction that key exists to prevent.
                _field_set(fdef, "additivity", "non_additive")
                _field_set(fdef, "aggregation_behavior", "none")
                filled += 1
                continue
            _field_set(fdef, "non_additive_over", list(over))
            _field_set(fdef, "additivity", "semi_additive")
            filled += 1
        return filled

    def derive_grain(
        self,
        table_keys: dict[str, list[str]],
        entity_name: str,
        *,
        join_graph: list[Any] | None = None,
        name_map: dict[tuple[str, str], str] | None = None,
    ) -> Grain:
        """Grain for the SAP-export ingestion path (was ``_calculate_grain``).

        Takes the composed tables' primary keys KEYED BY TABLE, because the flat
        ``list[str]`` this used to accept had already thrown away the one thing the
        grain needs: which table each key column belongs to. Flattening also
        deduplicated by bare column name, which silently conflated
        ``VBAK.VBELN`` (the order) with ``VBFA.VBELN`` (the *subsequent* document)
        — two different values under one name. Delegates to
        :meth:`structural_grain`; see it for the derivation rules and for what
        ``name_map`` does (the parser passes the map it built while minting the
        fields, so grain members match ``fields[].name`` in every naming mode).
        """
        keys = self.structural_grain(
            table_keys=table_keys, join_graph=join_graph, name_map=name_map
        )
        if not keys:
            keys = ["id_placeholder"]
        return Grain(entity_grain=keys, business_grain=f"{entity_name}_item")

    def recompute_entity_grain(
        self, fields: list, *, join_graph: list[Any] | None = None
    ) -> list[str]:
        """Authoritative Silver ``entity_grain`` for the admin save path.

        With a ``join_graph`` this runs the same :meth:`structural_grain`
        derivation as the ingestion path, reconstructing the per-table keys from
        each identifier field's ``source`` (``VBAK.VBELN``). Both paths therefore
        agree by construction — the split that let one of them emit raw SAP codes
        while the other emitted published names is closed.

        Without a join graph (or when no identifier field carries a resolvable
        ``source``) it falls back to *every* ``field_role: identifier`` name,
        de-duplicated in order. That fallback is a SUPERKEY on any multi-table
        Silver — correct for uniqueness, wrong for rule 7's subset clause — so it
        exists only to keep single-table and hand-authored entities working.

        Returns ``[]`` when no identifier field exists; the caller decides what an
        empty grain means (validation rejects it).
        """
        names: list[str] = []
        table_keys: dict[str, list[str]] = {}
        for fdef in fields or []:
            if not isinstance(fdef, dict) or fdef.get("field_role") != "identifier":
                continue
            name = fdef.get("name")
            if not name or name in names:
                continue
            names.append(name)
            src = str(fdef.get("source") or "")
            table, _, column = src.partition(".")
            if table.strip() and column.strip():
                table_keys.setdefault(table.strip(), []).append(column.strip())

        if not join_graph or not table_keys:
            return names

        declared = set(names)
        # The map covers ALL fields, not just identifiers: join predicates may
        # equate through a non-key column, and a name minted off-convention
        # (alias mode, or a hand-rename) is only resolvable through it.
        name_map = self.name_map_from_fields(fields)
        structural = self.structural_grain(
            table_keys=table_keys, join_graph=join_graph, published=declared, name_map=name_map
        )
        # Belt and braces after the published-aware representative choice: a
        # hand-edited Silver may name a column off-convention with no equal
        # sibling to fall back on, and a grain member that is not a selectable
        # column is the exact defect being fixed here.
        resolved = [q for q in structural if q in declared]
        return resolved or names

    def derive_join_graph(self, relations: list) -> list[JoinCondition]:
        """Join graph from ``sap_json_parser._build_join_graph`` (L217-235).

        ── Composite keys are ONE edge ──────────────────────────────────────────
        The export ships one relation ROW per key COLUMN, and ``subsequence`` is
        the field that says which rows belong to the same join: ``EKPO→EBKN``
        arrives as ``(subsequence 1: BANFN)`` + ``(subsequence 2: BNFPO)``. Emitting
        one ``JoinCondition`` per row — the previous behaviour — produced N edges
        for the same table pair, and **each one alone is a fanning join** (joining
        EKPO to EKET on ``EBELN`` only multiplies by every schedule line of the
        order). Both layer standards require the composite predicate on a single
        entry: ``docs/semantic-layer/SILVER_LAYER.md`` §3.3 — "Multi-key joins use
        ``AND``".

        Grouping key is ``(parent_relation, tabname, sequence)``: ``sequence`` is
        the execution order of the join plan, so two steps that genuinely join the
        same pair twice stay separate edges. Measured across all 17 shipped
        exports: 9 composite pairs, every one internally consistent in both
        ``sequence`` and ``join_type``, and zero repeated ``(field_main, field_sec)``
        rows — so no dedup is needed here, only composition.

        Members are ordered by ``subsequence`` because the export does NOT ship
        them in order (``KNVV→KNVP`` arrives as 1, 4, 2, 3), and an arbitrary
        predicate order would make the generated YAML non-deterministic across
        re-ingests of the same payload.

        ── Which side is which ─────────────────────────────────────────────────
        ``field_main`` is the column on ``parent_relation`` (the LEFT table);
        ``field_sec`` is the column on ``tabname`` (the RIGHT table). This was
        inverted here for as long as the mapper has existed, and it stayed
        invisible because the two names are equal on 47 of the 50 join-carrying
        relation rows in the shipped exports. All 3 asymmetric rows discriminate,
        and all 3 agree: resolving each side against the exports' own ``columns``
        blocks scores 47/3 under the old orientation and **50/0** under this one.
        Semantics agree independently — ``VBAK→VBFA`` now yields
        ``VBAK.VBELN = VBFA.VBELV``, the correct SAP document-flow predicate
        (``VBFA.VBELV`` is the *preceding* document), where the old orientation
        emitted ``VBAK.VBELV``, a column VBAK does not have.
        """
        # dict preserves first-seen order → the emitted join_graph keeps the
        # export's edge order, as before.
        groups: dict[tuple[str, str, int], list[Any]] = {}
        for rel in relations or []:
            try:
                seq_int = int(rel.sequence)
            except (ValueError, TypeError):
                seq_int = 1
            # sequence 1 is the ROOT table of the plan: it has no parent and
            # nothing to join to, so it contributes no edge.
            if seq_int <= 1:
                continue
            groups.setdefault((rel.parent_relation, rel.tabname, seq_int), []).append(rel)

        join_graph: list[JoinCondition] = []
        for (left_table, right_table, seq_int), members in groups.items():
            ordered = sorted(members, key=lambda r: _subsequence_of(r))
            predicate = " AND ".join(
                f"{left_table}.{rel.field_main} = {right_table}.{rel.field_sec}" for rel in ordered
            )
            # First non-empty join_type wins. Verified consistent within every
            # composite group in the shipped exports; the fallback keeps the
            # historical default for rows that ship an empty join_type.
            join_type = next((r.join_type for r in ordered if r.join_type), "") or "LEFT OUTER"
            join_graph.append(
                JoinCondition(
                    left_table=left_table,
                    right_table=right_table,
                    join_type=join_type,
                    condition=predicate,
                    sequence=seq_int,
                )
            )
        return join_graph

    def canonical_type(self, raw_type: str | None, *, source_system: str | None = None) -> str:
        """Re-encode a raw column type (SAP / SQL / canonical) into the canonical
        string, using the source's :class:`TypeMapper`."""
        return get_profile(source_system).type_mapper.canonical(raw_type)

    # ── The normalization pass (admin Manual/DDL path) ──────────────────────────

    def complete(self, raw: dict[str, Any], *, layer: str) -> dict[str, Any]:
        """Return a NEW dict with all mechanical required fields filled in.

        Non-destructive: only absent/empty fields are filled. The single allowed
        rewrite is per-field ``type`` → canonical (loss-less re-encode). Idempotent:
        ``complete(complete(x)) == complete(x)``. The input dict is never mutated.
        """
        lyr = (layer or "").strip().lower()
        mapper = get_profile(raw.get("source_system")).type_mapper
        out: dict[str, Any] = dict(raw)

        if lyr == "bronze":
            return self._complete_bronze(out, mapper)
        return self._complete_silver_gold(out, mapper, lyr)

    def assert_semantic_complete(self, raw: dict[str, Any], *, layer: str) -> None:
        """Raise ``ValueError`` with a precise, human-actionable message when a
        field the deriver intentionally does NOT fabricate is missing/empty.

        ``complete()`` fills the *mechanical* + *innocuous* fields (ids, version,
        alias, empty descriptions, canonical types). It deliberately never invents
        these *semantic* fields — a wrong guess is worse than a clear error:
          - ``classification`` (M/T/C) — drives ``entity_role``;
          - ``module`` — drives the workspace path + grouping;
          - ``composed_of`` (Silver only) — the real bronze lineage.

        Run this AFTER ``complete()`` and BEFORE Pydantic validation so the
        message reads better than the raw ``ValidationError``. ``/derive`` does
        NOT call it (it previews the gap via ``validation_error`` instead).

        Bronze has NO semantic requirement here (owner decision 2026-08-03): a
        keyless Bronze is accepted, not rejected. ``key_field`` is the
        data-product author's key declaration and ASK consumes it as authority —
        when a source table declares none, that is an upstream authoring error
        the ASK author escalates to the Data Modeler admin; blocking the save
        here would only re-guess the key. ``structural_grain`` treats such a
        table as contributing no key columns."""
        lyr = (layer or "").strip().lower()
        eid = raw.get("id") or "(no id)"
        if lyr == "bronze":
            return
        # Silver only. `classification` drives `entity_role` at Silver, so it is
        # required there. At Gold it drives nothing — `entity_role` is authored —
        # and it has no upstream source either, since no ingestion path emits Gold.
        # It stays accepted as an optional catalog hint (GoldNode.classification).
        if lyr == "silver" and not str(raw.get("classification") or "").strip():
            raise ValueError(
                f"{lyr} '{eid}' is missing required `classification` "
                f"(M=master / T=transactional / C=configuration) — it drives entity_role."
            )
        module = raw.get("module")
        module_ok = (
            any(str(m).strip() for m in module)
            if isinstance(module, list)
            else bool(str(module or "").strip())
        )
        if not module_ok:
            raise ValueError(
                f"{lyr} '{eid}' is missing required `module` (e.g. sd/mm/pp/fi) — "
                f"it drives the workspace path and grouping."
            )
        if lyr == "silver":
            composed = raw.get("composed_of")
            composed_list = (
                [c for c in composed if str(c).strip()] if isinstance(composed, list) else []
            )
            if not composed_list:
                raise ValueError(
                    f"silver '{eid}' is missing required `composed_of` (the bronze "
                    f"id(s) it reads from) — this lineage cannot be auto-derived."
                )
            # Multi-bronze Silver MUST declare how the tables join (SilverNode also
            # enforces this). The conditions need real keys → never fabricated;
            # surface a clear, actionable message instead of the raw model error.
            join_graph = raw.get("join_graph")
            if len(composed_list) > 1 and not (isinstance(join_graph, list) and join_graph):
                raise ValueError(
                    f"silver '{eid}' composes {len(composed_list)} bronze tables but has no "
                    f"`join_graph` — multi-bronze Silvers must declare how they join "
                    f"(left_table/right_table/join_type/condition/sequence per pair)."
                )

    def _complete_bronze(self, out: dict[str, Any], mapper) -> dict[str, Any]:
        if not out.get("layer"):
            out["layer"] = "bronze"
        if not out.get("version"):
            out["version"] = "1"
        if out.get("source_system_id") in (None, ""):
            out["source_system_id"] = 0
        # Innocuous semantic placeholders (D1 hybrid) — fill so validation never
        # 422s on these; they surface In Review for enrichment, never invented.
        if not out.get("alias"):
            out["alias"] = out.get("name") or ""
        if not out.get("description"):
            out["description"] = ""

        fields = out.get("fields") or {}
        new_fields: dict[str, Any] = {}
        # Input dedup: the SAP exports repeat (tabname, fldname) rows and the old
        # parser accumulated them, so declared primary_keys can arrive duplicated.
        # Same idiom as the per-table dedup in `structural_grain`.
        derived_pks: list[str] = list(dict.fromkeys(out.get("primary_key") or []))
        declared_pks: set[str] = set(derived_pks)
        if isinstance(fields, dict):
            for fname, fdef in fields.items():
                fd = dict(fdef) if isinstance(fdef, dict) else {}
                # Type → canonical when present; default STRING when absent
                # (matches the TypeMapper's unknown→STRING rule; required by
                # BronzeField so a typeless column never 422s).
                #
                # This is a verified NO-OP on parser output, not a double
                # application: `TypeMapper.parse` accepts canonical input as
                # identity (`_KEYWORD_BASE` maps STRING/DECIMAL/DATE… to
                # themselves, source_profiles.py:72-77), so
                # canonical(canonical(x)) == canonical(x). Checked over every
                # (inttype, leng) pair in the shipped SAP payloads: zero drift.
                # It matters because yaml_file_service calls complete() on files
                # the parser produced.
                fd["type"] = mapper.canonical(fd["type"]) if fd.get("type") else "STRING"
                if not fd.get("alias"):
                    # Sanitized, not bare-lowercased: the alias is name-bearing
                    # under ColumnNamingMode.ALIAS, so a hand-authored Bronze
                    # with an accented field name must not persist a value the
                    # published-column contract cannot reproduce.
                    fd["alias"] = normalize_identifier(fname, fallback=str(fname))
                if not fd.get("description"):
                    fd["description"] = ""
                if "key_field" not in fd:
                    # Derive the flag FROM the declared primary_key: BronzeNode
                    # demands agreement in both directions, so a YAML that
                    # declares primary_key and omits key_field must self-repair
                    # (previously forced to False, leaving the node incoherent).
                    fd["key_field"] = fname in declared_pks
                new_fields[fname] = fd
                if fd.get("key_field") and fname not in derived_pks:
                    derived_pks.append(fname)
            out["fields"] = new_fields
        # Always dedup. The union with the key_field flags applies ONLY when the
        # author declared no primary_key: silently widening a declared one would
        # hide a real inconsistency (PK=[A] plus key_field:true on B) that the
        # validator must reject.
        if out.get("primary_key"):
            out["primary_key"] = list(dict.fromkeys(out["primary_key"]))
        else:
            out["primary_key"] = derived_pks
        return out

    def _complete_silver_gold(self, out: dict[str, Any], mapper, layer: str) -> dict[str, Any]:
        if not out.get("version"):
            out["version"] = "1"
        if out.get("source_system_no") in (None, ""):
            out["source_system_no"] = 0
        if not out.get("internal_id"):
            out["internal_id"] = out.get("id") or ""
        # `business_process` is deliberately NOT filled from `module`. They are two
        # different axes (standards §4.1) — a module is `SD`, a business process is
        # `ORDER TO CASH` — and seeding one from the other produced a value that was
        # wrong by construction and then indexed into the retrieval text. Same
        # placeholder treatment as `description` below: empty validates, and the
        # enrichment scope flags it via `has_business_process`.
        # `assert_semantic_complete` deliberately does not require it (only
        # classification / module / composed_of are strict).
        if out.get("business_process") is None:
            out["business_process"] = ""
        #
        # Innocuous placeholder (D1 hybrid): empty description validates and is
        # flagged for enrichment; classification/module/composed_of stay strict
        # (see assert_semantic_complete).
        if not out.get("description"):
            out["description"] = ""

        # Field `source` is OPTIONAL, lineage-only metadata (neither the SQL engine
        # nor the retrieval summary ever read it). It is never fabricated: for Silver
        # it is real bronze lineage supplied by the author / bronze picker; for Gold
        # (and flat Silver) there is no bronze origin, so the field simply omits it
        # rather than carrying a redundant `{db_table_name}.{name}` self-reference.

        # Fields: canonical type (rewrite) + field_role (fill when absent).
        fields = out.get("fields") or []
        new_fields: list[Any] = []
        identifier_names: list[str] = []
        if isinstance(fields, list):
            for fdef in fields:
                fd = dict(fdef) if isinstance(fdef, dict) else {}
                base: str | None
                if fd.get("type"):
                    ct = mapper.parse(fd["type"])
                    fd["type"] = ct.render()
                    base = ct.base
                else:
                    fd["type"] = "STRING"  # required by SilverField; unknown→STRING
                    base = "STRING"
                if not fd.get("field_role"):
                    fd["field_role"] = self.field_role_for_canonical(base)
                if not fd.get("description"):
                    fd["description"] = ""  # innocuous placeholder (D1 hybrid)
                self._apply_additivity_shim(fd)
                if fd.get("field_role") == "identifier" and fd.get("name"):
                    identifier_names.append(fd["name"])
                new_fields.append(fd)
            out["fields"] = new_fields

        # entity_role — Silver only, and only when absent (author wins).
        #
        # Gold is AUTHORED and defaults to `fact`: the derivation rule keys off SAP
        # artefacts (``CONTFLAG``, "all tables", item-level-ness) that do not exist at
        # Gold, so deriving there decided the role on absent evidence — a Gold with
        # `classification: T` but no measure field silently became a `dimension`.
        # Mirrors the Silver gate in ``YAMLFileService._finalize_silver_gold``; both
        # write paths must agree or a Gold created via import/derive/DDL would still
        # be filled with the derived value.
        if not out.get("entity_role"):
            if layer != "silver":
                out["entity_role"] = "fact"
            else:
                name = (out.get("name") or "").lower()
                has_measure = any(
                    isinstance(f, dict) and f.get("field_role") == "measure" for f in new_fields
                )
                out["entity_role"] = self.entity_role(
                    classification=out.get("classification"),
                    is_item="item" in name,
                    has_measure=has_measure,
                    relations_present=None,  # YAML carries no SAP relations
                    all_relations_config=False,
                )

        # grain — filled only when ABSENT (this pass stays non-destructive, so an
        # author's declared grain is never rewritten here). The fill runs the same
        # structural derivation as the two write paths when a join graph is
        # available, and only falls back to the raw identifier set (a superkey on
        # any multi-table entity) when there is nothing better to go on.
        grain = out.get("grain") if isinstance(out.get("grain"), dict) else {}
        entity_grain = list(grain.get("entity_grain") or [])
        if not entity_grain:
            jg = out.get("join_graph") if isinstance(out.get("join_graph"), list) else None
            fields_list = out.get("fields") if isinstance(out.get("fields"), list) else []
            entity_grain = (
                self.recompute_entity_grain(fields_list, join_graph=jg)
                or identifier_names
                or ["id_placeholder"]
            )
        business_grain = grain.get("business_grain") or f"{out.get('name') or 'entity'}_item"
        out["grain"] = {"entity_grain": entity_grain, "business_grain": business_grain}

        # Measure fan-out, AFTER the grain is settled (it is derived against it) and
        # fill-when-absent, so this stays a non-destructive pass like everything else
        # here. See `apply_measure_fanout`.
        self.apply_measure_fanout(
            out.get("fields") if isinstance(out.get("fields"), list) else [],
            entity_grain=entity_grain,
            join_graph=out.get("join_graph") if isinstance(out.get("join_graph"), list) else None,
        )

        # composed_of / join_graph: Silver keeps the author's (never synthesized).
        # At GOLD both keys are DROPPED — they are not part of that contract any more
        # (see `GoldNode`). This used to synthesize `composed_of = [db_table_name]`,
        # which is exactly the restatement that made the key worthless: a Gold's
        # physical table is `db_table_name`, said once. Dropping here (rather than
        # leaving them for Pydantic's `extra='ignore'`) matters because `complete()`
        # feeds the admin save path — what it returns is what gets WRITTEN to the
        # YAML, so leaving them in would keep minting dead keys on every save.
        if layer == "gold":
            out.pop("composed_of", None)
            out.pop("join_graph", None)

        return out

    @staticmethod
    def _apply_additivity_shim(fd: dict[str, Any]) -> None:
        """MATERIALIZE the legacy-encoding shim into the YAML (REQ_ADDITIVITY_CONTRACT §4.5).

        The shim itself is *guaranteed* on ``SilverField`` — every construction
        path reads a legacy ``measure`` + ``aggregation_behavior: none`` as
        ``additivity: non_additive``, so correctness never depends on which
        writer ran. This copy exists for a different reason: it operates on the
        raw dict *before* model construction, so a YAML saved through the admin
        path gets the key written to disk and becomes self-describing instead of
        relying on every future reader to re-derive it. Legacy files are
        therefore migrated gradually, as they are touched.

        Deliberately one-directional: ``additive`` is never written out, because
        absence already means additive and stamping it on every measure would
        churn every YAML in the catalog for no information gain.
        """
        if (
            fd.get("field_role") == "measure"
            and fd.get("aggregation_behavior") == "none"
            and not fd.get("additivity")
        ):
            fd["additivity"] = "non_additive"

    @staticmethod
    def _module_str(module: Any) -> str:
        if isinstance(module, list):
            module = module[0] if module else ""
        return module if isinstance(module, str) else ""

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Design C — the edges block resolves id qualifiers against the CURRENT db_table_name.

SILVER §7.2.1 / GOLD §6.3.1 require every qualifier in a `join_condition` to already
BE the `db_table_name` of its side, and that remains the contract. This is the READ-side
salvage for predicates that violate it.

Why they exist: an entity whose SAP export names no physical table gets
`db_table_name = <its id>` (`SilverNode` model validator), and a relationship authored
at that moment — by AI Suggest or by hand — bakes the id into the predicate STRING.
Correcting `db_table_name` afterwards does not fix the predicate, because the name was
embedded by value. Found during the P7 E2E run (2026-08-03) on the real
`sales_order → inv_mov_stock` edge.

Resolving at render time means the prompt always reflects the current
`db_table_name`, so the correction propagates without touching any YAML.
"""

from __future__ import annotations

from ask_sql_generation.application.freeform_generator import (
    _format_edges_hint,
    _requalify_predicate,
)
from ask_sql_generation.application.scope_validator import build_entity_table_map

_SO_ID, _SO_TBL = "silver_s4h_sd_sales_order", "SILVER_SD_SALES_ORDER"
_IM_ID, _IM_TBL = "silver_s4h_mm_inv_mov_stock", "SILVER_MM_INVENTORY_MOVEMENT"

_YAMLS = [
    f"id: {_SO_ID}\nlayer: silver\ndb_table_name: {_SO_TBL}\n",
    f"id: {_IM_ID}\nlayer: silver\ndb_table_name: {_IM_TBL}\n",
]
_MAP = {_SO_ID: _SO_TBL, _IM_ID: _IM_TBL}


def _edge(predicate: str, *, target_table: str = "") -> dict:
    return {
        "source_node": _SO_ID,
        "target_node": _IM_ID,
        "source_table": _SO_TBL,
        # `_build_edge_pair` emits "" when the qualifier contract was violated,
        # rather than fabricating the source's own id.
        "target_table": target_table,
        "join_type": "LEFT OUTER",
        "cardinality": "many_to_many",
        "join_predicate": predicate,
        "traversal_cost": 3.0,
        "aggregation_safety": "requires_dedup",
        "description": None,
    }


def _on_clause(hint: str) -> str:
    return next(line.strip() for line in hint.splitlines() if line.strip().startswith("ON "))


# ── build_entity_table_map ───────────────────────────────────────────────────


def test_map_reads_id_and_db_table_name_from_the_yamls() -> None:
    assert build_entity_table_map(_YAMLS) == _MAP


def test_map_omits_entities_whose_table_still_equals_their_id() -> None:
    """Nothing to resolve, so no entry — the caller need not re-check."""
    assert build_entity_table_map([f"id: {_SO_ID}\ndb_table_name: {_SO_ID}\n"]) == {}


def test_map_survives_unparseable_and_non_dict_yaml() -> None:
    assert build_entity_table_map(["", "   ", "just a string", *_YAMLS]) == _MAP


# ── _requalify_predicate ─────────────────────────────────────────────────────


def test_both_sides_are_resolved_to_physical_tables() -> None:
    out = _requalify_predicate(
        f"{_SO_ID}.matnr_vbap = {_IM_ID}.matnr_marc AND {_SO_ID}.werks_vbap = {_IM_ID}.werks_marc",
        _MAP,
    )
    assert out == (
        f"{_SO_TBL}.matnr_vbap = {_IM_TBL}.matnr_marc "
        f"AND {_SO_TBL}.werks_vbap = {_IM_TBL}.werks_marc"
    )
    assert _SO_ID not in out and _IM_ID not in out


def test_non_equality_shapes_survive_verbatim() -> None:
    """`IN (...)`, literals and AND structure must be untouched — the reason the
    predicate is rendered verbatim in the first place."""
    out = _requalify_predicate(
        f"{_SO_ID}.vbeln_vbak = {_IM_ID}.mblnr_mkpf AND {_IM_ID}.bwart_mseg IN ('261','262')",
        _MAP,
    )
    assert out == (
        f"{_SO_TBL}.vbeln_vbak = {_IM_TBL}.mblnr_mkpf AND {_IM_TBL}.bwart_mseg IN ('261','262')"
    )


def test_compliant_predicate_is_left_alone() -> None:
    compliant = f"{_SO_TBL}.matnr_vbap = {_IM_TBL}.matnr_mseg"
    assert _requalify_predicate(compliant, _MAP) == compliant


def test_only_qualifier_position_is_substituted() -> None:
    """A bare id, or one used as a column name, must not be rewritten — the token
    has to be followed by a dot."""
    assert _requalify_predicate(f"x.note = '{_SO_ID}'", _MAP) == f"x.note = '{_SO_ID}'"
    assert _requalify_predicate(f"t.{_SO_ID} = 1", _MAP) == f"t.{_SO_ID} = 1"


def test_no_map_and_empty_predicate_are_no_ops() -> None:
    pred = f"{_SO_ID}.a = {_IM_ID}.b"
    assert _requalify_predicate(pred, None) == pred
    assert _requalify_predicate(pred, {}) == pred
    assert _requalify_predicate("", _MAP) == ""


# ── end to end through the rendered block ────────────────────────────────────


def test_rendered_on_clause_names_physical_tables() -> None:
    edge = _edge(f"{_SO_ID}.matnr_vbap = {_IM_ID}.matnr_marc")
    assert _on_clause(_format_edges_hint([edge], _MAP)) == (
        f"ON {_SO_TBL}.matnr_vbap = {_IM_TBL}.matnr_marc"
    )
    # Without the map the block still renders — degraded, never crashing.
    assert _SO_ID in _on_clause(_format_edges_hint([edge]))


def test_header_label_falls_back_to_the_map_when_the_edge_has_no_table() -> None:
    """`target_table: ""` is the honest output of a violating edge; the YAMLs
    still know the physical name, so the label must not stay bare."""
    hint = _format_edges_hint([_edge(f"{_SO_ID}.a = {_IM_ID}.b")], _MAP)
    assert f"{_IM_ID} (table: {_IM_TBL})" in hint


def test_edge_supplied_table_wins_over_the_map() -> None:
    """The edge document stays the primary source; the map is only a fallback."""
    hint = _format_edges_hint([_edge(f"{_SO_ID}.a = {_IM_ID}.b", target_table="OTHER_TABLE")], _MAP)
    assert f"{_IM_ID} (table: OTHER_TABLE)" in hint

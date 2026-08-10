"""Measure fan-out is DERIVED, not curated — and only where it is real.

In a denormalised Silver a measure's own grain is usually coarser than the row
grain: a header amount is restated on every item, a stock level on every movement
line. Nothing in the semantic layer said so, so the SQL generator had to infer it
from field descriptions and measurably did not — three successive attempts at one
business question either summed a snapshot, reduced on the wrong key, or ran the
aggregate AT the reduce grain (P7 E2E, 2026-08-03).

`EntityDeriver.fanout_dims_by_table` states it structurally instead, from data the
parser already holds: `source` + the identifier fields' per-table keys + the
`join_graph` equalities. The rule is one line — a measure repeats over every grain
member its own source table's key does not functionally determine.

The two shapes below are the real shipped corpus, kept as fixtures because they are
the two cases that must not be conflated: MSEG's key IS the grain (additive, must
stay silent) while MARD's key appears nowhere in it (repeats over everything).
"""

from __future__ import annotations

import pytest

from ask_knowledge_graph.domain.entity_deriver import EntityDeriver
from ask_knowledge_graph.domain.nodes import JoinCondition

# ── inv_mov_stock: MKPF → MSEG → {MARC, MARD} ────────────────────────────────
_IMS_GRAIN = ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg"]
_IMS_JOINS = [
    JoinCondition(
        left_table="MKPF",
        right_table="MSEG",
        join_type="INNER",
        condition="MKPF.MBLNR = MSEG.MBLNR AND MKPF.MJAHR = MSEG.MJAHR",
        sequence=2,
    ),
    JoinCondition(
        left_table="MSEG",
        right_table="MARC",
        join_type="LEFT OUTER",
        condition="MSEG.MATNR = MARC.MATNR AND MSEG.WERKS = MARC.WERKS",
        sequence=3,
    ),
    JoinCondition(
        left_table="MSEG",
        right_table="MARD",
        join_type="LEFT OUTER",
        condition="MSEG.MATNR = MARD.MATNR AND MSEG.WERKS = MARD.WERKS AND MSEG.LGORT = MARD.LGORT",
        sequence=4,
    ),
]


def _ident(name: str, source: str) -> dict:
    return {
        "name": name,
        "source": source,
        "field_role": "identifier",
        "type": "STRING(10)",
        "description": name,
    }


def _measure(name: str, source: str, **extra) -> dict:
    return {
        "name": name,
        "source": source,
        "field_role": "measure",
        "type": "DECIMAL(13)",
        "description": name,
        **extra,
    }


def _dim(name: str, source: str) -> dict:
    return {
        "name": name,
        "source": source,
        "field_role": "dimension",
        "type": "STRING(10)",
        "description": name,
    }


def _ims_fields() -> list[dict]:
    return [
        _ident("mblnr_mkpf", "MKPF.MBLNR"),
        _ident("mjahr_mkpf", "MKPF.MJAHR"),
        _ident("mblnr_mseg", "MSEG.MBLNR"),
        _ident("mjahr_mseg", "MSEG.MJAHR"),
        _ident("zeile_mseg", "MSEG.ZEILE"),
        # MSEG's OWN material / plant / storage location — the columns it joins to
        # MARC and MARD ON. Not key columns, so `_table_keys_from_identifiers` never
        # sees them, which is exactly how the closure bug below stayed invisible. The
        # live `inv_mov_stock` publishes all three as dimensions; the fixture did not,
        # so it could not reproduce the defect.
        _dim("matnr_mseg", "MSEG.MATNR"),
        _dim("werks_mseg", "MSEG.WERKS"),
        _dim("lgort_mseg", "MSEG.LGORT"),
        _ident("matnr_marc", "MARC.MATNR"),
        _ident("werks_marc", "MARC.WERKS"),
        _ident("matnr_mard", "MARD.MATNR"),
        _ident("werks_mard", "MARD.WERKS"),
        _ident("lgort_mard", "MARD.LGORT"),
        _measure("menge_mseg", "MSEG.MENGE"),
        _measure("labst_mard", "MARD.LABST"),
        _measure("eisbe_marc", "MARC.EISBE"),
    ]


# The grain the owner authored on 2026-08-03 to give the snapshot measures something
# to reduce BY: the movement line plus the material/plant/storage-location triple.
# Non-minimal on purpose — see the ledger — but it is the shape that turns every
# degenerate reduce key into a usable one, so both shapes are pinned here.
_IMS_GRAIN_WIDE = [
    "mblnr_mkpf",
    "mjahr_mkpf",
    "zeile_mseg",
    "matnr_marc",
    "werks_marc",
    "lgort_mard",
]


# ── sales_order: VBAK → {VBAP, VBPA, VBFA, VBKD} ─────────────────────────────
_SO_GRAIN = ["vbeln_vbak", "posnr_vbap", "posnr_vbpa", "parvw_vbpa", "ruuid_vbfa", "posnr_vbkd"]
_SO_JOINS = [
    JoinCondition(
        left_table="VBAK",
        right_table="VBAP",
        join_type="INNER",
        condition="VBAK.VBELN = VBAP.VBELN",
        sequence=2,
    ),
    JoinCondition(
        left_table="VBAK",
        right_table="VBPA",
        join_type="LEFT OUTER",
        condition="VBAK.VBELN = VBPA.VBELN",
        sequence=3,
    ),
]


def _so_fields() -> list[dict]:
    return [
        _ident("vbeln_vbak", "VBAK.VBELN"),
        _ident("vbeln_vbap", "VBAP.VBELN"),
        _ident("posnr_vbap", "VBAP.POSNR"),
        _ident("posnr_vbpa", "VBPA.POSNR"),
        _ident("parvw_vbpa", "VBPA.PARVW"),
        _ident("ruuid_vbfa", "VBFA.RUUID"),
        _ident("posnr_vbkd", "VBKD.POSNR"),
        _measure("netwr_vbak", "VBAK.NETWR"),
        _measure("kwmeng_vbap", "VBAP.KWMENG"),
    ]


@pytest.fixture
def deriver() -> EntityDeriver:
    return EntityDeriver()


# ── the derivation ───────────────────────────────────────────────────────────


def test_grain_bearing_table_declares_no_fanout(deriver: EntityDeriver) -> None:
    """MSEG's key IS the grain, so a movement quantity is genuinely additive.

    A false positive here would be worse than the bug: it would block a legitimate
    SUM over movement lines.
    """
    dims = deriver.fanout_dims_by_table(
        fields=_ims_fields(), entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS
    )
    assert dims["MSEG"] == []


def test_n_to_one_table_repeats_over_the_whole_grain(deriver: EntityDeriver) -> None:
    """MARD/MARC keys appear nowhere in the grain, so their values repeat everywhere."""
    dims = deriver.fanout_dims_by_table(
        fields=_ims_fields(), entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS
    )
    assert dims["MARD"] == _IMS_GRAIN
    assert dims["MARC"] == _IMS_GRAIN


def test_join_equality_makes_determination_transitive(deriver: EntityDeriver) -> None:
    """VBAP determines `vbeln_vbak` through `VBAK.VBELN = VBAP.VBELN`.

    Without the union-find over predicates this would name `vbeln_vbak` as a
    fan-out dimension and forbid summing across sales documents — the opposite of
    the truth.
    """
    dims = deriver.fanout_dims_by_table(
        fields=_so_fields(), entity_grain=_SO_GRAIN, join_graph=_SO_JOINS
    )
    assert dims["VBAP"] == ["posnr_vbpa", "parvw_vbpa", "ruuid_vbfa", "posnr_vbkd"]
    assert "vbeln_vbak" not in dims["VBAP"]


def test_header_table_repeats_over_every_item_level_member(deriver: EntityDeriver) -> None:
    """The defect no curation pass had reached: 7 of sales_order's 22 measures."""
    dims = deriver.fanout_dims_by_table(
        fields=_so_fields(), entity_grain=_SO_GRAIN, join_graph=_SO_JOINS
    )
    assert dims["VBAK"] == ["posnr_vbap", "posnr_vbpa", "parvw_vbpa", "ruuid_vbfa", "posnr_vbkd"]


def test_a_key_determines_the_non_key_columns_of_its_own_table(
    deriver: EntityDeriver,
) -> None:
    """A primary key determines the WHOLE row, so the closure seeds from every column.

    Regression guard for a defect shipped 2026-08-03 and found the next day, once the
    grain named a column belonging to ANOTHER table. `MSEG.MATNR = MARD.MATNR` means a
    movement line determines the material, so a movement quantity stays additive even
    with the material in the grain. Seeding the closure from MSEG's key alone claimed
    the opposite and flagged `menge_mseg` — the one genuinely additive measure in the
    entity — as repeating over material, plant and storage location.

    A false fan-out is not a harmless over-warning: it makes the model perform the
    two-step reduce, which is the step it measurably gets wrong most often.
    """
    dims = deriver.fanout_dims_by_table(
        fields=_ims_fields(), entity_grain=_IMS_GRAIN_WIDE, join_graph=_IMS_JOINS
    )
    assert dims["MSEG"] == []
    # …and the snapshot tables still keep exactly the members they do not determine.
    assert dims["MARD"] == ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg"]
    assert dims["MARC"] == ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg", "lgort_mard"]


def test_table_with_no_reconstructable_key_is_treated_conservatively(
    deriver: EntityDeriver,
) -> None:
    """An undeclared key is not evidence of uniqueness — same stance as keyless Bronze.

    v2: this test used to assert `"MARD" not in dims` and `additivity is None`, i.e.
    that an unkeyed table's measures were left looking ADDITIVE. That is the unsafe
    direction and the exact opposite of what the name and the docstring promise — the
    test pinned the bug. A missing entry is indistinguishable downstream from "the
    grain determines it", so the whole grain is now emitted explicitly.
    """
    fields = [f for f in _ims_fields() if not f["name"].endswith("_mard")]
    fields.append(_measure("labst_mard", "MARD.LABST"))
    dims = deriver.fanout_dims_by_table(
        fields=fields, entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS
    )
    assert dims["MARD"] == _IMS_GRAIN  # no key reconstructed → determines nothing
    deriver.apply_measure_fanout(fields, entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS)
    labst = next(f for f in fields if f["name"] == "labst_mard")
    assert labst["additivity"] == "non_additive"
    assert labst["aggregation_behavior"] == "none"


def test_empty_grain_is_a_no_op(deriver: EntityDeriver) -> None:
    assert deriver.fanout_dims_by_table(fields=_ims_fields(), entity_grain=[]) == {}


# ── the fill ─────────────────────────────────────────────────────────────────


def test_apply_fills_semi_additive_and_the_dimensions(deriver: EntityDeriver) -> None:
    """The ordinary case: a reduce key survives the subtraction, so it can be named."""
    fields = _ims_fields()
    filled = deriver.apply_measure_fanout(
        fields, entity_grain=_IMS_GRAIN_WIDE, join_graph=_IMS_JOINS
    )
    by_name = {f["name"]: f for f in fields}
    assert filled == 2  # labst + eisbe; menge is additive
    assert by_name["labst_mard"]["additivity"] == "semi_additive"
    assert by_name["labst_mard"]["non_additive_over"] == ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg"]
    # …which leaves the MARD triple as the key to reduce BY. That complement being
    # non-empty is the whole reason `semi_additive` is expressible here.
    assert [g for g in _IMS_GRAIN_WIDE if g not in by_name["labst_mard"]["non_additive_over"]] == [
        "matnr_marc",
        "werks_marc",
        "lgort_mard",
    ]
    # The additive one must stay untouched — absence is the contract's "additive".
    assert "additivity" not in by_name["menge_mseg"]
    assert "non_additive_over" not in by_name["menge_mseg"]


def test_apply_says_non_additive_when_the_reduce_key_would_be_empty(
    deriver: EntityDeriver,
) -> None:
    """`semi_additive` over the WHOLE grain is not an executable instruction.

    "Reduce to one row per the grain MINUS `non_additive_over`" degenerates to "one row
    per the empty set" — it names a hazard while withholding the key needed to handle
    it, which is measurably worse than saying less (P7 E2E: 31 of 32 derived measures
    on `inv_mov_stock` were in this state under the minimal grain, and every model
    tested flailed on the stock question while progressively fixing the demand one).
    So the honest encoding is the one a curator hand-picked for these very fields
    before the derivation existed: never aggregate this here.
    """
    fields = _ims_fields()
    deriver.apply_measure_fanout(fields, entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS)
    labst = next(f for f in fields if f["name"] == "labst_mard")
    assert labst["additivity"] == "non_additive"
    assert labst["aggregation_behavior"] == "none"  # the contract requires the pair
    assert "non_additive_over" not in labst  # nothing true to put in it


def test_apply_never_overwrites_an_author(deriver: EntityDeriver) -> None:
    """A curator's deliberate `non_additive` ("never aggregate here, use the Gold")
    must survive — fill-when-absent, like `field_role`."""
    fields = _ims_fields()
    labst = next(f for f in fields if f["name"] == "labst_mard")
    labst["aggregation_behavior"] = "none"
    labst["additivity"] = "non_additive"
    deriver.apply_measure_fanout(fields, entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS)
    assert labst["additivity"] == "non_additive"
    assert "non_additive_over" not in labst


def test_apply_is_idempotent(deriver: EntityDeriver) -> None:
    fields = _ims_fields()
    first = deriver.apply_measure_fanout(fields, entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS)
    second = deriver.apply_measure_fanout(fields, entity_grain=_IMS_GRAIN, join_graph=_IMS_JOINS)
    assert (first, second) == (2, 0)


def test_apply_works_on_model_objects_too(deriver: EntityDeriver) -> None:
    """The SAP parser passes `SilverField` models, the admin paths pass dicts."""
    from ask_knowledge_graph.domain.nodes import SilverField

    models = [
        SilverField(**{k: v for k, v in f.items() if k != "non_additive_over"})
        for f in _ims_fields()
    ]
    deriver.apply_measure_fanout(models, entity_grain=_IMS_GRAIN_WIDE, join_graph=_IMS_JOINS)
    labst = next(f for f in models if f.name == "labst_mard")
    assert labst.additivity == "semi_additive"
    assert labst.non_additive_over == ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg"]

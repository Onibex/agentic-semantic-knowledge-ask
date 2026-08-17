"""Golden parity: SapJsonParser output must be byte-identical after the
EntityDeriver refactor. The golden snapshot was captured from the parser
BEFORE delegation; this guards the active SAP merge + legacy ingestion paths.

Two blocks have been deliberately re-captured since:

1. ``silver.grain``, when grain derivation moved to the structural contract
   (published `<column>_<table>` names, N:1 tables dropped, join-equal columns
   collapsed — see ``EntityDeriver.structural_grain``).
2. ``silver.fields[].synonyms``, when ``SilverField`` gained the key. The parser
   emits no synonyms, so every field gained exactly ``synonyms: []`` — a pure
   model-surface addition, not a behaviour change.
3. ``silver.fields[].additivity`` + ``non_additive_over`` on MEASURES, when the
   parser began declaring each measure's fan-out (2026-08-03). 22 of
   ``sales_order``'s fields and 37 of ``inv_mov_stock``'s gained exactly those two
   keys, and nothing else moved — including the measures that are genuinely
   additive, which correctly stayed silent. See
   ``EntityDeriver.fanout_dims_by_table``.

Each was re-captured only after asserting that ``bronze`` and every other
``silver`` key were unchanged AND that the differing fields differed ONLY by the
newly-emitted keys, so the snapshot still pins everything else byte-for-byte. Do
not re-capture without running that guard — a golden rewritten on a red test pins
the bug instead of the behaviour.
"""

import json
import re
from pathlib import Path

import pytest

from ask_knowledge_graph.infrastructure.sap_json_parser import SapJsonParser

_FIX = Path(__file__).parent / "fixtures"
_CASES = ["sap_s4h_sales_order", "sap_s4h_inv_mov_stock"]


@pytest.fixture(autouse=True)
def _pin_technical_naming(monkeypatch):
    """Pin ``ASK_COLUMN_NAMING=technical`` for this whole module.

    The golden snapshot encodes TECHNICAL-mode published column names
    (``vbeln_vbak``). Without this, the suite silently inherits the ambient
    config: run from the project root on a deployment configured for
    ``column_naming: alias`` (a real client setup) and every case fails with a
    confusing StopIteration, while CI stays green only because it has no
    ``config/settings.json``. A golden test must pin its own inputs, not read
    the developer's environment. The alias-mode contract has its own suite
    (``test_sap_parser_alias_mode.py``)."""
    monkeypatch.setenv("ASK_COLUMN_NAMING", "technical")


def _golden() -> dict:
    return json.loads((_FIX / "parser_golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", _CASES)
def test_parser_parity(name):
    raw = json.loads((_FIX / f"{name}.json").read_text(encoding="utf-8"))
    bronze_nodes, silver_node = SapJsonParser().parse_to_domain(raw)
    got = {
        "bronze": [b.model_dump() for b in bronze_nodes],
        "silver": silver_node.model_dump(),
    }
    assert got == _golden()[name]


def test_parser_emits_one_canonical_type_vocabulary_for_both_layers():
    """Supersedes the former ``test_parser_keeps_raw_sap_types``.

    Field ``type`` is the canonical ANSI vocabulary at **both** layers the parser
    writes. Two forks are closed by this: the parser vs the admin
    ``/import`` + ``/derive`` boundary (which always canonicalized), and Bronze
    vs Silver — ``EntityDeriver._complete_silver_gold`` already rewrote Silver
    types on every admin save, so a Silver touched through the SPA was canonical
    while the same Silver produced here was raw SAP.

    Both halves are asserted so neither side can drift back silently.
    """
    raw = json.loads((_FIX / "sap_s4h_sales_order.json").read_text(encoding="utf-8"))
    bronze_nodes, silver_node = SapJsonParser().parse_to_domain(raw)

    bases = ("STRING", "INTEGER", "DECIMAL", "DATE", "TIMESTAMP", "BOOLEAN")
    bronze_types = {f.type for b in bronze_nodes for f in b.fields.values()}
    silver_types = {f.type for f in silver_node.fields}
    assert bronze_types and silver_types

    for label, types in (("bronze", bronze_types), ("silver", silver_types)):
        assert all(t.startswith(bases) for t in types), (label, types)
        # No raw SAP code shape (a letter followed by digits) survives.
        assert not any(re.fullmatch(r"[A-Za-z]\d+", t) for t in types), (label, types)

    vbak = next(b for b in bronze_nodes if b.name == "VBAK")
    assert vbak.fields["VBELN"].type == "STRING(10)"  # C10
    assert vbak.fields["NETWR"].type == "DECIMAL(15)"  # P15 — SAP carries no scale
    assert vbak.fields["ERDAT"].type == "DATE"  # D8

    # The same column resolves identically on both sides.
    netwr_vbak = next(f for f in silver_node.fields if f.name == "netwr_vbak")
    assert netwr_vbak.type == vbak.fields["NETWR"].type

    # field_role still keys off the RAW SAP inttype, not the canonical string, so
    # canonicalization must not have changed it: P -> measure, D -> timestamp.
    assert netwr_vbak.field_role == "measure"
    assert next(f for f in silver_node.fields if f.name == "erdat_vbak").field_role == "timestamp"


def test_secondary_categorization_tags_survive_validation():
    """``tag1`` / ``tag2`` are read from the export (ASK Spec 6.1: tag1 <- Tag 4,
    tag2 <- Tag 5) and passed to ``SilverNode``, but the model did not declare
    them, so Pydantic's ``extra='ignore'`` dropped them — making the catalog
    faceting the public spec documents impossible. They are modelled now."""
    raw = json.loads((_FIX / "sap_s4h_sales_order.json").read_text(encoding="utf-8"))
    _, silver_node = SapJsonParser().parse_to_domain(raw)

    dumped = silver_node.model_dump()
    assert "tag1" in dumped and "tag2" in dumped
    assert silver_node.tag2 == raw["info"]["tag5"]
    assert silver_node.tag1 == raw["info"]["tag4"]


def test_bronze_primary_key_is_deduplicated():
    """The SAP exports repeat whole ``(tabname, fldname)`` rows; the parser used
    to append one primary_key member per occurrence, which is how 9 shipped
    bronze YAMLs ended up with a 2-4x duplicated primary_key. The inv_mov_stock
    fixture reproduces it (MARC 4 items/2 unique, MARD 9/3, MSEG 6/3)."""
    raw = json.loads((_FIX / "sap_s4h_inv_mov_stock.json").read_text(encoding="utf-8"))
    bronze_nodes, silver_node = SapJsonParser().parse_to_domain(raw)

    for node in bronze_nodes:
        assert len(node.primary_key) == len(set(node.primary_key)), node.name
        # Every PK member exists in fields and agrees with its key_field flag.
        for key in node.primary_key:
            assert key in node.fields, (node.name, key)
            assert node.fields[key].key_field is True, (node.name, key)

    # The duplicated source rows also duplicated Silver field entries.
    names = [f.name for f in silver_node.fields]
    assert len(names) == len(set(names))


def test_table_without_key_flags_ingests_keyless_with_warning(caplog):
    """A table whose export declares no ``key_field='X'`` ingests as a keyless
    Bronze with a warning naming the table — it is no longer rejected (owner
    decision 2026-08-03). ``key_field`` is the data-product author's key
    declaration and ASK consumes it as authority: the ASK author escalates the
    missing declaration to the Data Modeler admin instead of being blocked.
    Seen live: VBFA in ``sales_order`` (its S/4 key RUUID was left out of the
    selection). The keyless table must contribute nothing to the Silver grain."""
    raw = json.loads((_FIX / "sap_s4h_sales_order.json").read_text(encoding="utf-8"))
    for col in raw["columns"]:
        if col["tabname"] == "VBFA":
            col["key_field"] = ""

    with caplog.at_level("WARNING"):
        bronze_nodes, silver_node = SapJsonParser().parse_to_domain(raw)

    vbfa = next(b for b in bronze_nodes if b.name == "VBFA")
    assert vbfa.primary_key == []
    assert not any(f.key_field for f in vbfa.fields.values())
    assert any("VBFA" in rec.message for rec in caplog.records)
    # No VBFA column may leak into the grain — a keyless table cannot state
    # a uniqueness constraint, so it contributes no key columns.
    assert not any(g.endswith("_vbfa") for g in silver_node.grain.entity_grain)


def test_bronze_description_comes_from_the_export_not_a_placeholder():
    """``SapRelationSchema`` did not declare ``description_table``, so Pydantic
    dropped it (extra='ignore') and the placeholder branch fired unconditionally —
    every generated Bronze read ``SAP Table VBAK`` while the export carried the
    real label. That matters: ``description`` is one of the 8 keys indexed for a
    Bronze and, with no embedding, the only text by which one is reachable."""
    raw = json.loads((_FIX / "sap_s4h_sales_order.json").read_text(encoding="utf-8"))
    bronze_nodes, _ = SapJsonParser().parse_to_domain(raw)

    vbak = next(b for b in bronze_nodes if b.name == "VBAK")
    assert vbak.description.startswith("Sales Document Header Data")
    assert not any(b.description.startswith("SAP Table ") for b in bronze_nodes)

    # An empty/absent label still falls back — the placeholder is a fallback, not a bug.
    for rel in raw["relations"]:
        rel["description_table"] = ""
    bronze_nodes, _ = SapJsonParser().parse_to_domain(raw)
    assert next(b for b in bronze_nodes if b.name == "VBAK").description == "SAP Table VBAK"


def test_alias_mojibake_is_sanitized_and_id_stays_valid():
    """The upstream export ships a trailing U+FFFD in TSPAT's ``alias_tabname``
    (``sales_division 1.json``), which is the last segment of the bronze id — so
    the corruption made the id ungrammatical and unreconstructible from
    name+alias. Sanitation DROPS the character rather than replacing it, so no
    phantom underscore is left behind."""
    raw = json.loads((_FIX / "sap_s4h_sales_order.json").read_text(encoding="utf-8"))
    for col in raw["columns"]:
        if col["tabname"] == "VBAK":
            col["alias_tabname"] = "ORDER_HEADER�"
    for rel in raw["relations"]:
        if rel["tabname"] == "VBAK":
            rel["alias_tabname"] = "ORDER_HEADER�"

    bronze_nodes, _ = SapJsonParser().parse_to_domain(raw)
    vbak = next(b for b in bronze_nodes if b.name == "VBAK")
    assert vbak.alias == "ORDER_HEADER"
    assert vbak.id == "bronze_s4h_vbak_order_header"


def test_sales_order_is_dimension_d_fallthrough():
    """sales_order has SAP info.type == 'D' → entity_role dimension (fall-through)."""
    assert _golden()["sap_s4h_sales_order"]["silver"]["entity_role"] == "dimension"
    assert _golden()["sap_s4h_inv_mov_stock"]["silver"]["entity_role"] == "fact"


def test_composite_key_join_is_one_edge_with_and():
    """A composite-key join is ONE ``join_graph`` entry with an AND-composed
    predicate — never one entry per key column.

    The export ships one relation ROW per key column (``subsequence`` orders
    them). Emitting an edge per row produced N entries for the same table pair,
    and each one ALONE is a fanning join: ``MSEG INNER JOIN MARC ON MATNR`` alone
    multiplies by every plant of the material. ``SILVER_LAYER.md`` §3.3 requires
    the composite predicate on a single entry.
    """
    raw = json.loads((_FIX / "sap_s4h_inv_mov_stock.json").read_text(encoding="utf-8"))
    _, silver = SapJsonParser().parse_to_domain(raw)

    pairs = [(j.left_table, j.right_table, j.sequence) for j in silver.join_graph]
    assert len(pairs) == len(set(pairs)), f"duplicate table pairs in join_graph: {pairs}"

    by_pair = {(j.left_table, j.right_table): j for j in silver.join_graph}
    # MSEG→MARD is the 3-key case: the predicate carries all three, AND-composed.
    mard = by_pair[("MSEG", "MARD")]
    assert mard.condition == (
        "MSEG.MATNR = MARD.MATNR AND MSEG.WERKS = MARD.WERKS AND MSEG.LGORT = MARD.LGORT"
    )
    assert mard.join_type == "LEFT OUTER"


def test_composite_key_predicate_follows_declared_subsequence():
    """Key columns are ordered by ``subsequence``, not by their position in the
    export — which ships them shuffled (``KNVV→KNVP`` arrives 1, 4, 2, 3). Without
    the sort, re-ingesting the same payload could reorder the predicate and make
    the generated YAML churn."""
    raw = json.loads((_FIX / "sap_s4h_inv_mov_stock.json").read_text(encoding="utf-8"))
    mard_rels = [
        r for r in raw["relations"] if r["parent_relation"] == "MSEG" and r["tabname"] == "MARD"
    ]
    assert len(mard_rels) == 3, "fixture must carry the 3-key MSEG→MARD join"
    # Shuffle the rows: the emitted predicate must not follow file order.
    raw["relations"] = [r for r in raw["relations"] if r not in mard_rels] + list(
        reversed(mard_rels)
    )

    _, silver = SapJsonParser().parse_to_domain(raw)
    mard = next(j for j in silver.join_graph if (j.left_table, j.right_table) == ("MSEG", "MARD"))
    expected = " AND ".join(
        f"MSEG.{r['field_sec']} = MARD.{r['field_main']}"
        for r in sorted(mard_rels, key=lambda r: int(r["subsequence"]))
    )
    assert mard.condition == expected


def test_join_predicate_sides_are_not_swapped():
    """``field_main`` is the PARENT's column, ``field_sec`` is the CHILD's.

    The mapper had these inverted since it was written, and it stayed invisible
    because the two names are equal on 47 of the 50 join-carrying relation rows
    in the shipped exports. Only asymmetric rows discriminate — resolving each
    side against the exports' own ``columns`` blocks scores 47/3 inverted and
    50/0 correct. ``VBAK→VBFA`` is the asymmetric row in this fixture and it is
    also semantically decisive: ``VBFA.VBELV`` is the PRECEDING document, so a
    sales order joins document flow as ``VBAK.VBELN = VBFA.VBELV``. The inverted
    form named ``VBAK.VBELV``, a column VBAK does not have.
    """
    raw = json.loads((_FIX / "sap_s4h_sales_order.json").read_text(encoding="utf-8"))
    vbfa_rel = next(
        r for r in raw["relations"] if r["parent_relation"] == "VBAK" and r["tabname"] == "VBFA"
    )
    assert vbfa_rel["field_main"] != vbfa_rel["field_sec"], "fixture must keep an asymmetric row"

    bronze_nodes, silver = SapJsonParser().parse_to_domain(raw)
    vbfa = next(j for j in silver.join_graph if j.right_table == "VBFA")
    assert vbfa.condition == "VBAK.VBELN = VBFA.VBELV"

    # The columns each side names must actually exist on that side's Bronze.
    fields = {b.name: set(b.fields) for b in bronze_nodes}
    assert vbfa_rel["field_main"] in fields["VBAK"]
    assert vbfa_rel["field_sec"] in fields["VBFA"]

"""EntityDeriver — discrete heuristics + the non-destructive complete() pass."""

from types import SimpleNamespace

import pytest

from ask_knowledge_graph.domain.entity_deriver import EntityDeriver

_D = EntityDeriver()


# ── discrete heuristics ──────────────────────────────────────────────────────


def test_entity_role_branches():
    assert _D.entity_role(classification="C", is_item=False, has_measure=False) == "reference"
    assert _D.entity_role(classification="T", is_item=True, has_measure=False) == "fact"
    assert _D.entity_role(classification="T", is_item=False, has_measure=True) == "fact"
    assert _D.entity_role(classification="T", is_item=False, has_measure=False) == "dimension"
    assert (
        _D.entity_role(
            classification="M", is_item=False, has_measure=False, relations_present=False
        )
        == "dimension"
    )
    assert (
        _D.entity_role(
            classification="M",
            is_item=False,
            has_measure=False,
            relations_present=True,
            all_relations_config=True,
        )
        == "reference"
    )
    assert (
        _D.entity_role(
            classification="M",
            is_item=False,
            has_measure=False,
            relations_present=True,
            all_relations_config=False,
        )
        == "dimension"
    )
    # D / unknown / None → dimension (the real-data fall-through)
    assert _D.entity_role(classification="D", is_item=False, has_measure=True) == "dimension"
    assert _D.entity_role(classification=None, is_item=True, has_measure=True) == "dimension"


def test_field_role_for_inttype():
    assert _D.field_role_for_inttype(key_field=True, inttype="C") == "identifier"
    assert _D.field_role_for_inttype(key_field=False, inttype="P") == "measure"
    assert _D.field_role_for_inttype(key_field=False, inttype="D") == "timestamp"
    assert _D.field_role_for_inttype(key_field=False, inttype="C") == "dimension"


def test_field_role_for_canonical():
    assert _D.field_role_for_canonical("DECIMAL") == "measure"
    assert _D.field_role_for_canonical("DATE") == "timestamp"
    assert _D.field_role_for_canonical("TIMESTAMP") == "timestamp"
    assert _D.field_role_for_canonical("STRING") == "dimension"


def test_recompute_entity_grain():
    fields = [
        {"name": "vbeln_vbak", "field_role": "identifier"},
        {"name": "net_value", "field_role": "measure"},
        {"name": "posnr_vbap", "field_role": "identifier"},
        {"name": "vbeln_vbak", "field_role": "identifier"},  # dup → kept once
        {"name": "", "field_role": "identifier"},  # blank → skipped
        "not-a-dict",  # tolerated
    ]
    # No join graph → the every-identifier fallback (a superkey; see the docstring).
    assert _D.recompute_entity_grain(fields) == ["vbeln_vbak", "posnr_vbap"]
    # No identifier field → empty (caller decides what that means).
    assert _D.recompute_entity_grain([{"name": "x", "field_role": "dimension"}]) == []
    assert _D.recompute_entity_grain([]) == []
    assert _D.field_role_for_canonical("INTEGER") == "dimension"  # only P/DECIMAL is a measure


# ── grain derivation (the structural contract) ───────────────────────────────
#
# The shipped catalog's real shapes are pinned here on purpose. Every Silver grain
# in production was unresolvable — raw SAP codes matching no `fields[].name`, so
# prompt rules 7-8 could not execute against a single one of the 16 — and the
# admin path's answer (every identifier field) was a superkey that falsifies rule
# 7's "a subset returns MANY rows" clause. Both failure modes are silent: the YAML
# still looks plausible. These tests are the guard.

# `sales_order`: VBAK header + item/partner/flow/business children, exactly as the
# export declares them (each child joined on VBELN alone).
_SALES_ORDER_KEYS = {
    "VBAK": ["VBELN"],
    "VBAP": ["VBELN", "POSNR"],
    "VBPA": ["VBELN", "POSNR", "PARVW"],
    "VBFA": ["VBELV", "POSNV", "VBELN", "POSNN", "VBTYP_N"],
    "VBKD": ["VBELN", "POSNR"],
}
_SALES_ORDER_JOINS = [
    {
        "left_table": "VBAK",
        "right_table": "VBAP",
        "condition": "VBAK.VBELN = VBAP.VBELN",
        "sequence": 2,
    },
    {
        "left_table": "VBAK",
        "right_table": "VBPA",
        "condition": "VBAK.VBELN = VBPA.VBELN",
        "sequence": 3,
    },
    {
        "left_table": "VBAK",
        "right_table": "VBFA",
        "condition": "VBAK.VBELN = VBFA.VBELV",
        "sequence": 4,
    },
    {
        "left_table": "VBAK",
        "right_table": "VBKD",
        "condition": "VBAK.VBELN = VBKD.VBELN",
        "sequence": 5,
    },
]

# `inv_mov_stock`: MKPF→MSEG fans out by line; MARC/MARD are joined on their FULL
# keys, so they attach exactly one row each and widen nothing.
_INV_KEYS = {
    "MKPF": ["MBLNR", "MJAHR"],
    "MSEG": ["MBLNR", "MJAHR", "ZEILE"],
    "MARC": ["MATNR", "WERKS"],
    "MARD": ["MATNR", "WERKS", "LGORT"],
}
_INV_JOINS = [
    {
        "left_table": "MKPF",
        "right_table": "MSEG",
        "condition": "MKPF.MBLNR = MSEG.MBLNR AND MKPF.MJAHR = MSEG.MJAHR",
        "sequence": 2,
    },
    {
        "left_table": "MSEG",
        "right_table": "MARC",
        "condition": "MSEG.MATNR = MARC.MATNR AND MSEG.WERKS = MARC.WERKS",
        "sequence": 3,
    },
    {
        "left_table": "MSEG",
        "right_table": "MARD",
        "condition": "MSEG.MATNR = MARD.MATNR AND MSEG.WERKS = MARD.WERKS AND MSEG.LGORT = MARD.LGORT",
        "sequence": 4,
    },
]


def test_structural_grain_members_are_published_column_names():
    """Every member must be a selectable `<column>_<table>` column, never a raw
    SAP code. This is the defect that made the grain contract dead on all 16
    shipped Silvers."""
    grain = _D.structural_grain(table_keys=_SALES_ORDER_KEYS, join_graph=_SALES_ORDER_JOINS)
    assert grain, "a keyed, join-carrying Silver must derive a grain"
    assert all(g == g.lower() and "_" in g for g in grain)
    assert "VBELN" not in grain and "POSNR" not in grain


def test_structural_grain_collapses_join_equal_columns():
    """VBELN reaches five tables (as VBELV on VBFA) and every occurrence is bound
    equal by a predicate, so it is ONE key column — named after the anchor."""
    grain = _D.structural_grain(table_keys=_SALES_ORDER_KEYS, join_graph=_SALES_ORDER_JOINS)
    assert grain[0] == "vbeln_vbak"
    for redundant in ("vbeln_vbap", "vbeln_vbpa", "vbeln_vbkd", "vbelv_vbfa"):
        assert redundant not in grain
    # VBFA's OWN vbeln is the *subsequent* document — a different value under the
    # same bare name, and precisely what flat de-duplication used to destroy.
    assert "vbeln_vbfa" in grain
    # Loose predicates legitimately widen the grain: VBPA joined on VBELN alone
    # really does fan out by both of its remaining key members.
    assert {"posnr_vbap", "posnr_vbpa", "parvw_vbpa", "posnr_vbkd"} <= set(grain)


def test_structural_grain_drops_fully_covered_n_to_one_tables():
    """A join covering the right table's ENTIRE key attaches one row and must
    contribute nothing — including when it leaves from non-key columns, which is
    exactly what MSEG→MARD does."""
    grain = _D.structural_grain(table_keys=_INV_KEYS, join_graph=_INV_JOINS)
    assert grain == ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg"]
    for dropped in ("matnr_marc", "werks_marc", "matnr_mard", "werks_mard", "lgort_mard"):
        assert dropped not in grain


def test_structural_grain_single_table_and_empty():
    # A dimension Silver with no joins: its own key, published.
    assert _D.structural_grain(table_keys={"T001W": ["WERKS"]}) == ["werks_t001w"]
    assert _D.structural_grain(table_keys={}) == []
    # Junk predicates must not crash or invent members.
    assert _D.structural_grain(
        table_keys={"T001W": ["WERKS"]},
        join_graph=[{"right_table": "", "condition": "not a predicate", "sequence": "x"}],
    ) == ["werks_t001w"]


def test_derive_grain_uses_the_structural_contract():
    g = _D.derive_grain(_INV_KEYS, "inv_mov_stock", join_graph=_INV_JOINS)
    assert g.entity_grain == ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg"]
    assert g.business_grain == "inv_mov_stock_item"
    assert _D.derive_grain({}, "x").entity_grain == ["id_placeholder"]


def test_both_write_paths_agree():
    """The ingestion path and the admin save path must derive the SAME grain — the
    split where one emitted raw SAP codes and the other a superkey is what this
    whole change closes."""
    fields = [
        {"name": "mblnr_mkpf", "source": "MKPF.MBLNR", "field_role": "identifier"},
        {"name": "mjahr_mkpf", "source": "MKPF.MJAHR", "field_role": "identifier"},
        {"name": "mblnr_mseg", "source": "MSEG.MBLNR", "field_role": "identifier"},
        {"name": "mjahr_mseg", "source": "MSEG.MJAHR", "field_role": "identifier"},
        {"name": "zeile_mseg", "source": "MSEG.ZEILE", "field_role": "identifier"},
        {"name": "matnr_marc", "source": "MARC.MATNR", "field_role": "identifier"},
        {"name": "werks_marc", "source": "MARC.WERKS", "field_role": "identifier"},
        {"name": "matnr_mard", "source": "MARD.MATNR", "field_role": "identifier"},
        {"name": "werks_mard", "source": "MARD.WERKS", "field_role": "identifier"},
        {"name": "lgort_mard", "source": "MARD.LGORT", "field_role": "identifier"},
        {"name": "labst_mard", "source": "MARD.LABST", "field_role": "measure"},
    ]
    from_admin = _D.recompute_entity_grain(fields, join_graph=_INV_JOINS)
    from_ingest = _D.derive_grain(_INV_KEYS, "inv_mov_stock", join_graph=_INV_JOINS).entity_grain
    assert from_admin == from_ingest == ["mblnr_mkpf", "mjahr_mkpf", "zeile_mseg"]


def test_structural_grain_prefers_a_representative_the_entity_publishes():
    """When a Silver carries only the CHILD's copy of a join-equal column, the
    grain must name that one — the class members are equal by predicate, so the
    choice is cosmetic, but emitting a name the entity does not publish would
    hand back a grain member no query can reference."""
    published = {"mblnr_mseg", "mjahr_mseg", "zeile_mseg"}  # no MKPF columns exposed
    grain = _D.structural_grain(table_keys=_INV_KEYS, join_graph=_INV_JOINS, published=published)
    assert grain == ["mblnr_mseg", "mjahr_mseg", "zeile_mseg"]
    # Without the hint, the root-most member wins (both are correct constraints).
    assert _D.structural_grain(table_keys=_INV_KEYS, join_graph=_INV_JOINS)[0] == "mblnr_mkpf"


def test_recompute_entity_grain_keeps_only_published_fields():
    """A structural member that is not a declared field of this entity is dropped;
    if nothing survives, the identifier fallback keeps the save path working."""
    fields = [
        # `source` says MKPF.MBLNR but the author named the column off-convention,
        # so the derived `mblnr_mkpf` is not selectable and must not be emitted.
        {"name": "doc_number", "source": "MKPF.MBLNR", "field_role": "identifier"},
    ]
    assert _D.recompute_entity_grain(fields, join_graph=_INV_JOINS) == ["doc_number"]


def test_derive_join_graph_skips_root():
    rels = [
        SimpleNamespace(
            sequence=1,
            parent_relation="",
            tabname="VBAK",
            join_type="",
            field_main="",
            field_sec="",
        ),
        SimpleNamespace(
            sequence=2,
            parent_relation="VBAK",
            tabname="VBAP",
            join_type="INNER",
            field_main="VBELN",
            field_sec="VBELN",
        ),
    ]
    jg = _D.derive_join_graph(rels)
    assert len(jg) == 1
    assert jg[0].left_table == "VBAK" and jg[0].right_table == "VBAP"
    assert jg[0].condition == "VBAK.VBELN = VBAP.VBELN"
    assert jg[0].sequence == 2


# ── complete() ───────────────────────────────────────────────────────────────


def _silver_core():
    return {
        "id": "silver_s4h_sd_demo",
        "layer": "silver",
        "source_system": "s4h",
        "module": "sd",
        "name": "demo",
        "classification": "T",
        "composed_of": ["bronze_s4h_t_t"],
        "fields": [
            {"name": "amt", "source": "T.AMT", "type": "P15"},
            {"name": "doc", "source": "T.DOC", "field_role": "identifier", "type": "C10"},
        ],
    }


def test_complete_bronze_fills_scaffolding():
    raw = {
        "id": "bronze_s4h_t_t",
        "layer": "bronze",
        "source_system": "s4h",
        "name": "T",
        "alias": "T",
        "description": "x",
        "fields": {
            "DOC": {"type": "C10", "alias": "doc", "key_field": True, "description": "d"},
            "AMT": {"type": "P15", "alias": "amt", "key_field": False, "description": "a"},
        },
    }
    out = _D.complete(raw, layer="bronze")
    assert out["version"] == "1"
    assert out["source_system_id"] == 0
    assert out["primary_key"] == ["DOC"]
    assert out["fields"]["DOC"]["type"] == "STRING(10)"
    assert out["fields"]["AMT"]["type"] == "DECIMAL(15)"
    # input untouched (non-destructive)
    assert raw["fields"]["DOC"]["type"] == "C10"
    assert "version" not in raw


def test_complete_silver_fills_and_derives():
    raw = _silver_core()
    out = _D.complete(raw, layer="silver")
    assert out["version"] == "1"
    assert out["source_system_no"] == 0
    assert out["internal_id"] == "silver_s4h_sd_demo"
    # business_process is NOT seeded from `module`: they are two different axes
    # (standards §4.1). A module code is not a process name, so the deriver leaves
    # it empty and the enrichment scope flags it via `has_business_process`.
    assert out["business_process"] == ""
    assert out["entity_role"] == "fact"  # T + measure (amt P15→DECIMAL→measure)
    assert out["fields"][0]["field_role"] == "measure"
    assert out["fields"][0]["type"] == "DECIMAL(15)"
    assert out["grain"]["entity_grain"] == ["doc"]
    assert out["grain"]["business_grain"] == "demo_item"
    assert out["composed_of"] == ["bronze_s4h_t_t"]  # author's, not synthesized


def test_complete_gold_drops_composed_of_and_join_graph():
    """Neither key is part of the Gold contract, so `complete()` must not emit them.

    It used to synthesize `composed_of = [db_table_name]` — the restatement that made
    the key worthless. `complete()` feeds the admin save path, so anything it returns
    gets WRITTEN: leaving the keys to Pydantic's `extra='ignore'` would keep minting
    dead keys into the YAML on every save.
    """
    raw = {
        "id": "gold_s4h_kpi",
        "layer": "gold",
        "source_system": "s4h",
        "module": "sd",
        "name": "kpi",
        "classification": "T",
        "db_table_name": "GOLD_KPI",
        # An author (or an older YAML) supplying them must still get them dropped.
        "composed_of": ["MY_SCHEMA.GOLD_KPI"],
        "join_graph": [
            {"left_table": "A", "right_table": "B", "join_type": "INNER", "condition": "A.x = B.x"}
        ],
        "fields": [
            {"name": "amount", "field_role": "measure", "type": "DECIMAL(15,2)"},  # no source
            {"name": "kept", "source": "ALREADY.SET", "field_role": "dimension", "type": "TEXT"},
        ],
    }
    out = _D.complete(raw, layer="gold")
    assert "composed_of" not in out
    assert "join_graph" not in out
    # `source` is optional lineage — the deriver never fabricates a self-reference,
    # so a field without one stays without one; an author-set source is untouched.
    assert not out["fields"][0].get("source")
    assert out["fields"][1]["source"] == "ALREADY.SET"


def test_complete_idempotent():
    once = _D.complete(_silver_core(), layer="silver")
    twice = _D.complete(once, layer="silver")
    assert once == twice


def test_complete_non_destructive_preserves_author_values():
    raw = _silver_core()
    raw["entity_role"] = "reference"
    raw["fields"][0]["field_role"] = "attribute"  # author override
    raw["description"] = "real description"
    raw["fields"][0]["description"] = "real field desc"
    out = _D.complete(raw, layer="silver")
    assert out["entity_role"] == "reference"  # not overwritten
    assert out["fields"][0]["field_role"] == "attribute"  # not overwritten
    assert out["description"] == "real description"  # placeholder did not clobber
    assert out["fields"][0]["description"] == "real field desc"


# ── D1 hybrid: innocuous placeholders + strict semantic assertion ─────────────


def test_complete_bronze_fills_innocuous_placeholders():
    """LLM omitted alias/description/key_field/type — deriver fills so it validates."""
    raw = {
        "id": "bronze_s4h_t_t",
        "layer": "bronze",
        "source_system": "s4h",
        "name": "VBAK",
        "fields": {"DOC": {}, "AMT": {"type": "P15"}},  # bare fields
    }
    out = _D.complete(raw, layer="bronze")
    assert out["alias"] == "VBAK"  # entity alias ← name
    assert out["description"] == ""  # innocuous placeholder
    assert out["fields"]["DOC"]["alias"] == "doc"  # ← field name lowercased
    assert out["fields"]["DOC"]["description"] == ""
    assert out["fields"]["DOC"]["key_field"] is False  # default
    assert out["fields"]["DOC"]["type"] == "STRING"  # typeless → STRING
    assert out["fields"]["AMT"]["type"] == "DECIMAL(15)"


def test_complete_silver_fills_field_description_placeholder():
    raw = _silver_core()
    out = _D.complete(raw, layer="silver")
    assert out["description"] == ""  # entity placeholder
    assert all("description" in f for f in out["fields"])  # every field has one


def test_assert_semantic_complete_passes_on_valid_silver():
    out = _D.complete(_silver_core(), layer="silver")
    _D.assert_semantic_complete(out, layer="silver")  # does not raise


def test_assert_semantic_complete_bronze_accepts_keyless():
    """Bronze is a no-op again (owner decision 2026-08-03): a keyless Bronze is
    accepted, not rejected. ``key_field`` is the data-product author's key
    declaration, consumed as authority — a missing declaration is an upstream
    authoring error the ASK author escalates to the Data Modeler admin, and
    blocking the save here would only re-guess the key. Supersedes
    ``test_assert_semantic_complete_bronze_requires_a_key`` (which itself
    superseded the original no-op test — the contract has now come full circle,
    but deliberately: the reject variant predated the confirmed upstream
    contract)."""
    for raw in (
        {"id": "bronze_x", "primary_key": ["MATNR"]},
        {"id": "bronze_x", "primary_key": []},
        {"id": "bronze_x"},
    ):
        _D.assert_semantic_complete(raw, layer="bronze")  # no raise


def test_assert_semantic_complete_missing_composed_of():
    raw = _silver_core()
    raw.pop("composed_of")
    out = _D.complete(raw, layer="silver")
    with pytest.raises(ValueError, match="composed_of"):
        _D.assert_semantic_complete(out, layer="silver")
    # empty list is also rejected
    out["composed_of"] = []
    with pytest.raises(ValueError, match="composed_of"):
        _D.assert_semantic_complete(out, layer="silver")


def test_assert_semantic_complete_missing_classification():
    raw = _silver_core()
    raw.pop("classification")
    out = _D.complete(raw, layer="silver")
    with pytest.raises(ValueError, match="classification"):
        _D.assert_semantic_complete(out, layer="silver")


def test_assert_semantic_complete_missing_module():
    raw = _silver_core()
    raw.pop("module")
    out = _D.complete(raw, layer="silver")
    with pytest.raises(ValueError, match="module"):
        _D.assert_semantic_complete(out, layer="silver")


def test_assert_semantic_complete_multibronze_silver_needs_join_graph():
    raw = _silver_core()
    raw["composed_of"] = ["bronze_s4h_a_a", "bronze_s4h_b_b"]  # 2 bronzes, no join_graph
    out = _D.complete(raw, layer="silver")
    with pytest.raises(ValueError, match="join_graph"):
        _D.assert_semantic_complete(out, layer="silver")
    # with a join_graph present it passes
    out["join_graph"] = [
        {
            "left_table": "A",
            "right_table": "B",
            "join_type": "INNER",
            "condition": "A.K = B.K",
            "sequence": 2,
        }
    ]
    _D.assert_semantic_complete(out, layer="silver")  # no raise


def test_assert_semantic_complete_gold_no_composed_of_requirement():
    raw = {
        "id": "gold_s4h_kpi",
        "layer": "gold",
        "source_system": "s4h",
        "module": "sd",
        "name": "kpi",
        "classification": "T",
        "db_table_name": "GOLD_KPI",
        "fields": [{"name": "amount", "field_role": "measure", "type": "DECIMAL(15,2)"}],
    }
    out = _D.complete(raw, layer="gold")
    _D.assert_semantic_complete(out, layer="gold")  # gold needs no composed_of from author

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""build_skeleton — the layer contracts, pinned against the official standards
(platform/docs/semantic-layer/): unqualified db_table_name, no composed_of /
join_graph / source / aggregation_behavior at Gold, DDL key → identifiers →
grain, Bronze client-column exclusion, and the annotation-absent degradation."""

from __future__ import annotations

from ask_admin_api.application.ddl_parser import parse_relations
from ask_admin_api.application.ddl_skeleton import (
    EntityAnnotation,
    FieldAnnotation,
    annotation_user_payload,
    build_skeleton,
    detect_module,
)
from tests.unit.test_ddl_parser import CLICKHOUSE_DDL


def _clickhouse_rel():
    return parse_relations(CLICKHOUSE_DDL)[0]


def _annotation() -> EntityAnnotation:
    return EntityAnnotation(
        entity_name="ventas_detalle",
        description="Detalle de ventas por documento y posicion",
        entity_role="fact",
        classification="T",
        business_process="ORDER TO CASH",
        fields=[
            FieldAnnotation(
                column="valor_neto",
                field_role="measure",
                description="Valor neto de la venta",
                alias="valor_neto",
            ),
            FieldAnnotation(
                column="fecha_doc",
                field_role="timestamp",
                description="Fecha del documento",
            ),
            # deliberately annotates a KEY column as dimension — the DDL key must win
            FieldAnnotation(column="docventas", field_role="dimension", description="Doc"),
        ],
    )


# ── Gold ─────────────────────────────────────────────────────────────────────


def test_gold_skeleton_honors_the_official_contract():
    doc, _ = build_skeleton(
        _clickhouse_rel(),
        layer="gold",
        source_system="s4h",
        module="sd",
        annotation=_annotation(),
    )
    assert doc["id"] == "gold_s4h_ventas_detalle"
    assert doc["module"] == "sd"
    assert doc["db_table_name"] == "gold_md_final"  # UNQUALIFIED (GOLD §3.1)
    assert doc["entity_role"] == "fact"
    assert doc["business_process"] == "ORDER TO CASH"
    assert "composed_of" not in doc and "join_graph" not in doc
    assert "classification" not in doc
    for fd in doc["fields"]:
        assert "source" not in fd  # never authored at Gold (§4)
        assert "aggregation_behavior" not in fd  # absent = not curated (§4.1)
        assert "additivity" not in fd


def test_gold_grain_comes_from_order_by_and_key_columns_are_identifiers():
    doc, warnings = build_skeleton(
        _clickhouse_rel(),
        layer="gold",
        source_system="s4h",
        module="sd",
        annotation=_annotation(),
    )
    assert doc["grain"]["entity_grain"] == ["mandante", "docventas", "posicion", "year", "month"]
    roles = {f["name"]: f.get("field_role") for f in doc["fields"]}
    # docventas was annotated 'dimension' but is in the ORDER BY key — key wins
    for key_col in ("mandante", "docventas", "posicion", "year", "month"):
        assert roles[key_col] == "identifier"
    assert any("ORDER BY" in w and "verify" in w for w in warnings)


def test_gold_field_names_and_types_are_deterministic():
    doc, _ = build_skeleton(
        _clickhouse_rel(),
        layer="gold",
        source_system="s4h",
        module="sd",
        annotation=_annotation(),
    )
    by_name = {f["name"]: f for f in doc["fields"]}
    assert by_name["_version"]["type"] == "TIMESTAMP"  # DateTime64(3)
    assert by_name["hora"]["type"] == "TIMESTAMP"  # Nullable(DateTime('UTC'))
    assert by_name["posicion"]["type"] == "INTEGER"  # Int64
    assert by_name["valor_neto"]["type"] == "DECIMAL(76,7)"
    assert by_name["valor_neto"]["field_role"] == "measure"  # from the annotation
    assert by_name["valor_neto"]["description"] == "Valor neto de la venta"


def test_gold_without_annotation_still_builds_a_valid_entity():
    doc, warnings = build_skeleton(
        _clickhouse_rel(),
        layer="gold",
        source_system="s4h",
        module="gen",
        annotation=None,
    )
    assert doc["id"] == "gold_s4h_gold_md_final"  # name defaulted from the table
    assert doc["module"] == "gen"
    assert doc["entity_role"] == "fact"
    assert any("annotation unavailable" in w for w in warnings)
    # roles for non-key columns are absent — EntityDeriver derives them on import
    by_name = {f["name"]: f for f in doc["fields"]}
    assert "field_role" not in by_name["valor_neto"]
    assert by_name["mandante"]["field_role"] == "identifier"  # keys always deterministic


def test_gold_imports_clean_through_the_real_import_validators():
    """End-to-end against the actual EntityDeriver + GoldNode — the exact gate
    that 422'd the 2026-08-12 ClickHouse import."""
    from ask_knowledge_graph.domain.entity_deriver import EntityDeriver
    from ask_knowledge_graph.domain.nodes import GoldNode

    doc, _ = build_skeleton(
        _clickhouse_rel(),
        layer="gold",
        source_system="s4h",
        module="sd",
        annotation=_annotation(),
    )
    deriver = EntityDeriver()
    completed = deriver.complete(dict(doc), layer="gold")
    deriver.assert_semantic_complete(completed, layer="gold")  # must not raise
    GoldNode.model_validate(completed)  # must not raise


# ── Silver (flat) ────────────────────────────────────────────────────────────


def test_silver_skeleton_is_flat_with_classification():
    doc, _ = build_skeleton(
        _clickhouse_rel(),
        layer="silver",
        source_system="s4h",
        module="sd",
        annotation=_annotation(),
    )
    assert doc["id"] == "silver_s4h_sd_ventas_detalle"
    assert doc["classification"] == "T"
    assert doc["composed_of"] == ["gold_md_final"]  # its own physical table
    assert "join_graph" not in doc
    for fd in doc["fields"]:
        assert "source" not in fd  # flat Silver has no bronze lineage


def test_silver_without_annotation_defaults_classification_with_warning():
    doc, warnings = build_skeleton(
        _clickhouse_rel(),
        layer="silver",
        source_system="s4h",
        module="sd",
        annotation=None,
    )
    assert doc["classification"] == "T"
    assert any("classification defaulted" in w for w in warnings)


def test_silver_imports_clean_through_the_real_import_validators():
    from ask_knowledge_graph.domain.entity_deriver import EntityDeriver
    from ask_knowledge_graph.domain.nodes import SilverNode

    doc, _ = build_skeleton(
        _clickhouse_rel(),
        layer="silver",
        source_system="s4h",
        module="sd",
        annotation=_annotation(),
    )
    deriver = EntityDeriver()
    completed = deriver.complete(dict(doc), layer="silver")
    deriver.assert_semantic_complete(completed, layer="silver")
    SilverNode.model_validate(completed)


# ── Bronze ───────────────────────────────────────────────────────────────────

_BRONZE_DDL = """
CREATE TABLE "VBAK" (
    "MANDT" NVARCHAR(3) NOT NULL,
    "VBELN" NVARCHAR(10) NOT NULL,
    "NETWR" DECIMAL(15,2),
    PRIMARY KEY ("MANDT", "VBELN")
)
"""


def test_bronze_excludes_client_column_from_primary_key():
    rel = parse_relations(_BRONZE_DDL)[0]
    doc, warnings = build_skeleton(
        rel,
        layer="bronze",
        source_system="s4h",
        module="gen",
        annotation=EntityAnnotation(entity_name="order_header", description="Sales orders"),
    )
    assert doc["primary_key"] == ["VBELN"]  # MANDT excluded (BRONZE §3.5)
    assert doc["fields"]["MANDT"]["key_field"] is False
    assert doc["fields"]["VBELN"]["key_field"] is True
    assert any("client column" in w for w in warnings)
    assert doc["id"] == "bronze_s4h_vbak_order_header"
    assert doc["alias"] == "ORDER_HEADER"
    assert doc["name"] == "VBAK"


def test_bronze_imports_clean_through_the_real_validators():
    from ask_knowledge_graph.domain.entity_deriver import EntityDeriver
    from ask_knowledge_graph.domain.nodes import BronzeNode

    rel = parse_relations(_BRONZE_DDL)[0]
    doc, _ = build_skeleton(
        rel,
        layer="bronze",
        source_system="s4h",
        module="gen",
        annotation=None,
    )
    completed = EntityDeriver().complete(dict(doc), layer="bronze")
    BronzeNode.model_validate(completed)


def test_accented_business_name_folds_consistently_in_the_id():
    # Spanish annotation: the id's entity segment and any other folded segment
    # must agree — stripping non-ASCII instead of folding gave 'organizacin'.
    ddl = "CREATE TABLE organizacion_ventas (a INT)"
    rel = parse_relations(ddl)[0]
    ann = EntityAnnotation(entity_name="Organización Ventas", description="Ventas por organización")
    doc, _ = build_skeleton(
        rel, layer="gold", source_system="s4h", module="sd", annotation=ann
    )
    assert doc["id"] == "gold_s4h_organizacion_ventas"
    assert doc["description"] == "Ventas por organización"  # free text keeps accents


def test_bronze_field_alias_collisions_dedup():
    ddl = "CREATE TABLE t (a INT, b INT)"
    rel = parse_relations(ddl)[0]
    ann = EntityAnnotation(
        entity_name="t",
        description="",
        fields=[
            FieldAnnotation(column="a", field_role="dimension", description="", alias="same"),
            FieldAnnotation(column="b", field_role="dimension", description="", alias="same"),
        ],
    )
    doc, _ = build_skeleton(
        rel, layer="bronze", source_system="s4h", module="gen", annotation=ann
    )
    aliases = [doc["fields"]["a"]["alias"], doc["fields"]["b"]["alias"]]
    assert aliases == ["same", "same_2"]  # in-file uniqueness invariant


# ── module auto-detection (owner decision: no Module picker in the UI) ───────


def test_module_detected_from_layer_prefixed_table_name():
    assert detect_module("SILVER_SD_SALES_ORDER") == "sd"
    assert detect_module("silver_sd_sales_order") == "sd"
    assert detect_module("GOLD_FI_LEDGER_BALANCE") == "fi"
    assert detect_module("gold_mm_stock") == "mm"


def test_module_falls_back_to_gen_when_the_token_is_not_a_module():
    # The live ClickHouse table: `md` follows the prefix but is NOT a module.
    assert detect_module("gold_md_final") == "gen"
    assert detect_module("SILVER_FOO_BAR") == "gen"


def test_module_falls_back_to_gen_without_a_layer_prefix():
    assert detect_module("gold_md_final".replace("gold_", "")) == "gen"
    assert detect_module("VBAK") == "gen"
    assert detect_module("") == "gen"
    assert detect_module("dbt_qas_bi_orders") == "gen"


def test_explicit_declared_module_always_wins():
    assert detect_module("SILVER_SD_SALES_ORDER", declared="fi") == "fi"
    assert detect_module("gold_md_final", declared="co") == "co"
    assert detect_module("GOLD_FI_X", declared="  SD  ") == "sd"
    # An unknown explicit value is the author's word, honoured as-is.
    assert detect_module("gold_md_final", declared="zz") == "zz"
    # Empty/whitespace override → detection still runs.
    assert detect_module("SILVER_SD_X", declared="   ") == "sd"


def test_skeleton_uses_the_detected_module_without_being_told():
    rel = parse_relations("CREATE TABLE SILVER_SD_SALES_ORDER (VBELN NVARCHAR(10))")[0]
    doc, _ = build_skeleton(rel, layer="silver", source_system="s4h", annotation=None)
    assert doc["module"] == "sd"
    assert doc["id"] == "silver_s4h_sd_silver_sd_sales_order"


def test_skeleton_defaults_module_to_gen_on_the_clickhouse_table():
    doc, _ = build_skeleton(
        _clickhouse_rel(), layer="gold", source_system="s4h", annotation=_annotation()
    )
    assert doc["module"] == "gen"


# ── Annotation payload ───────────────────────────────────────────────────────


def test_annotation_payload_is_column_list_not_raw_ddl():
    payload = annotation_user_payload(_clickhouse_rel(), layer="gold", context="Ventas BI")
    assert "CREATE TABLE" not in payload  # nothing to transcribe
    assert "BUSINESS CONTEXT (authoritative):" in payload
    assert "- valor_neto | Decimal(76, 7)" in payload
    assert "- hora | Nullable(DateTime('UTC'))" in payload

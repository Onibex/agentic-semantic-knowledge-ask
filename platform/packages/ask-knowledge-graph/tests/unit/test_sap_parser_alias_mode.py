"""SapJsonParser under ColumnNamingMode.ALIAS (REQ_CURATED_COLUMN_NAMING.md).

A client's ETL names physical curated columns ``<alias_fldname>_<tabname>``
(Spanish business aliases). These tests pin the whole alias-mode surface on a
synthetic two-table export: published field names, grain members resolving
through the name map, join-equality collapse across differently-aliased
copies, measure fan-out, ``source``/``join_graph`` invariance, and the
identifier-hygiene warnings for a dirty alias and an in-table collision.
"""

from __future__ import annotations

import copy

from ask_knowledge_graph.domain.naming import ColumnNamingMode
from ask_knowledge_graph.infrastructure.sap_json_parser import SapJsonParser


def _col(tabname, fldname, alias, *, key="", inttype="C", leng=10, desc=""):
    return {
        "tabname": tabname,
        "alias_tabname": f"{tabname}_ALIAS",
        "fldname": fldname,
        "alias_fldname": alias,
        "key_field": key,
        "inttype": inttype,
        "leng": leng,
        "description_field": desc,
    }


_PAYLOAD = {
    "entity": "sales_credit",
    "info": {
        "id": 200,
        "domainv": "ORDER TO CASH",
        "type": "T",
        "description": "Órdenes de venta con límites de crédito — descripción en español",
        "tag2": "s4h",
        "tag3": "100",
        "version": "1",
    },
    "dataprodclass": {"mmodule": "SD"},
    "columns": [
        _col("VBAK", "VBELN", "documento_ventas", key="X", desc="Número de documento"),
        _col("VBAK", "NETWR", "valor_neto", inttype="P", leng=15, desc="Valor neto"),
        # Dirty alias (accent + space + case) — normalized with a warning.
        _col("VBAK", "KKBER", "Crédito Total", desc="Área de control de crédito"),
        # Deliberate in-table collision AFTER normalization → `_2` + warning.
        _col("VBAK", "KLIMK", "credito_total", desc="Límite de crédito"),
        _col("VBAP", "VBELN", "documento_ventas", key="X", desc="Documento (posición)"),
        _col("VBAP", "POSNR", "posicion", key="X", inttype="N", leng=6, desc="Posición"),
    ],
    "relations": [
        {
            "parent_relation": "VBAK",
            "tabname": "VBAP",
            "field_main": "VBELN",
            "field_sec": "VBELN",
            "join_type": "INNER",
            "sequence": 2,
            "subsequence": 1,
            "description_table": "Sales Document Item Data",
            "contflag": "A",
        },
    ],
}


def _parse(mode):
    parser = SapJsonParser(naming_mode=mode)
    bronze, silver = parser.parse_to_domain(copy.deepcopy(_PAYLOAD))
    return parser, bronze, silver


def test_alias_mode_publishes_alias_based_names():
    _, _, silver = _parse(ColumnNamingMode.ALIAS)
    assert [f.name for f in silver.fields] == [
        "documento_ventas_vbak",
        "valor_neto_vbak",
        "credito_total_vbak",
        "credito_total_2_vbak",  # in-table collision → ordinal suffix
        "documento_ventas_vbap",
        "posicion_vbap",
    ]


def test_alias_mode_name_prefix_equals_persisted_bronze_alias():
    # ONE normalization applied once: the published prefix and the Bronze
    # alias can never drift.
    _, bronze, silver = _parse(ColumnNamingMode.ALIAS)
    aliases = {
        (node.name, fld): fdef.alias for node in bronze for fld, fdef in node.fields.items()
    }
    for f in silver.fields:
        table, _, column = f.source.partition(".")
        assert f.name == f"{aliases[(table, column)]}_{table.lower()}"


def test_alias_mode_grain_resolves_through_published_names():
    # VBAK.VBELN = VBAP.VBELN collapses to ONE member (root-most wins), and the
    # members are the PUBLISHED names — grain rule 7 stays selectable.
    _, _, silver = _parse(ColumnNamingMode.ALIAS)
    assert silver.grain.entity_grain == ["documento_ventas_vbak", "posicion_vbap"]


def test_alias_mode_measure_fanout_uses_published_names():
    _, _, silver = _parse(ColumnNamingMode.ALIAS)
    netwr = next(f for f in silver.fields if f.source == "VBAK.NETWR")
    assert netwr.field_role == "measure"
    assert netwr.additivity == "semi_additive"
    assert netwr.non_additive_over == ["posicion_vbap"]


def test_alias_mode_source_and_join_graph_stay_sap_codes():
    # `source` is the stable spine — raw SAP codes in EVERY naming mode.
    _, _, silver = _parse(ColumnNamingMode.ALIAS)
    assert {f.source for f in silver.fields} == {
        "VBAK.VBELN",
        "VBAK.NETWR",
        "VBAK.KKBER",
        "VBAK.KLIMK",
        "VBAP.VBELN",
        "VBAP.POSNR",
    }
    assert silver.join_graph[0].condition == "VBAK.VBELN = VBAP.VBELN"


def test_alias_mode_descriptions_flow_untouched():
    # Accents live in description_field only — never sanitized.
    _, _, silver = _parse(ColumnNamingMode.ALIAS)
    kkber = next(f for f in silver.fields if f.source == "VBAK.KKBER")
    assert kkber.description == "Área de control de crédito"
    assert silver.description.startswith("Órdenes de venta")


def test_dirty_alias_and_collision_emit_warnings_not_rejections():
    parser, _, _ = _parse(ColumnNamingMode.ALIAS)
    warnings = parser.naming_warnings
    assert any("KKBER" in w and "'credito_total'" in w for w in warnings)
    assert any("KLIMK" in w and "credito_total_2" in w for w in warnings)


def test_normalizations_are_aggregated_into_one_warning():
    """A Spanish export normalizes many aliases; hundreds of individually-true
    warnings bury the few that need a decision, so they collapse into one."""
    payload = copy.deepcopy(_PAYLOAD)
    # Six more dirty aliases → 7 normalizations in total with KKBER.
    for i in range(6):
        payload["columns"].append(
            _col("VBAK", f"ZZC{i}", f"Camión Número {i}", desc=f"Camión {i}")
        )
    parser = SapJsonParser(naming_mode=ColumnNamingMode.ALIAS)
    parser.parse_to_domain(payload)
    summary = [w for w in parser.naming_warnings if "normalized to ASCII" in w]
    assert len(summary) == 1  # ONE line, not one per field
    assert "7 identifier(s)" in summary[0]
    assert "MISMATCH RISK" in summary[0]  # alias mode raises the stakes
    assert "(+2 more)" in summary[0]  # 5 examples shown, rest counted


def test_technical_mode_says_normalizations_are_harmless_for_column_names():
    parser = SapJsonParser(naming_mode=ColumnNamingMode.TECHNICAL)
    parser.parse_to_domain(copy.deepcopy(_PAYLOAD))
    summary = [w for w in parser.naming_warnings if "normalized to ASCII" in w]
    assert len(summary) == 1
    assert "harmless for column names in technical mode" in summary[0]


def test_namespaced_sap_field_warns_that_the_published_name_needs_quoting():
    """TECHNICAL mode only lowercases the raw SAP name, so `/CWM/MEINS` publishes
    as `/cwm/meins_vbak`. We do not rewrite it (the client's ETL owns that rule)
    but it must not ship silently."""
    payload = copy.deepcopy(_PAYLOAD)
    payload["columns"].append(_col("VBAK", "/CWM/MEINS", "puom", desc="Unidad paralela"))
    parser = SapJsonParser(naming_mode=ColumnNamingMode.TECHNICAL)
    _, silver = parser.parse_to_domain(payload)
    assert "/cwm/meins_vbak" in [f.name for f in silver.fields]
    assert any("not a bare SQL identifier" in w for w in parser.naming_warnings)


def test_alias_mode_keeps_a_namespaced_field_clean_and_silent():
    payload = copy.deepcopy(_PAYLOAD)
    payload["columns"].append(_col("VBAK", "/CWM/MEINS", "puom", desc="Unidad paralela"))
    parser = SapJsonParser(naming_mode=ColumnNamingMode.ALIAS)
    _, silver = parser.parse_to_domain(payload)
    assert "puom_vbak" in [f.name for f in silver.fields]
    assert not any("not a bare SQL identifier" in w for w in parser.naming_warnings)


def test_warnings_reset_between_parses():
    parser = SapJsonParser(naming_mode=ColumnNamingMode.ALIAS)
    parser.parse_to_domain(copy.deepcopy(_PAYLOAD))
    assert parser.naming_warnings
    clean = copy.deepcopy(_PAYLOAD)
    clean["columns"] = [c for c in clean["columns"] if c["fldname"] not in ("KKBER", "KLIMK")]
    parser.parse_to_domain(clean)
    assert parser.naming_warnings == []


def test_technical_mode_is_unchanged_by_the_same_payload():
    _, _, silver = _parse(ColumnNamingMode.TECHNICAL)
    assert [f.name for f in silver.fields] == [
        "vbeln_vbak",
        "netwr_vbak",
        "kkber_vbak",
        "klimk_vbak",
        "vbeln_vbap",
        "posnr_vbap",
    ]
    assert silver.grain.entity_grain == ["vbeln_vbak", "posnr_vbap"]


def test_clean_env_resolves_technical_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ASK_COLUMN_NAMING", raising=False)
    monkeypatch.chdir(tmp_path)  # no config/settings.json in reach
    parser = SapJsonParser()
    _, silver = parser.parse_to_domain(copy.deepcopy(_PAYLOAD))
    assert silver.fields[0].name == "vbeln_vbak"

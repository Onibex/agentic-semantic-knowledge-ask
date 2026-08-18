# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``YAMLFileService.import_yaml`` runs the EntityDeriver normalization pass
before validation, so hand-authored / DDL+AI YAMLs that omit mechanical
scaffolding still import — while author content + comments survive.
"""

import textwrap
from pathlib import Path

import pytest

from ask_admin_api.application.yaml_file_service import YAMLFileService
from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text


def _svc(tmp_path: Path) -> YAMLFileService:
    ws = tmp_path / "workspace" / "ask"
    ws.mkdir(parents=True)
    return YAMLFileService(workspace_path=str(ws), repo_root=str(tmp_path))


def _read(tmp_path: Path, *parts: str) -> dict:
    return load_yaml_text(
        (tmp_path / "workspace" / "ask" / Path(*parts)).read_text(encoding="utf-8")
    )


def test_import_completes_minimal_silver(tmp_path):
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: silver_s4h_sd_demo
        layer: silver
        source_system: s4h
        module: sd
        name: demo
        classification: T
        description: A demo silver entity
        composed_of: [bronze_s4h_t_t]
        fields:
          - name: amt   # author comment stays
            source: T.AMT
            type: P15
            description: Net amount
          - name: doc
            source: T.DOC
            field_role: identifier
            type: C10
            description: Document id
    """)
    node = svc.import_yaml(yaml)
    assert node.id == "silver_s4h_sd_demo"

    written = (tmp_path / "workspace" / "ask" / "s4h" / "silver" / "sd" / "demo.yaml").read_text(
        encoding="utf-8"
    )
    assert "author comment stays" in written  # ruamel round-trip preserved the comment

    data = _read(tmp_path, "s4h", "silver", "sd", "demo.yaml")
    assert data["internal_id"] == "silver_s4h_sd_demo"  # = id fallback
    assert str(data["version"]) == "1"
    assert data["source_system_no"] == 0
    # NOT seeded from `module`: a module code is not a process name (standards §4.1).
    # Left empty so the enrichment scope flags it via `has_business_process`.
    assert data["business_process"] == ""
    assert data["entity_role"] == "fact"  # T + measure (amt)
    assert data["grain"]["business_grain"] == "demo_item"
    amt, doc = data["fields"][0], data["fields"][1]
    assert amt["type"] == "DECIMAL(15)"  # canonicalized (the one rewrite)
    assert amt["field_role"] == "measure"  # derived
    assert doc["type"] == "STRING(10)"
    assert doc["field_role"] == "identifier"  # author value preserved


def test_import_writes_gold_without_composed_of_or_join_graph(tmp_path):
    """Neither key belongs to a Gold, and import must not write them back.

    An author supplying them (here: a schema-qualified `composed_of`, the shape the
    shipped Golds used to carry) gets them dropped — the physical table is
    `db_table_name`, stated once.
    """
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: gold_s4h_kpi
        layer: gold
        source_system: s4h
        module: sd
        name: kpi
        classification: T
        description: A KPI gold table
        db_table_name: GOLD_KPI
        composed_of: ["MY_SCHEMA.GOLD_KPI"]
        fields:
          - name: total
            source: GOLD_KPI.TOTAL
            field_role: measure
            type: DECIMAL(15,2)
            description: total value
    """)
    node = svc.import_yaml(yaml)
    assert node.id == "gold_s4h_kpi"
    data = _read(tmp_path, "s4h", "gold", "sd", "kpi.yaml")
    assert "composed_of" not in data
    assert "join_graph" not in data
    assert data["db_table_name"] == "GOLD_KPI"


def test_import_completes_minimal_bronze(tmp_path):
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: bronze_s4h_t_t
        layer: bronze
        source_system: s4h
        name: T
        alias: T
        description: A raw table
        fields:
          DOC:
            type: C10
            alias: doc
            key_field: true
            description: doc id
          AMT:
            type: P15
            alias: amt
            key_field: false
            description: amount
    """)
    node = svc.import_yaml(yaml)
    assert node.id == "bronze_s4h_t_t"
    data = _read(tmp_path, "s4h", "bronze", "t.yaml")
    assert data["source_system_id"] == 0
    assert data["primary_key"] == ["DOC"]
    assert data["fields"]["DOC"]["type"] == "STRING(10)"
    assert data["fields"]["AMT"]["type"] == "DECIMAL(15)"


def test_import_propagates_field_placeholders_to_validated_yaml(tmp_path):
    """Regression (DDL smoke): a Silver field that OMITS description must get the
    deriver's "" placeholder written into the validated YAML — not 422. Earlier
    `_apply_fields` only propagated type/field_role, dropping the description fill."""
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: silver_s4h_pp_demo
        layer: silver
        source_system: s4h
        module: pp
        name: demo
        classification: T
        composed_of: [bronze_s4h_t_t]
        fields:
          - name: amt_afko
            source: AFKO.AMT
            type: float8
          - name: doc_afko
            source: AFKO.DOC
            field_role: identifier
            type: varchar(24)
    """)
    node = svc.import_yaml(yaml)  # must NOT raise
    assert node.id == "silver_s4h_pp_demo"
    data = _read(tmp_path, "s4h", "silver", "pp", "demo.yaml")
    # description placeholder reached every field (the bug) + Postgres types mapped
    assert all("description" in f for f in data["fields"])
    assert data["fields"][0]["type"] == "DECIMAL"  # float8 → DECIMAL
    assert data["fields"][1]["type"] == "STRING(24)"  # varchar(24) → STRING(24)


def test_import_bronze_fills_missing_field_alias_and_keyfield(tmp_path):
    """Bronze fields omitting alias/key_field still validate (deriver fills them).

    ``key_field`` is derived FROM the declared ``primary_key``, because BronzeNode
    now demands agreement in both directions — a YAML that declares a key and
    omits the flags must self-repair instead of validating as incoherent.
    """
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: bronze_s4h_x_x
        layer: bronze
        source_system: s4h
        name: X
        primary_key:
          - AUFNR
        fields:
          AUFNR:
            type: text
          NETWR:
            type: float8
    """)
    svc.import_yaml(yaml)  # must NOT raise
    data = _read(tmp_path, "s4h", "bronze", "x.yaml")
    f = data["fields"]["AUFNR"]
    assert f["alias"] == "aufnr" and f["description"] == ""
    assert f["key_field"] is True  # derived from primary_key
    assert data["fields"]["NETWR"]["key_field"] is False
    assert data["fields"]["NETWR"]["type"] == "DECIMAL"  # float8


def test_import_bronze_without_any_key_imports_keyless(tmp_path):
    """A Bronze with neither `primary_key` nor a `key_field: true` column
    imports as a KEYLESS Bronze (owner decision 2026-08-03) — `key_field` is
    the data-product author's declaration, consumed as authority: a missing
    declaration is escalated to the Data Modeler admin, not blocked at import.
    The deriver completes `primary_key: []` so the file round-trips validly."""
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: bronze_s4h_x_x
        layer: bronze
        source_system: s4h
        name: X
        fields:
          AUFNR:
            type: text
    """)
    svc.import_yaml(yaml)  # must NOT raise
    data = _read(tmp_path, "s4h", "bronze", "x.yaml")
    assert data["primary_key"] == []
    assert data["fields"]["AUFNR"]["key_field"] is False


def test_import_bronze_deduplicates_declared_primary_key(tmp_path):
    """The SAP exports repeat (tabname, fldname) rows, so a re-imported Bronze can
    arrive with a duplicated primary_key. The deriver dedups it AND the dedup must
    reach the validated object — `import_yaml` validates the round-trip map, not
    the completed dict, so the deriver's repair has to be written back."""
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: bronze_s4h_marc_plant_data
        layer: bronze
        source_system: s4h
        name: MARC
        primary_key:
          - MATNR
          - WERKS
          - MATNR
          - WERKS
        fields:
          MATNR:
            type: C18
            key_field: true
          WERKS:
            type: C4
            key_field: true
    """)
    svc.import_yaml(yaml)  # must NOT raise
    data = _read(tmp_path, "s4h", "bronze", "marc.yaml")
    assert list(data["primary_key"]) == ["MATNR", "WERKS"]


def test_import_multibronze_silver_without_join_graph_raises(tmp_path):
    """Regression (DDL smoke): a multi-bronze Silver with no join_graph fails with
    a clear message (not the raw Pydantic error)."""
    svc = _svc(tmp_path)
    yaml = textwrap.dedent("""\
        id: silver_s4h_mm_demo
        layer: silver
        source_system: s4h
        module: mm
        name: demo
        classification: T
        composed_of: [bronze_s4h_ekko_h, bronze_s4h_ekpo_i]
        fields:
          - name: ebeln
            source: EKKO.EBELN
            field_role: identifier
            type: varchar(20)
            description: PO number
    """)
    with pytest.raises(ValueError, match="join_graph"):
        svc.import_yaml(yaml)

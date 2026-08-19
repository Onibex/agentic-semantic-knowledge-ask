# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Shared fixtures for the YAML Visualizer (/v1/viz/*) router tests.

Boots the real FastAPI app against a temp workspace backed by a real git repo,
with auth bypassed (ENVIRONMENT=local + DEV_BYPASS_AUTH=true). Every viz router
keeps its own lazy YAMLFileService / GitService singletons, so the fixture
resets all of them around each test.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Repo

from ask_knowledge_graph.infrastructure.yaml_serializer import dump_yaml, load_yaml_text

SILVER_ID = "silver_s4h_sd_sales_order"
BRONZE_ID = "bronze_s4h_vbak_order_header"


@pytest.fixture(autouse=True)
def _pin_deployment_config(monkeypatch):
    """Neutralize AMBIENT deployment config for every test in this package.

    Both deployment flags resolve from the environment and, failing that, from a
    CWD-relative ``config/settings.json`` — which is gitignored and therefore
    absent in CI but present, and configured for a real client, on a developer's
    machine. Without this, running the suite from the project root on a
    deployment set to ``column_naming: alias`` / ``language: es`` fails tests
    that assert TECHNICAL-mode published names (``netwr_vbak``) with a diff that
    looks nothing like its cause. A unit test must control its inputs; deployment
    config is an input.

    Tests that exercise the other modes override these with their own
    ``monkeypatch.setenv`` (fixtures run before the test body, so the test wins).
    """
    monkeypatch.setenv("ASK_COLUMN_NAMING", "technical")
    monkeypatch.setenv("ASK_SEMANTIC_LANGUAGE", "en")

SAMPLE_BRONZE_YAML = textwrap.dedent("""\
    id: bronze_s4h_vbak_order_header
    layer: bronze
    source_system: s4h
    name: VBAK
    alias: ORDER_HEADER
    description: SAP Sales Order Header
    primary_key: [VBELN]
    fields:
      VBELN:
        type: C10
        alias: sales_doc
        key_field: true
        description: Sales document number
      NETWR:
        type: P15
        alias: net_value
        key_field: false
        description: Net order value
""")

SAMPLE_SILVER_YAML = textwrap.dedent("""\
    id: silver_s4h_sd_sales_order
    layer: silver
    module: sd
    name: sales_order
    description: Sales order Silver entity
    entity_role: fact
    classification: T
    db_table_name: SILVER_SD_SALES_ORDER
    grain:
      entity_grain: [VBELN, POSNR]
      business_grain: sales_order_item
    composed_of: [VBAK, VBAP]
    join_graph:
      - left_table: VBAK
        right_table: VBAP
        join_type: INNER
        condition: "VBAK.VBELN = VBAP.VBELN"
        sequence: 1
    fields:
      - name: net_value
        source: VBAK.NETWR
        field_role: measure
        type: P15
        description: Net order value
        aggregation_behavior: SUM
      - name: sales_doc
        source: VBAK.VBELN
        field_role: identifier
        type: C10
        description: Sales document ID
    relationships:
      - target_entity: silver_s4h_sd_customer_master
        relationship_type: many_to_one
        join_condition: "SALES_ORDER.kunnr = CUSTOMER.kunnr"
        semantic_label: sold_to_customer
        traversal_cost: 1
        cross_module: false
        description: Customer that placed the order
""")

_BRONZE_REL = "workspace/ask/s4h/bronze/vbak.yaml"
_SILVER_REL = "workspace/ask/s4h/silver/sd/sales_order.yaml"


def _reset_viz_singletons() -> None:
    from ask_admin_api.routers import (
        viz_admin,
        viz_conflicts,
        viz_ingest,
        viz_yamls,
    )

    for mod in (viz_yamls, viz_ingest, viz_conflicts, viz_admin):
        # viz_admin and viz_yamls only have _yaml_svc; the others have both.
        if hasattr(mod, "_yaml_svc"):
            mod._yaml_svc = None
        if hasattr(mod, "_git_svc"):
            mod._git_svc = None


@pytest.fixture
def viz_repo(tmp_path: Path, monkeypatch) -> Path:
    """A temp repo_root with a git repo + two seed YAMLs committed."""
    repo_root = tmp_path
    workspace = repo_root / "workspace" / "ask"
    bronze_dir = workspace / "s4h" / "bronze"
    silver_dir = workspace / "s4h" / "silver" / "sd"
    bronze_dir.mkdir(parents=True)
    silver_dir.mkdir(parents=True)
    (bronze_dir / "vbak.yaml").write_text(SAMPLE_BRONZE_YAML, encoding="utf-8")
    (silver_dir / "sales_order.yaml").write_text(SAMPLE_SILVER_YAML, encoding="utf-8")

    repo = Repo.init(repo_root)
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    repo.index.add([_BRONZE_REL, _SILVER_REL])
    repo.index.commit("seed: initial semantic layer")

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    monkeypatch.setenv("WORKSPACE_PATH", str(workspace))
    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("BASELINE_PATH", ".sap_baseline")

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()
    _reset_viz_singletons()

    yield repo_root

    _reset_viz_singletons()
    get_settings.cache_clear()


@pytest.fixture
def viz_client(viz_repo: Path) -> TestClient:
    from ask_admin_api.main import app

    return TestClient(app)


def seed_silver_conflict(
    repo_root: Path,
    *,
    conflict_id: str = "conf-1",
    field_name: str = "net_value",
    conflict_type: str = "field_type_changed",
    resolved: bool = False,
) -> dict:
    """Inject a pending conflict + enrichment for the seed silver YAML.

    Pass H: the conflict block is written to the sidecar JSON store under
    ``.sap_baseline/<silver_id>.conflicts.json``; the YAML's ``_meta`` only
    carries ``field_enrichments``. Returns the conflict dict.
    """
    import json as _json

    silver_path = repo_root / _SILVER_REL
    raw = load_yaml_text(silver_path.read_text(encoding="utf-8"))

    conflict = {
        "id": conflict_id,
        "yaml_id": SILVER_ID,
        "field_name": field_name,
        "conflict_type": conflict_type,
        "sap_value": {"name": field_name, "source": "VBAK.NETWR", "type": "P31"},
        "current_value": {
            "name": field_name,
            "source": "VBAK.NETWR",
            "field_role": "measure",
            "type": "P15",
        },
        "enriched_properties": ["field_role"],
        "resolved": resolved,
        "resolution": None,
        "resolved_by": None,
        "resolved_at": None,
    }

    # YAML keeps only the enrichment metadata (no conflicts inline). Kept to
    # exercise the legacy read-time fallback in _extract_meta.
    raw["_meta"] = {
        "field_enrichments": {field_name: ["field_role"]},
    }
    silver_path.write_text(dump_yaml(raw), encoding="utf-8")

    # Conflict goes into the sidecar.
    sidecar_dir = repo_root / ".sap_baseline"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = sidecar_dir / f"{SILVER_ID}.conflicts.json"
    sidecar_path.write_text(_json.dumps([conflict], indent=2), encoding="utf-8")

    # Provenance lives in the .enrichments.json sidecar in production (written
    # by update_yaml). Mirror that so accept_sap tests exercise the real read
    # path — _extract_meta prefers the sidecar over the legacy inline _meta.
    enr_path = sidecar_dir / f"{SILVER_ID}.enrichments.json"
    enr_path.write_text(
        _json.dumps({"field_enrichments": {field_name: ["field_role"]}}, indent=2),
        encoding="utf-8",
    )

    return conflict

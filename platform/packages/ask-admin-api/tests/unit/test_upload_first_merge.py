# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Upload-first flow: a pre-packed YAML is imported, THEN the client's SAP
JSON arrives. Rule (owner, 2026-08-11): a JSON must NEVER overwrite a YAML
silently when no baseline exists — additions apply (they touch nothing),
removals and curated-prop differences become conflicts, and the import seeds
the provenance sidecar that makes the gate work.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from git import Repo

from ask_knowledge_graph.infrastructure.yaml_serializer import dump_yaml, load_yaml_text

# ── Fixtures (same stack as test_merge_structure) ────────────────────────────


def _col(tabname, fldname, alias, *, key="", inttype="C", leng=10, desc=""):
    return {
        "tabname": tabname,
        "alias_tabname": f"{tabname}_T",
        "fldname": fldname,
        "alias_fldname": alias,
        "key_field": key,
        "inttype": inttype,
        "leng": leng,
        "description_field": desc,
    }


def _rel(parent, tab, main, sec, seq, subseq=1):
    return {
        "parent_relation": parent,
        "tabname": tab,
        "field_main": main,
        "field_sec": sec,
        "join_type": "INNER",
        "sequence": seq,
        "subsequence": subseq,
        "description_table": f"SAP {tab}",
        "contflag": "A",
    }


_PAYLOAD_V1 = {
    "entity": "sales_order",
    "info": {
        "id": 6,
        "domainv": "ORDER TO CASH",
        "type": "T",
        "description": "Sales order",
        "tag2": "s4h",
        "tag3": "100",
        "version": "1",
    },
    "dataprodclass": {"mmodule": "SD"},
    "columns": [
        _col("VBAK", "VBELN", "sales_doc", key="X", desc="Sales Document"),
        _col("VBAK", "NETWR", "net_value", inttype="P", leng=15, desc="Net Value"),
        _col("VBAP", "VBELN", "sales_doc", key="X", desc="Sales Document"),
        _col("VBAP", "POSNR", "item", key="X", inttype="N", leng=6, desc="Item"),
        _col("VBAP", "KWMENG", "order_qty", inttype="P", leng=15, desc="Order Quantity"),
    ],
    "relations": [_rel("VBAK", "VBAP", "VBELN", "VBELN", 2)],
}

_PAYLOAD_V2 = copy.deepcopy(_PAYLOAD_V1)
_PAYLOAD_V2["columns"] += [
    _col("VBEP", "VBELN", "sales_doc", key="X", desc="Sales Document"),
    _col("VBEP", "POSNR", "item", key="X", inttype="N", leng=6, desc="Item"),
    _col("VBEP", "ETENR", "sched_line", key="X", inttype="N", leng=4, desc="Schedule Line"),
    _col("VBEP", "BMENG", "confirmed_qty", inttype="P", leng=13, desc="Confirmed Qty"),
]
_PAYLOAD_V2["relations"] += [
    _rel("VBAP", "VBEP", "VBELN", "VBELN", 3, 1),
    _rel("VBAP", "VBEP", "POSNR", "POSNR", 3, 2),
]
# The export sends NOTHING for KWMENG's description — an empty value is not a
# change proposal and must never challenge curated text.
for _c in _PAYLOAD_V2["columns"]:
    if _c["fldname"] == "KWMENG":
        _c["description_field"] = ""


@pytest.fixture
def merge_env(tmp_path: Path, monkeypatch):
    # SET, not delenv — see the same note in test_merge_structure.py: delenv
    # leaves config/settings.json as a second source, so an `alias`-configured
    # developer machine broke these TECHNICAL-mode expectations.
    monkeypatch.setenv("ASK_COLUMN_NAMING", "technical")
    repo_root = tmp_path
    workspace = repo_root / "workspace" / "ask"
    workspace.mkdir(parents=True)
    repo = Repo.init(repo_root)
    repo.config_writer().set_value("user", "name", "t").release()
    repo.config_writer().set_value("user", "email", "t@t.io").release()
    (workspace / ".keep").write_text("")
    repo.index.add(["workspace/ask/.keep"])
    repo.index.commit("seed")

    from ask_admin_api.application.git_service import GitService
    from ask_admin_api.application.yaml_file_service import YAMLFileService

    yaml_svc = YAMLFileService(workspace_path=str(workspace), repo_root=str(repo_root))
    git_svc = GitService(repo_root=str(repo_root))
    return yaml_svc, git_svc, repo_root


def _merge(payload, yaml_svc, git_svc, repo_root):
    from ask_admin_api.application.sap_merge_service import merge_sap_payload

    return merge_sap_payload(
        copy.deepcopy(payload),
        yaml_svc=yaml_svc,
        git_svc=git_svc,
        repo_root=repo_root,
        baseline_root=repo_root / ".sap_baseline",
        author_name="t",
        author_email="t@t.io",
        source_label="test",
    )


def _silver_text(yaml_svc, repo_root, silver_id) -> tuple[Path, dict]:
    node = yaml_svc.get_yaml(silver_id)
    path = repo_root / node.file_path
    return path, load_yaml_text(path.read_text(encoding="utf-8"))


CURATED_DESC = "Valor neto consolidado del documento — métrica curada del pre-empacado"
CURATED_ENTITY_DESC = "Pedidos de venta con contexto comercial completo (capa curada)"


@pytest.fixture
def uploaded_first(merge_env):
    """A curated pre-packed YAML in the workspace with NO SAP baseline.

    Built from a real first-ingest (so it is valid by construction), then
    curated + re-imported through import_yaml (which seeds provenance) and the
    baseline/sidecars removed — exactly the state an Upload-files landing
    leaves behind.
    """
    yaml_svc, git_svc, repo_root = merge_env
    out = _merge(_PAYLOAD_V1, yaml_svc, git_svc, repo_root)
    silver_id = out.silver_id
    _, raw = _silver_text(yaml_svc, repo_root, silver_id)

    raw["description"] = CURATED_ENTITY_DESC
    for f in raw["fields"]:
        if f["name"] == "netwr_vbak":
            f["description"] = CURATED_DESC
    # A curated extra field the export never carried.
    raw["fields"].append(
        {
            "name": "zzcust_vbak",
            "source": "VBAK.ZZCUST",
            "type": "STRING(5)",
            "description": "Clasificación custom del cliente",
            "field_role": "dimension",
        }
    )
    yaml_svc.import_yaml(dump_yaml(raw), force=True)

    # Wipe every SAP sidecar EXCEPT the provenance the import just seeded.
    baseline_root = repo_root / ".sap_baseline"
    for p in baseline_root.glob("*.json"):
        if not p.name.endswith(".enrichments.json"):
            p.unlink()

    return yaml_svc, git_svc, repo_root, silver_id


# ── Provenance seeding at import ─────────────────────────────────────────────


def test_import_seeds_provenance_sidecar(uploaded_first):
    yaml_svc, _, repo_root, silver_id = uploaded_first
    enr = json.loads(
        (repo_root / ".sap_baseline" / f"{silver_id}.enrichments.json").read_text(
            encoding="utf-8"
        )
    )
    assert "description" in enr["entity_enrichments"]
    assert "description" in enr["field_enrichments"]["netwr_vbak"]
    assert "description" in enr["field_enrichments"]["zzcust_vbak"]


# ── The rule: a JSON never overwrites a curated YAML without asking ──────────


def test_upload_first_ingest_conflicts_instead_of_overwriting(uploaded_first):
    yaml_svc, git_svc, repo_root, silver_id = uploaded_first

    out = _merge(_PAYLOAD_V2, yaml_svc, git_svc, repo_root)
    _, raw = _silver_text(yaml_svc, repo_root, silver_id)
    by_name = {f["name"]: f for f in raw["fields"]}
    conflicts = {(c["field_name"], c["conflict_type"]) for c in out.conflicts}

    # Curated prop differences → conflicts, values untouched.
    assert ("netwr_vbak", "field_modified") in conflicts
    assert by_name["netwr_vbak"]["description"] == CURATED_DESC
    assert ("__entity__", "entity_modified") in conflicts
    assert raw["description"] == CURATED_ENTITY_DESC

    # A curated field the export does not carry → removal CONFLICT, kept.
    assert ("zzcust_vbak", "field_removed") in conflicts
    assert "zzcust_vbak" in by_name

    # Empty incoming description is NOT a change proposal — no conflict, no clobber.
    assert not any(c["field_name"] == "kwmeng_vbap" for c in out.conflicts)
    assert by_name["kwmeng_vbap"]["description"] == "Order Quantity"

    # Additions land: VBEP fields + structure + grain, exactly like any merge.
    assert "bmeng_vbep" in by_name
    assert any("vbep" in c for c in raw["composed_of"])
    assert any(e["right_table"] == "VBEP" for e in raw["join_graph"])
    assert raw["grain"]["entity_grain"] == ["vbeln_vbak", "posnr_vbap", "etenr_vbep"]

    # Nothing auto-applied a description over curated content.
    assert not any(
        a["field_name"] == "netwr_vbak" and "description" in str(a["change_type"])
        for a in out.auto_applied
    )

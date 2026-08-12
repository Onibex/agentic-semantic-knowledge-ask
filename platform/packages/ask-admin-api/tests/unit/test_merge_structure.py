"""Structural merge on SAP re-ingest (VBEP-class scenario).

A re-ingest that adds/retires a table must land the WHOLE change, not just the
fields: composed_of, join_graph, grain and measure fan-out — the same
derivation the admin save path runs, so the two write paths agree. These tests
pin that, plus the field-shape rules (no literal-None axis keys, canonical key
order, renames by `source`, bronze primary_key resync).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from git import Repo

from ask_admin_api.application.merge_engine import (
    _add_field,
    merge_structure,
    reconcile_renames,
    rename_field_in_raw,
    structural_diff,
)
from ask_admin_api.application.sap_merge_service import (
    _normalize_silver_fields,
    _rederive_grain_and_fanout,
    _resync_bronze_primary_key,
)

# ── merge_structure (pure 3-way) ─────────────────────────────────────────────


def _edge(left, right, seq, cond, jt="INNER"):
    return {
        "left_table": left,
        "right_table": right,
        "join_type": jt,
        "condition": cond,
        "sequence": seq,
    }


def test_structure_additions_apply_without_baseline():
    """New bronze + new edge from the export land even on a first-sighting
    baseline (additions need no arbiter)."""
    raw = {
        "composed_of": ["bronze_s4h_vbak_h", "bronze_s4h_vbap_i"],
        "join_graph": [_edge("VBAK", "VBAP", 2, "VBAK.VBELN = VBAP.VBELN")],
    }
    incoming = {
        "composed_of": ["bronze_s4h_vbak_h", "bronze_s4h_vbap_i", "bronze_s4h_vbep_s"],
        "join_graph": [
            _edge("VBAK", "VBAP", 2, "VBAK.VBELN = VBAP.VBELN"),
            _edge("VBAP", "VBEP", 3, "VBAP.VBELN = VBEP.VBELN AND VBAP.POSNR = VBEP.POSNR"),
        ],
    }
    audit, changed = merge_structure(
        baseline_structure=None, current_raw=raw, incoming=incoming, yaml_id="s"
    )
    assert changed
    assert "bronze_s4h_vbep_s" in raw["composed_of"]
    assert any(e["right_table"] == "VBEP" for e in raw["join_graph"])
    assert {a["change_type"] for a in audit} == {"composed_of_changed", "join_edge_added"}


def test_structure_removal_requires_baseline_membership():
    """An entry SAP never sent (admin-added) survives; one SAP retires goes."""
    raw = {
        "composed_of": ["bronze_a", "bronze_admin_added", "bronze_gone"],
        "join_graph": [],
    }
    incoming = {"composed_of": ["bronze_a"], "join_graph": []}
    baseline = {"composed_of": ["bronze_a", "bronze_gone"], "join_graph": []}
    _, changed = merge_structure(
        baseline_structure=baseline, current_raw=raw, incoming=incoming, yaml_id="s"
    )
    assert changed
    assert raw["composed_of"] == ["bronze_a", "bronze_admin_added"]


def test_structure_removals_deferred_while_conflicts_pending():
    raw = {"composed_of": ["bronze_a", "bronze_gone"], "join_graph": []}
    incoming = {"composed_of": ["bronze_a"], "join_graph": []}
    baseline = {"composed_of": ["bronze_a", "bronze_gone"], "join_graph": []}
    _, changed = merge_structure(
        baseline_structure=baseline,
        current_raw=raw,
        incoming=incoming,
        yaml_id="s",
        defer_removals=True,
    )
    assert not changed
    assert raw["composed_of"] == ["bronze_a", "bronze_gone"]


def test_edge_condition_three_way():
    """SAP changed + admin untouched → applied. Both changed → admin wins,
    divergence audited. Baseline missing the edge → skipped (first sighting)."""
    cur = _edge("VBAK", "VBAP", 2, "VBAK.VBELN = VBAP.VBELN")
    raw = {"composed_of": [], "join_graph": [dict(cur)]}
    incoming = {"composed_of": [], "join_graph": [_edge("VBAK", "VBAP", 2, "NEW_COND")]}
    baseline = {"composed_of": [], "join_graph": [dict(cur)]}
    audit, changed = merge_structure(
        baseline_structure=baseline, current_raw=raw, incoming=incoming, yaml_id="s"
    )
    assert changed
    assert raw["join_graph"][0]["condition"] == "NEW_COND"
    assert any(a["change_type"] == "join_edge_condition_changed" for a in audit)

    # Both changed → admin's version kept, surfaced in the audit trail.
    raw2 = {"composed_of": [], "join_graph": [_edge("VBAK", "VBAP", 2, "ADMIN_FIXED")]}
    audit2, changed2 = merge_structure(
        baseline_structure=baseline,
        current_raw=raw2,
        incoming=incoming,
        yaml_id="s",
    )
    assert raw2["join_graph"][0]["condition"] == "ADMIN_FIXED"
    assert any(a["change_type"] == "join_edge_condition_divergence_kept" for a in audit2)
    assert not changed2

    # First sighting (baseline lacks the edge) → no prop changes applied.
    raw3 = {"composed_of": [], "join_graph": [dict(cur)]}
    _, changed3 = merge_structure(
        baseline_structure={"composed_of": [], "join_graph": []},
        current_raw=raw3,
        incoming=incoming,
        yaml_id="s",
    )
    assert raw3["join_graph"][0]["condition"] == cur["condition"]
    assert not changed3


# ── renames by source ────────────────────────────────────────────────────────


def test_reconcile_renames_pairs_removed_added_by_source():
    baseline = {
        "documento_vbak": {"type": "STRING(10)", "source": "VBAK.VBELN",
                           "description": "", "field_role": "identifier"},
    }
    incoming = {
        "doc_ventas_vbak": {"type": "STRING(10)", "source": "VBAK.VBELN",
                            "description": "", "field_role": "identifier"},
    }
    diff = structural_diff("s", baseline, incoming, is_bronze=False)
    renames = reconcile_renames(diff)
    assert [(r.old_name, r.new_name) for r in renames] == [
        ("documento_vbak", "doc_ventas_vbak")
    ]
    # The removed half is consumed; the added half stays for reconcile.
    assert [fc.change_type for fc in diff.field_changes] == ["added"]

    raw = {
        "fields": [
            {"name": "documento_vbak", "source": "VBAK.VBELN", "synonyms": ["order id"]}
        ]
    }
    assert rename_field_in_raw(raw, "documento_vbak", "doc_ventas_vbak")
    assert raw["fields"][0]["name"] == "doc_ventas_vbak"
    assert raw["fields"][0]["synonyms"] == ["order id"]  # enrichment survives


# ── field shape rules ────────────────────────────────────────────────────────


def test_add_field_uses_canonical_key_order_and_drops_none():
    raw = {"fields": []}
    _add_field(
        raw,
        "bmeng_vbep",
        {
            "type": "DECIMAL(13)",
            "source": "VBEP.BMENG",
            "description": "Confirmed Quantity",
            "field_role": "measure",
            "aggregation_behavior": None,
        },
        is_bronze=False,
    )
    added = raw["fields"][0]
    assert list(added.keys()) == ["name", "source", "type", "description", "field_role"]
    assert "aggregation_behavior" not in added


def test_normalize_silver_fields_repairs_legacy_damage():
    """Fields older merges appended (`type…name`, literal-None axis key) come
    out canonical; a clean field object is left untouched."""
    clean = {"name": "ok_vbak", "source": "VBAK.OK", "type": "STRING(1)",
             "description": "", "field_role": "dimension"}
    damaged = {
        "type": "DECIMAL(13)",
        "source": "VBEP.BMENG",
        "description": "Confirmed Quantity",
        "field_role": "measure",
        "aggregation_behavior": None,
        "name": "bmeng_vbep",
    }
    raw = {"fields": [clean, damaged]}
    assert _normalize_silver_fields(raw) is True
    assert raw["fields"][0] is clean  # untouched object
    fixed = raw["fields"][1]
    assert list(fixed.keys()) == ["name", "source", "type", "description", "field_role"]
    assert _normalize_silver_fields(raw) is False  # idempotent


def test_resync_bronze_primary_key_follows_key_field_flags():
    raw = {
        "primary_key": ["VBELN"],
        "fields": {
            "VBELN": {"key_field": True},
            "POSNR": {"key_field": True},  # merged flip not yet in the list
            "NETWR": {"key_field": False},
        },
    }
    assert _resync_bronze_primary_key(raw) is True
    assert raw["primary_key"] == ["VBELN", "POSNR"]
    assert _resync_bronze_primary_key(raw) is False


# ── grain + fan-out re-derivation ────────────────────────────────────────────

_JOIN_VBAP = {"left_table": "VBAK", "right_table": "VBAP", "join_type": "INNER",
              "condition": "VBAK.VBELN = VBAP.VBELN", "sequence": 2}
_JOIN_VBEP = {"left_table": "VBAP", "right_table": "VBEP", "join_type": "INNER",
              "condition": "VBAP.VBELN = VBEP.VBELN AND VBAP.POSNR = VBEP.POSNR",
              "sequence": 3}


def _silver_with_vbep() -> dict:
    return {
        "name": "sales_order",
        "grain": {"entity_grain": ["vbeln_vbak", "posnr_vbap"],
                  "business_grain": "sales_order_item"},
        "join_graph": [dict(_JOIN_VBAP), dict(_JOIN_VBEP)],
        "fields": [
            {"name": "vbeln_vbak", "source": "VBAK.VBELN", "field_role": "identifier"},
            {"name": "netwr_vbak", "source": "VBAK.NETWR", "field_role": "measure",
             "additivity": "semi_additive", "non_additive_over": ["posnr_vbap"]},
            {"name": "vbeln_vbap", "source": "VBAP.VBELN", "field_role": "identifier"},
            {"name": "posnr_vbap", "source": "VBAP.POSNR", "field_role": "identifier"},
            {"name": "kwmeng_vbap", "source": "VBAP.KWMENG", "field_role": "measure",
             "aggregation_behavior": "SUM"},
            # Merge-added VBEP fields — no axis keys yet.
            {"name": "vbeln_vbep", "source": "VBEP.VBELN", "field_role": "identifier"},
            {"name": "posnr_vbep", "source": "VBEP.POSNR", "field_role": "identifier"},
            {"name": "etenr_vbep", "source": "VBEP.ETENR", "field_role": "identifier"},
            {"name": "bmeng_vbep", "source": "VBEP.BMENG", "field_role": "measure"},
        ],
    }


def test_rederive_updates_grain_stale_fanout_and_new_measures():
    raw = _silver_with_vbep()
    assert _rederive_grain_and_fanout(raw, field_enrichments={}) is True

    # Grain gains the uncovered VBEP key member.
    assert raw["grain"]["entity_grain"] == ["vbeln_vbak", "posnr_vbap", "etenr_vbep"]

    by_name = {f["name"]: f for f in raw["fields"]}
    # Stale list refreshed: the VBAK header measure now also repeats over ETENR.
    assert by_name["netwr_vbak"]["non_additive_over"] == ["posnr_vbap", "etenr_vbep"]
    # VBAP measure gains its fan-out (was silently additive over ETENR).
    assert by_name["kwmeng_vbap"]["non_additive_over"] == ["etenr_vbep"]
    # The authored function is never touched.
    assert by_name["kwmeng_vbap"]["aggregation_behavior"] == "SUM"
    # VBEP's own key covers the whole grain → genuinely additive → says nothing.
    assert "additivity" not in by_name["bmeng_vbep"]
    assert "aggregation_behavior" not in by_name["bmeng_vbep"]


def test_rederive_respects_curated_additivity():
    raw = _silver_with_vbep()
    changed = _rederive_grain_and_fanout(
        raw, field_enrichments={"netwr_vbak": ["non_additive_over"]}
    )
    assert changed
    by_name = {f["name"]: f for f in raw["fields"]}
    # The curator's (stale-looking but recorded) value is untouchable.
    assert by_name["netwr_vbak"]["non_additive_over"] == ["posnr_vbap"]


# ── End-to-end: VBEP added on a re-ingest ────────────────────────────────────


def _col(tabname, fldname, alias, *, key="", inttype="C", leng=10, desc=""):
    return {
        "tabname": tabname,
        "alias_tabname": f"{tabname}_T",
        "fldname": fldname,
        "alias_fldname": alias,
        "key_field": key,
        "inttype": inttype,
        "leng": leng,
        "description_field": desc or fldname.title(),
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
        _col("VBAK", "VBELN", "sales_doc", key="X"),
        _col("VBAK", "NETWR", "net_value", inttype="P", leng=15),
        _col("VBAP", "VBELN", "sales_doc", key="X"),
        _col("VBAP", "POSNR", "item", key="X", inttype="N", leng=6),
        _col("VBAP", "KWMENG", "order_qty", inttype="P", leng=15),
    ],
    "relations": [_rel("VBAK", "VBAP", "VBELN", "VBELN", 2)],
}

_PAYLOAD_V2 = copy.deepcopy(_PAYLOAD_V1)
_PAYLOAD_V2["columns"] += [
    _col("VBEP", "VBELN", "sales_doc", key="X"),
    _col("VBEP", "POSNR", "item", key="X", inttype="N", leng=6),
    _col("VBEP", "ETENR", "sched_line", key="X", inttype="N", leng=4),
    _col("VBEP", "BMENG", "confirmed_qty", inttype="P", leng=13),
]
_PAYLOAD_V2["relations"] += [
    _rel("VBAP", "VBEP", "VBELN", "VBELN", 3, 1),
    _rel("VBAP", "VBEP", "POSNR", "POSNR", 3, 2),
]


@pytest.fixture
def merge_env(tmp_path: Path, monkeypatch):
    """Real YAMLFileService + GitService on a temp git repo — the exact stack
    merge_sap_payload runs behind the ingest endpoints."""
    monkeypatch.delenv("ASK_COLUMN_NAMING", raising=False)
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


def _read_silver(yaml_svc, repo_root, silver_id):
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    node = yaml_svc.get_yaml(silver_id)
    return load_yaml_text((repo_root / node.file_path).read_text(encoding="utf-8"))


def test_reingest_with_new_table_lands_structure_grain_and_fanout(merge_env):
    yaml_svc, git_svc, repo_root = merge_env

    out1 = _merge(_PAYLOAD_V1, yaml_svc, git_svc, repo_root)
    assert out1.created_entities  # first ingest

    out2 = _merge(_PAYLOAD_V2, yaml_svc, git_svc, repo_root)
    assert not out2.conflicts
    silver = _read_silver(yaml_svc, repo_root, out2.silver_id)

    # Structure landed with the fields.
    assert any("vbep" in c for c in silver["composed_of"])
    vbep_edge = next(e for e in silver["join_graph"] if e["right_table"] == "VBEP")
    assert vbep_edge["condition"] == "VBAP.VBELN = VBEP.VBELN AND VBAP.POSNR = VBEP.POSNR"

    # Grain widened by the uncovered VBEP key member.
    assert silver["grain"]["entity_grain"] == ["vbeln_vbak", "posnr_vbap", "etenr_vbep"]

    by_name = {f["name"]: f for f in silver["fields"]}
    # New fields: canonical key order, no literal-None axis keys.
    assert list(by_name["bmeng_vbep"].keys())[:5] == [
        "name", "source", "type", "description", "field_role",
    ]
    assert all(
        f.get("aggregation_behavior", "sentinel") is not None for f in silver["fields"]
    )
    # Stale fan-out refreshed on the pre-existing measures…
    assert by_name["netwr_vbak"]["non_additive_over"] == ["posnr_vbap", "etenr_vbep"]
    assert by_name["kwmeng_vbap"]["non_additive_over"] == ["etenr_vbep"]
    # …and VBEP's own measure is genuinely additive → carries nothing.
    assert "additivity" not in by_name["bmeng_vbep"]

    # Baseline snapshot now carries the structure (3-way arbiter from here on).
    baseline = json.loads(
        (repo_root / ".sap_baseline" / f"{out2.silver_id}.json").read_text(encoding="utf-8")
    )
    assert any("vbep" in c for c in baseline["silver_structure"]["composed_of"])

    # Idempotency: same payload again → nothing to apply, nothing rewritten.
    out3 = _merge(_PAYLOAD_V2, yaml_svc, git_svc, repo_root)
    assert out3.auto_applied == []
    assert out3.conflicts == []

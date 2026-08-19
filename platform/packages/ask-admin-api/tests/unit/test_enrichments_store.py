# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for EnrichmentsStore + the lazy migration of legacy `_meta`.

The store is plumbing — round-trip + edge cases (empty maps deletes the file,
malformed JSON returns empty defaults). Integration with yaml_file_service is
tested via the lazy-migration path: a YAML with inline `_meta.field_enrichments`
must end up CLEAN (no `_meta`) after the first update_yaml, with the data
moved to the sidecar.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── EnrichmentsStore direct unit tests ──────────────────────────────────────


def test_read_empty_when_sidecar_missing(tmp_path: Path):
    from ask_admin_api.application.enrichments_store import EnrichmentsStore

    store = EnrichmentsStore(tmp_path)
    entity, fields = store.read("silver_x")
    assert entity == []
    assert fields == {}


def test_round_trip_persists_both_maps(tmp_path: Path):
    from ask_admin_api.application.enrichments_store import EnrichmentsStore

    store = EnrichmentsStore(tmp_path)
    store.write(
        "silver_x",
        entity_enrichments=["description", "alias"],
        field_enrichments={"netwr_vbak": ["description", "synonyms"]},
    )
    entity, fields = store.read("silver_x")
    assert entity == ["alias", "description"]  # sorted on write
    assert fields == {"netwr_vbak": ["description", "synonyms"]}


def test_write_empty_deletes_sidecar(tmp_path: Path):
    """Both empty → the file is removed so git diffs stay clean."""
    from ask_admin_api.application.enrichments_store import EnrichmentsStore

    store = EnrichmentsStore(tmp_path)
    store.write("silver_x", entity_enrichments=["alias"], field_enrichments=None)
    path = tmp_path / "silver_x.enrichments.json"
    assert path.exists()

    store.write("silver_x", entity_enrichments=None, field_enrichments=None)
    assert not path.exists()


def test_malformed_sidecar_returns_empty(tmp_path: Path):
    from ask_admin_api.application.enrichments_store import EnrichmentsStore

    (tmp_path / "silver_x.enrichments.json").write_text("{this is not valid json", encoding="utf-8")
    entity, fields = EnrichmentsStore(tmp_path).read("silver_x")
    assert entity == []
    assert fields == {}


def test_sidecar_drops_unexpected_types(tmp_path: Path):
    """Sidecar contents come from disk — be defensive with shapes."""
    from ask_admin_api.application.enrichments_store import EnrichmentsStore

    (tmp_path / "silver_x.enrichments.json").write_text(
        json.dumps(
            {
                "entity_enrichments": "not-a-list",  # invalid
                "field_enrichments": {
                    "netwr_vbak": ["description"],
                    "broken": "should-be-list",  # invalid
                },
            }
        ),
        encoding="utf-8",
    )
    entity, fields = EnrichmentsStore(tmp_path).read("silver_x")
    assert entity == []
    assert fields == {"netwr_vbak": ["description"]}


# ── Lazy migration via yaml_file_service.update_yaml ────────────────────────


def _build_service(tmp_path: Path):
    """Spin up a YAMLFileService on a tmp workspace + sidecar root."""
    workspace = tmp_path / "workspace"
    silver_dir = workspace / "s4h" / "silver" / "sd"
    silver_dir.mkdir(parents=True)
    # Seed the silver YAML with a legacy `_meta` block — what we want to migrate.
    silver_yaml = textwrap.dedent(
        """\
        id: silver_sd_sales_order
        layer: silver
        module: sd
        name: sales_order
        entity_role: fact
        description: Sales order header
        composed_of: [VBAK]
        fields:
          - name: vbeln_vbak
            source: VBAK.VBELN
            type: C10
            field_role: identifier
            description: Sales doc
        _meta:
          field_enrichments:
            vbeln_vbak: [description]
          entity_enrichments: [description]
        """
    )
    (silver_dir / "sales_order.yaml").write_text(silver_yaml, encoding="utf-8")

    from ask_admin_api.application.yaml_file_service import YAMLFileService

    return YAMLFileService(workspace_path=str(workspace), repo_root=str(tmp_path))


def test_update_yaml_migrates_legacy_meta_to_sidecar(tmp_path: Path):
    """A YAML with legacy `_meta` is migrated on the first update_yaml call."""
    from ask_admin_api.models.viz_models import VizFieldUpdate, VizYAMLUpdateRequest

    svc = _build_service(tmp_path)
    svc.update_yaml(
        "silver_sd_sales_order",
        VizYAMLUpdateRequest(
            fields=[VizFieldUpdate(name="vbeln_vbak", description="Unique sales document id")],
            author_name="t",
            author_email="t@x.com",
        ),
    )

    # 1. The YAML body no longer contains `_meta`.
    yaml_text = _read_text(tmp_path / "workspace" / "s4h" / "silver" / "sd" / "sales_order.yaml")
    assert "_meta" not in yaml_text, "Legacy `_meta` should be stripped after first save"

    # 2. The sidecar carries both the legacy entries AND the new edit.
    sidecar = tmp_path / ".sap_baseline" / "silver_sd_sales_order.enrichments.json"
    assert sidecar.exists()
    payload = json.loads(_read_text(sidecar))
    assert "vbeln_vbak" in payload.get("field_enrichments", {})
    assert "description" in payload["field_enrichments"]["vbeln_vbak"]
    # Legacy entity_enrichments preserved through migration.
    assert "description" in payload.get("entity_enrichments", [])


def test_update_yaml_keeps_yaml_clean_for_new_entries(tmp_path: Path):
    """An entity without legacy `_meta` never gains one after enrichment edits."""
    from ask_admin_api.application.yaml_file_service import YAMLFileService
    from ask_admin_api.models.viz_models import VizFieldUpdate, VizYAMLUpdateRequest

    workspace = tmp_path / "workspace"
    silver_dir = workspace / "s4h" / "silver" / "sd"
    silver_dir.mkdir(parents=True)
    (silver_dir / "sales_order.yaml").write_text(
        textwrap.dedent(
            """\
            id: silver_sd_sales_order
            layer: silver
            module: sd
            name: sales_order
            entity_role: fact
            description: Sales order header
            composed_of: [VBAK]
            fields:
              - name: vbeln_vbak
                source: VBAK.VBELN
                type: C10
                field_role: identifier
            """
        ),
        encoding="utf-8",
    )
    svc = YAMLFileService(workspace_path=str(workspace), repo_root=str(tmp_path))
    svc.update_yaml(
        "silver_sd_sales_order",
        VizYAMLUpdateRequest(
            description="Sales order header with billing context",
            fields=[
                VizFieldUpdate(name="vbeln_vbak", description="Unique sales document id"),
            ],
            author_name="t",
            author_email="t@x.com",
        ),
    )
    yaml_text = _read_text(silver_dir / "sales_order.yaml")
    assert "_meta" not in yaml_text
    assert "field_enrichments" not in yaml_text
    # Sidecar persisted the provenance.
    payload = json.loads(
        _read_text(tmp_path / ".sap_baseline" / "silver_sd_sales_order.enrichments.json")
    )
    assert payload["entity_enrichments"] == ["description"]
    assert "vbeln_vbak" in payload["field_enrichments"]

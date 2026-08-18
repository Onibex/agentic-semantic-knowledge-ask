# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``POST /v1/admin/yaml/derive`` — preview the EntityDeriver, write nothing."""

from __future__ import annotations

import textwrap


def _count_yaml(repo_root) -> int:
    return len(list((repo_root / "workspace" / "ask").rglob("*.yaml")))


def test_derive_silver_returns_derived_flags_and_writes_nothing(viz_client, viz_repo):
    before = _count_yaml(viz_repo)
    yaml = textwrap.dedent("""\
        id: silver_s4h_sd_brand_new
        layer: silver
        source_system: s4h
        module: sd
        name: brand_new
        classification: T
        description: A brand new silver
        composed_of: [bronze_s4h_vbak_order_header]
        fields:
          - name: amt
            source: VBAK.NETWR
            type: P15
            description: amount
          - name: doc
            source: VBAK.VBELN
            field_role: identifier
            type: C10
            description: doc id
    """)
    r = viz_client.post("/v1/admin/yaml/derive", json={"yaml_content": yaml})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["layer"] == "silver"
    assert body["validation_error"] is None
    node = body["node"]
    assert node["internal_id"] == "silver_s4h_sd_brand_new"
    assert node["entity_role"] == "fact"
    assert node["grain"]["business_grain"] == "brand_new_item"
    assert node["fields"][0]["type"] == "DECIMAL(15)"  # canonicalized
    assert node["fields"][0]["field_role"] == "measure"  # derived
    assert "internal_id" in body["entity_derived"]
    assert "entity_role" in body["entity_derived"]
    # per-field derived flags
    amt_flag = next(f for f in body["fields"] if f["name"] == "amt")
    assert "field_role" in amt_flag["derived"]
    assert "type" in amt_flag["derived"]
    # nothing written
    assert _count_yaml(viz_repo) == before


def test_derive_surfaces_validation_error_for_missing_semantic_field(viz_client):
    # D1 hybrid: `description` is now an *innocuous* field the deriver auto-fills
    # (""), so omitting it no longer 422s. The genuinely-semantic field the deriver
    # refuses to invent is Silver `composed_of` — its absence is what /derive must
    # surface (it validates in Pydantic as [] but is semantically incomplete).
    yaml = textwrap.dedent("""\
        id: silver_s4h_sd_nocomposed
        layer: silver
        source_system: s4h
        module: sd
        name: nocomposed
        classification: T
        fields:
          - name: doc
            source: VBAK.VBELN
            field_role: identifier
            type: C10
            description: doc id
    """)
    r = viz_client.post("/v1/admin/yaml/derive", json={"yaml_content": yaml})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_error"] is not None
    assert "composed_of" in body["validation_error"].lower()


def test_derive_fills_innocuous_description_placeholder(viz_client):
    # D1 hybrid: omitting `description` is no longer an error — the deriver fills
    # "" so the node validates; the empty value is flagged for enrichment.
    yaml = textwrap.dedent("""\
        id: silver_s4h_sd_nodesc
        layer: silver
        source_system: s4h
        module: sd
        name: nodesc
        classification: T
        composed_of: [bronze_s4h_vbak_order_header]
        fields:
          - name: doc
            source: VBAK.VBELN
            field_role: identifier
            type: C10
    """)
    r = viz_client.post("/v1/admin/yaml/derive", json={"yaml_content": yaml})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_error"] is None
    assert body["node"]["description"] == ""
    assert body["node"]["fields"][0]["description"] == ""


def test_derive_rejects_bad_layer(viz_client):
    r = viz_client.post("/v1/admin/yaml/derive", json={"yaml_content": "layer: metric\nid: x"})
    assert r.status_code == 400

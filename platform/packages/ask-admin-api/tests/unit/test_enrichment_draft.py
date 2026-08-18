# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Body-aware (draft) enrichment endpoints — wiring without a saved entity.

The LLM-backed paths are covered by ``test_enrichment_service.py`` (the draft
routes call the SAME service methods); here we assert the routes are registered
and that the relationship-suggest draft loads its target by id (404 on missing).
"""

from __future__ import annotations


def test_relationships_suggest_draft_404_on_missing_target(viz_client):
    r = viz_client.post(
        "/v1/admin/enrich/relationships-suggest/draft",
        json={
            "source_raw_yaml": {"id": "silver_s4h_sd_draft", "layer": "silver", "name": "draft"},
            "target_entity_id": "silver_does_not_exist",
        },
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_entity_preview_draft_route_registered(viz_client):
    # Missing required body fields → 422 (route exists); a 404 would mean unmounted.
    r = viz_client.post("/v1/admin/enrich/entity/preview/draft", json={})
    assert r.status_code == 422


def test_field_draft_route_registered(viz_client):
    r = viz_client.post("/v1/admin/enrich/field/draft", json={})
    assert r.status_code == 422

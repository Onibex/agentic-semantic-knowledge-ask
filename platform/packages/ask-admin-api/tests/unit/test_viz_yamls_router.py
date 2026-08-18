# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Integration tests for /v1/viz/yamls/* — list, get, update, history, diff, restore.

Covers test plan blocks Graph (read/edit) + History (H1-H5). Uses a real git
repo + temp workspace (see conftest.viz_client) with auth bypassed.
"""

from __future__ import annotations

from tests.unit.conftest import BRONZE_ID, SILVER_ID

# ── list / get / search ─────────────────────────────────────────────────────────


def test_list_yamls(viz_client):
    resp = viz_client.get("/v1/viz/yamls")
    assert resp.status_code == 200, resp.text
    ids = {n["id"] for n in resp.json()}
    assert ids == {BRONZE_ID, SILVER_ID}


def test_list_yamls_layer_filter(viz_client):
    resp = viz_client.get("/v1/viz/yamls", params={"layer": "silver"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == SILVER_ID


def test_get_yaml_full_node(viz_client):
    resp = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}")
    assert resp.status_code == 200, resp.text
    node = resp.json()
    assert node["layer"] == "silver"
    assert node["entity_role"] == "fact"
    assert node["classification"] == "T"
    assert node["db_table_name"] == "SILVER_SD_SALES_ORDER"
    assert node["grain"]["entity_grain"] == ["VBELN", "POSNR"]
    assert node["grain"]["business_grain"] == "sales_order_item"
    field_names = {f["name"] for f in node["fields"]}
    assert {"net_value", "sales_doc"} <= field_names


def test_get_yaml_404(viz_client):
    resp = viz_client.get("/v1/viz/yamls/does_not_exist")
    assert resp.status_code == 404


def test_get_yaml_exposes_relationships(viz_client):
    node = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}").json()
    rels = node["relationships"]
    assert len(rels) == 1
    assert rels[0]["target_entity"] == "silver_s4h_sd_customer_master"
    assert rels[0]["semantic_label"] == "sold_to_customer"
    assert rels[0]["relationship_type"] == "many_to_one"


def test_search_yamls(viz_client):
    resp = viz_client.get("/v1/viz/yamls/search", params={"q": "sales_order"})
    assert resp.status_code == 200
    ids = {n["id"] for n in resp.json()}
    assert SILVER_ID in ids


def test_search_yamls_empty_query_400(viz_client):
    resp = viz_client.get("/v1/viz/yamls/search", params={"q": ""})
    assert resp.status_code == 400


# ── update + commit ──────────────────────────────────────────────────────────────


def test_update_yaml_persists_and_commits(viz_client):
    resp = viz_client.put(
        f"/v1/viz/yamls/{SILVER_ID}",
        json={
            "author_name": "Admin",
            "author_email": "admin@example.com",
            "description": "Curated sales order entity",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Curated sales order entity"

    # the change is reflected in a fresh read
    again = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}")
    assert again.json()["description"] == "Curated sales order entity"

    # and a commit was created with the enrichment message
    hist = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/history").json()
    assert hist["total_count"] >= 2  # seed + this update
    assert hist["commits"][0]["message"] == f"viz: update {SILVER_ID}"
    # Author is the server-verified JWT identity (dev-bypass claim), not the body.
    assert hist["commits"][0]["author_email"] == "admin@local"


def test_update_persists_relationships_synonyms_normalization(viz_client):
    resp = viz_client.put(
        f"/v1/viz/yamls/{SILVER_ID}",
        json={
            "fields": [
                {
                    "name": "net_value",
                    "synonyms": ["revenue", "amount"],
                    "normalization_flag": "currency",
                }
            ],
            "relationships": [
                {
                    "target_entity": "silver_s4h_sd_customer_master",
                    "relationship_type": "many_to_one",
                    "semantic_label": "sold_to",
                    "traversal_cost": 1.0,
                }
            ],
            "normalization": {
                "currency": {
                    "currency_field": "WAERK",
                    "amount_fields": ["net_value"],
                    "target_currency": "USD",
                }
            },
        },
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    nv = next(f for f in node["fields"] if f["name"] == "net_value")
    assert nv["synonyms"] == ["revenue", "amount"]
    assert nv["normalization_flag"] == "currency"
    assert any(r["target_entity"] == "silver_s4h_sd_customer_master" for r in node["relationships"])
    assert node["normalization"]["currency"]["target_currency"] == "USD"


def test_update_yaml_field_enrichment_tracked(viz_client):
    resp = viz_client.put(
        f"/v1/viz/yamls/{BRONZE_ID}",
        json={
            "author_name": "Admin",
            "author_email": "admin@example.com",
            "fields": [{"name": "NETWR", "alias": "net_revenue"}],
        },
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    netwr = next(f for f in node["fields"] if f["name"] == "NETWR")
    assert netwr["alias"] == "net_revenue"
    assert "NETWR" in node["meta"]["field_enrichments"]


def test_update_yaml_404(viz_client):
    resp = viz_client.put(
        "/v1/viz/yamls/nope",
        json={"author_name": "x", "author_email": "x@y.com", "description": "z"},
    )
    assert resp.status_code == 404


# ── history / diff / restore round trip ──────────────────────────────────────────


def test_history_diff_and_restore_round_trip(viz_client):
    # Capture the seed (oldest) SHA before any edit.
    hist0 = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/history").json()
    seed_sha = hist0["commits"][-1]["sha"]

    # Make an edit → new commit.
    viz_client.put(
        f"/v1/viz/yamls/{SILVER_ID}",
        json={
            "author_name": "Admin",
            "author_email": "admin@example.com",
            "description": "EDITED description",
        },
    )
    hist1 = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/history").json()
    head_sha = hist1["commits"][0]["sha"]
    assert head_sha != seed_sha

    # Diff seed → head must mention the new description.
    diff = viz_client.get(
        f"/v1/viz/yamls/{SILVER_ID}/diff",
        params={"from_sha": seed_sha, "to_sha": head_sha},
    ).json()
    assert "EDITED description" in diff["unified_diff"]

    # Snapshot at seed SHA still has the original description.
    at_seed = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/history/{seed_sha}").json()
    assert at_seed["description"] == "Sales order Silver entity"

    # Restore to seed → live file reverts.
    restored = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/restore/{seed_sha}",
        json={"author_email": "admin@example.com", "reason": "rollback"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["description"] == "Sales order Silver entity"

    # restore created its own commit
    hist2 = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/history").json()
    assert hist2["commits"][0]["message"].startswith(f"restore({SILVER_ID})")


def test_get_yaml_at_invalid_sha_422(viz_client):
    resp = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/history/deadbeefdeadbeef")
    assert resp.status_code == 422


def test_diff_with_last_publish_when_never_published(viz_client):
    """Pass F: an entity with no prior publish event returns
    ``last_publish_sha=None`` and an empty diff. The UI uses this to render
    'Never published yet' instead of a misleading empty change set."""
    resp = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/diff-with-last-publish")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["yaml_id"] == SILVER_ID
    assert body["last_publish_sha"] is None
    assert body["unified_diff"] == ""


def test_diff_with_last_publish_after_publish_then_edit(viz_client, viz_repo):
    """Pass F end-to-end: simulate a publish (empty git commit), then make
    a workspace edit. The endpoint must return the publish SHA and a diff
    that contains the edited field."""
    from ask_admin_api.application.git_service import GitService

    # Simulate a publish event identical to what /admin/yaml/index/{id}
    # records on a successful publish.
    git = GitService(repo_root=str(viz_repo))
    publish_sha = git.empty_commit(
        message=f"publish({SILVER_ID}): indexed by admin@example.com",
        author_name="admin",
        author_email="admin@example.com",
    )
    assert publish_sha is not None

    # Edit the workspace YAML — diff vs last publish must surface this change.
    viz_client.put(
        f"/v1/viz/yamls/{SILVER_ID}",
        json={
            "author_name": "admin",
            "author_email": "admin@example.com",
            "description": "POST-PUBLISH description",
        },
    )

    resp = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/diff-with-last-publish")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_publish_sha"] == publish_sha
    assert "POST-PUBLISH description" in body["unified_diff"]


def test_history_pagination(viz_client):
    # Generate several commits.
    for i in range(3):
        viz_client.put(
            f"/v1/viz/yamls/{SILVER_ID}",
            json={
                "author_name": "Admin",
                "author_email": "admin@example.com",
                "description": f"rev {i}",
            },
        )
    page1 = viz_client.get(
        f"/v1/viz/yamls/{SILVER_ID}/history", params={"page": 1, "per_page": 2}
    ).json()
    assert len(page1["commits"]) == 2
    assert page1["has_more"] is True

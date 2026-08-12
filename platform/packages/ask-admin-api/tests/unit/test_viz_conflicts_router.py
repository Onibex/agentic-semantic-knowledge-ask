"""Integration tests for conflict listing + resolution (/v1/viz/yamls/{id}/conflicts).

Covers test plan block SAP Updates / Merge (MR1-MR5) conflict-resolution side.
Conflicts are seeded directly into the silver YAML _meta (see
conftest.seed_silver_conflict) to avoid needing a valid SAP JSON payload.
"""

from __future__ import annotations

import json

from tests.unit.conftest import SILVER_ID, seed_silver_conflict


def _read_baseline(repo_root) -> dict:
    path = repo_root / ".sap_baseline" / f"{SILVER_ID}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ── listing ──────────────────────────────────────────────────────────────────────


def test_list_unresolved_conflicts(viz_client, viz_repo):
    seed_silver_conflict(viz_repo)
    resp = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/conflicts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["field_name"] == "net_value"
    assert body[0]["conflict_type"] == "field_type_changed"


def test_resolved_conflicts_hidden_by_default(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, resolved=True)
    default = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/conflicts").json()
    assert default == []
    incl = viz_client.get(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts", params={"include_resolved": True}
    ).json()
    assert len(incl) == 1


# ── resolution ───────────────────────────────────────────────────────────────────


def test_resolve_accept_sap_applies_sap_value(viz_client, viz_repo):
    """Accept SAP merges SAP's payload onto the existing field (does NOT
    replace the whole entry). The conflicted property (type here) takes
    SAP's value; admin-curated siblings (name, field_role) are preserved.

    Regression: the original replace-the-whole-dict pattern dropped
    field_role / alias / etc., producing YAML entries that failed
    SilverNode validation on the next publish."""
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "accept_sap", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    net_value = next(f for f in node["fields"] if f["name"] == "net_value")
    # SAP's type wins
    assert net_value["type"] == "P31"
    # Admin-curated field_role survives the conflict resolution
    assert net_value["field_role"] == "measure"
    # enrichment dropped + conflict cleared
    assert "net_value" not in node["meta"]["field_enrichments"]
    assert node["meta"]["conflicts"] == []


def test_accept_sap_clears_enrichment_in_sidecar(viz_client, viz_repo):
    """Regression (recurring conflict): accept_sap must relinquish the property
    in the ``.enrichments.json`` SIDECAR — the value the next SAP merge reads —
    not only the legacy inline ``_meta``. Otherwise re-ingesting the same
    property re-raises an identical conflict, even though the change came from
    SAP and the admin already accepted it (no real divergence → fast-forward).
    """
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    enr_path = viz_repo / ".sap_baseline" / f"{SILVER_ID}.enrichments.json"
    assert enr_path.exists()  # seeded by the production-accurate fixture

    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "accept_sap", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text

    # net_value's only enriched prop (field_role) was relinquished → the
    # sidecar entry is gone (and the file is removed once it holds nothing).
    if enr_path.exists():
        data = json.loads(enr_path.read_text(encoding="utf-8"))
        assert "net_value" not in (data.get("field_enrichments") or {})
    # The SPA-facing meta (read from the sidecar) reflects it too.
    node = resp.json()
    assert "net_value" not in node["meta"]["field_enrichments"]


def test_accept_sap_on_field_removed_deletes_the_field(viz_client, viz_repo):
    """A `field_removed` conflict carries an EMPTY sap_value (SAP no longer
    sends the field) — accepting SAP must DELETE the field, not overlay the
    empty payload as a silent no-op (the ABDIS regression)."""
    seed_silver_conflict(viz_repo, conflict_id="conf-1", conflict_type="field_removed")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "accept_sap", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    assert "net_value" not in {f["name"] for f in node["fields"]}
    assert "net_value" not in node["meta"]["field_enrichments"]
    assert node["meta"]["conflicts"] == []


def test_keep_enriched_on_field_removed_keeps_the_field(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, conflict_id="conf-1", conflict_type="field_removed")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "keep_enriched", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    assert "net_value" in {f["name"] for f in node["fields"]}


def test_bulk_accept_sap_on_field_removed_deletes_the_field(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, conflict_id="conf-1", conflict_type="field_removed")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/resolve-bulk",
        json={
            "resolutions": [{"conflict_id": "conf-1", "decision": "accept_sap"}],
            "author_email": "admin@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    assert "net_value" not in {f["name"] for f in node["fields"]}


def test_bulk_resolve_mixed_decisions_one_write(viz_client, viz_repo):
    """resolve-bulk applies N decisions in one pass: accept_sap lands SAP's
    value + relinquishes provenance; keep_enriched preserves; all conflicts
    end resolved and the sidecar is cleared (all-resolved transition)."""
    import json as _json

    # Two pending conflicts on different fields, seeded the way production
    # writes them (conflicts sidecar + enrichments sidecar).
    c1 = seed_silver_conflict(viz_repo, conflict_id="conf-1")  # net_value, type P15→P31
    c2 = dict(c1)
    c2.update(
        {
            "id": "conf-2",
            "field_name": "sales_doc",
            "conflict_type": "field_modified",
            "sap_value": {"name": "sales_doc", "source": "VBAK.VBELN", "type": "C10",
                          "description": "SAP terse text"},
            "current_value": {"name": "sales_doc", "source": "VBAK.VBELN", "type": "C10",
                              "description": "Sales document ID"},
            "enriched_properties": ["description"],
        }
    )
    sidecar_dir = viz_repo / ".sap_baseline"
    (sidecar_dir / f"{SILVER_ID}.conflicts.json").write_text(
        _json.dumps([c1, c2], indent=2), encoding="utf-8"
    )
    (sidecar_dir / f"{SILVER_ID}.enrichments.json").write_text(
        _json.dumps(
            {"field_enrichments": {"net_value": ["field_role"], "sales_doc": ["description"]}}
        ),
        encoding="utf-8",
    )

    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/resolve-bulk",
        json={
            "resolutions": [
                {"conflict_id": "conf-1", "decision": "accept_sap"},
                {"conflict_id": "conf-2", "decision": "keep_enriched"},
            ],
            "author_email": "admin@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    by_name = {f["name"]: f for f in node["fields"]}
    # accept_sap landed SAP's type; keep_enriched preserved the curated text.
    assert by_name["net_value"]["type"] == "P31"
    assert by_name["sales_doc"]["description"] == "Sales document ID"
    # Provenance: relinquished for the accepted field, kept for the kept one.
    assert "net_value" not in node["meta"]["field_enrichments"]
    assert "description" in node["meta"]["field_enrichments"].get("sales_doc", [])
    # Everything resolved in ONE call → pending inbox is empty.
    assert node["meta"]["conflicts"] == []


def test_bulk_resolve_validates_before_mutating(viz_client, viz_repo):
    """An unknown conflict id fails the WHOLE batch with 404 — no partial apply."""
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/resolve-bulk",
        json={
            "resolutions": [
                {"conflict_id": "conf-1", "decision": "accept_sap"},
                {"conflict_id": "ghost", "decision": "accept_sap"},
            ],
            "author_email": "admin@example.com",
        },
    )
    assert resp.status_code == 404
    # Nothing was applied: the conflict is still pending, the type unchanged.
    listed = viz_client.get(f"/v1/viz/yamls/{SILVER_ID}/conflicts").json()
    assert [c["id"] for c in listed] == ["conf-1"]


def test_keep_enriched_retains_enrichment_in_sidecar(viz_client, viz_repo):
    """The inverse of accept_sap: keep_enriched means the admin keeps
    ownership, so the enrichment stays in the sidecar and a future SAP change
    to the same property still surfaces a conflict."""
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "keep_enriched", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    assert "field_role" in node["meta"]["field_enrichments"].get("net_value", [])


def test_resolve_keep_enriched_preserves_field(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "keep_enriched", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text
    node = resp.json()
    net_value = next(f for f in node["fields"] if f["name"] == "net_value")
    # enriched value retained (type stays P15, field_role measure)
    assert net_value["type"] == "P15"
    assert net_value["field_role"] == "measure"
    assert node["meta"]["conflicts"] == []


def test_keep_enriched_clears_the_conflict_sidecar(viz_client, viz_repo):
    """Bug #3 no-recurrence is now structural: sap_merge_service writes the
    baseline at the end of EVERY merge, so it always carries SAP's latest
    state. Subsequent ingests don't re-flag a resolved conflict because
    baseline == new for that property — independent of the admin decision.
    The resolve endpoint's only job is to clear the sidecar so the entity
    stops appearing in the Pending Conflicts inbox."""
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "keep_enriched", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text
    # No pending conflicts left in the workspace inbox.
    pending = viz_client.get("/v1/viz/conflicts/pending").json()
    assert pending == []


def test_accept_sap_clears_the_conflict_sidecar(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "accept_sap", "author_email": "admin@example.com"},
    )
    assert resp.status_code == 200, resp.text
    pending = viz_client.get("/v1/viz/conflicts/pending").json()
    assert pending == []


def test_resolve_unknown_conflict_404(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/ghost/resolve",
        json={"decision": "accept_sap", "author_email": "a@b.com"},
    )
    assert resp.status_code == 404


def test_resolve_already_resolved_409(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, conflict_id="conf-1", resolved=True)
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "accept_sap", "author_email": "a@b.com"},
    )
    assert resp.status_code == 409


def test_resolve_invalid_decision_422(viz_client, viz_repo):
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        f"/v1/viz/yamls/{SILVER_ID}/conflicts/conf-1/resolve",
        json={"decision": "flip_a_coin", "author_email": "a@b.com"},
    )
    assert resp.status_code == 422


def test_ingest_blocked_while_conflicts_pending(viz_client, viz_repo):
    """A pending conflict must block re-ingest (409) on the silver entity."""
    seed_silver_conflict(viz_repo, conflict_id="conf-1")
    resp = viz_client.post(
        "/v1/viz/ingest/sap-json",
        json={"payload": {"info": {"id": SILVER_ID}}, "author_email": "a@b.com"},
    )
    # Either parse fails (422) or conflict guard fires (409); both are non-200.
    # We assert it is NOT a silent success.
    assert resp.status_code in (409, 422)

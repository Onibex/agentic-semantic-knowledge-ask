"""Router tests for /v1/ingest/* — X-API-Key M2M endpoint.

Pass B (2026-05): the machine endpoint now routes through the SAME merge
service as /v1/viz/ingest/sap-json. There is no longer a "direct to
catalog" Kafka path that bypasses governance — every SAP push lands as
draft, surfaces conflicts on enriched fields, and waits for a human to
promote + publish. This test file covers:

* Auth matrix (missing / wrong / unconfigured / valid).
* First-ingest creates Silver + Bronze as draft (workspace fixture).
* Pre-existing entity → merge flow auto-applies safe field changes.
* Idempotency-Key dedupes retries within the TTL window.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Repo

# ── SAP JSON fixture (shape mirrors what SapJsonParser/SapRootSchema expects)
# We exercise the real parser, not a mock, so first-ingest produces real
# domain nodes written to the workspace as draft YAMLs.
_SAP_PAYLOAD = {
    "entity": "sales_order",
    "info": {
        "id": 100,
        "domainv": "ORDER TO CASH",
        "type": "T",
        "description": "Sales order header — net values per document",
        "tag2": "s4h",
        "tag3": "100",
        "version": "1",
    },
    "dataprodclass": {"mmodule": "SD"},
    "columns": [
        {
            "tabname": "VBAK",
            "alias_tabname": "order_header",
            "fldname": "VBELN",
            "alias_fldname": "sales_doc",
            "key_field": "X",
            "inttype": "C",
            "leng": 10,
            "description_field": "Sales doc number",
        },
        {
            "tabname": "VBAK",
            "alias_tabname": "order_header",
            "fldname": "NETWR",
            "alias_fldname": "net_value",
            "key_field": "",
            "inttype": "P",
            "leng": 15,
            "description_field": "Net order value",
        },
    ],
    "relations": [],
}


@pytest.fixture
def m2m_client(tmp_path: Path, monkeypatch):
    """TestClient pointed at a temp workspace + git repo, with API-key auth."""
    repo_root = tmp_path
    workspace = repo_root / "workspace" / "ask"
    workspace.mkdir(parents=True)

    repo = Repo.init(repo_root)
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    # Empty commit so iter_commits works
    seed = workspace / ".keep"
    seed.write_text("")
    repo.index.add(["workspace/ask/.keep"])
    repo.index.commit("seed: empty workspace")

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("ASK_INGEST_API_KEY", "secret-key-123")
    monkeypatch.setenv("WORKSPACE_PATH", str(workspace))
    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("BASELINE_PATH", ".sap_baseline")

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.routers import ingest as ingest_router

    ingest_router._yaml_svc = None
    ingest_router._git_svc = None
    ingest_router._idempotency_cache.clear()

    from ask_admin_api.main import app

    yield TestClient(app), repo_root, workspace

    ingest_router._yaml_svc = None
    ingest_router._git_svc = None
    ingest_router._idempotency_cache.clear()
    get_settings.cache_clear()


# ── Auth matrix ─────────────────────────────────────────────────────────────


def test_missing_api_key_returns_401(m2m_client):
    cli, _, _ = m2m_client
    resp = cli.post("/v1/ingest/sap-json", json={"data": _SAP_PAYLOAD})
    assert resp.status_code == 401
    assert "Invalid API key" in resp.json()["detail"]


def test_wrong_api_key_returns_401(m2m_client):
    cli, _, _ = m2m_client
    resp = cli.post(
        "/v1/ingest/sap-json",
        json={"data": _SAP_PAYLOAD},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_api_key_not_configured_returns_503(tmp_path, monkeypatch):
    """If ASK_INGEST_API_KEY is missing in env, the endpoint must 503 (not
    401) so Kafka Connect retries instead of dropping the message."""
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("ASK_INGEST_API_KEY", raising=False)
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()
    from ask_admin_api.main import app

    cli = TestClient(app)

    resp = cli.post(
        "/v1/ingest/sap-json",
        json={"data": _SAP_PAYLOAD},
        headers={"X-API-Key": "anything"},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()
    get_settings.cache_clear()


# ── Merge flow ─────────────────────────────────────────────────────────────


def test_valid_api_key_first_ingest_creates_workspace_files(m2m_client):
    """First-ingest writes the Silver + Bronze YAMLs to the workspace and
    seeds the baseline so the next push computes a real diff. The state
    machine was retired — there is nothing further to assert on _meta.state."""
    cli, repo_root, workspace = m2m_client
    resp = cli.post(
        "/v1/ingest/sap-json",
        json={"data": _SAP_PAYLOAD},
        headers={"X-API-Key": "secret-key-123"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["silver_id"] == "silver_s4h_sd_sales_order"
    assert body["conflicts"] == []
    assert body["baseline_updated"] is True

    silver_file = workspace / "s4h" / "silver" / "sd" / "sales_order.yaml"
    bronze_file = workspace / "s4h" / "bronze" / "vbak.yaml"
    assert silver_file.exists()
    assert bronze_file.exists()

    baseline = repo_root / ".sap_baseline" / "silver_s4h_sd_sales_order.json"
    assert baseline.exists()
    baseline_data = json.loads(baseline.read_text(encoding="utf-8"))
    assert baseline_data["silver_id"] == "silver_s4h_sd_sales_order"


def test_idempotency_key_dedupes_repeat_calls(m2m_client):
    """Repeating the same Idempotency-Key inside the TTL window must return
    the cached MergeResult instead of re-running the merge — Kafka Connect
    retries do not duplicate work."""
    cli, _, _ = m2m_client
    headers = {"X-API-Key": "secret-key-123", "Idempotency-Key": "trace-abc-123"}
    first = cli.post("/v1/ingest/sap-json", json={"data": _SAP_PAYLOAD}, headers=headers)
    assert first.status_code == 200
    second = cli.post("/v1/ingest/sap-json", json={"data": _SAP_PAYLOAD}, headers=headers)
    assert second.status_code == 200
    # Same payload identity-shaped response on retry.
    assert second.json() == first.json()


def test_edit_in_full_enrichment_then_reingest_raises_conflict(m2m_client):
    """End-to-end regression for the aufpl_afko bug.

    A field enriched via an *edit-in-full* (``fields_full`` — the ONLY path the
    SPA uses for field edits) must be protected on the next SAP push. Before the
    fix the edit-in-full path never recorded provenance, so the re-ingest
    silently auto-applied over the curated value; now it parks a conflict.
    """
    from ask_admin_api.models.viz_models import VizFieldFull, VizYAMLUpdateRequest
    from ask_admin_api.routers import ingest as ingest_router

    cli, _repo_root, _workspace = m2m_client
    headers = {"X-API-Key": "secret-key-123"}

    # 1. First ingest → Silver created as draft + baseline seeded.
    first = cli.post("/v1/ingest/sap-json", json={"data": _SAP_PAYLOAD}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["conflicts"] == []
    silver_id = first.json()["silver_id"]

    # 2. Enrich the NETWR-backed field via edit-in-full. Rebuild the field list
    #    from what was actually persisted so names/sources match the parser.
    svc = ingest_router._get_yaml_service()
    node = svc.get_yaml(silver_id)
    target = None
    fields_full = []
    for f in node.fields:
        desc = f.description
        if f.source == "VBAK.NETWR":
            desc = "Curated net revenue"  # the enrichment (differs from baseline)
            target = f.name
        fields_full.append(
            VizFieldFull(
                name=f.name,
                source=f.source,
                field_role=f.field_role,
                type=f.type,
                description=desc,
                aggregation_behavior=f.aggregation_behavior,
            )
        )
    assert target is not None
    svc.update_yaml(
        silver_id,
        VizYAMLUpdateRequest(author_email="curator@onibex.com", fields_full=fields_full),
        git_service=ingest_router._get_git_service(),
        author_name="curator",
        author_email="curator@onibex.com",
    )

    # 3. SAP pushes a DIFFERENT description for that same field.
    modified = json.loads(json.dumps(_SAP_PAYLOAD))
    for col in modified["columns"]:
        if col["fldname"] == "NETWR":
            col["description_field"] = "SAP overwrote the description"
    second = cli.post("/v1/ingest/sap-json", json={"data": modified}, headers=headers)
    assert second.status_code == 200, second.text

    # 4. The enriched field is protected → conflict, NOT a silent auto-apply.
    conflicts = second.json()["conflicts"]
    assert conflicts, "enriched field must raise a conflict, not auto-apply"
    conflict = next(c for c in conflicts if c["field_name"] == target)
    assert conflict["conflict_type"] == "field_modified"
    assert "description" in conflict["enriched_properties"]

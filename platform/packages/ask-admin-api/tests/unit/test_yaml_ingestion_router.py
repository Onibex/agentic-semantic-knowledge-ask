"""Router tests for /v1/admin/yaml/* — fake service + reader, no OpenSearch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeDomainResult:
    """Mirrors ask_knowledge_graph.domain.models.IngestionResult enough for the router."""

    entities_indexed: int = 0
    fields_indexed: int = 0
    edges_indexed: int = 0
    error: str | None = None
    entity_id: str | None = None
    raw_stats: dict[str, Any] = field(default_factory=dict)


class _FakeIngestionService:
    def __init__(self) -> None:
        self.last_sap_json: dict | None = None
        self.last_yaml_request: Any = None
        self.last_deleted: str | None = None

    def ingest_sap_json(self, data: dict) -> _FakeDomainResult:
        self.last_sap_json = data
        # Mirror the real service: when the SAP payload produces a Silver,
        # raw_stats carries `silver_entity_id` + `silver_yaml` so the
        # router can cascade to RAG. Toggle via the `_no_silver` marker
        # so individual tests can simulate Bronze-only payloads.
        if data.get("_no_silver"):
            return _FakeDomainResult(
                entities_indexed=1,
                fields_indexed=0,
                edges_indexed=0,
                raw_stats={"entities": 1, "fields": 0, "edges": 0},
            )
        return _FakeDomainResult(
            entities_indexed=2,
            fields_indexed=10,
            edges_indexed=3,
            entity_id="silver_s4h_sd_sales_order",
            raw_stats={
                "entities": 2,
                "fields": 10,
                "edges": 3,
                "silver_entity_id": "silver_s4h_sd_sales_order",
                "silver_yaml": _SILVER_YAML,
            },
        )

    def ingest_yaml(self, request: Any) -> _FakeDomainResult:
        self.last_yaml_request = request
        return _FakeDomainResult(
            entities_indexed=1,
            fields_indexed=4,
            edges_indexed=0,
            entity_id="silver_test",
        )

    def delete_entity(self, entity_id: str) -> _FakeDomainResult:
        self.last_deleted = entity_id
        return _FakeDomainResult(raw_stats={"entities_deleted": 1, "fields_deleted": 7})


@dataclass
class _FakeRagIndexResult:
    indexed: int = 0
    batches_sent: int = 0


@dataclass
class _FakeRagDeleteResult:
    deleted: int = 0


class _FakeRagIndexingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []
        self.delete_calls: list[tuple[str, list[str] | None, list[str] | None]] = []
        self._delete_return = 5

    def index_chunks(self, collection, chunks, *, batch_size=64):
        self.calls.append((collection, list(chunks)))
        return _FakeRagIndexResult(indexed=len(chunks), batches_sent=1)

    def delete_documents(self, collection, source_files=None, entity_ids=None):
        self.delete_calls.append((collection, source_files, entity_ids))
        return _FakeRagDeleteResult(deleted=self._delete_return)


class _FakeReader:
    def get_lightweight_entities(self) -> list[dict]:
        return [
            {"id": "silver_s4h_sd_sales_order", "name": "sales_order", "layer": "silver"},
            {"id": "gold_s4h_sd_sales_performance", "name": "sales_performance", "layer": "gold"},
        ]

    def get_entity_by_id(self, entity_id: str) -> dict | None:
        if entity_id == "silver_s4h_sd_sales_order":
            return {
                "id": entity_id,
                "raw_yaml": "id: silver_...\nlayer: silver\n",
                "layer": "silver",
            }
        return None


@dataclass
class _FakeSummary:
    """Minimal stand-in for VizYAMLSummary (catalog now reads working YAMLs)."""

    id: str
    name: str
    layer: str  # plain string — exercises the str(layer) branch in list_catalog


class _FakeYamlFileService:
    def list_yamls(self, layer: Any = None) -> list[_FakeSummary]:
        return [
            _FakeSummary("silver_s4h_sd_sales_order", "sales_order", "silver"),
            _FakeSummary("gold_s4h_sd_sales_performance", "sales_performance", "gold"),
        ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.routers import yaml_ingestion

    fake_svc = _FakeIngestionService()
    fake_reader = _FakeReader()
    fake_rag = _FakeRagIndexingService()
    yaml_ingestion._service_singleton = fake_svc
    # Per-env reader cache (None = legacy, "dev"/"prod" = env-suffixed). Seed
    # the same fake for every env so /published-ids?env=... + the env=None
    # get_entity path all resolve to the fake.
    yaml_ingestion._reader_singletons.update(
        {None: fake_reader, "dev": fake_reader, "prod": fake_reader}
    )
    yaml_ingestion._rag_service_singleton = fake_rag

    from ask_admin_api.main import app

    yield TestClient(app), fake_svc, fake_reader, fake_rag

    yaml_ingestion._service_singleton = None
    yaml_ingestion._reader_singletons.clear()
    yaml_ingestion._rag_service_singleton = None
    get_settings.cache_clear()


def test_admin_ingest_sap_json_is_deprecated_410(client):
    """Pass B (2026-05): POST /v1/admin/yaml/ingest-sap-json now returns
    410 Gone. Producers must use /v1/viz/ingest/sap-json (JWT) or
    /v1/ingest/sap-json (X-API-Key) so every SAP push routes through
    the merge engine and lands as draft."""
    cli, svc, _, rag = client
    resp = cli.post("/v1/admin/yaml/ingest-sap-json", json={"data": {"x": 1}})
    assert resp.status_code == 410
    detail = resp.json().get("detail", "")
    assert "viz/ingest/sap-json" in detail
    # No side effects: the catalog/RAG fakes must not have been invoked.
    assert svc.last_sap_json is None
    assert rag.calls == []


def test_ingest_yaml_endpoint_is_deprecated_410(client):
    """Pass I (2026-06): direct YAML → OpenSearch path retired. The new
    contract is import → workspace + (separately) Publish → runtime."""
    cli, svc, _, _ = client
    resp = cli.post("/v1/admin/yaml/ingest", json={"yaml_content": "id: x\nlayer: silver\n"})
    assert resp.status_code == 410
    detail = resp.json().get("detail", "")
    assert "import" in detail
    # No side effects on the catalog fake.
    assert svc.last_yaml_request is None


def test_delete_entity_cascades_to_rag(client):
    cli, svc, _, rag = client
    resp = cli.delete("/v1/admin/yaml/silver_s4h_sd_sales_order")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "entities_deleted": 1,
        "fields_deleted": 7,
        "rag_chunks_deleted": 5,
        "error": None,
    }
    assert svc.last_deleted == "silver_s4h_sd_sales_order"
    # Cascade fired on rag_schema with entity_ids filter.
    assert rag.delete_calls == [
        ("rag_schema", None, ["silver_s4h_sd_sales_order"]),
    ]


def test_delete_unpublishes_from_published_envs_prod_first(client, monkeypatch):
    """Tier-1 gap fix: delete must remove the entity from the env-suffixed
    indices the chat reads (via unpublish), prod before dev, so a published
    entity does not stay answerable after a delete. The catalog delete still
    runs afterwards."""
    cli, svc, _, _ = client
    from ask_admin_api.routers import yaml_ingestion

    calls: list[tuple[str, str]] = []

    class _FakePublisher:
        def __init__(self, **_kw):
            pass

        def unpublish(self, entity_id, env, *, by):  # noqa: A002
            calls.append((entity_id, env))

    monkeypatch.setattr(yaml_ingestion, "PublishService", _FakePublisher)

    resp = cli.delete("/v1/admin/yaml/silver_s4h_sd_sales_order")
    assert resp.status_code == 200
    # prod unpublished BEFORE dev (the unpublish gate order)...
    assert calls == [
        ("silver_s4h_sd_sales_order", "prod"),
        ("silver_s4h_sd_sales_order", "dev"),
    ]
    # ...and the catalog delete still ran.
    assert svc.last_deleted == "silver_s4h_sd_sales_order"


def test_delete_skips_unpublish_when_not_published(client, monkeypatch):
    """A not-published env is a no-op (PublishNotReadyError) and must NOT block
    the catalog delete."""
    cli, svc, _, _ = client
    from ask_admin_api.application.lifecycle_service import PublishNotReadyError
    from ask_admin_api.routers import yaml_ingestion

    class _FakePublisher:
        def __init__(self, **_kw):
            pass

        def unpublish(self, entity_id, env, *, by):  # noqa: A002
            raise PublishNotReadyError("not published")

    monkeypatch.setattr(yaml_ingestion, "PublishService", _FakePublisher)

    resp = cli.delete("/v1/admin/yaml/silver_s4h_sd_sales_order")
    assert resp.status_code == 200
    assert svc.last_deleted == "silver_s4h_sd_sales_order"


def test_delete_entity_does_not_fail_when_rag_cascade_explodes(client, monkeypatch):
    """RAG failure must not poison the response — catalog deletion already
    succeeded and is the source of truth."""
    cli, svc, _, rag = client

    def _boom(*_a, **_kw):
        raise RuntimeError("opensearch unreachable")

    monkeypatch.setattr(rag, "delete_documents", _boom)
    resp = cli.delete("/v1/admin/yaml/silver_s4h_sd_sales_order")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entities_deleted"] == 1
    assert body["fields_deleted"] == 7
    assert body["rag_chunks_deleted"] == 0  # cascade failed, count is 0
    assert body["error"] is None


def test_delete_succeeds_when_not_in_registry(client, monkeypatch):
    """Regression: deleting an entity that was never published (registry index
    missing / 'not found' in OpenSearch) must NOT 500 — the catalog/registry
    delete is best-effort. The workspace/lifecycle/business-domain cleanup is
    what actually removes the data product."""
    cli, svc, _, _ = client

    def _boom(_entity_id):
        raise RuntimeError("Entity 'bronze_s4h_vbak_order_header' not found in OpenSearch.")

    monkeypatch.setattr(svc, "delete_entity", _boom)
    resp = cli.delete("/v1/admin/yaml/bronze_s4h_vbak_order_header")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entities_deleted"] == 0  # registry delete skipped, not fatal
    assert body["error"] is None


def test_catalog_lists_working_yamls(client, monkeypatch):
    """Catalog now reads the WORKING YAMLs (curation source of truth), NOT a
    published env index — so unpublished entities are visible."""
    from ask_admin_api.routers import yaml_ingestion

    monkeypatch.setattr(yaml_ingestion, "_yaml_file_service", lambda: _FakeYamlFileService())

    cli, _, _, _ = client
    resp = cli.get("/v1/admin/yaml/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entities"]) == 2
    ids = {e["id"] for e in body["entities"]}
    assert "silver_s4h_sd_sales_order" in ids
    assert "gold_s4h_sd_sales_performance" in ids
    # layer carried through as a plain string for the list payload.
    assert {e["layer"] for e in body["entities"]} == {"silver", "gold"}


def test_published_ids_is_env_aware(client):
    """/published-ids reads the env-suffixed registry (a deployment query).
    A valid env resolves to its reader; a bad env is a 400."""
    cli, _, _, _ = client

    resp = cli.get("/v1/admin/yaml/published-ids", params={"env": "dev"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["env"] == "dev"
    assert set(body["ids"]) == {
        "silver_s4h_sd_sales_order",
        "gold_s4h_sd_sales_performance",
    }

    # No env → legacy un-suffixed registry (env reported as null).
    resp_legacy = cli.get("/v1/admin/yaml/published-ids")
    assert resp_legacy.status_code == 200
    assert resp_legacy.json()["env"] is None

    # Unknown env → 400 (not a silent empty list).
    resp_bad = cli.get("/v1/admin/yaml/published-ids", params={"env": "staging"})
    assert resp_bad.status_code == 400


def test_get_entity_returns_full_doc_when_found(client):
    cli, _, _, _ = client
    resp = cli.get("/v1/admin/yaml/silver_s4h_sd_sales_order")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["entity"]["raw_yaml"].startswith("id: silver_")


def test_get_entity_returns_not_found_for_missing_id(client):
    cli, _, _, _ = client
    resp = cli.get("/v1/admin/yaml/does_not_exist")
    assert resp.status_code == 200  # 200 + found=False is the contract
    body = resp.json()
    assert body["found"] is False
    assert body["entity"] is None


# ─────────────────────────────────────────────────────────────────────────────
# /v1/admin/yaml/ingest-full — unified catalog + RAG indexing
# ─────────────────────────────────────────────────────────────────────────────
_SILVER_YAML = """\
id: silver_s4h_sd_sales_order
layer: silver
version: '1'
source_system: s4h
source_system_no: 100
business_process: ORDER TO CASH
module: SD
name: sales_order
classification: T
description: Sales order test fixture
entity_role: fact
grain:
  entity_grain: [VBELN]
  business_grain: sales_order
composed_of: [bronze_s4h_vbak_order_header]
fields:
- name: vbeln
  source: VBAK.VBELN
  field_role: identifier
  type: C10
  description: Sales doc
- name: net_value
  source: VBAK.NETWR
  field_role: measure
  type: P15
  description: Net order value
"""


_BRONZE_YAML = """\
id: bronze_s4h_vbak_order_header
layer: bronze
version: '1'
source_system: s4h
source_system_id: 100
name: VBAK
alias: ORDER_HEADER
description: Sales doc header
primary_key: [VBELN]
fields:
  VBELN: { type: C10, alias: sales_doc, key_field: true, description: Sales doc number }
  NETWR: { type: P15, alias: net_value, key_field: false, description: Net value }
"""


def test_ingest_full_endpoint_is_deprecated_410(client):
    cli, _, _, rag = client
    resp = cli.post(
        "/v1/admin/yaml/ingest-full",
        json={"yaml_content": _SILVER_YAML, "also_index_rag": True},
    )
    assert resp.status_code == 410
    assert "import" in resp.json().get("detail", "")
    assert rag.calls == []  # nothing got pushed downstream


# ─────────────────────────────────────────────────────────────────────────────
# Pass I — POST /v1/admin/yaml/import (workspace-only write)
# ─────────────────────────────────────────────────────────────────────────────

# Standalone valid Silver — uses real SilverNode schema (id pattern enforced).
_IMPORT_SILVER_YAML = """\
id: silver_s4h_sd_imported_entity
internal_id: s4h_100_999
layer: silver
version: '1'
source_system: s4h
source_system_no: 100
business_process: ORDER TO CASH
module: SD
name: imported_entity
classification: T
description: Imported via the Pass I workspace endpoint
entity_role: fact
grain:
  entity_grain: [VBELN]
  business_grain: imported_entity_item
composed_of: [bronze_s4h_vbak_order_header]
fields:
- name: net_value
  source: VBAK.NETWR
  field_role: measure
  type: P15
  description: Net order value
"""


@pytest.fixture
def import_client(tmp_path, monkeypatch):
    """TestClient pointed at an empty temp workspace — needed because
    /import writes a file to disk and the test inspects what was written."""
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    ws = tmp_path / "ws" / "ask"
    ws.mkdir(parents=True)
    monkeypatch.setenv("WORKSPACE_PATH", str(ws))
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.main import app

    yield TestClient(app), tmp_path, ws
    get_settings.cache_clear()


def test_import_new_yaml_writes_file_and_no_runtime_write(import_client):
    cli, repo_root, ws = import_client
    resp = cli.post(
        "/v1/admin/yaml/import",
        json={"yaml_content": _IMPORT_SILVER_YAML, "force": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entity_id"] == "silver_s4h_sd_imported_entity"
    assert body["layer"] == "silver"
    assert body["overwritten"] is False

    target = ws / "s4h" / "silver" / "sd" / "imported_entity.yaml"
    assert target.exists()
    # Workspace-only — no OpenSearch calls (we never injected a KG fake).


def test_import_existing_yaml_rejects_409(import_client):
    cli, _, ws = import_client
    # Pre-create the target file.
    target = ws / "s4h" / "silver" / "sd" / "imported_entity.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("id: pre-existing\nlayer: silver\n")

    resp = cli.post(
        "/v1/admin/yaml/import",
        json={"yaml_content": _IMPORT_SILVER_YAML, "force": False},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json().get("detail", "")
    # File NOT overwritten.
    assert target.read_text().startswith("id: pre-existing")


def test_import_existing_yaml_with_force_overwrites(import_client):
    cli, _, ws = import_client
    target = ws / "s4h" / "silver" / "sd" / "imported_entity.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("id: pre-existing\nlayer: silver\n")

    resp = cli.post(
        "/v1/admin/yaml/import",
        json={"yaml_content": _IMPORT_SILVER_YAML, "force": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["overwritten"] is True
    # File now contains the imported content (carries description from the import).
    body = target.read_text()
    assert "imported_entity" in body
    assert "Pass I" in body


def test_import_invalid_yaml_422(import_client):
    cli, _, _ = import_client
    resp = cli.post(
        "/v1/admin/yaml/import",
        json={"yaml_content": "this is not yaml -- {broken", "force": False},
    )
    assert resp.status_code == 422


def test_import_missing_layer_422(import_client):
    cli, _, _ = import_client
    resp = cli.post(
        "/v1/admin/yaml/import",
        json={"yaml_content": "id: x\nname: x\nsource_system: s4h\n", "force": False},
    )
    assert resp.status_code == 422
    assert "layer" in resp.json().get("detail", "").lower()


# ── §7.1 DDL pre-validator (400 before the LLM is ever called) ─────────────────


def test_ddl_import_rejects_non_ddl_400_without_llm(client, monkeypatch):
    """Garbage input is rejected at the pre-validator — the LLM is never built."""
    cli = client[0]
    from ask_admin_api.application import ddl_import_service as ddl_mod

    def _boom(*_a, **_k):  # would raise if the route reached the LLM
        raise AssertionError("generate_yaml must not be called on invalid DDL")

    monkeypatch.setattr(ddl_mod.DdlImportService, "generate_yaml", _boom)
    resp = cli.post(
        "/v1/admin/yaml/import/ddl",
        json={"ddl": "what is the weather?", "layer": "bronze", "source_system": "s4h"},
    )
    assert resp.status_code == 400
    assert "create table" in resp.json().get("detail", "").lower()


def test_ddl_import_rejects_bad_layer_400(client):
    cli = client[0]
    resp = cli.post(
        "/v1/admin/yaml/import/ddl",
        json={"ddl": "CREATE TABLE X (a int);", "layer": "metric", "source_system": "s4h"},
    )
    assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Publish workspace → index (bulk + per-entity, state-gated)
# ─────────────────────────────────────────────────────────────────────────────
_WS_SILVER_YAML = """\
id: silver_s4h_sd_sales_order
layer: silver
module: sd
name: sales_order
entity_role: fact
composed_of: [bronze_s4h_vbak_order_header]
fields:
- name: net_value
  source: VBAK.NETWR
  field_role: measure
  type: P15
  description: Net order value
"""

_WS_DIMENSION_YAML = """\
id: silver_s4h_sd_draft_entity
layer: silver
module: sd
name: draft_entity
entity_role: dimension
composed_of: [bronze_x]
fields:
- name: x
  source: T.X
  field_role: dimension
  type: C1
  description: x
"""

# Bronze referenced by the Silver — needed for cascade tests.
_WS_BRONZE_YAML = """\
id: bronze_s4h_vbak_order_header
layer: bronze
source_system: s4h
name: VBAK
alias: ORDER_HEADER
description: Sales doc header
primary_key: [VBELN]
fields:
  VBELN: { type: C10, alias: sales_doc, key_field: true, description: Sales doc }
  NETWR: { type: P15, alias: net_value, key_field: false, description: Net value }
"""

# A Silver pointing at an entity that does NOT exist in the workspace — the
# cascade must surface that as a warning.
_WS_REL_ORPHAN_YAML = """\
id: silver_s4h_sd_with_rel
layer: silver
module: sd
name: with_rel
entity_role: dimension
composed_of: []
fields:
- name: y
  source: T.Y
  field_role: dimension
  type: C1
  description: y
relationships:
- target_entity: silver_s4h_sd_does_not_exist
  relationship_type: many_to_one
  join_condition: "X.y = D.y"
  semantic_label: orphan_link
  traversal_cost: 1.5
  cross_module: false
  description: Points at a missing entity to exercise the warning path
"""


@pytest.fixture
def ws_client(tmp_path, monkeypatch):
    """TestClient pointed at a temp workspace, with the KG service + RAG mocked.

    Layout:
      sales_order.yaml   — silver, composed_of bronze (drives the cascade test)
      vbak.yaml          — bronze referenced by sales_order
      dimension.yaml     — another silver, no references (kept for index_workspace
                           layer-filter tests)
      with_rel.yaml      — silver with a relationship to a missing entity (drives
                           the orphan-reference warning test)
    """
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")

    ws = tmp_path / "ws" / "ask"
    ws.mkdir(parents=True)
    (ws / "sales_order.yaml").write_text(_WS_SILVER_YAML, encoding="utf-8")
    (ws / "vbak.yaml").write_text(_WS_BRONZE_YAML, encoding="utf-8")
    (ws / "dimension.yaml").write_text(_WS_DIMENSION_YAML, encoding="utf-8")
    (ws / "with_rel.yaml").write_text(_WS_REL_ORPHAN_YAML, encoding="utf-8")
    monkeypatch.setenv("WORKSPACE_PATH", str(ws))
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.routers import yaml_ingestion

    fake_svc = _FakeIngestionService()
    fake_rag = _FakeRagIndexingService()
    yaml_ingestion._service_singleton = fake_svc
    yaml_ingestion._rag_service_singleton = fake_rag

    from ask_admin_api.main import app

    yield TestClient(app), fake_svc, fake_rag

    yaml_ingestion._service_singleton = None
    yaml_ingestion._rag_service_singleton = None
    get_settings.cache_clear()


def test_index_workspace_publishes_everything_by_default(ws_client):
    cli, _svc, _rag = ws_client
    resp = cli.post("/v1/admin/yaml/index-workspace", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert body["indexed"] == 4
    assert body["skipped"] == 0
    assert body["layers"] == []  # no layer filter when none requested


def test_index_workspace_layer_filter_restricts_targets(ws_client):
    """The optional layers filter lets the bulk action publish only Silvers
    (the per-entity cascade still pulls in their composed_of Bronces)."""
    cli, _svc, _rag = ws_client
    resp = cli.post("/v1/admin/yaml/index-workspace", json={"layers": ["silver"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["indexed"] == 3  # three silvers
    assert body["skipped"] == 1  # the bronze got skipped
    assert body["layers"] == ["silver"]


def test_index_entity_reads_workspace_file(ws_client):
    cli, _svc, _rag = ws_client
    resp = cli.post("/v1/admin/yaml/index/silver_s4h_sd_sales_order")
    assert resp.status_code == 200, resp.text
    assert resp.json()["entities_indexed"] >= 1


def test_index_entity_404_for_unknown_id(ws_client):
    cli, _svc, _rag = ws_client
    resp = cli.post("/v1/admin/yaml/index/does_not_exist")
    assert resp.status_code == 404


def test_index_entity_cascades_composed_of_bronzes(ws_client):
    """Publishing a Silver also publishes its composed_of Bronces so the
    runtime join graph has no dead edges."""
    cli, _svc, _rag = ws_client
    resp = cli.post("/v1/admin/yaml/index/silver_s4h_sd_sales_order")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cascade_indexed"] == ["bronze_s4h_vbak_order_header"]
    assert body["entities_indexed"] >= 2  # silver + its cascade
    assert body["cascade_warnings"] == []


def test_index_entity_warns_when_relationship_target_missing_from_workspace(ws_client):
    """Relationship targets that don't exist in the workspace surface as
    cascade_warnings — the publish itself still succeeds."""
    cli, _svc, _rag = ws_client
    resp = cli.post("/v1/admin/yaml/index/silver_s4h_sd_with_rel")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    warnings = body["cascade_warnings"]
    assert any("silver_s4h_sd_does_not_exist" in w for w in warnings)

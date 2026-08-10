"""OpenSearch CRUD for Workspaces, Business Domains, and Organization.

Three indices, all dedicated to the hierarchy. Entity registry indices
(``ask-entity-registry-v1`` etc.) are NOT touched — workspaces reference
entities by ID only.

Index design:
  ask-workspaces-v1        — doc id = workspace UUID
  ask-business-domains-v1  — doc id = BD UUID; ``workspace_id`` for filtering
  ask-organization-v1      — doc id = "default" (singleton)

``BusinessDomain`` was formerly ``DataProduct`` and its index was
``ask-data-products-v1``; both renamed in the UX_CHANGES audit (Iter 1). The
membership field ``entity_ids`` became ``data_product_ids``. Pre-prod, so no
migration — the new index is created fresh (audit Q2).

Concurrency model:
  * Slug uniqueness is checked in the service layer with a search-then-write
    pattern. There's a tiny TOCTOU race window for two simultaneous creates
    with the same slug; the second one would land. Acceptable for the
    "10 workspaces, one admin at a time" volume we target.
  * Cascade delete is performed by the service (this repo only deletes one
    doc at a time + provides ``list_business_domains_by_workspace``).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from ..models.workspaces import (
    BusinessDomain,
    Organization,
    Workspace,
)

logger = logging.getLogger(__name__)


INDEX_WORKSPACES = "ask-workspaces-v1"
INDEX_BUSINESS_DOMAINS = "ask-business-domains-v1"
INDEX_ORGANIZATION = "ask-organization-v1"

ORGANIZATION_ID = "default"  # singleton


# ── Index mappings ──────────────────────────────────────────────────────────


_WORKSPACES_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "slug": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "objective": {"type": "text"},
            "description": {"type": "text"},
            "roles": {
                "type": "nested",
                "properties": {
                    "email": {"type": "keyword"},
                    "role": {"type": "keyword"},
                },
            },
            "created_at": {"type": "keyword"},
            "created_by": {"type": "keyword"},
            "updated_at": {"type": "keyword"},
            "updated_by": {"type": "keyword"},
        }
    }
}

_BUSINESS_DOMAINS_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "workspace_id": {"type": "keyword"},
            "slug": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "description": {"type": "text"},
            "data_product_ids": {"type": "keyword"},
            "created_at": {"type": "keyword"},
            "created_by": {"type": "keyword"},
            "updated_at": {"type": "keyword"},
            "updated_by": {"type": "keyword"},
        }
    }
}

_ORGANIZATION_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "company_name": {"type": "text"},
            "source_system": {"type": "keyword"},
            "sap_version": {"type": "keyword"},
            "core_bases": {"type": "keyword"},
            "url": {"type": "keyword"},
            "updated_at": {"type": "keyword"},
            "updated_by": {"type": "keyword"},
        }
    }
}


# ── Repository ──────────────────────────────────────────────────────────────


class WorkspaceRepository:
    """OpenSearch CRUD for the hierarchy. Reads connection from settings.json."""

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client or _build_client()
        # Don't crash if OpenSearch is down at boot — let the first request
        # report a clear error. Index creation is lazy.
        self._indices_ensured = False

    # ── Index lifecycle ─────────────────────────────────────────────────────

    def ensure_indices(self) -> None:
        """Create the three indices if they don't exist. Idempotent."""
        if self._indices_ensured:
            return
        for name, mapping in (
            (INDEX_WORKSPACES, _WORKSPACES_MAPPING),
            (INDEX_BUSINESS_DOMAINS, _BUSINESS_DOMAINS_MAPPING),
            (INDEX_ORGANIZATION, _ORGANIZATION_MAPPING),
        ):
            try:
                if not self._client.indices.exists(index=name):
                    self._client.indices.create(index=name, body=mapping)
                    logger.info("Created OpenSearch index %s", name)
            except Exception:
                logger.exception("Failed to ensure index %s", name)
                raise
        self._indices_ensured = True

    # ── Workspaces ──────────────────────────────────────────────────────────

    def list_workspaces(self) -> list[Workspace]:
        self.ensure_indices()
        resp = self._client.search(
            index=INDEX_WORKSPACES,
            body={"query": {"match_all": {}}, "size": 1000, "sort": [{"slug": "asc"}]},
        )
        return [_load_workspace(h["_id"], h["_source"]) for h in resp["hits"]["hits"]]

    def get_workspace(self, ws_id: str) -> Workspace | None:
        self.ensure_indices()
        try:
            doc = self._client.get(index=INDEX_WORKSPACES, id=ws_id)
            return _load_workspace(doc["_id"], doc["_source"])
        except NotFoundError:
            return None

    def get_workspace_by_slug(self, slug: str) -> Workspace | None:
        self.ensure_indices()
        resp = self._client.search(
            index=INDEX_WORKSPACES,
            body={"query": {"term": {"slug": slug}}, "size": 1},
        )
        hits = resp["hits"]["hits"]
        if not hits:
            return None
        return _load_workspace(hits[0]["_id"], hits[0]["_source"])

    def create_workspace(self, body: dict[str, Any]) -> Workspace:
        """``body`` is the full doc (without ``id``). Generates a UUID."""
        self.ensure_indices()
        ws_id = str(uuid.uuid4())
        # refresh=wait_for so a subsequent list_workspaces() sees the doc
        # without a 1-second polling delay — matters for the SPA flow
        # (create → redirect to detail page).
        self._client.index(index=INDEX_WORKSPACES, id=ws_id, body=body, refresh="wait_for")
        return _load_workspace(ws_id, body)

    def update_workspace(self, ws_id: str, body: dict[str, Any]) -> Workspace:
        self.ensure_indices()
        self._client.index(index=INDEX_WORKSPACES, id=ws_id, body=body, refresh="wait_for")
        return _load_workspace(ws_id, body)

    def delete_workspace(self, ws_id: str) -> bool:
        self.ensure_indices()
        try:
            self._client.delete(index=INDEX_WORKSPACES, id=ws_id, refresh="wait_for")
            return True
        except NotFoundError:
            return False

    # ── Business Domains ──────────────────────────────────────────────────────

    def list_business_domains_by_workspace(self, ws_id: str) -> list[BusinessDomain]:
        self.ensure_indices()
        resp = self._client.search(
            index=INDEX_BUSINESS_DOMAINS,
            body={
                "query": {"term": {"workspace_id": ws_id}},
                "size": 1000,
                "sort": [{"slug": "asc"}],
            },
        )
        return [_load_bd(h["_id"], h["_source"]) for h in resp["hits"]["hits"]]

    def list_all_business_domains(self) -> list[BusinessDomain]:
        self.ensure_indices()
        resp = self._client.search(
            index=INDEX_BUSINESS_DOMAINS,
            body={"query": {"match_all": {}}, "size": 1000},
        )
        return [_load_bd(h["_id"], h["_source"]) for h in resp["hits"]["hits"]]

    def get_business_domain(self, bd_id: str) -> BusinessDomain | None:
        self.ensure_indices()
        try:
            doc = self._client.get(index=INDEX_BUSINESS_DOMAINS, id=bd_id)
            return _load_bd(doc["_id"], doc["_source"])
        except NotFoundError:
            return None

    def get_business_domain_by_slug(self, workspace_id: str, slug: str) -> BusinessDomain | None:
        self.ensure_indices()
        resp = self._client.search(
            index=INDEX_BUSINESS_DOMAINS,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"workspace_id": workspace_id}},
                            {"term": {"slug": slug}},
                        ]
                    }
                },
                "size": 1,
            },
        )
        hits = resp["hits"]["hits"]
        if not hits:
            return None
        return _load_bd(hits[0]["_id"], hits[0]["_source"])

    def create_business_domain(self, body: dict[str, Any]) -> BusinessDomain:
        self.ensure_indices()
        bd_id = str(uuid.uuid4())
        self._client.index(index=INDEX_BUSINESS_DOMAINS, id=bd_id, body=body, refresh="wait_for")
        return _load_bd(bd_id, body)

    def update_business_domain(self, bd_id: str, body: dict[str, Any]) -> BusinessDomain:
        self.ensure_indices()
        self._client.index(index=INDEX_BUSINESS_DOMAINS, id=bd_id, body=body, refresh="wait_for")
        return _load_bd(bd_id, body)

    def add_data_product(
        self, bd_id: str, entity_id: str, *, now: str, updated_by: str
    ) -> BusinessDomain | None:
        """Atomically add ONE entity to a BD's ``data_product_ids`` (add-if-absent).

        Unlike ``update_business_domain`` (full-array replace from the client),
        this is a single scripted update applied atomically by OpenSearch, so
        concurrent adds of different entities are commutative — no lost update
        when the UI fires a burst of "+" clicks (the old read-modify-write of the
        whole array let the last writer win). ``retry_on_conflict`` covers the
        rare same-doc version clash. Returns the fresh doc (GET is realtime, so
        no ``refresh="wait_for"`` round-trip needed), or ``None`` if the BD is
        gone — the service maps that to BusinessDomainNotFoundError.
        """
        return self._script_membership(
            bd_id,
            source=(
                "String id = params.id;"
                "if (ctx._source.data_product_ids == null) {"
                "  ctx._source.data_product_ids = [id];"
                "  ctx._source.updated_at = params.now; ctx._source.updated_by = params.by;"
                "} else if (!ctx._source.data_product_ids.contains(id)) {"
                "  ctx._source.data_product_ids.add(id);"
                "  ctx._source.updated_at = params.now; ctx._source.updated_by = params.by;"
                "} else { ctx.op = 'noop'; }"
            ),
            entity_id=entity_id,
            now=now,
            updated_by=updated_by,
        )

    def remove_data_product(
        self, bd_id: str, entity_id: str, *, now: str, updated_by: str
    ) -> BusinessDomain | None:
        """Atomically drop ONE entity from a BD's ``data_product_ids``.

        Symmetric to ``add_data_product`` — a single atomic scripted update,
        idempotent (no-op if the entity wasn't a member). Returns the fresh doc
        or ``None`` if the BD no longer exists.
        """
        return self._script_membership(
            bd_id,
            source=(
                "String id = params.id;"
                "if (ctx._source.data_product_ids == null) { ctx.op = 'noop'; }"
                "else {"
                "  int before = ctx._source.data_product_ids.size();"
                "  ctx._source.data_product_ids.removeIf(x -> id.equals(x));"
                "  if (ctx._source.data_product_ids.size() == before) { ctx.op = 'noop'; }"
                "  else { ctx._source.updated_at = params.now; ctx._source.updated_by = params.by; }"
                "}"
            ),
            entity_id=entity_id,
            now=now,
            updated_by=updated_by,
        )

    def _script_membership(
        self, bd_id: str, *, source: str, entity_id: str, now: str, updated_by: str
    ) -> BusinessDomain | None:
        self.ensure_indices()
        try:
            self._client.update(
                index=INDEX_BUSINESS_DOMAINS,
                id=bd_id,
                body={
                    "script": {
                        "lang": "painless",
                        "source": source,
                        "params": {"id": entity_id, "now": now, "by": updated_by},
                    }
                },
                retry_on_conflict=3,
            )
        except NotFoundError:
            return None
        # GET by id is realtime in OpenSearch (served from the translog), so it
        # reflects the scripted update without waiting for an index refresh.
        doc = self._client.get(index=INDEX_BUSINESS_DOMAINS, id=bd_id)
        return _load_bd(doc["_id"], doc["_source"])

    def delete_business_domain(self, bd_id: str) -> bool:
        self.ensure_indices()
        try:
            self._client.delete(index=INDEX_BUSINESS_DOMAINS, id=bd_id, refresh="wait_for")
            return True
        except NotFoundError:
            return False

    def delete_business_domains_by_workspace(self, ws_id: str) -> int:
        """Cascade delete — used after deleting a workspace. Returns count deleted."""
        self.ensure_indices()
        resp = self._client.delete_by_query(
            index=INDEX_BUSINESS_DOMAINS,
            body={"query": {"term": {"workspace_id": ws_id}}},
            refresh=True,
        )
        return int(resp.get("deleted", 0))

    # ── Organization (singleton) ────────────────────────────────────────────

    def get_organization(self) -> Organization:
        """Returns the singleton org doc. Auto-creates a blank one if missing."""
        self.ensure_indices()
        try:
            doc = self._client.get(index=INDEX_ORGANIZATION, id=ORGANIZATION_ID)
            return Organization(id=ORGANIZATION_ID, **doc["_source"])
        except NotFoundError:
            return Organization(id=ORGANIZATION_ID)

    def upsert_organization(self, body: dict[str, Any]) -> Organization:
        self.ensure_indices()
        self._client.index(
            index=INDEX_ORGANIZATION, id=ORGANIZATION_ID, body=body, refresh="wait_for"
        )
        return Organization(id=ORGANIZATION_ID, **body)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _build_client() -> OpenSearch:
    """Reads OpenSearch config from settings.json the same way ask-knowledge-graph does."""
    settings_path = Path("config/settings.json")
    cfg: dict[str, Any] = {}
    if settings_path.exists():
        try:
            cfg = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Could not parse settings.json — using OpenSearch defaults")

    # Env-first (OPENSEARCH_*) with settings.json fallback — same resolution the
    # secrets repo + system_prompts repo use, so env vars win and this survives
    # the cleanup that strips ``opensearch`` from settings.json.
    os_cfg = cfg.get("opensearch") or {}
    host = os.getenv("OPENSEARCH_HOST")
    port_env = os.getenv("OPENSEARCH_PORT")
    use_ssl_env = os.getenv("OPENSEARCH_USE_SSL")
    username = os.getenv("OPENSEARCH_USER") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or None

    if not host:
        host = os_cfg.get("host", "localhost")
        port = int(port_env or os_cfg.get("port", 9200))
        use_ssl = (
            bool(os_cfg.get("use_ssl", False)) if use_ssl_env is None else _truthy(use_ssl_env)
        )
        username = username or os_cfg.get("username") or None
        password = password or os_cfg.get("password") or None
        verify_certs = bool(os_cfg.get("verify_certs", False))
    else:
        port = int(port_env or 9200)
        use_ssl = _truthy(use_ssl_env or "")
        verify_certs = _truthy(os.getenv("OPENSEARCH_VERIFY_CERTS", ""))

    kwargs: dict[str, Any] = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
        # Default urllib3 pool is effectively 1 connection here — under a burst
        # of concurrent requests (rapid canvas "+", catalog refetch, warmup) the
        # pool fills and connections get discarded + re-handshaked, adding
        # latency ("Connection pool is full, discarding connection"). This client
        # is shared by the BD repo AND the lifecycle repo, so a larger pool
        # benefits both. Overridable via settings.json opensearch.pool_maxsize.
        "maxsize": int(os_cfg.get("pool_maxsize", 20)),
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _load_workspace(ws_id: str, source: dict[str, Any]) -> Workspace:
    """Build a Workspace pydantic from an OS doc — pulls the id from _id."""
    return Workspace(id=ws_id, **source)


def _load_bd(bd_id: str, source: dict[str, Any]) -> BusinessDomain:
    return BusinessDomain(id=bd_id, **source)

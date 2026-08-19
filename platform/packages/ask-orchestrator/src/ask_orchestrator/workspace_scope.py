# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Workspace scope lookup for the orchestrator's /v1/query path.

The orchestrator and admin-api are physically separate services, but they
share the same OpenSearch cluster. Rather than make a per-request HTTP hop
to admin-api just to translate ``workspace_id → list[entity_id]``, the
orchestrator queries OpenSearch directly using the same indices admin-api
owns (``ask-workspaces-v1``, ``ask-business-domains-v1``).

The Business Domain index + its ``data_product_ids`` field were both renamed
in the UX_CHANGES audit (Iter 1) — formerly ``ask-data-products-v1`` /
``entity_ids``. This consumer was updated in lockstep (hard swap, no alias).

The lookup is wrapped in a short TTL cache because (a) workspace data
changes infrequently (admin operation), (b) every chat message hits this
path and (c) OpenSearch round-trips are 5-15 ms — adds up under load.

If the workspace doesn't exist or has no BDs, the caller gets ``None`` so
it can raise a clean 404. An empty list (workspace exists, has BDs, but
they have no data products) is returned as ``[]`` — different from "missing".

Env gating (Option B): organizational membership (workspace → BD →
``data_product_ids``) is global (not env-suffixed), so a membership change is
visible to every env immediately. To stop that from making an entity
answerable in an env it was never published to, the resolved membership is
intersected with the entities actually present in ``ask-entity-registry-v1-{env}``
(the ground truth of "published to {env}"). Result ``[]`` = a real empty scope
(answer nothing), distinct from ``None`` = no/unknown workspace (unscoped).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from ask_knowledge_graph.infrastructure.env_index import env_index, normalize_env

logger = logging.getLogger(__name__)

INDEX_WORKSPACES = "ask-workspaces-v1"
INDEX_BUSINESS_DOMAINS = "ask-business-domains-v1"
# Base entity registry — env-suffixed (ask-entity-registry-v1-{env}) is the
# ground truth of "what is published to this environment".
BASE_ENTITY_REGISTRY = "ask-entity-registry-v1"

# Cache TTL — short enough that workspace edits propagate fast (≤ 30s) but
# long enough to amortize OpenSearch round-trips during a burst of queries.
_CACHE_TTL_SECONDS = 30.0

# Hard cap on the published-id fetch. The semantic layer is small today; if a
# deployment ever exceeds this, the scope would silently truncate, so we log.
_MAX_ENV_IDS = 10000


class WorkspaceScopeProvider:
    """Translates ``workspace_id`` (UUID or slug) into the flat entity_ids list.

    Singleton in the orchestrator process; thread-safe.
    """

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client or _build_client()
        # Result cache, keyed by (workspace, env) — see _cache_key.
        self._cache: dict[str, tuple[float, list[str] | None]] = {}
        # Per-env set of published entity ids (shared across workspaces).
        self._env_cache: dict[str, tuple[float, set[str]]] = {}
        self._lock = threading.Lock()

    def get_entity_ids(self, workspace_id_or_slug: str, env: str | None = None) -> list[str] | None:
        """Returns the deduped flat list of entity_ids for the workspace's DPs,
        env-gated to entities actually published to ``env`` (Option B).

        * ``None`` → workspace not found (router → 404) — UNSCOPED downstream.
        * ``[]``   → workspace resolves to zero entities answerable in ``env``
          (no DPs, OR none of its DP entities are published to ``env``). EMPTY
          SCOPE downstream — the agent sees nothing, by design.
        * non-empty list → ready-to-use allowlist for retrieval scope.

        ``env`` is ``'dev'`` / ``'prod'`` (the chat's QueryRequest.env). When
        ``None`` (CLI / batch / legacy), no env intersection is applied and the
        full data-product membership is returned (back-compat).
        """
        if not workspace_id_or_slug:
            return None

        cache_key = self._cache_key(workspace_id_or_slug, env)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]

        membership = self._fetch(workspace_id_or_slug)
        result = self._intersect_with_env(membership, env)

        with self._lock:
            self._cache[cache_key] = (time.monotonic(), result)
        return result

    def get_schema_entity_ids(
        self, workspace_id_or_slug: str, env: str | None = None
    ) -> list[str] | None:
        """Schema-plane scope: chat membership ∪ its ``composed_of`` bronzes.

        BACKLOG A/D1. Bronze entities are never chat data products
        (REQ_BRONZE_RETRIEVAL_SCOPE: Bronze = schema docs, never text-to-SQL),
        so ``get_entity_ids`` normally carries only Silver/Gold ids — filtering
        SCHEMA_QUERY with it verbatim would make "describe VBAK"-style
        questions unanswerable even when VBAK composes an in-scope Silver.
        This variant widens the allowlist with each member's ``composed_of``
        (indexed top-level on entity docs). Legacy table-name entries
        (``[VBAK, ...]``) don't resolve to entity ids and pass through
        harmlessly — the downstream filter is by id, so they match nothing.

        Same ``None`` / ``[]`` semantics as :meth:`get_entity_ids`.
        """
        base = self.get_entity_ids(workspace_id_or_slug, env=env)
        if not base:
            return base  # None (unknown workspace) or [] (empty scope)

        cache_key = f"schema\x00{self._cache_key(workspace_id_or_slug, env)}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]

        expanded = list(base)
        seen = set(base)
        for bronze_id in self._fetch_composed_of(base, env):
            if bronze_id and bronze_id not in seen:
                seen.add(bronze_id)
                expanded.append(bronze_id)

        with self._lock:
            self._cache[cache_key] = (time.monotonic(), expanded)
        return expanded

    def _fetch_composed_of(self, entity_ids: list[str], env: str | None) -> list[str]:
        """Flat ``composed_of`` of the given entities, read from the registry.

        Uses the env-suffixed index when ``env`` is set (same ground truth the
        published-ids gate reads); the base index otherwise (legacy/CLI).
        Best-effort: a missing index or search failure returns ``[]`` — the
        scope then degrades to the unexpanded membership, never wider.
        """
        norm = normalize_env(env)
        index = env_index(BASE_ENTITY_REGISTRY, norm) if norm else BASE_ENTITY_REGISTRY
        try:
            resp = self._client.search(
                index=index,
                body={
                    "query": {"terms": {"id": list(entity_ids)}},
                    "_source": ["composed_of"],
                    "size": len(entity_ids),
                },
            )
        except NotFoundError:
            return []
        except Exception:  # noqa: BLE001 — scope expansion is best-effort
            logger.warning("composed_of expansion failed for %s", index, exc_info=True)
            return []
        out: list[str] = []
        for h in resp["hits"]["hits"]:
            for ref in h.get("_source", {}).get("composed_of", []) or []:
                if isinstance(ref, str) and ref:
                    out.append(ref)
        return out

    def list_workspaces(self) -> list[dict[str, str]]:
        """Catalog of every workspace as ``{id, slug, name, description}``.

        Used by the public ``GET /external/workspaces`` discovery endpoint so a
        B2B client can find the ``workspace_id`` (slug) to pass to
        ``/external/ask``. Reads ``ask-workspaces-v1`` directly (same index the
        admin-api owns) — no HTTP hop, no auth coupling. Not cached: discovery
        is low-traffic compared to per-message scope lookups, and a fresh list
        keeps newly-created workspaces visible immediately.

        Returns ``[]`` when the index does not exist yet (fresh deploy).
        """
        try:
            resp = self._client.search(
                index=INDEX_WORKSPACES,
                body={
                    "query": {"match_all": {}},
                    "_source": ["slug", "name", "description"],
                    "size": _MAX_ENV_IDS,
                },
            )
        except NotFoundError:
            return []
        workspaces: list[dict[str, str]] = []
        for h in resp["hits"]["hits"]:
            src = h.get("_source", {}) or {}
            workspaces.append(
                {
                    "id": h["_id"],
                    "slug": src.get("slug") or h["_id"],
                    "name": src.get("name") or "",
                    "description": src.get("description") or "",
                }
            )
        return workspaces

    def invalidate(self, workspace_id_or_slug: str | None = None) -> None:
        """Force the next get_entity_ids call to re-query OpenSearch.

        Without argument, drops the whole cache (admin "edited a DP" hook).
        """
        with self._lock:
            if workspace_id_or_slug is None:
                self._cache.clear()
                self._env_cache.clear()  # a publish changes what's in each env
            else:
                # Drop every (ws, env) variant for this workspace.
                prefix = f"{workspace_id_or_slug}\x00"
                for key in [k for k in self._cache if k.startswith(prefix)]:
                    self._cache.pop(key, None)

    # ── Internals ─────────────────────────────────────────────────────────

    def _fetch(self, workspace_id_or_slug: str) -> list[str] | None:
        """Single OpenSearch trip: resolve workspace, then aggregate DP entity_ids.

        Looks like UUID? Try get-by-id first (cheaper). Fall back to slug search.
        """
        ws_id: str | None = None

        if _looks_like_uuid(workspace_id_or_slug):
            try:
                doc = self._client.get(index=INDEX_WORKSPACES, id=workspace_id_or_slug)
                ws_id = doc["_id"]
            except NotFoundError:
                pass

        if ws_id is None:
            try:
                resp = self._client.search(
                    index=INDEX_WORKSPACES,
                    body={"query": {"term": {"slug": workspace_id_or_slug}}, "size": 1},
                )
            except NotFoundError:
                # Index doesn't exist yet (fresh deploy, no workspaces ever created).
                return None
            hits = resp["hits"]["hits"]
            if not hits:
                return None
            ws_id = hits[0]["_id"]

        # Aggregate data_product_ids across this workspace's Business Domains.
        try:
            resp = self._client.search(
                index=INDEX_BUSINESS_DOMAINS,
                body={
                    "query": {"term": {"workspace_id": ws_id}},
                    "_source": ["data_product_ids"],
                    "size": 1000,
                },
            )
        except NotFoundError:
            # BD index doesn't exist yet (fresh deploy, no BDs ever created)
            return []

        seen: set[str] = set()
        ordered: list[str] = []
        for h in resp["hits"]["hits"]:
            for eid in h.get("_source", {}).get("data_product_ids", []) or []:
                if eid and eid not in seen:
                    seen.add(eid)
                    ordered.append(eid)
        return ordered

    @staticmethod
    def _cache_key(workspace_id_or_slug: str, env: str | None) -> str:
        # NUL separator can't appear in a slug/UUID, so (ws, env) keys never collide.
        return f"{workspace_id_or_slug}\x00{normalize_env(env) or ''}"

    def _intersect_with_env(
        self, membership: list[str] | None, env: str | None
    ) -> list[str] | None:
        """Env-gate the membership (Option B).

        ``membership is None`` (workspace not found) stays ``None`` — unscoped.
        ``env is None`` (legacy) returns the membership untouched. Otherwise the
        membership is intersected (order-preserving) with the entities actually
        published to ``env``, so a data-product change can't make an entity
        answerable in an env it was never published to. The result may be ``[]``.
        """
        if membership is None or normalize_env(env) is None:
            return membership
        published = self._published_ids_for_env(env)
        return [eid for eid in membership if eid in published]

    def _published_ids_for_env(self, env: str | None) -> set[str]:
        """Set of entity ids present in ``ask-entity-registry-v1-{env}``.

        Cached per env (own TTL) and reused across workspaces — it is the same
        set for every query against a given env during the TTL window.
        """
        norm = normalize_env(env)
        if norm is None:  # defensive — callers gate on env before reaching here
            return set()
        now = time.monotonic()
        with self._lock:
            cached = self._env_cache.get(norm)
            if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]
        ids = self._fetch_published_ids(norm)
        with self._lock:
            self._env_cache[norm] = (time.monotonic(), ids)
        return ids

    def _fetch_published_ids(self, norm_env: str) -> set[str]:
        index = env_index(BASE_ENTITY_REGISTRY, norm_env)
        try:
            resp = self._client.search(
                index=index,
                body={"query": {"match_all": {}}, "_source": ["id"], "size": _MAX_ENV_IDS},
            )
        except NotFoundError:
            # Env index not created yet → nothing published there → empty scope.
            return set()
        hits = resp["hits"]["hits"]
        if len(hits) >= _MAX_ENV_IDS:
            logger.warning(
                "published-ids fetch hit the %d cap for env %r — workspace scope "
                "may be truncated; switch to a scroll if the layer has grown",
                _MAX_ENV_IDS,
                norm_env,
            )
        return {
            (h.get("_source", {}).get("id") or h.get("_id"))
            for h in hits
            if (h.get("_source", {}).get("id") or h.get("_id"))
        }


# ── Helpers ────────────────────────────────────────────────────────────────


def _looks_like_uuid(value: str) -> bool:
    return len(value) == 36 and value.count("-") == 4


def _build_client() -> OpenSearch:
    settings_path = Path("config/settings.json")
    cfg: dict[str, Any] = {}
    if settings_path.exists():
        try:
            cfg = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("settings.json unparseable; using OpenSearch defaults")

    # OpenSearch is env-first (OPENSEARCH_*), with the legacy settings.json
    # ``opensearch`` block kept as a fallback for the migration window. Mirrors
    # ask_llm_gateway.infrastructure.secrets.repository — env vars win so this
    # survives the cleanup that strips ``opensearch`` from settings.json.
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
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


# Module-level singleton, lazy-built so tests can swap it.
_provider: WorkspaceScopeProvider | None = None


def get_scope_provider() -> WorkspaceScopeProvider:
    global _provider
    if _provider is None:
        _provider = WorkspaceScopeProvider()
    return _provider


def reset_scope_provider() -> None:
    """Used by tests + reload endpoint."""
    global _provider
    _provider = None

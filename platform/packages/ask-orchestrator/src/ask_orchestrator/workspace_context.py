# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Workspace context lookup for the agent's system prompt.

Renders the ACTIVE workspace + its business domains (names + descriptions) as a
short prompt block so the flow understands WHAT it is answering over — the
workspace's purpose and the business domains in scope. Mirrors
``organization_context`` (company profile) and reuses ``workspace_scope``'s
OpenSearch client + uuid helper.

Why: the workspace / business-domain descriptions are the human-authored
"what this scope is about" text — the modern replacement for the dead
``pipeline_v2.*.description`` blocks that used to live (unused) in
settings.json. Prepending them lets the LLM frame answers in domain terms.

Like ``workspace_scope`` / ``organization_context``, this is cached with a
short TTL because the data changes infrequently and every chat message hits it.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from opensearchpy.exceptions import NotFoundError

from .workspace_scope import (
    INDEX_BUSINESS_DOMAINS,
    INDEX_WORKSPACES,
    _build_client,
    _looks_like_uuid,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
# Cap on business domains rendered into the block (keeps the prompt bounded).
_MAX_DOMAINS = 50


class WorkspaceContextProvider:
    """Fetches the active workspace + its BDs and renders a prompt snippet.

    Singleton in the orchestrator process; thread-safe. Cached per workspace.
    """

    def __init__(self, client=None) -> None:
        self._client = client or _build_client()
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()

    def get_context_text(self, workspace_id_or_slug: str) -> str | None:
        """Render the workspace + its business domains as a prompt block.

        Returns None when the workspace is unknown or has nothing meaningful.
        """
        if not workspace_id_or_slug:
            return None
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(workspace_id_or_slug)
            if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]
        try:
            text = self._fetch_and_render(workspace_id_or_slug)
        except Exception as exc:  # noqa: BLE001 — context is best-effort, never break the query
            logger.warning("workspace context lookup failed for %s: %s", workspace_id_or_slug, exc)
            text = None
        with self._lock:
            self._cache[workspace_id_or_slug] = (time.monotonic(), text)
        return text

    def invalidate(self, workspace_id_or_slug: str | None = None) -> None:
        with self._lock:
            if workspace_id_or_slug is None:
                self._cache.clear()
            else:
                self._cache.pop(workspace_id_or_slug, None)

    # ── Internals ─────────────────────────────────────────────────────────

    def _fetch_and_render(self, workspace_id_or_slug: str) -> str | None:
        ws = self._resolve_workspace(workspace_id_or_slug)
        if ws is None:
            return None
        bds = self._fetch_business_domains(ws["_id"])
        return _render(ws.get("_source") or {}, bds)

    def _resolve_workspace(self, workspace_id_or_slug: str) -> dict | None:
        if _looks_like_uuid(workspace_id_or_slug):
            try:
                return self._client.get(index=INDEX_WORKSPACES, id=workspace_id_or_slug)
            except NotFoundError:
                pass
        try:
            resp = self._client.search(
                index=INDEX_WORKSPACES,
                body={"query": {"term": {"slug": workspace_id_or_slug}}, "size": 1},
            )
        except NotFoundError:
            return None
        hits = resp["hits"]["hits"]
        return hits[0] if hits else None

    def _fetch_business_domains(self, ws_id: str) -> list[dict[str, Any]]:
        try:
            resp = self._client.search(
                index=INDEX_BUSINESS_DOMAINS,
                body={
                    "query": {"term": {"workspace_id": ws_id}},
                    "_source": ["name", "description"],
                    "size": _MAX_DOMAINS,
                },
            )
        except NotFoundError:
            return []
        return [h.get("_source") or {} for h in resp["hits"]["hits"]]


# ── Render helper ──────────────────────────────────────────────────────────


def _render(ws_src: dict[str, Any], bds: list[dict[str, Any]]) -> str | None:
    """Build the prompt snippet. Returns None if there's nothing meaningful."""
    name = (ws_src.get("name") or "").strip()
    objective = (ws_src.get("objective") or "").strip()
    description = (ws_src.get("description") or "").strip()

    domain_lines: list[str] = []
    for bd in bds:
        bn = (bd.get("name") or "").strip()
        if not bn:
            continue
        bdesc = (bd.get("description") or "").strip().replace("\n", " ")
        domain_lines.append(f"- {bn}: {bdesc}" if bdesc else f"- {bn}")

    if not name and not domain_lines:
        return None

    lines = ["WORKSPACE CONTEXT", "-----------------"]
    if name:
        lines.append(f"Workspace: {name}")
    if objective:
        lines.append(f"Objective: {objective}")
    if description:
        lines.append(f"About: {description}")
    if domain_lines:
        lines.append("Business domains in scope:")
        lines.extend(domain_lines)
    return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────────────────────


_provider: WorkspaceContextProvider | None = None


def get_workspace_context_provider() -> WorkspaceContextProvider:
    global _provider
    if _provider is None:
        _provider = WorkspaceContextProvider()
    return _provider


def reset_workspace_context_provider() -> None:
    global _provider
    _provider = None

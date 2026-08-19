# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""OpenSearch storage for editable system prompts.

Index ``ask-system-prompts-v1`` holds one doc per editable prompt
(``_id`` = prompt key, e.g. ``"enrichment"``). Falls back to hardcoded
defaults when no doc is stored — admins are free to leave the index empty.

Why an index rather than a config file:
  * Same persistence story as workspaces / secrets — one infrastructure to
    operate, one backup to restore.
  * Editable at runtime via PUT without redeploys.
  * History is kept in OpenSearch (updated_at + updated_by); a separate
    audit index can be wired later without changing this contract.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

logger = logging.getLogger(__name__)


INDEX_SYSTEM_PROMPTS = "ask-system-prompts-v1"


_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "body": {"type": "text"},
            "updated_at": {"type": "keyword"},
            "updated_by": {"type": "keyword"},
        }
    }
}


class SystemPromptRecord:
    """Plain DTO — keeps the repo signature free of Pydantic at this layer."""

    __slots__ = ("key", "body", "updated_at", "updated_by")

    def __init__(
        self,
        key: str,
        body: str,
        updated_at: str = "",
        updated_by: str = "",
    ) -> None:
        self.key = key
        self.body = body
        self.updated_at = updated_at
        self.updated_by = updated_by


class SystemPromptsRepository:
    """Tiny CRUD layer for ``ask-system-prompts-v1`` (singletons by key)."""

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client or _build_client()
        self._index_ensured = False

    def ensure_index(self) -> None:
        if self._index_ensured:
            return
        try:
            if not self._client.indices.exists(index=INDEX_SYSTEM_PROMPTS):
                self._client.indices.create(index=INDEX_SYSTEM_PROMPTS, body=_MAPPING)
                logger.info("Created OpenSearch index %s", INDEX_SYSTEM_PROMPTS)
        except Exception:
            logger.exception("Failed to ensure index %s", INDEX_SYSTEM_PROMPTS)
            raise
        self._index_ensured = True

    def get(self, key: str) -> SystemPromptRecord | None:
        self.ensure_index()
        try:
            doc = self._client.get(index=INDEX_SYSTEM_PROMPTS, id=key)
        except NotFoundError:
            return None
        source = doc["_source"]
        return SystemPromptRecord(
            key=key,
            body=str(source.get("body") or ""),
            updated_at=str(source.get("updated_at") or ""),
            updated_by=str(source.get("updated_by") or ""),
        )

    def upsert(self, key: str, body: str, updated_by: str) -> SystemPromptRecord:
        self.ensure_index()
        record_body = {
            "body": body,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "updated_by": updated_by,
        }
        self._client.index(
            index=INDEX_SYSTEM_PROMPTS,
            id=key,
            body=record_body,
            refresh="wait_for",
        )
        return SystemPromptRecord(
            key=key,
            body=body,
            updated_at=record_body["updated_at"],
            updated_by=updated_by,
        )

    def delete(self, key: str) -> bool:
        self.ensure_index()
        try:
            self._client.delete(index=INDEX_SYSTEM_PROMPTS, id=key, refresh="wait_for")
            return True
        except NotFoundError:
            return False


def _build_client() -> OpenSearch:
    """Reuse the same env-first resolution the secrets repo uses."""
    host = os.getenv("OPENSEARCH_HOST")
    port_env = os.getenv("OPENSEARCH_PORT")
    use_ssl_env = os.getenv("OPENSEARCH_USE_SSL")
    username = os.getenv("OPENSEARCH_USER") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or None

    if not host:
        settings_path = Path("config/settings.json")
        cfg: dict[str, Any] = {}
        if settings_path.exists():
            try:
                cfg = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Could not parse settings.json — using OpenSearch defaults")
        os_cfg = cfg.get("opensearch") or {}
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
        "maxsize": 20,  # avoid the size-1 pool churn under concurrent requests
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")

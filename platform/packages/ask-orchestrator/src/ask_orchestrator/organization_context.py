"""Organization context lookup for the agent's system prompt.

The admin can set company name + SAP version + active modules + URL via
``/v1/admin/organization``. This module reads the same OpenSearch index
that admin-api wrote (one document, ``id = "default"``) and renders it as
a short text block that gets prepended to the agent's system prompts.

Why: lets the LLM personalize answers ("for ACME Corp running SAP S/4HANA
SD/MM/PP …") without the user repeating the context in every question.

Like ``workspace_scope``, this is cached with a short TTL because Org data
changes infrequently and every chat message hits this path.
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

logger = logging.getLogger(__name__)

INDEX_ORGANIZATION = "ask-organization-v1"
ORGANIZATION_ID = "default"

_CACHE_TTL_SECONDS = 60.0


class OrganizationContextProvider:
    """Fetches the singleton org doc and renders it as system-prompt context.

    Singleton in the orchestrator process; thread-safe.
    """

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client or _build_client()
        self._cached_at: float = 0.0
        self._cached_text: str | None = None
        self._lock = threading.Lock()

    def get_context_text(self) -> str | None:
        """Render the org as a prompt snippet. Returns None when not configured.

        Format (subject to evolution):

            CUSTOMER CONTEXT
            ----------------
            Company: ACME Corp
            SAP version: S/4HANA 2023
            Portal: https://acme.example.com

        The snippet is intentionally short — adds ~50-100 tokens to every
        prompt. Worth it: the LLM frames answers correctly without the user
        having to say "I'm at ACME" every time.
        """
        now = time.monotonic()
        with self._lock:
            if self._cached_text is not None and (now - self._cached_at) < _CACHE_TTL_SECONDS:
                return self._cached_text

        text = self._fetch_and_render()

        with self._lock:
            self._cached_text = text
            self._cached_at = time.monotonic()
        return text

    def invalidate(self) -> None:
        with self._lock:
            self._cached_text = None
            self._cached_at = 0.0

    # ── Internals ─────────────────────────────────────────────────────────

    def _fetch_and_render(self) -> str | None:
        try:
            doc = self._client.get(index=INDEX_ORGANIZATION, id=ORGANIZATION_ID)
        except NotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("organization lookup failed: %s", exc)
            return None

        source = doc.get("_source") or {}
        return _render(source)


# ── Render helper ──────────────────────────────────────────────────────────


def _render(source: dict[str, Any]) -> str | None:
    """Build the prompt snippet. Returns None if there's nothing meaningful."""
    company = (source.get("company_name") or "").strip()
    # Generic source system (system + version) — prefer the new field, fall back
    # to the deprecated SAP-specific ``sap_version`` for unmigrated orgs.
    source_system = (source.get("source_system") or source.get("sap_version") or "").strip()
    # ``core_bases`` (Active SAP modules) is currently hidden from the
    # Organization UI — see OrganizationPage.tsx. We keep the field in the
    # data model + the persistence layer so legacy deployments don't lose
    # data, but we no longer surface it in the agent's CUSTOMER CONTEXT
    # block (would lie to the LLM about a value the admin can't manage).
    url = (source.get("url") or "").strip()

    if not any([company, source_system, url]):
        return None

    lines = ["CUSTOMER CONTEXT", "----------------"]
    if company:
        lines.append(f"Company: {company}")
    if source_system:
        lines.append(f"Source system: {source_system}")
    if url:
        lines.append(f"Portal: {url}")
    return "\n".join(lines)


# ── Client helper (mirrors workspace_scope._build_client) ──────────────────


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


# ── Singleton ──────────────────────────────────────────────────────────────


_provider: OrganizationContextProvider | None = None


def get_organization_provider() -> OrganizationContextProvider:
    global _provider
    if _provider is None:
        _provider = OrganizationContextProvider()
    return _provider


def reset_organization_provider() -> None:
    global _provider
    _provider = None

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/setup/...`` — Unified read-only view of the effective system config.

Built specifically for the SPA's Setup page: returns a generic
``sections[]`` array where each section follows the same shape regardless of
provider. The SPA renders one card per section without knowing about
individual providers — the backend filters out fields that don't apply, marks
sensitive ones, and resolves env-var vs file source per field.

Scope (per Tier 2 decision): only what the SPA-visualizer consumes —
**LLM, Embedder, OpenSearch**. Database / Auth / SAP AI Core are served by
their own dedicated endpoints.

Source of truth (post encrypted-secrets refactor):

  * LLM / Embedder   → ``ask-system-settings-v1`` index (via SecretsRepository).
                       Sensitive fields come masked as ``"***"``.
  * OpenSearch       → environment variables (``OPENSEARCH_*``) with a tiny
                       ``settings.json.opensearch`` fallback for the dev
                       migration window. Bootstrap chicken-and-egg: OS creds
                       cannot live encrypted inside OS.

Endpoints
─────────
GET  /v1/admin/setup/effective           Unified config snapshot for the SPA
POST /v1/admin/setup/test/opensearch     OpenSearch cluster health probe
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from opensearchpy.exceptions import OpenSearchException
from pydantic import BaseModel

from ask_llm_gateway.infrastructure.secrets import SecretsRepository, provider_fields

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/setup", tags=["admin/setup"])

_SETTINGS_PATH = Path("config/settings.json")


# ── Models ───────────────────────────────────────────────────────────────────


class ConfigField(BaseModel):
    """One displayable field. Sensitive values come server-masked as ``***``."""

    name: str
    label: str | None = None
    value: str
    # ``encrypted`` and ``plain`` come from the secrets backend (ask-system-settings-v1).
    # ``environment`` / ``file`` / ``default`` keep the original semantics so existing
    # SPA renderers degrade gracefully.
    source: str  # "environment" | "file" | "default" | "encrypted" | "plain"
    sensitive: bool = False
    help_text: str | None = None


class ConfigSection(BaseModel):
    """One renderable card.

    ``test_target`` tells the SPA which POST endpoint to call for testing.
    None means the section has no inline test (display only).
    """

    id: str
    title: str
    provider: str | None = None
    provider_label: str | None = None
    fields: list[ConfigField]
    info: str | None = None
    test_target: str | None = None


class SetupEffectiveResponse(BaseModel):
    sections: list[ConfigSection]


class OpenSearchTestResponse(BaseModel):
    success: bool
    latency_ms: int
    cluster_name: str = ""
    status: str = ""
    detail: str = ""
    error: str | None = None


# ── Provider labels (display only) ──────────────────────────────────────────


_PROVIDER_LABELS: dict[str, str] = {
    "sap_aicore": "SAP AI Core",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "azure": "Azure OpenAI",
    "databricks": "Databricks",
    "bedrock": "AWS Bedrock",
    "vertex_ai": "Google Vertex AI",
    "huggingface": "Hugging Face (local)",
}


# ── Repo singleton ──────────────────────────────────────────────────────────


_REPO: SecretsRepository | None = None


def _repo() -> SecretsRepository:
    global _REPO
    if _REPO is None:
        _REPO = SecretsRepository()
    return _REPO


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_settings_safely() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_llm_or_embedder_section(target: str, title: str) -> ConfigSection:
    """Build a card from the encrypted-secrets backend.

    Falls back to an empty card when no doc is stored (admin hasn't configured
    this target yet). On OpenSearch failure, returns a card with an info banner
    instead of 500-ing the whole snapshot — the OpenSearch section will show
    the underlying problem.
    """
    try:
        raw = _repo().get_raw(target)
    except OpenSearchException as exc:
        logger.warning("Secrets backend unavailable for %s section: %s", target, exc)
        return ConfigSection(
            id=target,
            title=title,
            fields=[],
            info="Secrets backend unreachable — check the OpenSearch card below.",
            test_target=target,
        )

    if raw is None:
        return ConfigSection(
            id=target,
            title=title,
            fields=[],
            info="Not configured yet — set the provider in the LLM Providers tab.",
            test_target=target,
        )

    provider = str(raw.get("provider") or "")
    model = str(raw.get("model") or "")
    plain = dict(raw.get("plain") or {})
    encrypted_keys = set((raw.get("encrypted") or {}).keys())

    fields: list[ConfigField] = []

    # Model is always plain, always shown.
    if model:
        fields.append(ConfigField(name="model", value=model, source="plain", sensitive=False))

    # Walk the registry so the SPA always sees the same field set per provider.
    for fname, sensitive in provider_fields(provider):
        if sensitive:
            stored = fname in encrypted_keys
            # Env override wins for visibility purposes (deployment may pin a
            # value directly, e.g. a K8s Secret on the env var name).
            env_val = os.getenv(fname)
            if env_val and not stored:
                fields.append(
                    ConfigField(
                        name=fname,
                        value="***",
                        source="environment",
                        sensitive=True,
                    )
                )
            else:
                fields.append(
                    ConfigField(
                        name=fname,
                        value="***" if stored else "",
                        source="encrypted" if stored else "default",
                        sensitive=True,
                    )
                )
        else:
            stored_val = plain.get(fname, "")
            env_val = os.getenv(fname) if fname.isupper() else None
            if env_val:
                fields.append(
                    ConfigField(
                        name=fname,
                        value=env_val,
                        source="environment",
                        sensitive=False,
                    )
                )
            elif stored_val:
                fields.append(
                    ConfigField(
                        name=fname,
                        value=str(stored_val),
                        source="plain",
                        sensitive=False,
                    )
                )
            else:
                fields.append(
                    ConfigField(
                        name=fname,
                        value="",
                        source="default",
                        sensitive=False,
                    )
                )

    return ConfigSection(
        id=target,
        title=title,
        provider=provider or None,
        provider_label=_PROVIDER_LABELS.get(provider) or provider or None,
        fields=fields,
        info=(
            "Runs offline locally via sentence-transformers — no API key required."
            if provider == "huggingface"
            else None
        ),
        test_target=target,
    )


def _build_opensearch_section() -> ConfigSection:
    """OpenSearch card — env vars are the canonical source.

    Bootstrap chicken-and-egg: the secrets backend itself lives in OpenSearch,
    so OS creds cannot live encrypted inside OS. They stay in env vars
    (``.env`` for dev, K8s Secret in prod). A legacy ``settings.json.opensearch``
    block is read as a fallback during the migration window.
    """
    cfg = _read_settings_safely()
    os_cfg = cfg.get("opensearch") or {}

    def _field(name: str, env_name: str, fallback: Any, sensitive: bool = False) -> ConfigField:
        env_val = os.getenv(env_name)
        if env_val:
            return ConfigField(
                name=name,
                value="***" if sensitive else env_val,
                source="environment",
                sensitive=sensitive,
            )
        if fallback not in (None, ""):
            return ConfigField(
                name=name,
                value="***" if sensitive else str(fallback),
                source="file",
                sensitive=sensitive,
            )
        return ConfigField(name=name, value="", source="default", sensitive=sensitive)

    fields = [
        _field("host", "OPENSEARCH_HOST", os_cfg.get("host", "localhost")),
        _field("port", "OPENSEARCH_PORT", os_cfg.get("port", 9200)),
        _field("use_ssl", "OPENSEARCH_USE_SSL", "enabled" if os_cfg.get("use_ssl") else "disabled"),
        _field(
            "embedding_dim",
            "OPENSEARCH_EMBEDDING_DIM",
            os_cfg.get("embedding_dim", 1024),
        ),
    ]
    if os.getenv("OPENSEARCH_USER") or os_cfg.get("username"):
        fields.append(_field("username", "OPENSEARCH_USER", os_cfg.get("username")))
    if os.getenv("OPENSEARCH_PASSWORD") or os_cfg.get("password"):
        fields.append(
            _field("password", "OPENSEARCH_PASSWORD", os_cfg.get("password"), sensitive=True)
        )
    return ConfigSection(
        id="opensearch",
        title="OpenSearch",
        fields=fields,
        info="OpenSearch credentials live in environment variables (bootstrap).",
        test_target="opensearch",
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/effective", response_model=SetupEffectiveResponse)
async def get_setup_effective(
    _claims: TokenClaims = Depends(validate_token),
) -> SetupEffectiveResponse:
    """Read-only snapshot of the effective config the SPA renders.

    Three sections — LLM, Embedder, OpenSearch. All three follow the same
    ``fields[]`` shape so the SPA renders any provider with one component.
    """
    llm = _build_llm_or_embedder_section("llm", "LLM")
    embedder = _build_llm_or_embedder_section("embedder", "Embedder")
    opensearch = _build_opensearch_section()
    return SetupEffectiveResponse(sections=[llm, embedder, opensearch])


@router.post("/test/opensearch", response_model=OpenSearchTestResponse)
async def test_opensearch_connection(
    _claims: TokenClaims = Depends(validate_token),
) -> OpenSearchTestResponse:
    """Ping the OpenSearch ``_cluster/health`` endpoint with the active config.

    Always 200 — the success / error is in the body so the SPA can render
    inline without exception handling.
    """
    trace_id = uuid.uuid4().hex
    cfg = _read_settings_safely()
    os_cfg = cfg.get("opensearch") or {}

    host = os.getenv("OPENSEARCH_HOST") or os_cfg.get("host", "localhost")
    port = int(os.getenv("OPENSEARCH_PORT") or os_cfg.get("port", 9200))
    use_ssl = _truthy(os.getenv("OPENSEARCH_USE_SSL", "")) or bool(os_cfg.get("use_ssl", False))
    username = os.getenv("OPENSEARCH_USER") or os_cfg.get("username") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or os_cfg.get("password") or None
    verify_certs = _truthy(os.getenv("OPENSEARCH_VERIFY_CERTS", "")) or bool(
        os_cfg.get("verify_certs", False)
    )

    scheme = "https" if use_ssl else "http"
    url = f"{scheme}://{host}:{port}/_cluster/health"

    started = time.monotonic()
    try:
        import httpx

        auth = (username, password) if username and password else None
        async with httpx.AsyncClient(timeout=8.0, verify=verify_certs) as client:
            resp = await client.get(url, auth=auth)
            resp.raise_for_status()
            data = resp.json()
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "[%s] opensearch test ok %dms status=%s",
            trace_id,
            latency_ms,
            data.get("status"),
        )
        return OpenSearchTestResponse(
            success=True,
            latency_ms=latency_ms,
            cluster_name=str(data.get("cluster_name", "")),
            status=str(data.get("status", "")),
            detail=f"Cluster '{data.get('cluster_name', '?')}' is {data.get('status', '?')}",
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        latency_ms = int((time.monotonic() - started) * 1000)
        msg = str(exc)
        if len(msg) > 500:
            msg = msg[:500] + "..."
        logger.warning("[%s] opensearch test failed: %s", trace_id, msg)
        return OpenSearchTestResponse(
            success=False,
            latency_ms=latency_ms,
            detail="Could not reach OpenSearch",
            error=msg,
        )


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")

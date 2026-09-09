# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``GET /v1/admin/config`` — read ``config/settings.json``.

**Read-only, as of 2026-09-09, and that is the point.** ``POST /v1/admin/config``
was deleted here: it was the last thing in the platform that wrote this file,
and by then nothing called it. Every section a human edits had already moved to
the encrypted store (LLM, embedder, database, and finally the SAP connection),
and every deployment flag had moved to the environment.

What that buys is the whole reason for the exercise: **a file nobody writes can
be a read-only Kubernetes ConfigMap.** No ReadWriteOnce volume shared by three
pods, and therefore no podAffinity pinning them to one node, which is what kept
the two backends from scheduling at all. See
ITERATION_K8S_MULTICLOUD_PLAN section 3.

Four sections still have live readers, all of them deploy-time tuning that a
ConfigMap serves fine: ``schema_mode`` (flash strategy), ``hybrid_pipeline``
(precise retrieval), ``pipeline_v2`` (smart catalog) and
``sap_ai_core.config_path``.

One writable file DOES remain, and it is a different one: ``config/api-config.json``,
owned by ``routers/contracts`` and also baked into the MCP server image. It needs
the same treatment before the chart can drop shared storage entirely.

Rules
─────
* File is resolved relative to the process CWD (``Path("config/settings.json")``).
* GET masks sensitive fields before returning.
"""

from __future__ import annotations

import importlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/config"])

# ── Config file path (CWD-relative) ─────────────────────────────────────────
_CONFIG_PATH = Path("config/settings.json")

# ── Sensitive field paths (dot-notation) ────────────────────────────────────
_SENSITIVE_PATHS: list[tuple[str, ...]] = [
    ("hana", "password"),
    ("postgresql", "password"),
    ("opensearch", "password"),
    ("ias", "client_secret"),
]

# Sections that USED to live in this file and now live in the encrypted store.
# Accepting one here would return 200 and write a file nothing reads, which is
# worse than an error: the admin would believe the value took effect.
_MOVED_SECTIONS: dict[str, str] = {
    "sap_s4hana": "PUT /v1/admin/sap-connection",
}

# ── Mask sentinel ────────────────────────────────────────────────────────────
_MASK = "••••••••"


# ── Pydantic models ──────────────────────────────────────────────────────────
from pydantic import BaseModel  # noqa: E402  (after stdlib imports is fine)


class ConfigResponse(BaseModel):
    config: dict[str, Any]


class ConfigSaveRequest(BaseModel):
    config: dict[str, Any]


class ConfigSaveResponse(BaseModel):
    success: bool
    cleared: list[str] = []
    message: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_raw() -> dict[str, Any]:
    """Return the raw (unmasked) config dict, or {} if the file doesn't exist."""
    if not _CONFIG_PATH.exists():
        return {}
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _mask_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-copied config dict with sensitive fields replaced by the mask."""
    import copy

    masked = copy.deepcopy(cfg)
    for path in _SENSITIVE_PATHS:
        node = masked
        for key in path[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict) and path[-1] in node and node[path[-1]]:
            node[path[-1]] = _MASK
    return masked


def _is_masked(value: Any) -> bool:
    """Return True if *value* is the sentinel mask or starts with ``••``."""
    if not isinstance(value, str):
        return False
    return value.startswith("••")


def _merge_config(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge *incoming* into *existing* and return the result.

    * Top-level keys absent from *incoming* are kept from *existing*.
    * For the special nested sections ``deployments`` and ``sap_ai_core`` a
      one-level deep merge is performed so individual sub-keys survive.
    * For every other key the incoming value wins (shallow replace).
    * Sensitive fields that arrive masked are restored from *existing*.
    """
    import copy

    result = copy.deepcopy(existing)

    _ONE_LEVEL_DEEP_MERGE_KEYS = {"deployments", "sap_ai_core"}

    for top_key, top_val in incoming.items():
        if top_key in _ONE_LEVEL_DEEP_MERGE_KEYS and isinstance(top_val, dict):
            existing_sub = result.get(top_key, {})
            if isinstance(existing_sub, dict):
                merged_sub = {**existing_sub, **top_val}
                result[top_key] = merged_sub
            else:
                result[top_key] = top_val
        else:
            result[top_key] = top_val

    # Restore masked sensitive fields from the existing config
    for path in _SENSITIVE_PATHS:
        node_result = result
        node_existing = existing
        for key in path[:-1]:
            if not isinstance(node_result, dict) or key not in node_result:
                node_result = None
                break
            node_result = node_result[key]
            node_existing = node_existing.get(key, {}) if isinstance(node_existing, dict) else {}

        leaf = path[-1]
        if isinstance(node_result, dict) and leaf in node_result:
            incoming_val = node_result[leaf]
            if _is_masked(incoming_val):
                # Restore from existing
                existing_val = (
                    node_existing.get(leaf, "") if isinstance(node_existing, dict) else ""
                )
                node_result[leaf] = existing_val

    return result


def _reset_router_singletons() -> list[str]:
    """Reset cached singletons in sibling router modules without circular imports."""
    cleared: list[str] = []
    targets = [
        "ask_admin_api.routers.dictionary",
        "ask_admin_api.routers.embeddings",
        "ask_admin_api.routers.yaml_ingestion",
    ]
    for module_path in targets:
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, "reset_singletons"):
                names = mod.reset_singletons()
                cleared.extend(names)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reset_singletons failed for %s: %s", module_path, exc)
    return cleared


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Read settings.json (sensitive fields masked)",
    description=(
        "Returns the content of ``config/settings.json`` relative to the "
        "process CWD.  Sensitive fields (passwords, client_secret) are "
        "replaced with ``••••••••``.  Returns an empty dict if the file "
        "does not yet exist."
    ),
)
async def get_config(
    claims: TokenClaims = Depends(validate_token),
) -> ConfigResponse:
    trace_id = uuid.uuid4().hex
    auth_email = getattr(claims, "email", "unknown")
    logger.info("[%s] GET /v1/admin/config user=%s", trace_id, auth_email)

    raw = _read_raw()
    masked = _mask_config(raw)
    return ConfigResponse(config=masked)

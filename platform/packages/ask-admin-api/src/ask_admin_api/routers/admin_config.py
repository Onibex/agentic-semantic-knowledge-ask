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

**One** section still has a live reader, deploy-time tuning that a ConfigMap
serves fine: ``hybrid_pipeline`` (precise retrieval). ``sap_ai_core.config_path``
went with the SAP AI Core service-key file: that provider's key now lives in the
encrypted store like every other credential.

``schema_mode`` and ``pipeline_v2`` went on 2026-09-09, on Alberth's
observation that neither should have a dependency any more: the publish path
writes one doc_type so ``yaml`` is the only mode with anything behind it, and
the query scope comes from the workspace. Both readers turned out to be dead
code rather than live settings.

``config/api-config.json`` used to be the one writable file left. It went the
same way on 2026-09-09: the API contracts now live in ``ask-api-contracts-v1``,
env-suffixed, and the MCP server fetches them at boot instead of reading a
mounted file. **No file on disk is written by the platform any more**, which is
what lets the chart drop shared storage entirely.

Rules
─────
* File is resolved relative to the process CWD (``Path("config/settings.json")``).
* GET masks sensitive fields before returning.
"""

from __future__ import annotations

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

# ── Mask sentinel ────────────────────────────────────────────────────────────
_MASK = "••••••••"


# ── Pydantic models ──────────────────────────────────────────────────────────
from pydantic import BaseModel  # noqa: E402  (after stdlib imports is fine)


class ConfigResponse(BaseModel):
    config: dict[str, Any]


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

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``POST /v1/admin/mcp/test`` and ``/mcp/restart`` — the MCP server controls.

``test`` reads ``mcp_url`` from the encrypted store's ``sap_s4hana`` section
(the MCP server is the thing that talks to that SAP system, so they are stored
together) and makes a GET request to ``{mcp_url}/health`` to verify it is
reachable. That section used to live in ``config/settings.json``; see
``routers/sap_connection`` for why it moved.

``restart`` backs the "Restart MCP" button on ASK Setup's Contracts page. The
container work lives in ``application/container_control``, shared with the SAP
save, which needs the same restart for the same reason.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ask_llm_gateway.infrastructure.secrets import resolve_sap_config

from ..application.container_control import MCP_CONTAINER, restart_container
from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/mcp"])

# ── Config helpers ────────────────────────────────────────────────────────────

_CONFIG_PATH = Path("config/settings.json")


def _read_raw() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


# ── Response models ───────────────────────────────────────────────────────────


class ConnectionTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    message: str = ""


class RestartResult(BaseModel):
    ok: bool
    message: str = ""
    # Which of the four cases produced this answer, so a caller can tell "this
    # deployment has no Docker" from "the restart broke" without parsing the
    # message. Additive: the SPA reads ok + message and keeps working.
    outcome: str = ""


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post(
    "/mcp/test",
    response_model=ConnectionTestResult,
    summary="Test MCP server health",
)
async def test_mcp_connection(
    user: TokenClaims = Depends(validate_token),
) -> ConnectionTestResult:
    trace_id = uuid.uuid4().hex
    logger.info(
        "POST /v1/admin/mcp/test",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    # Same source as the SAP connection itself: the encrypted store, not the
    # file. mcp_url is stored in that section because the MCP server is the
    # thing that talks to this SAP system.
    mcp_url: str = str(resolve_sap_config().get("mcp_url") or "").rstrip("/")

    if not mcp_url:
        logger.info(
            "[%s] mcp_url not configured",
            trace_id,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )
        return ConnectionTestResult(ok=False, message="mcp_url not configured")

    health_url = f"{mcp_url}/health"
    logger.info(
        "[%s] Testing MCP server url=%s",
        trace_id,
        health_url,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    try:
        resp = requests.get(
            health_url,
            verify=False,
            timeout=8,
        )
        if resp.status_code < 300:
            return ConnectionTestResult(
                ok=True,
                status_code=resp.status_code,
                message="MCP server responded",
            )
        return ConnectionTestResult(
            ok=False,
            status_code=resp.status_code,
            message=f"HTTP {resp.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] MCP connection test failed: %s",
            trace_id,
            exc,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )
        return ConnectionTestResult(ok=False, message=str(exc))


@router.post(
    "/mcp/restart",
    response_model=RestartResult,
    summary="Restart the MCP server container",
)
async def restart_mcp(
    user: TokenClaims = Depends(validate_token),
) -> RestartResult:
    """Restart ask-mcp so it re-reads the stored API contracts.

    Since the contracts moved into OpenSearch, the MCP fetches them from
    ``GET /v1/internal/api-contracts`` at boot and there is no file to reload,
    so a restart IS how a newly saved contract reaches it. That makes this
    button more useful than it was, not less.

    It used to shell out to the ``docker`` CLI, which the image does not carry,
    so it answered "docker CLI not found on this host" everywhere. See
    ``application/container_control`` for the measurement and the reasoning.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "POST /v1/admin/mcp/restart",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    # Synchronous on purpose, unlike the SAP save: here the restart IS the
    # request, and the user is watching a spinner for its outcome.
    report = restart_container(MCP_CONTAINER)

    log = logger.info if report.ok else logger.warning
    log(
        "[%s] MCP restart: %s (%s)",
        trace_id,
        report.message,
        report.outcome.value,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    return RestartResult(
        ok=report.ok,
        message=report.message,
        outcome=report.outcome.value,
    )

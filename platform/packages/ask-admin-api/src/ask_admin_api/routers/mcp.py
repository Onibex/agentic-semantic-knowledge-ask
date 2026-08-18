# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``POST /v1/admin/mcp/test`` — test MCP server health endpoint.

Reads ``config/settings.json`` for ``sap_s4hana.mcp_url`` and makes a GET
request to ``{mcp_url}/health`` to verify the MCP server is reachable.
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

    raw = _read_raw()
    sap_cfg: dict[str, Any] = raw.get("sap_s4hana", {})
    mcp_url: str = (sap_cfg.get("mcp_url") or "").rstrip("/")

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
    import subprocess

    trace_id = uuid.uuid4().hex
    logger.info(
        "POST /v1/admin/mcp/restart",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=mcp", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = [c.strip() for c in result.stdout.strip().splitlines() if c.strip()]
        if not containers:
            return RestartResult(ok=False, message="No container matching 'mcp' found.")
        container = containers[0]
        r = subprocess.run(
            ["docker", "restart", container],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            logger.info("[%s] MCP container '%s' restarted", trace_id, container)
            return RestartResult(ok=True, message=f"Container '{container}' restarted.")
        return RestartResult(ok=False, message=r.stderr.strip() or "docker restart failed.")
    except FileNotFoundError:
        return RestartResult(ok=False, message="docker CLI not found on this host.")
    except subprocess.TimeoutExpired:
        return RestartResult(ok=False, message="Timeout waiting for docker restart.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] MCP restart failed: %s", trace_id, exc)
        return RestartResult(ok=False, message=str(exc))

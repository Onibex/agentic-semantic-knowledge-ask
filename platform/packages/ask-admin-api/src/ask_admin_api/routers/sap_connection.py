# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``GET /v1/admin/sap-connection`` and ``POST /v1/admin/sap-connection/test``
— read SAP S/4HANA connection settings and test OData connectivity.

Rules
─────
* GET returns the ``sap_s4hana`` section from ``config/settings.json`` with
  ``password`` masked.
* POST /test reads the same section, builds the OData ``$metadata`` URL, and
  makes a synchronous HTTP GET to verify the endpoint is reachable.
* Uses ``requests`` (synchronous) — wrapping in a thread pool executor is
  intentionally omitted for a single test call.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/sap-connection"])

# ── Config helpers ────────────────────────────────────────────────────────────

_CONFIG_PATH = Path("config/settings.json")
_MASK = "••••••••"


def _read_raw() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


# ── Response models ───────────────────────────────────────────────────────────


class ConnectionTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    message: str = ""


class SapConnectionResponse(BaseModel):
    config: dict[str, Any]


class SapConnectionSaveRequest(BaseModel):
    host: str
    odata_path: str = "/sap/opu/odata/sap/API_SALES_ORDER_SRV"
    username: str
    password: str | None = None  # None or the mask string → keep existing password


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.put(
    "/sap-connection",
    response_model=SapConnectionResponse,
    summary="Save sap_s4hana config section to settings.json",
)
async def save_sap_connection(
    body: SapConnectionSaveRequest,
    user: TokenClaims = Depends(validate_token),
) -> SapConnectionResponse:
    trace_id = uuid.uuid4().hex
    logger.info(
        "PUT /v1/admin/sap-connection",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )
    raw = _read_raw()
    existing = raw.get("sap_s4hana", {})

    # Keep existing password when the caller sends None, empty, or the mask.
    new_password = body.password
    if not new_password or new_password == _MASK:
        new_password = existing.get("password", "")

    updated: dict[str, Any] = {
        **existing,  # preserve extra keys (mcp_url, port, …)
        "host": body.host.rstrip("/"),
        "odata_path": body.odata_path,
        "username": body.username,
        "password": new_password,
    }
    raw["sap_s4hana"] = updated
    _CONFIG_PATH.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("[%s] sap_s4hana section updated", trace_id, extra={"trace_id": trace_id})

    def _restart_mcp(tid: str) -> None:
        import httpx
        try:
            transport = httpx.HTTPTransport(uds="/var/run/docker.sock")
            with httpx.Client(transport=transport, base_url="http://docker", timeout=30) as client:
                resp = client.post("/containers/agenticai-mcp/restart")
            if resp.status_code == 204:
                logger.info("[%s] agenticai-mcp restarted via Docker API", tid, extra={"trace_id": tid})
            else:
                logger.warning("[%s] MCP restart returned %d", tid, resp.status_code, extra={"trace_id": tid})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] MCP restart failed (run manually: docker restart agenticai-mcp): %s", tid, exc, extra={"trace_id": tid})

    threading.Thread(target=_restart_mcp, args=(trace_id,), daemon=True).start()

    masked = dict(updated)
    if masked.get("password"):
        masked["password"] = _MASK
    return SapConnectionResponse(config=masked)


@router.get(
    "/sap-connection",
    response_model=SapConnectionResponse,
    summary="Read sap_s4hana config section (password masked)",
)
async def get_sap_connection(
    user: TokenClaims = Depends(validate_token),
) -> SapConnectionResponse:
    trace_id = uuid.uuid4().hex
    logger.info(
        "GET /v1/admin/sap-connection",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )
    raw = _read_raw()
    section: dict[str, Any] = dict(raw.get("sap_s4hana", {}))
    if section.get("password"):
        section["password"] = _MASK
    return SapConnectionResponse(config=section)


@router.post(
    "/sap-connection/test",
    response_model=ConnectionTestResult,
    summary="Test SAP S/4HANA OData connectivity",
)
async def test_sap_connection(
    user: TokenClaims = Depends(validate_token),
) -> ConnectionTestResult:
    trace_id = uuid.uuid4().hex
    logger.info(
        "POST /v1/admin/sap-connection/test",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    raw = _read_raw()
    sap_cfg: dict[str, Any] = raw.get("sap_s4hana", {})

    if not sap_cfg:
        logger.info(
            "[%s] sap_s4hana not configured",
            trace_id,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )
        return ConnectionTestResult(
            ok=False,
            message="sap_s4hana not configured in settings.json",
        )

    host: str = sap_cfg.get("host", "").rstrip("/")
    odata_path: str = sap_cfg.get("odata_path", "").rstrip("/")
    username: str = sap_cfg.get("username", "")
    password: str = sap_cfg.get("password", "")

    url = f"{host}{odata_path}/$metadata"
    logger.info(
        "[%s] Testing SAP connection url=%s",
        trace_id,
        url,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    try:
        resp = requests.get(
            url,
            auth=(username, password),
            verify=False,
            timeout=10,
            headers={"Accept": "application/xml"},
        )
        if resp.status_code < 400:
            return ConnectionTestResult(
                ok=True,
                status_code=resp.status_code,
                message="OData service responded",
            )
        return ConnectionTestResult(
            ok=False,
            status_code=resp.status_code,
            message=f"HTTP {resp.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] SAP connection test failed: %s",
            trace_id,
            exc,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )
        return ConnectionTestResult(ok=False, message=str(exc))

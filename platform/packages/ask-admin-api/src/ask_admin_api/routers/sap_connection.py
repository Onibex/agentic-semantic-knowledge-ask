# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``/v1/admin/sap-connection`` — read, write and test the SAP S/4HANA connection.

**Where this lives now.** The encrypted secrets store
(``ask-system-settings-v1``, target ``sap_s4hana``), alongside the LLM, embedder
and database connections. It used to be the ``sap_s4hana`` section of
``config/settings.json``, which kept the SAP password in CLEARTEXT in a file
three services mounted from a shared writable volume. That volume is what forces
a ReadWriteOnce mount in Kubernetes, and the pod affinity that comes with it
(ITERATION_K8S_MULTICLOUD_PLAN section 3).

**The HTTP contract did not change**, deliberately: same paths, same request
bodies, same response shapes, same masking. The Setup SPA needed no edit for the
move itself.

Rules
─────
* GET returns the stored section with ``password`` masked. A masked value is
  never the real one, so a client can round-trip it safely.
* PUT is a PARTIAL update: every field is optional and absent means leave alone.
  That matters more than it looks, because the store's ``upsert`` replaces the
  whole document, so anything not merged back is deleted. Two screens own
  different halves of this one section, and without the merge, saving the SAP
  form would wipe ``mcp_url`` and take action execution down with it, silently.
* A ``password`` that arrives empty or as the mask keeps whatever is stored,
  which is what lets an admin edit the host without re-typing the password.
  That is the store's own ``preserve_blank_secrets`` behaviour, not a local
  reimplementation.
* ``mcp_url`` and ``port`` are part of this section because the MCP server is
  the thing that talks to this SAP system, so the MCP page has an endpoint of
  its own instead of writing here through the generic config route.
* POST /test builds the OData ``$metadata`` URL and does a synchronous GET.
  ``requests`` on purpose: wrapping one probe call in an executor buys nothing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ask_llm_gateway.infrastructure.secrets import (
    SAP_PROVIDER,
    SAP_TARGET,
    SecretsRepository,
    get_secrets_provider,
    resolve_sap_config,
    sap_fields,
)

from ..application.container_control import (
    MCP_CONTAINER,
    restart_container_in_background,
)
from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/sap-connection"])

_MASK = "••••••••"

_REPO: SecretsRepository | None = None


def _repo() -> SecretsRepository:
    global _REPO
    if _REPO is None:
        _REPO = SecretsRepository()
    return _REPO


def _masked_section() -> dict[str, Any]:
    """The stored section as the SPA should see it: password replaced by the mask."""
    section = dict(resolve_sap_config())
    if section.get("password"):
        section["password"] = _MASK
    return section


# ── Response models ───────────────────────────────────────────────────────────


class ConnectionTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    message: str = ""


class SapConnectionResponse(BaseModel):
    config: dict[str, Any]


class SapConnectionSaveRequest(BaseModel):
    """A partial update. Every field is optional and ``None`` means leave alone.

    That is what lets two screens own different halves of one section: the SAP
    form sends host / odata_path / username / password and never mentions the
    MCP server, while the MCP page sends mcp_url / port and does not need to
    know the SAP credentials.

    An empty string is NOT the same as ``None``: it clears the field. The
    exception is ``password``, where both empty and the mask mean "keep the
    stored one", because a client that round-trips a masked GET must not wipe
    the password by echoing the mask back.
    """

    host: str | None = None
    odata_path: str | None = None
    username: str | None = None
    password: str | None = None
    mcp_url: str | None = None
    port: int | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.put(
    "/sap-connection",
    response_model=SapConnectionResponse,
    summary="Save the SAP S/4HANA connection to the encrypted store",
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

    # ``upsert`` REPLACES the document, and ``preserve_blank_secrets`` only
    # carries SENSITIVE fields forward. So every non-sensitive field the caller
    # did not send has to be merged in here, or saving the SAP form would wipe
    # mcp_url (breaking action execution, silently, with no screen reporting it)
    # and saving the MCP form would wipe the host. The file-based version did
    # this with ``**existing``; dropping it would have been silent data loss.
    stored = resolve_sap_config()
    fields: dict[str, str] = {
        name: str(stored[name])
        for name, sensitive, _kind in sap_fields()
        if not sensitive and stored.get(name) not in (None, "")
    }

    # The password never round-trips through here. An empty value or the mask
    # both mean "keep the stored one", and both reach the store as "" so
    # preserve_blank_secrets carries the existing ciphertext forward untouched.
    password = body.password or ""
    fields["password"] = "" if password == _MASK else password

    incoming: dict[str, str | None] = {
        "host": body.host.rstrip("/") if body.host is not None else None,
        "odata_path": body.odata_path,
        "username": body.username,
        "mcp_url": body.mcp_url.rstrip("/") if body.mcp_url is not None else None,
        "port": str(body.port) if body.port is not None else None,
    }
    for name, value in incoming.items():
        if value is not None:
            fields[name] = value

    try:
        _repo().upsert(
            SAP_TARGET,
            provider=SAP_PROVIDER,
            model="",
            fields=fields,
            updated_by=user.email or "",
            preserve_blank_secrets=True,
        )
    except Exception as exc:  # noqa: BLE001 — surface a store failure as a 503
        logger.exception("[%s] could not write the SAP connection", trace_id)
        raise HTTPException(
            status_code=503,
            detail=f"Could not write the SAP connection to the secrets store: {exc}",
        ) from exc

    # The read path caches per TTL; without this the SPA's next GET shows stale
    # values right after a save.
    get_secrets_provider().invalidate(SAP_TARGET)
    logger.info("[%s] SAP connection updated", trace_id, extra={"trace_id": trace_id})

    # The credentials reach the OData proxy through SAP_S4_SALESORDER_* in the
    # environment, which patch.js reads at boot, so a save only takes effect on
    # a restart. In the background because the user asked to STORE credentials:
    # a missing or slow MCP must not make a successful save look like a failure.
    restart_container_in_background(MCP_CONTAINER, trace_id=trace_id)

    return SapConnectionResponse(config=_masked_section())


@router.get(
    "/sap-connection",
    response_model=SapConnectionResponse,
    summary="Read the SAP S/4HANA connection (password masked)",
)
async def get_sap_connection(
    user: TokenClaims = Depends(validate_token),
) -> SapConnectionResponse:
    trace_id = uuid.uuid4().hex
    logger.info(
        "GET /v1/admin/sap-connection",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )
    return SapConnectionResponse(config=_masked_section())


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

    sap_cfg = resolve_sap_config()

    if not sap_cfg:
        logger.info(
            "[%s] the SAP connection is not configured",
            trace_id,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )
        return ConnectionTestResult(
            ok=False,
            message="The SAP connection is not configured yet.",
        )

    host: str = str(sap_cfg.get("host", "")).rstrip("/")
    odata_path: str = str(sap_cfg.get("odata_path", "")).rstrip("/")
    username: str = str(sap_cfg.get("username", ""))
    password: str = str(sap_cfg.get("password", ""))

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

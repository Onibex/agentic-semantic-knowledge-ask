# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``GET /v1/admin/contracts`` and ``POST /v1/admin/contracts``
— read/write ``config/api-config.json``.

Rules
─────
* GET reads ``config/api-config.json`` relative to the process CWD. Returns
  an empty skeleton ``{"server": {}, "apis": []}`` if the file doesn't exist.
* POST accepts a ``ContractsSaveRequest``, writes it to the same path (creating
  parent directories if needed), and confirms with ``ContractsSaveResponse``.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/contracts"])

# ── Config file path ──────────────────────────────────────────────────────────

_CONTRACTS_PATH = Path("config/api-config.json")

_EMPTY_CONFIG: dict[str, Any] = {"server": {}, "apis": []}


# ── Pydantic models ───────────────────────────────────────────────────────────


class ContractsSaveRequest(BaseModel):
    config: dict[str, Any]


class ContractsResponse(BaseModel):
    config: dict[str, Any]


class ContractsSaveResponse(BaseModel):
    success: bool
    message: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/contracts",
    response_model=ContractsResponse,
    summary="Read api-config.json",
    description=(
        "Returns the content of ``config/api-config.json`` relative to the "
        'process CWD. Returns ``{\\"server\\": {}, \\"apis\\": []}`` if the '
        "file does not yet exist."
    ),
)
async def get_contracts(
    user: TokenClaims = Depends(validate_token),
) -> ContractsResponse:
    trace_id = uuid.uuid4().hex
    logger.info(
        "GET /v1/admin/contracts",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    if not _CONTRACTS_PATH.exists():
        return ContractsResponse(config=dict(_EMPTY_CONFIG))

    try:
        data: dict[str, Any] = json.loads(_CONTRACTS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[%s] Could not read api-config.json: %s",
            trace_id,
            exc,
            extra={"trace_id": trace_id, "auth_email": user.email},
        )
        return ContractsResponse(config=dict(_EMPTY_CONFIG))

    return ContractsResponse(config=data)


@router.post(
    "/contracts",
    response_model=ContractsSaveResponse,
    summary="Save api-config.json",
    description=(
        "Writes the supplied config to ``config/api-config.json``. "
        "Creates parent directories if needed. Overwrites the entire file."
    ),
)
async def save_contracts(
    body: ContractsSaveRequest,
    user: TokenClaims = Depends(validate_token),
) -> ContractsSaveResponse:
    trace_id = uuid.uuid4().hex
    logger.info(
        "POST /v1/admin/contracts",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    _CONTRACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONTRACTS_PATH.write_text(
        json.dumps(body.config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "[%s] api-config.json written successfully",
        trace_id,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    return ContractsSaveResponse(success=True, message="Contracts saved.")

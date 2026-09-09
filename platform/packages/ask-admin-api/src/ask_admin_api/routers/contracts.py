# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``GET`` and ``POST /v1/admin/contracts``, plus the machine-to-machine read.

The API contracts used to live in ``config/api-config.json``, read and written
relative to the process CWD. They now live in OpenSearch, one document per
environment, which is what removed the last shared writable file in the
platform. See :mod:`..application.contracts_repository` for why they got their
own index instead of joining the encrypted settings store.

Three routes, two audiences:

  * ``GET`` and ``POST /v1/admin/contracts`` are the Setup SPA's Contracts
    page, admin-gated as before. Their request and response bodies are
    unchanged, so the SPA needed no edit for this move.
  * ``GET /v1/internal/api-contracts`` is the MCP server fetching its own
    configuration at boot. It authenticates with the same ``X-API-Key`` the
    ingest router uses rather than a user token, and it is deliberately NOT a
    new unauthenticated surface.

**The environment.** Both admin routes take an optional ``env`` query
parameter, ``dev`` (the default) or ``prod``. The SPA does not send it today
and gets ``dev``, which is the authoring environment and matches what the
single shared file used to be in practice.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..application.contracts_repository import EMPTY_CONFIG, ContractsRepository
from ..application.env_targets import ALL_ENVIRONMENTS, is_valid_env
from ..auth.api_key import verify_api_key
from ..auth.validator import TokenClaims, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin/contracts"])

# Same prefix as the `internal` router, kept in this module because it serves
# the contracts and nothing else. Registered separately in main.py.
internal_router = APIRouter(prefix="/v1/internal", tags=["internal"])

_DEFAULT_ENV = "dev"


# ── Pydantic models ───────────────────────────────────────────────────────────


class ContractsSaveRequest(BaseModel):
    config: dict[str, Any]


class ContractsResponse(BaseModel):
    config: dict[str, Any]


class ContractsSaveResponse(BaseModel):
    success: bool
    message: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _checked_env(env: str) -> str:
    """Validate the environment, or 400 naming what was expected.

    Loud on a typo rather than quietly resolving to some other index: a save
    that lands in an index nobody reads is exactly the kind of silent no-op
    this codebase keeps removing.
    """
    if not is_valid_env(env):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown environment {env!r}; expected one of {list(ALL_ENVIRONMENTS)}.",
        )
    return env


# ── Admin endpoints ───────────────────────────────────────────────────────────


@router.get(
    "/contracts",
    response_model=ContractsResponse,
    summary="Read the API contracts",
    description=(
        "Returns the API contracts stored for ``env`` (default ``dev``). "
        'Returns ``{"server": {}, "apis": []}`` when none have been saved yet.'
    ),
)
async def get_contracts(
    env: str = Query(default=_DEFAULT_ENV, description="dev or prod"),
    user: TokenClaims = Depends(validate_token),
) -> ContractsResponse:
    trace_id = uuid.uuid4().hex
    resolved_env = _checked_env(env)
    logger.info(
        "GET /v1/admin/contracts env=%s",
        resolved_env,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    config = ContractsRepository(env=resolved_env).get()
    # The screen needs a skeleton to render, so absence becomes the empty
    # shape here. The machine-to-machine route below does the opposite on
    # purpose: an MCP server must not boot on an empty contract set.
    return ContractsResponse(config=config if config is not None else dict(EMPTY_CONFIG))


@router.post(
    "/contracts",
    response_model=ContractsSaveResponse,
    summary="Save the API contracts",
    description=(
        "Replaces the API contracts stored for ``env`` (default ``dev``) with "
        "the supplied config. Call ``POST /v1/admin/mcp/restart`` afterwards "
        "for the MCP server to pick them up."
    ),
)
async def save_contracts(
    body: ContractsSaveRequest,
    env: str = Query(default=_DEFAULT_ENV, description="dev or prod"),
    user: TokenClaims = Depends(validate_token),
) -> ContractsSaveResponse:
    trace_id = uuid.uuid4().hex
    resolved_env = _checked_env(env)
    logger.info(
        "POST /v1/admin/contracts env=%s",
        resolved_env,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    ContractsRepository(env=resolved_env).upsert(body.config, updated_by=user.email or "")
    logger.info(
        "[%s] contracts saved for env=%s",
        trace_id,
        resolved_env,
        extra={"trace_id": trace_id, "auth_email": user.email},
    )

    return ContractsSaveResponse(success=True, message="Contracts saved.")


# ── Machine-to-machine read (the MCP server at boot) ──────────────────────────


@internal_router.get(
    "/api-contracts",
    response_model=ContractsResponse,
    summary="Read the API contracts with an API key",
    description=(
        "The MCP server's boot fetch. Authenticates with ``X-API-Key`` rather "
        "than a user token. Returns 404 when no contracts are stored for the "
        "environment, so the caller can retry instead of starting empty."
    ),
)
async def get_contracts_for_machine(
    env: str = Query(default=_DEFAULT_ENV, description="dev or prod"),
    principal: dict[str, Any] = Depends(verify_api_key),
) -> ContractsResponse:
    trace_id = uuid.uuid4().hex
    resolved_env = _checked_env(env)
    logger.info(
        "GET /v1/internal/api-contracts env=%s principal=%s",
        resolved_env,
        principal.get("principal"),
        extra={"trace_id": trace_id},
    )

    config = ContractsRepository(env=resolved_env).get()
    if config is None:
        # 404 and not an empty skeleton. A client that boots on an empty
        # contract set exposes zero tools while reporting healthy, which is the
        # silent-degradation pattern this move exists to remove. An operator
        # who deliberately saved an empty set gets a stored document and a 200,
        # which is a different and legitimate answer.
        raise HTTPException(
            status_code=404,
            detail=(
                f"No API contracts stored for env={resolved_env!r}. "
                "Save them on the Setup Contracts page first."
            ),
        )
    return ContractsResponse(config=config)

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_orchestrator/auth/xsuaa.py
─────────────────────────────────────────────────────────────────────────────
SAP BTP XSUAA token validation as a FastAPI dependency.

Dual-flag dev bypass (decision #9 of Iter 1 plan)
────────────────────────────────────────────────
The bypass is active ONLY when BOTH conditions hold:
  - ENVIRONMENT == "local"
  - DEV_BYPASS_AUTH == true

In any other combination — including ENVIRONMENT=production with
DEV_BYPASS_AUTH=true — the real XSUAA validation runs. Production-grade
deployments in Kyma fix ENVIRONMENT=production and DEV_BYPASS_AUTH=false
in the ConfigMap, so even an attacker setting DEV_BYPASS_AUTH=true at
runtime cannot disable auth.

WARNING: NUNCA activar DEV_BYPASS_AUTH=true fuera de ENVIRONMENT=local.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Header, HTTPException

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


MOCK_USER: dict[str, Any] = {
    "user_id": "local-dev",
    "email": "dev@local",
    "scopes": ["openid"],
    "bypass": True,
}


def _validate_real_token(token: str, credentials: dict | None) -> dict[str, Any]:
    """Validate the JWT against the bound XSUAA service. Raises on failure."""
    if credentials is None:
        raise HTTPException(
            status_code=503,
            detail="XSUAA credentials not configured",
        )
    # Imported lazily so unit tests don't need the SAP SDK on the import path.
    from sap import xssec  # type: ignore[import-not-found]

    try:
        ctx = xssec.create_security_context(token, credentials)
    except Exception as exc:  # noqa: BLE001 — the SDK raises a wide family
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    return {
        "user_id": ctx.get_user_attribute("user_uuid") or ctx.get_logon_name(),
        "email": ctx.get_email(),
        "scopes": list(ctx.get_scopes() or []),
        "bypass": False,
    }


async def verify_xsuaa_token(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """FastAPI dependency: validates the XSUAA JWT and returns user context.

    Bypass logic is gated by both ENVIRONMENT and DEV_BYPASS_AUTH. The
    settings cache is invalidated by tests via monkeypatching the env vars
    and clearing get_settings.cache_clear().
    """
    settings: Settings = get_settings()

    if settings.bypass_active:
        logger.warning("XSUAA bypass ACTIVE — local dev only. user=%s", MOCK_USER["email"])
        return MOCK_USER

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[len("Bearer ") :]
    return _validate_real_token(token, settings.xsuaa_credentials)

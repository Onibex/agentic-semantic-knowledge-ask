"""
ask_admin_api/auth/xsuaa.py
─────────────────────────────────────────────────────────────────────────────
SAP BTP XSUAA token validation as a FastAPI dependency. Same dual-flag dev
bypass policy as ask-orchestrator: bypass requires BOTH ENVIRONMENT=local AND
DEV_BYPASS_AUTH=true. Code is duplicated from ask-orchestrator/auth/xsuaa.py
on purpose — the two services may diverge (e.g. admin getting a stricter
role-check) without coupling.

WARNING: NUNCA activar DEV_BYPASS_AUTH=true fuera de ENVIRONMENT=local.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Header, HTTPException

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


MOCK_USER: dict[str, Any] = {
    "user_id": "local-admin-dev",
    "email": "admin@local",
    "scopes": ["openid", "admin"],
    "bypass": True,
}


def _validate_real_token(token: str, credentials: dict | None) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=503,
            detail="XSUAA credentials not configured",
        )
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
    """FastAPI dependency: validates the XSUAA JWT and returns user context."""
    settings: Settings = get_settings()

    if settings.bypass_active:
        logger.warning("XSUAA bypass ACTIVE — local dev only. user=%s", MOCK_USER["email"])
        return MOCK_USER

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[len("Bearer ") :]
    return _validate_real_token(token, settings.xsuaa_credentials)

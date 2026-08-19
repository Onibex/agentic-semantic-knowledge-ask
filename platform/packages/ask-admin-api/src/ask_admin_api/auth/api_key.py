# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_admin_api/auth/api_key.py
─────────────────────────────────────────────────────────────────────────────
API-key authentication for machine-to-machine endpoints (Kafka Connect HTTP
Sink, Watson X webhooks, etc.).

WHY a separate auth path from XSUAA
─────────────────────────────────────
XSUAA is OAuth2/JWT — designed for interactive human flows where a
short-lived token is exchanged via OIDC. Kafka Connect HTTP Sink Connector
(and Watson X "Key Value Pair" custom-header support) cannot perform that
exchange; they only know how to set a static HTTP header on every request.

API-key auth is the lowest-common-denominator the industry settled on:
  - Single HTTP header (here: ``X-API-Key``).
  - Server compares against a secret loaded from env (here:
    ``ASK_INGEST_API_KEY``, populated from a Kyma Secret in production).
  - Comparison is constant-time (``hmac.compare_digest``) so timing attacks
    can't leak character-by-character information.

Audience separation: the dependency only protects ``/v1/ingest/*`` routes,
which are explicitly published for automated producers. Admin routes
(``/v1/admin/*``) keep XSUAA — different audience, different rotation
cadence, different blast radius.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import Header, HTTPException

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """FastAPI dependency: validate the inbound ``X-API-Key`` header.

    Returns a small principal dict mirroring the XSUAA dependency's shape so
    downstream logging code can stay uniform across both auth methods.
    """
    settings: Settings = get_settings()

    if not settings.ingest_api_key:
        # 503 (not 401) on purpose — the deployment is misconfigured, not
        # the caller. Kafka Connect's HTTP Sink retries on 5xx but gives up
        # on 4xx; we want it to retry until the secret is mounted.
        raise HTTPException(status_code=503, detail="Ingest API key not configured")

    if not x_api_key or not hmac.compare_digest(x_api_key, settings.ingest_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {
        "auth_method": "api_key",
        "principal": "kafka-connect",
        "user_id": "kafka-connect",
        "email": "",
        "scopes": [],
        "bypass": False,
    }

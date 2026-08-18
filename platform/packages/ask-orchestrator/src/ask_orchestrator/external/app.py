# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
FastAPI sub-app for the public external API.

Mounted at ``/external`` from ``ask_orchestrator.main``. Exposes its own
isolated OpenAPI spec at ``/external/openapi.json`` so external
integrators (WatsonX, n8n) only see public endpoints — never internal
chat / admin / control-plane routes.

Same Python process as the main orchestrator: shares singletons,
TokenTracker, settings.json. The only thing that differs is the
contract surface and the entrypoints registered on this sub-app.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ..config import get_settings
from .openapi import build_external_openapi
from .routers import ask, workspaces

external_app = FastAPI(
    title="ASK External API",
    version="1.0.0",
    description=(
        "Public agent endpoint for B2B integrations (WatsonX Orchestrator, "
        "n8n, Zapier, custom clients). Stable contract independent of the "
        "internal chat API."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    # Mounting at /external gives the sub-app root_path="/external"; by default
    # FastAPI then prepends a relative `{"url": "/external"}` server to the spec.
    # We advertise our OWN absolute server (build_external_openapi), so suppress
    # that injection — otherwise importers see two servers and may pick the
    # relative one and 404.
    root_path_in_servers=False,
)

external_app.include_router(ask.router)
external_app.include_router(workspaces.router)


# The default FastAPI spec is OpenAPI 3.1 with a relative server and no
# security scheme — unusable for B2B importers (WatsonX Orchestrate). Override
# `openapi()` so `/external/openapi.json` serves a 3.0.3 doc with an absolute
# server URL and the OAuth2 clientCredentials scheme. See external/openapi.py.
def _external_openapi() -> dict[str, Any]:
    return build_external_openapi(external_app, get_settings())


external_app.openapi = _external_openapi  # type: ignore[method-assign]

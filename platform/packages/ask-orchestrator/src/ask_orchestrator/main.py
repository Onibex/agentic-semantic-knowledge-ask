# Copyright (c) 2026 Onibex. All rights reserved.
# Part of Onibex ASK Platform. Source-available under PolyForm Strict 1.0.0 /
# Free Trial 1.0.0 — see LICENSE.md

"""
ask_orchestrator/main.py
─────────────────────────────────────────────────────────────────────────────
FastAPI entrypoint for the ASK Orchestrator.

Boundaries (enforced by .import-linter.toml at the repo root):
- main / routers / auth / models / config MUST NOT import from src.* directly.
- Only orchestration.legacy_adapter is allowed to bridge into legacy code
  during Iteration 1. Subsequent iterations replace this bridge with calls
  to extracted capability packages.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .external.app import external_app
from .logging_config import configure_logging
from .routers import artifact, health, internal, profile, query, title

# Wire structured logging before anything else creates loggers.
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Boot-time validation of the encrypted-secrets master key.

    See ``docs/HANDOFF_encrypted_secrets_opensearch.md`` §4. Fail-closed:
    if ``ONIBEX_ENCRYPTION_KEY`` is missing or malformed, the process aborts
    here rather than silently running without crypto. Dev environments must
    generate a key (``Fernet.generate_key()``) and put it in ``.env``.
    """
    from ask_llm_gateway.infrastructure.secrets.crypto import validate_master_key

    try:
        validate_master_key()
        logger.info("ONIBEX_ENCRYPTION_KEY validated — encrypted secrets backend ready")
    except SystemExit as exc:
        logger.critical("Encrypted secrets boot check failed: %s", exc)
        raise
    yield
    logger.info("ask-orchestrator shutting down")


app = FastAPI(
    title="ASK Orchestrator",
    version="0.1.0",
    description=(
        "Single entry point for the ASK Platform. Routes user requests by "
        "macro intent. Iteration 1 wraps the legacy pipelines; later "
        "iterations replace the bridge with extracted capability packages."
    ),
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(query.router)
app.include_router(artifact.router)
app.include_router(profile.router)
app.include_router(title.router)
app.include_router(internal.router)

# Public B2B sub-app — mounted at /external. Has its own isolated OpenAPI
# spec at /external/openapi.json so integrators (WatsonX, n8n) only see
# the public ask endpoint, never internal chat / admin / control routes.
app.mount("/external", external_app)

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_admin_api/config.py
─────────────────────────────────────────────────────────────────────────────
Settings loaded from environment variables. Mirrors ask-orchestrator/config.py
by design — the two services are physically separate and may diverge later
(distinct env-var names, distinct default ports, etc.). Code duplication is
the explicit price of clean separation.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "production"] = "production"
    dev_bypass_auth: bool = False
    log_level: str = "INFO"

    xsuaa_credentials_json: str | None = None
    xsuaa_client_id: str | None = None
    xsuaa_client_secret: str | None = None
    xsuaa_url: str | None = None
    xsuaa_uaa_domain: str | None = None
    xsuaa_verification_key: str | None = None
    xsuaa_xsappname: str | None = None

    # ── Semantic Layer paths (post repo-split) ───────────────────────────────
    # The semantic layer YAMLs live in a SEPARATE git repo from this codebase
    # (typically mounted as a PVC in prod, or a sibling directory in dev).
    # Both env vars MUST be set explicitly; an empty default makes the boot
    # check in main.py fail loudly instead of silently falling back to "."
    # which used to resolve to the code repo's .git and mix YAML commits with
    # code commits (the bug that motivated the split).
    #
    # repo_root      → where the .git of the semantic-layer repo lives.
    # workspace_path → where the backend globs for *.yaml / *.yml.
    #                  Usually == repo_root, but kept separate so the repo
    #                  can hold non-YAML files (README, scripts/) without
    #                  the glob walking into them.
    # baseline_path  → relative to repo_root; holds SAP-baseline + conflict +
    #                  enrichment sidecars (e.g. ``.sap_baseline``).
    #
    # Example .env:
    #   REPO_ROOT=C:/Onibex/python/semantic-layer-s4h
    #   WORKSPACE_PATH=C:/Onibex/python/semantic-layer-s4h
    workspace_path: str = ""
    baseline_path: str = ".sap_baseline"
    repo_root: str = ""

    # ── Machine-to-machine API key for /v1/ingest/* (Kafka Connect, Watson X) ─
    # Loaded from env ``ASK_INGEST_API_KEY`` — the ``ASK_`` prefix mirrors
    # the convention used by the rest of the platform (ASK_ADMIN_URL,
    # ASK_ORCHESTRATOR_URL...). The Python attribute name keeps the prefix
    # out so the rest of the code reads naturally; the binding is done via
    # ``validation_alias``. Populated by a Kyma Secret in production; in
    # local dev set it in ``.env`` or ``docker-compose.yml``. Generate with
    # ``openssl rand -hex 32``.
    ingest_api_key: str | None = Field(default=None, validation_alias="ASK_INGEST_API_KEY")

    # ── Orchestrator URL for cross-process cache invalidation ────────────────
    # After saving LLM/Embedder secrets, the admin-api fires a best-effort POST
    # to {ask_orchestrator_url}/v1/internal/reload so the orchestrator's LLM
    # singleton is rebuilt immediately with the new credentials rather than
    # waiting for the 60s SecretsProvider TTL to expire.
    # Set ASK_ORCHESTRATOR_URL in .env (local) or Kyma Secret (production).
    ask_orchestrator_url: str = Field(
        default="http://localhost:8080",
        validation_alias="ASK_ORCHESTRATOR_URL",
    )

    @property
    def xsuaa_credentials(self) -> dict | None:
        if self.xsuaa_credentials_json:
            return json.loads(self.xsuaa_credentials_json)
        required = (
            self.xsuaa_client_id,
            self.xsuaa_client_secret,
            self.xsuaa_url,
            self.xsuaa_uaa_domain,
            self.xsuaa_verification_key,
            self.xsuaa_xsappname,
        )
        if not all(required):
            return None
        return {
            "clientid": self.xsuaa_client_id,
            "clientsecret": self.xsuaa_client_secret,
            "url": self.xsuaa_url,
            "uaadomain": self.xsuaa_uaa_domain,
            "verificationkey": self.xsuaa_verification_key,
            "xsappname": self.xsuaa_xsappname,
        }

    @property
    def bypass_active(self) -> bool:
        return self.environment == "local" and self.dev_bypass_auth


@lru_cache
def get_settings() -> Settings:
    return Settings()

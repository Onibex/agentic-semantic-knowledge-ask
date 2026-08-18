# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_orchestrator/config.py
─────────────────────────────────────────────────────────────────────────────
Settings loaded from environment variables with safe defaults.

Critical env vars
─────────────────
- ENVIRONMENT:        "production" (default) | "local"
- DEV_BYPASS_AUTH:    bool, default False. Honored ONLY when ENVIRONMENT=local.

XSUAA credentials — two acceptable shapes
─────────────────────────────────────────
1) Individual env vars (matches existing k8s/chat-app.yaml secret pattern):
   XSUAA_CLIENT_ID, XSUAA_CLIENT_SECRET, XSUAA_URL,
   XSUAA_UAA_DOMAIN, XSUAA_VERIFICATION_KEY, XSUAA_XSAPPNAME
2) Combined JSON for tests/local: XSUAA_CREDENTIALS_JSON='{"clientid":...}'

When option 1 is incomplete and option 2 is unset, `xsuaa_credentials`
returns None and the orchestrator fails closed (503).
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "production"] = "production"
    dev_bypass_auth: bool = False
    log_level: str = "INFO"

    # Iter 8.8: feature flags removed — `legacy/` no longer exists, so the
    # rollback paths were physically deleted. Iter 2/3/4/5 added these flags
    # to gate progressive cutovers; their default-on state held for 6+ iters
    # without rollback events.

    xsuaa_credentials_json: str | None = None
    xsuaa_client_id: str | None = None
    xsuaa_client_secret: str | None = None
    xsuaa_url: str | None = None
    xsuaa_uaa_domain: str | None = None
    xsuaa_verification_key: str | None = None
    xsuaa_xsappname: str | None = None

    # ── Public external API contract (OpenAPI for B2B importers) ──────────────
    # The /external OpenAPI spec must advertise ABSOLUTE, externally-reachable
    # URLs: importers like WatsonX Orchestrate build both the request URL and
    # the OAuth token URL from the spec, from OUTSIDE the docker network — so a
    # relative `/external` server or an internal `keycloak:8080` tokenUrl would
    # never resolve for them. Everything derives from EXTERNAL_HOST (the single
    # knob the deploy already uses; see docker-compose.yml); the explicit
    # *_url overrides win when an env pins them.
    external_host: str = "localhost"
    external_scheme: str = "http"
    external_api_port: int = 8085
    keycloak_public_port: int = 8180
    keycloak_realm: str = "ask-platform"
    external_api_base_url: str | None = None  # e.g. http://52.14.62.101:8085
    keycloak_token_url: str | None = None  # explicit tokenUrl override

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
        """Auth bypass is active ONLY when both flags align."""
        return self.environment == "local" and self.dev_bypass_auth

    @property
    def external_server_url(self) -> str:
        """Absolute base URL advertised as ``servers[0].url`` in the /external
        OpenAPI spec, including the ``/external`` mount prefix."""
        base = self.external_api_base_url or (
            f"{self.external_scheme}://{self.external_host}:{self.external_api_port}"
        )
        return f"{base.rstrip('/')}/external"

    @property
    def oauth_token_url(self) -> str:
        """Externally-reachable OAuth2 token endpoint advertised in the
        ``clientCredentials`` flow of the /external OpenAPI spec."""
        if self.keycloak_token_url:
            return self.keycloak_token_url
        return (
            f"{self.external_scheme}://{self.external_host}:{self.keycloak_public_port}"
            f"/realms/{self.keycloak_realm}/protocol/openid-connect/token"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ─────────────────────────────────────────────────────────────────────────────
# SettingsCache — in-memory cache for `config/settings.json`
# ─────────────────────────────────────────────────────────────────────────────
# Distinct from `Settings` above:
#   - `Settings` reads ENVIRONMENT + XSUAA_* from env vars (12-factor).
#   - `SettingsCache` caches the JSON file mounted at `config/settings.json`
#     (DB creds, AI Core deployments, pricing, etc.) which the admin UI edits
#     at runtime.
#
# Before this cache, every `/v1/query` hit `settings.json` 4 times via
# `json.loads(Path(...).read_text())`. With N concurrent threads that's 4·N
# disk reads/request — pure overhead. `SettingsCache` keeps the parsed dict
# in memory and exposes `invalidate()` so `/v1/internal/reload` (and the
# future ConfigMap watcher) can drop it when the file changes.
_DEFAULT_SETTINGS_PATH = Path("config/settings.json")


class SettingsCache:
    """Process-wide cache for the orchestrator's runtime JSON settings.

    Keyed on absolute path so tests using a tmp_path fixture don't bleed
    into production reads.
    """

    _lock: ClassVar[threading.RLock] = threading.RLock()
    _cache: ClassVar[dict[Path, dict[str, Any]]] = {}

    @classmethod
    def get(cls, path: Path | str = _DEFAULT_SETTINGS_PATH) -> dict[str, Any]:
        resolved = Path(path).resolve()
        cached = cls._cache.get(resolved)
        if cached is not None:
            return cached
        with cls._lock:
            cached = cls._cache.get(resolved)
            if cached is None:
                cached = json.loads(resolved.read_text(encoding="utf-8"))
                cls._cache[resolved] = cached
            return cached

    @classmethod
    def invalidate(cls, path: Path | str | None = None) -> None:
        """Drop cached settings.

        With no argument, drops every cached path (used by `reset_singletons`).
        With a path, drops only that entry.
        """
        with cls._lock:
            if path is None:
                cls._cache.clear()
                return
            cls._cache.pop(Path(path).resolve(), None)

    @classmethod
    def typed(cls, path: Path | str = _DEFAULT_SETTINGS_PATH):
        """Return the runtime settings as a validated :class:`RuntimeSettings`.

        Opt-in alternative to :meth:`get` (which returns a raw ``dict``).
        New call sites should prefer this for IDE autocomplete + boot-time
        validation; existing dict-based callers keep working unchanged.
        """
        from ask_llm_gateway.runtime_settings import RuntimeSettings

        return RuntimeSettings.from_dict(cls.get(path))

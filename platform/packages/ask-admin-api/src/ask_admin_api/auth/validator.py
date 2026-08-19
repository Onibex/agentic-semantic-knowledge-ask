# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_admin_api/auth/validator.py
─────────────────────────────────────────────────────────────────────────────
Multi-issuer JWT validator for the ASK Admin API.

Auth modes
──────────
  AUTH_MODE=xsuaa    — validate against SAP XSUAA JWKS
  AUTH_MODE=keycloak (default) — validate against Keycloak / OIDC JWKS
  Dev bypass is NOT a mode — it's a separate dual-flag (ENVIRONMENT=local +
  DEV_BYPASS_AUTH=true), evaluated before AUTH_MODE is read.

JWKS cache
──────────
Keys are cached in-process with a 10-minute TTL. On expiry the next request
triggers a fresh fetch via httpx. No Redis / external cache required — this
is a low-traffic admin service.

Role extraction
───────────────
  xsuaa:    `scope` claim — keeps scopes prefixed with `ask.`
             e.g. `ask.ask-admin-api!t1234.admin` → role `admin`
  keycloak: `resource_access.ask-admin-spa.roles[]` array

Dev bypass
──────────
Same dual-flag policy as managed.py: BOTH ENVIRONMENT=local AND
DEV_BYPASS_AUTH=true must be set. In production, both are false.

WARNING: NUNCA activar DEV_BYPASS_AUTH=true fuera de ENVIRONMENT=local.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Literal

import httpx
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from ..config import get_settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_JWKS_TTL_SECONDS = 600  # 10 minutes
# Hard ceiling on serving stale keys when the JWKS endpoint is unreachable.
# Past this age we fail closed (503) rather than trust keys that may have been
# rotated out — otherwise an outage across a key rotation keeps old signing
# keys trusted indefinitely.
_JWKS_STALE_MAX_SECONDS = 3600  # 1 hour

_BYPASS_CLAIMS = {
    "sub": "local-admin-dev",
    "email": "admin@local",
    # Default realm roles (see keycloak-realm-config.json roles.realm[]).
    # Kept in lockstep with the realm so dev-bypass mirrors a real principal
    # once require_role() is wired. ask-user is the auto-granted default role.
    "roles": ["ask-admin", "ask-user"],
    "issuer": "xsuaa",
}


# ── JWKS cache ───────────────────────────────────────────────────────────────


class _JwksEntry:
    __slots__ = ("keys", "fetched_at")

    def __init__(self, keys: list[dict[str, Any]]) -> None:
        self.keys = keys
        self.fetched_at = time.monotonic()

    def is_expired(self) -> bool:
        return (time.monotonic() - self.fetched_at) > _JWKS_TTL_SECONDS


_jwks_cache: dict[str, _JwksEntry] = {}


def _fetch_jwks(url: str) -> list[dict[str, Any]]:
    """Fetch JWKS from the given URL, returning the list of JWK objects.

    Raises HTTPException(503) when the JWKS endpoint is unreachable so the
    caller can surface a meaningful error to the API consumer.
    """
    entry = _jwks_cache.get(url)
    if entry is not None and not entry.is_expired():
        return entry.keys

    try:
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        keys: list[dict[str, Any]] = response.json().get("keys", [])
    except Exception as exc:  # noqa: BLE001
        logger.error("JWKS fetch failed for %s: %s", url, exc)
        # Serve cached keys even if past the soft TTL (better than failing) —
        # but only up to a hard ceiling, then fail closed so rotated-out keys
        # are not trusted forever during a prolonged JWKS outage.
        if entry is not None:
            stale_age = time.monotonic() - entry.fetched_at
            if stale_age <= _JWKS_STALE_MAX_SECONDS:
                logger.warning("Returning stale JWKS for %s (age %.0fs)", url, stale_age)
                return entry.keys
            logger.error(
                "Stale JWKS for %s exceeded %ds ceiling — failing closed",
                url,
                _JWKS_STALE_MAX_SECONDS,
            )
        raise HTTPException(
            status_code=503,
            detail=f"Could not fetch JWKS from {url}: {exc}",
        )

    _jwks_cache[url] = _JwksEntry(keys)
    return keys


# ── TokenClaims model ────────────────────────────────────────────────────────


class TokenClaims(BaseModel):
    """Normalised, issuer-agnostic JWT claims returned by ``validate_token``."""

    sub: str
    email: str
    roles: list[str]
    issuer: Literal["xsuaa", "keycloak"]


# ── Token validation helpers ─────────────────────────────────────────────────


def _decode_with_jwks(
    token: str,
    jwks_url: str,
    *,
    audience: str | None = None,
) -> dict[str, Any]:
    """Decode and verify a JWT using JWKS. Returns the payload dict or raises
    HTTPException(401) on any validation failure.

    Uses python-jose for RSA/ECDSA signature verification.
    """

    from jose import JWTError, jwt  # type: ignore[import-not-found]

    keys = _fetch_jwks(jwks_url)

    # Peek at the header to find the matching key by `kid`.
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token header: {exc}")

    kid = header.get("kid")
    matching_keys = [k for k in keys if k.get("kid") == kid] if kid else keys

    if not matching_keys:
        # No matching kid — try all keys (the JWKS may not include kid).
        matching_keys = keys

    last_exc: Exception | None = None
    for jwk_data in matching_keys:
        try:
            # Contract: signature-only (multi-issuer — we trust any token the
            # configured JWKS signed, regardless of which client minted it). When
            # no audience is passed, verify_aud MUST be off: python-jose defaults
            # it on, and then REJECTS every token carrying an `aud` claim (e.g. the
            # oauth2-proxy ID token's aud=oauth2-proxy) with "Invalid audience" →
            # spurious 401. Only verify aud when an explicit audience is given.
            # ID tokens (what oauth2-proxy forwards) also carry an `at_hash`
            # claim; python-jose verifies it against the access token by default,
            # which we don't have under the signature-only contract → "No
            # access_token provided to compare against at_hash claim." Disable it
            # (and verify_aud, see above) so only signature + expiry are checked.
            options: dict[str, Any] = {
                "verify_exp": True,
                "verify_aud": bool(audience),
                "verify_at_hash": False,
            }
            kwargs: dict[str, Any] = {"algorithms": [header.get("alg", "RS256")]}
            if audience:
                kwargs["audience"] = audience
            payload: dict[str, Any] = jwt.decode(
                token,
                jwk_data,
                options=options,
                **kwargs,
            )
            return payload
        except JWTError as exc:
            last_exc = exc
            continue

    raise HTTPException(
        status_code=401,
        detail=f"Token signature verification failed: {last_exc}",
    )


def _extract_roles_xsuaa(payload: dict[str, Any]) -> list[str]:
    """Extract roles from an XSUAA token.

    XSUAA encodes roles as space-separated scopes in the `scope` claim.
    We keep only scopes that start with `ask.` and strip the prefix up to
    and including the last dot (e.g. `ask.ask-admin-api!t1234.admin` → `admin`).
    We also keep bare `ask.<role>` forms (e.g. `ask.admin` → `admin`).
    """
    raw_scope: str = payload.get("scope", "")
    roles: list[str] = []
    for scope in raw_scope.split():
        if not scope.startswith("ask."):
            continue
        # Strip the `ask.` prefix; if the remainder contains dots (e.g.
        # `ask-admin-api!t1234.admin`), take the part after the last dot.
        remainder = scope[len("ask.") :]
        role = remainder.rsplit(".", 1)[-1] if "." in remainder else remainder
        if role:
            roles.append(role)
    return roles


def _extract_roles_keycloak(payload: dict[str, Any]) -> list[str]:
    """Extract REALM roles from a Keycloak token.

    The ASK realm assigns ``ask-admin`` / ``ask-user`` as **realm** roles, which
    Keycloak publishes on the default ``realm_access.roles`` claim — the same
    claim the SPA reads (``authStore.extractUser``). The realm also maps a flat
    ``realm_roles`` claim (see keycloak-realm-config.json) which we accept as a
    fallback for tokens where the default mapper is disabled.

    Note: client roles (``resource_access.<client>.roles``) are intentionally
    NOT read — the realm defines no client roles, so that path is always empty,
    and reading it would make every real user resolve to ``roles == []`` (which,
    once ``require_role`` is wired, would 403 even legitimate admins).
    """
    realm_access: dict[str, Any] = payload.get("realm_access") or {}
    roles: list[str] = list(realm_access.get("roles") or [])
    if not roles:
        roles = list(payload.get("realm_roles") or [])
    return [str(r) for r in roles]


def _validate_xsuaa(token: str) -> TokenClaims | None:
    """Try to validate the token against the SAP XSUAA JWKS.

    Returns claims on success, None on failure.
    """
    jwks_url = os.environ.get("XSUAA_JWKS_URL")
    if not jwks_url:
        xsuaa_url = os.environ.get("XSUAA_URL", "")
        if xsuaa_url:
            jwks_url = f"{xsuaa_url.rstrip('/')}/token_keys"
        else:
            logger.debug("XSUAA_JWKS_URL not set and XSUAA_URL not set — skipping xsuaa auth")
            return None

    try:
        payload = _decode_with_jwks(token, jwks_url)
    except HTTPException as exc:
        logger.warning("xsuaa token rejected: %s", exc.detail)
        return None

    return TokenClaims(
        sub=payload.get("sub") or payload.get("user_uuid") or "",
        email=payload.get("email") or payload.get("user_name") or "",
        roles=_extract_roles_xsuaa(payload),
        issuer="xsuaa",
    )


def _validate_keycloak(token: str) -> TokenClaims | None:
    """Try to validate the token against the Keycloak / OIDC JWKS.

    Returns claims on success, None on failure.
    """
    jwks_url = os.environ.get("KEYCLOAK_JWKS_URL")
    if not jwks_url:
        logger.debug("KEYCLOAK_JWKS_URL not set — skipping keycloak auth")
        return None

    try:
        payload = _decode_with_jwks(token, jwks_url)
    except HTTPException as exc:
        logger.warning("keycloak token rejected: %s", exc.detail)
        return None

    return TokenClaims(
        sub=payload.get("sub") or "",
        email=payload.get("email") or payload.get("preferred_username") or "",
        roles=_extract_roles_keycloak(payload),
        issuer="keycloak",
    )


# ── Public FastAPI dependencies ───────────────────────────────────────────────


async def validate_token(
    authorization: str | None = Header(default=None),
) -> TokenClaims:
    """FastAPI dependency: validates the JWT against the configured issuer(s)
    and returns ``TokenClaims``. Raises ``HTTPException(401)`` when all
    configured issuers reject the token.

    Auth mode is read from the ``AUTH_MODE`` env var at each call (no restart
    needed to switch modes in a live deployment).
    """
    settings = get_settings()

    # ── Dev bypass (dual-flag guard) ─────────────────────────────────────────
    if settings.bypass_active:
        logger.warning("Auth bypass ACTIVE — local dev only. sub=%s", _BYPASS_CLAIMS["sub"])
        return TokenClaims(**_BYPASS_CLAIMS)  # type: ignore[arg-type]

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed bearer token")

    token = authorization[len("Bearer ") :]

    # AUTH_MODE=keycloak (Keycloak/OIDC, default) | xsuaa (SAP XSUAA). Dev bypass is a
    # separate dual-flag handled above (bypass_active), not an AUTH_MODE value.
    auth_mode = os.environ.get("AUTH_MODE", "keycloak").lower()
    claims: TokenClaims | None = None

    if auth_mode == "xsuaa":
        claims = _validate_xsuaa(token)
    elif auth_mode == "keycloak":
        claims = _validate_keycloak(token)

    if claims is None:
        raise HTTPException(
            status_code=401,
            detail="Token validation failed: no configured issuer accepted the token",
        )

    return claims


def require_role(role: str):
    """Dependency factory: validates the token AND asserts the given role is
    present.

    Usage::

        @router.post("/admin/something")
        async def endpoint(
            _claims: TokenClaims = Depends(require_role("ask-admin")),
        ) -> ...:
            ...
    """

    async def _dependency(
        claims: TokenClaims = Depends(validate_token),
    ) -> TokenClaims:
        if role not in claims.roles:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: role '{role}' is required",
            )
        return claims

    # Set a readable name so FastAPI's OpenAPI schema shows something meaningful.
    _dependency.__name__ = f"require_role_{role}"
    return _dependency

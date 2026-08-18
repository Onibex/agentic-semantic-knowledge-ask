# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Critical security tests for the XSUAA dual-flag dev bypass (decision #9).

The bypass is active ONLY when BOTH conditions hold simultaneously:
  - ENVIRONMENT == "local"
  - DEV_BYPASS_AUTH == true

Production deployments fix ENVIRONMENT=production + DEV_BYPASS_AUTH=false in
the ConfigMap. These tests prove that even if an attacker flipped
DEV_BYPASS_AUTH=true at runtime, the bypass would NOT activate in production.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ask_orchestrator import config as config_module
from ask_orchestrator.auth.xsuaa import MOCK_USER, verify_xsuaa_token


@pytest.fixture
def fresh_settings(monkeypatch):
    """Reset env vars + clear the lru_cache so each test sees a fresh Settings."""
    for var in ("ENVIRONMENT", "DEV_BYPASS_AUTH", "XSUAA_CREDENTIALS_JSON"):
        monkeypatch.delenv(var, raising=False)
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_bypass_active_when_local_and_flag_true(fresh_settings, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    config_module.get_settings.cache_clear()

    user = await verify_xsuaa_token(authorization=None)
    assert user == MOCK_USER
    assert user["bypass"] is True


@pytest.mark.asyncio
async def test_bypass_inactive_when_only_flag_true(fresh_settings, monkeypatch):
    """ENVIRONMENT defaults to production; DEV_BYPASS_AUTH=true alone must NOT bypass."""
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    config_module.get_settings.cache_clear()

    with pytest.raises(HTTPException) as ei:
        await verify_xsuaa_token(authorization=None)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_bypass_inactive_when_only_environment_local(fresh_settings, monkeypatch):
    """ENVIRONMENT=local without DEV_BYPASS_AUTH=true must NOT bypass."""
    monkeypatch.setenv("ENVIRONMENT", "local")
    config_module.get_settings.cache_clear()

    with pytest.raises(HTTPException) as ei:
        await verify_xsuaa_token(authorization=None)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_production_with_bypass_flag_set_still_validates(fresh_settings, monkeypatch):
    """
    CRITICAL: In ENVIRONMENT=production, DEV_BYPASS_AUTH=true is IGNORED.
    The endpoint must still demand a real bearer token.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    config_module.get_settings.cache_clear()

    settings = config_module.get_settings()
    assert settings.bypass_active is False, (
        "SECURITY REGRESSION: production must never honor DEV_BYPASS_AUTH=true"
    )

    with pytest.raises(HTTPException) as ei:
        await verify_xsuaa_token(authorization=None)
    assert ei.value.status_code == 401
    assert ei.value.detail == "Missing bearer token"


@pytest.mark.asyncio
async def test_production_rejects_bearer_without_credentials(fresh_settings, monkeypatch):
    """If XSUAA credentials are missing in production, validation fails closed (503)."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    config_module.get_settings.cache_clear()

    with pytest.raises(HTTPException) as ei:
        await verify_xsuaa_token(authorization="Bearer fake.jwt.token")
    assert ei.value.status_code == 503
    assert "credentials" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_production_invalid_token_returns_401(fresh_settings, monkeypatch):
    """Invalid JWT must produce 401 (not 500), surfacing the SDK error message."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(
        "XSUAA_CREDENTIALS_JSON",
        '{"clientid":"x","clientsecret":"y","url":"https://example","uaadomain":"example","verificationkey":"-----BEGIN PUBLIC KEY-----\\nfake\\n-----END PUBLIC KEY-----","xsappname":"app"}',
    )
    config_module.get_settings.cache_clear()

    with pytest.raises(HTTPException) as ei:
        await verify_xsuaa_token(authorization="Bearer not.a.real.token")
    assert ei.value.status_code == 401
    assert "Invalid token" in ei.value.detail

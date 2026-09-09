# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Tests for the multi-provider LLM config router.

Focus: the ``/test`` endpoint. The aicore-specific endpoints already worked
pre-refactor and stay untested here, covered manually in the Setup wizard flow.

The ``GET`` / ``POST /v1/admin/llm/config`` tests that used to live here went
with those endpoints (2026-09). They wrote provider config, api_key included,
in CLEARTEXT to ``config/settings.json``; the Setup SPA has used the encrypted
``/v1/admin/secrets/llm`` plane for a while and nothing called the old pair.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def llm_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Boot the admin API against a temp settings.json with auth bypassed."""
    settings_path = tmp_path / "config" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "stack_mode": "direct",
                "llm": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-old"},
                "embedder": {"provider": "openai", "model": "text-embedding-3-large"},
            }
        ),
        encoding="utf-8",
    )

    # The router hard-codes _SETTINGS_PATH at module level; patch it.
    from ask_admin_api.routers import llm_config as router_module

    monkeypatch.setattr(router_module, "_SETTINGS_PATH", settings_path)

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    from ask_admin_api.config import get_settings

    get_settings.cache_clear()

    from ask_admin_api.main import app

    return TestClient(app)


# ── POST /admin/llm/test ─────────────────────────────────────────────────────


def test_test_endpoint_llm_success(llm_client: TestClient):
    """Patches build_llm so we don't hit a real provider."""
    fake_response = type("M", (), {"content": "ok"})()

    class FakeLLM:
        def invoke(self, prompt):
            return fake_response

    with patch("ask_llm_gateway.application.factory.build_llm", return_value=FakeLLM()):
        resp = llm_client.post(
            "/v1/admin/llm/test",
            json={"target": "llm", "provider": "anthropic", "model": "claude-3-5-haiku-20241022"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["target"] == "llm"
    assert body["provider"] == "anthropic"
    assert "latency_ms" in body
    assert body["error"] is None


def test_test_endpoint_embedder_success(llm_client: TestClient):
    class FakeEmbedder:
        def embed_query(self, text):
            return [0.1] * 1024

    with patch("ask_llm_gateway.application.factory.build_embedder", return_value=FakeEmbedder()):
        resp = llm_client.post(
            "/v1/admin/llm/test",
            json={
                "target": "embedder",
                "provider": "huggingface",
                "model": "BAAI/bge-large-en-v1.5",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "1024" in body["detail"]


def test_test_endpoint_returns_friendly_error_on_failure(llm_client: TestClient):
    def boom(cfg):
        raise ValueError("Invalid API Key format")

    with patch("ask_llm_gateway.application.factory.build_llm", side_effect=boom):
        resp = llm_client.post(
            "/v1/admin/llm/test",
            json={"target": "llm", "provider": "anthropic"},
        )

    # Even on provider failure the endpoint returns 200 with success=False —
    # the SPA shows the error inline.
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "Invalid API Key" in body["error"]


def test_test_endpoint_long_error_is_truncated(llm_client: TestClient):
    huge_msg = "x" * 2000

    def boom(cfg):
        raise RuntimeError(huge_msg)

    with patch("ask_llm_gateway.application.factory.build_llm", side_effect=boom):
        resp = llm_client.post(
            "/v1/admin/llm/test",
            json={"target": "llm", "provider": "anthropic"},
        )

    body = resp.json()
    assert body["success"] is False
    # Capped at 500 + ellipsis
    assert len(body["error"]) <= 505
    assert body["error"].endswith("...")

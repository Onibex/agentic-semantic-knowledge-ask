"""Tests for the multi-provider LLM config router (Tier 2 extensions).

Focus: the new fields (api_base, api_version, params) and the /test endpoint.
The aicore-specific endpoints already worked pre-refactor and stay untested
here — covered manually in the Setup wizard flow.
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


# ── GET /admin/llm/config ────────────────────────────────────────────────────


def test_get_config_returns_all_fields_with_api_key_masked(llm_client: TestClient):
    resp = llm_client.get("/v1/admin/llm/config")
    assert resp.status_code == 200
    body = resp.json()

    # Stack mode + LLM section
    assert body["stack_mode"]["value"] == "direct"
    assert body["llm_provider"]["value"] == "openai"
    assert body["llm_model"]["value"] == "gpt-4o"
    # api_key is sensitive — returned as '***' regardless of source
    assert body["llm_api_key"]["value"] == "***"
    assert body["llm_api_key"]["masked"] is True

    # New fields exist + default to empty when not in settings.json
    assert body["llm_api_base"]["value"] == ""
    assert body["llm_api_version"]["value"] == ""
    assert body["llm_params"] == {}
    assert body["embedder_params"] == {}


# ── POST /admin/llm/config ───────────────────────────────────────────────────


def test_save_writes_api_base_and_api_version(llm_client: TestClient, tmp_path: Path):
    resp = llm_client.post(
        "/v1/admin/llm/config",
        json={
            "llm_provider": "azure",
            "llm_model": "azure/my-gpt-4o-deployment",
            "llm_api_base": "https://my-resource.openai.azure.com",
            "llm_api_version": "2024-08-01-preview",
        },
    )
    assert resp.status_code == 200, resp.text

    # Verify it actually landed in settings.json
    settings_path = tmp_path / "config" / "settings.json"
    cfg = json.loads(settings_path.read_text())
    assert cfg["llm"]["provider"] == "azure"
    assert cfg["llm"]["api_base"] == "https://my-resource.openai.azure.com"
    assert cfg["llm"]["api_version"] == "2024-08-01-preview"
    # Untouched fields are preserved
    assert cfg["llm"]["api_key"] == "sk-old"


def test_save_params_dict_replaces_existing(llm_client: TestClient, tmp_path: Path):
    resp = llm_client.post(
        "/v1/admin/llm/config",
        json={
            "llm_provider": "bedrock",
            "llm_params": {
                "AWS_BEARER_TOKEN_BEDROCK": "ABSK...",
                "AWS_REGION": "us-east-2",
            },
        },
    )
    assert resp.status_code == 200

    cfg = json.loads((tmp_path / "config" / "settings.json").read_text())
    assert cfg["llm"]["params"] == {
        "AWS_BEARER_TOKEN_BEDROCK": "ABSK...",
        "AWS_REGION": "us-east-2",
    }


def test_save_empty_params_clears_block(llm_client: TestClient, tmp_path: Path):
    # Seed a params dict first
    settings_path = tmp_path / "config" / "settings.json"
    cfg = json.loads(settings_path.read_text())
    cfg["llm"]["params"] = {"OLD_KEY": "old_value"}
    settings_path.write_text(json.dumps(cfg))

    # Send {} — should reset the params block to empty
    resp = llm_client.post("/v1/admin/llm/config", json={"llm_params": {}})
    assert resp.status_code == 200

    cfg = json.loads(settings_path.read_text())
    assert cfg["llm"]["params"] == {}


def test_save_null_params_preserves_existing(llm_client: TestClient, tmp_path: Path):
    # Seed
    settings_path = tmp_path / "config" / "settings.json"
    cfg = json.loads(settings_path.read_text())
    cfg["llm"]["params"] = {"KEEP_ME": "yes"}
    settings_path.write_text(json.dumps(cfg))

    # Send NOTHING for llm_params — existing should survive
    resp = llm_client.post(
        "/v1/admin/llm/config",
        json={"llm_model": "different-model"},
    )
    assert resp.status_code == 200

    cfg = json.loads(settings_path.read_text())
    assert cfg["llm"]["params"] == {"KEEP_ME": "yes"}
    assert cfg["llm"]["model"] == "different-model"


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

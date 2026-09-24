# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""SAP AI Core goes through LiteLLM's `sap` provider, like every other API provider."""

from __future__ import annotations

import json
import os

import pytest

from ask_llm_gateway.infrastructure import env_ledger
from ask_llm_gateway.infrastructure.secrets import export_fields_to_env, validate_provider_fields
from ask_llm_gateway.infrastructure.secrets.provider import set_secrets_provider_for_tests
from ask_llm_gateway.infrastructure.secrets.registry import known_providers, provider_fields

# The shape SAP BTP issues for a service key. Every value is fake.
SERVICE_KEY = {
    "clientid": "sb-00000000-0000-0000-0000-000000000000!b1|aicore!b1",
    "clientsecret": "fake-secret-value",
    "url": "https://example-subaccount.authentication.us10.hana.ondemand.com",
    "identityzone": "example-subaccount",
    "serviceurls": {"AI_API_URL": "https://api.ai.prod.us-east-1.aws.ml.hana.ondemand.com"},
}

ENV_NAMES = ("AICORE_SERVICE_KEY", "AICORE_RESOURCE_GROUP", "LLM_PROVIDER", "LLM_MODEL")


class _EmptyStore:
    """A secrets store with nothing in it, so the tests never reach OpenSearch."""

    def get(self, target, *, force_refresh=False):
        return None

    def export_to_env(self, target):
        return []

    def invalidate(self, target=None):
        pass


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    env_ledger.reset()
    set_secrets_provider_for_tests(_EmptyStore())
    yield
    set_secrets_provider_for_tests(None)
    env_ledger.reset()


# ── Registry and environment ─────────────────────────────────────────────────


def test_the_service_key_is_one_encrypted_field():
    assert provider_fields("sap") == [
        ("AICORE_SERVICE_KEY", True),
        ("AICORE_RESOURCE_GROUP", False),
    ]
    assert "sap_aicore" not in known_providers()


def test_fields_reach_the_environment_under_the_names_litellm_reads():
    raw = json.dumps(SERVICE_KEY)
    export_fields_to_env("llm", {"AICORE_SERVICE_KEY": raw, "AICORE_RESOURCE_GROUP": "default"})

    assert os.environ["AICORE_SERVICE_KEY"] == raw
    assert os.environ["AICORE_RESOURCE_GROUP"] == "default"


def test_a_blank_resource_group_is_not_exported():
    """Blank means LiteLLM's own default, `default`, not an empty group name."""
    export_fields_to_env(
        "llm", {"AICORE_SERVICE_KEY": json.dumps(SERVICE_KEY), "AICORE_RESOURCE_GROUP": ""}
    )

    assert "AICORE_RESOURCE_GROUP" not in os.environ


# ── Routing ──────────────────────────────────────────────────────────────────


def test_the_model_is_chosen_by_name():
    from ask_llm_gateway.infrastructure.litellm_llm import _litellm_model_string

    assert _litellm_model_string("sap", "gpt-4o") == "sap/gpt-4o"
    assert _litellm_model_string("sap", "sap/gpt-4o") == "sap/gpt-4o"


def test_build_llm_sends_sap_through_litellm(monkeypatch):
    import ask_llm_gateway.infrastructure.litellm_llm as litellm_llm
    from ask_llm_gateway.application.factory import build_llm

    captured = {}

    def _fake_build(**kwargs):
        captured.update(kwargs)
        return "FAKE_LLM"

    monkeypatch.setattr(litellm_llm, "build_litellm_chat", _fake_build)

    assert build_llm({"llm": {"provider": "sap", "model": "gpt-4o"}}) == "FAKE_LLM"
    assert captured["provider"] == "sap"
    assert captured["model"] == "gpt-4o"


def test_the_old_deployments_shape_names_no_provider():
    """`deployments.llm` in settings.json used to mean SAP AI Core. It means nothing now,
    and a file that still carries it says so instead of silently picking a route."""
    from ask_llm_gateway.application.factory import build_llm

    with pytest.raises(ValueError, match="No LLM provider configured"):
        build_llm({"deployments": {"llm": "d1234567890abcdef"}})


def test_the_display_label_names_the_product():
    from ask_llm_gateway.application.factory import get_provider_display

    assert (
        get_provider_display({"llm": {"provider": "sap", "model": "gpt-4o"}})
        == "SAP AI Core · gpt-4o"
    )


# ── Service key shape ────────────────────────────────────────────────────────


def test_a_whole_service_key_passes():
    validate_provider_fields("sap", {"AICORE_SERVICE_KEY": json.dumps(SERVICE_KEY)})


def test_an_x509_service_key_passes():
    key = {k: v for k, v in SERVICE_KEY.items() if k not in ("clientsecret", "url")}
    key.update(
        {
            "certificate": "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
            "key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
            "certurl": "https://example-subaccount.authentication.cert.us10.hana.ondemand.com",
        }
    )
    validate_provider_fields("sap", {"AICORE_SERVICE_KEY": json.dumps(key)})


def test_a_blank_key_is_left_to_the_stored_one():
    """On an edit, a blank secret keeps what is stored, so there is nothing to check."""
    validate_provider_fields("sap", {"AICORE_SERVICE_KEY": ""})
    validate_provider_fields("sap", {})


def test_a_truncated_paste_is_named_without_echoing_the_secret():
    raw = json.dumps(SERVICE_KEY)[:-1]

    with pytest.raises(ValueError) as exc:
        validate_provider_fields("sap", {"AICORE_SERVICE_KEY": raw})

    assert "not valid JSON" in str(exc.value)
    assert "fake-secret-value" not in str(exc.value)


def test_a_partial_key_names_what_is_missing():
    partial = {"clientid": "x", "clientsecret": "fake-secret-value"}

    with pytest.raises(ValueError) as exc:
        validate_provider_fields("sap", {"AICORE_SERVICE_KEY": json.dumps(partial)})

    message = str(exc.value)
    assert "url" in message
    assert "serviceurls.AI_API_URL" in message
    assert "fake-secret-value" not in message


def test_a_json_list_is_not_a_key():
    with pytest.raises(ValueError, match="JSON object"):
        validate_provider_fields("sap", {"AICORE_SERVICE_KEY": json.dumps([SERVICE_KEY])})


def test_other_providers_are_not_checked():
    validate_provider_fields("openai", {"api_key": "not json, and that is fine"})

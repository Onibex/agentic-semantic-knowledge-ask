# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The env ledger: what a configuration writes, it also takes back."""

from __future__ import annotations

import os

import pytest

from ask_llm_gateway.infrastructure import env_ledger
from ask_llm_gateway.infrastructure.provider_env import ensure_litellm_provider_env

AWS_NAMES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in AWS_NAMES:
        monkeypatch.delenv(name, raising=False)
    env_ledger.reset()
    yield
    env_ledger.reset()


def test_switching_provider_retires_the_previous_one():
    """The bug: Bedrock's keys outlived the config that wrote them.

    boto3 stops at the first credential source it finds, so a leftover
    AWS_ACCESS_KEY_ID beats a stored bearer token — and an Anthropic config
    cannot dislodge it, because it never writes an AWS name.
    """
    ensure_litellm_provider_env(
        "bedrock",
        scope="llm",
        params={"AWS_ACCESS_KEY_ID": "AKIA-old", "AWS_SECRET_ACCESS_KEY": "shh"},
    )
    assert os.environ["AWS_ACCESS_KEY_ID"] == "AKIA-old"

    ensure_litellm_provider_env("anthropic", scope="llm", api_key="sk-ant-1")

    assert "AWS_ACCESS_KEY_ID" not in os.environ
    assert "AWS_SECRET_ACCESS_KEY" not in os.environ
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-1"


def test_switching_the_llm_leaves_a_bedrock_embedder_alone():
    """Retirement is per scope: one embedder can hold what the LLM dropped."""
    ensure_litellm_provider_env(
        "bedrock", scope="embedder", params={"AWS_BEARER_TOKEN_BEDROCK": "tok", "AWS_REGION": "us-east-2"}
    )
    ensure_litellm_provider_env(
        "bedrock", scope="llm", params={"AWS_BEARER_TOKEN_BEDROCK": "tok", "AWS_REGION": "us-east-2"}
    )

    ensure_litellm_provider_env("openai", scope="llm", api_key="sk-oai")

    assert os.environ["AWS_BEARER_TOKEN_BEDROCK"] == "tok"
    assert os.environ["AWS_REGION"] == "us-east-2"
    assert os.environ["OPENAI_API_KEY"] == "sk-oai"


def test_probing_a_connection_does_not_retire_the_active_one():
    """/test runs under its own scope — the live model keeps its credentials."""
    ensure_litellm_provider_env("anthropic", scope="llm", api_key="sk-live")

    ensure_litellm_provider_env("openai", scope="probe", api_key="sk-probe")

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-live"
    assert os.environ["OPENAI_API_KEY"] == "sk-probe"


def test_a_value_from_the_container_environment_is_restored(monkeypatch):
    """A Kyma Secret / env_file value is borrowed, not consumed."""
    monkeypatch.setenv("AWS_REGION", "eu-central-1")

    ensure_litellm_provider_env("bedrock", scope="llm", params={"AWS_REGION": "us-east-2"})
    assert os.environ["AWS_REGION"] == "us-east-2"

    ensure_litellm_provider_env("anthropic", scope="llm", api_key="sk-ant")
    assert os.environ["AWS_REGION"] == "eu-central-1"


def test_a_variable_nobody_wrote_is_never_touched(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "from-the-instance")

    ensure_litellm_provider_env("anthropic", scope="llm", api_key="sk-ant")

    assert os.environ["AWS_ACCESS_KEY_ID"] == "from-the-instance"


def test_blank_values_never_overwrite_a_real_one(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "eu-central-1")

    ensure_litellm_provider_env("bedrock", scope="llm", params={"AWS_REGION": ""})

    assert os.environ["AWS_REGION"] == "eu-central-1"
    assert env_ledger.owned_by("litellm:llm") == set()

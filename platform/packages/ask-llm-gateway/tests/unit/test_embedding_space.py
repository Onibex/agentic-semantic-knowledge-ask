# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""One vector size for the index and the embedder, read in one place."""

from __future__ import annotations

import pytest

from ask_llm_gateway.embedding_space import (
    DEFAULT_EMBEDDING_DIM,
    EMBEDDING_DIM_ENV,
    index_embedding_dim,
)


@pytest.fixture
def captured_embedding(monkeypatch):
    """Replace ``litellm.embedding`` and return the kwargs of the last call."""
    import litellm

    captured: dict = {}

    def _fake_embedding(**kwargs):
        captured.clear()
        captured.update(kwargs)
        size = kwargs.get("dimensions") or (kwargs.get("parameters") or {}).get("dimensions") or 8
        return {"data": [{"embedding": [0.0] * size} for _ in kwargs["input"]]}

    monkeypatch.setattr(litellm, "embedding", _fake_embedding)
    return captured


def test_the_default_is_the_platform_standard(monkeypatch):
    monkeypatch.delenv(EMBEDDING_DIM_ENV, raising=False)

    assert index_embedding_dim() == DEFAULT_EMBEDDING_DIM == 1024


def test_the_environment_decides(monkeypatch):
    monkeypatch.setenv(EMBEDDING_DIM_ENV, "3072")

    assert index_embedding_dim() == 3072


def test_a_value_that_is_not_a_number_fails_instead_of_defaulting(monkeypatch):
    monkeypatch.setenv(EMBEDDING_DIM_ENV, "1024 dims")

    with pytest.raises(ValueError):
        index_embedding_dim()


def test_the_embedder_asks_the_model_for_the_index_size(monkeypatch, captured_embedding):
    from ask_llm_gateway.infrastructure.litellm_embedder import LiteLLMEmbedder

    monkeypatch.setenv(EMBEDDING_DIM_ENV, "1024")
    embedder = LiteLLMEmbedder(provider="openai", model="text-embedding-3-large")

    assert len(embedder.embed_query("ok")) == 1024
    assert captured_embedding["dimensions"] == 1024


def test_sap_is_asked_inside_parameters_because_litellm_drops_dimensions(
    monkeypatch, captured_embedding
):
    """Measured against SAP AI Core: `dimensions` arrived as nothing and gave 3072."""
    from ask_llm_gateway.infrastructure.litellm_embedder import LiteLLMEmbedder

    monkeypatch.setenv(EMBEDDING_DIM_ENV, "1024")
    embedder = LiteLLMEmbedder(provider="sap", model="text-embedding-3-large")

    assert len(embedder.embed_query("ok")) == 1024
    assert captured_embedding["model"] == "sap/text-embedding-3-large"
    assert captured_embedding["parameters"] == {"dimensions": 1024}
    assert "dimensions" not in captured_embedding


def test_sap_models_without_the_parameter_are_not_asked(monkeypatch, captured_embedding):
    from ask_llm_gateway.infrastructure.litellm_embedder import LiteLLMEmbedder

    monkeypatch.setenv(EMBEDDING_DIM_ENV, "1024")
    LiteLLMEmbedder(provider="sap", model="some-other-embedding-model").embed_query("ok")

    assert "parameters" not in captured_embedding
    assert "dimensions" not in captured_embedding


def test_azure_is_not_asked_because_litellm_forwards_it_unchecked(monkeypatch, captured_embedding):
    """An Azure model is a deployment name: an ada-002 behind it rejects `dimensions`."""
    from ask_llm_gateway.infrastructure.litellm_embedder import LiteLLMEmbedder

    monkeypatch.setenv(EMBEDDING_DIM_ENV, "1024")
    LiteLLMEmbedder(provider="azure", model="my-embeddings").embed_query("ok")

    assert "dimensions" not in captured_embedding

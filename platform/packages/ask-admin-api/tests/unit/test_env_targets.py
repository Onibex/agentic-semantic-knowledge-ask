"""env_targets + env_index resolution (UX_CHANGES audit CH-2, Iter 2)."""

from __future__ import annotations

import pytest

from ask_admin_api.application import env_targets as et


def test_opensearch_index_for():
    assert et.opensearch_index_for("ask-entity-registry-v1", "dev") == "ask-entity-registry-v1-dev"
    assert (
        et.opensearch_index_for("ask-entity-registry-v1", "prod") == "ask-entity-registry-v1-prod"
    )
    # Shim: None / "" → unchanged (legacy un-suffixed index).
    assert et.opensearch_index_for("ask-entity-registry-v1", None) == "ask-entity-registry-v1"
    assert et.opensearch_index_for("ask-entity-registry-v1", "") == "ask-entity-registry-v1"


def test_normalize_env():
    assert et.normalize_env("DEV") == "dev"
    assert et.normalize_env(" prod ") == "prod"
    assert et.normalize_env(None) is None
    assert et.normalize_env("") is None
    with pytest.raises(ValueError):
        et.normalize_env("staging")


def test_branch_for():
    assert et.branch_for("dev") == "dev"
    assert et.branch_for("prod") == "prod"
    with pytest.raises(ValueError):
        et.branch_for(None)


def test_source_branch_for_promotion_chain():
    # dev cuts from main; prod promotes from dev (never bypasses dev).
    assert et.source_branch_for("dev") == "main"
    assert et.source_branch_for("prod") == "dev"
    with pytest.raises(ValueError):
        et.source_branch_for("main")


def test_all_environments_hardcoded_to_two():
    assert et.ALL_ENVIRONMENTS == ("dev", "prod")

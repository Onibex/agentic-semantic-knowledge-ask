# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""resolve_db_target — per-environment DB selection (UX_CHANGES audit CH-2)."""

from __future__ import annotations

from ask_sql_executor.application.db_target import is_db_configured, resolve_db_target


def test_no_env_uses_top_level_block():
    s = {"db_type": "hana", "hana": {"host": "h-dev", "schema": "S"}, "postgresql": {"host": "pg"}}
    assert resolve_db_target(s, None) == ("hana", {"host": "h-dev", "schema": "S"})
    # Behaviour-neutral: today's orchestrator passes env=None.
    assert resolve_db_target(s) == ("hana", {"host": "h-dev", "schema": "S"})


def test_env_block_overrides():
    s = {
        "db_type": "hana",
        "hana": {"host": "h-dev"},
        "environments": {"prod": {"db_type": "hana", "hana": {"host": "h-prod"}}},
    }
    assert resolve_db_target(s, "prod")[1]["host"] == "h-prod"


def test_dev_falls_back_to_top_level_but_prod_does_not():
    # 'dev' with no block → top-level (the UI mirrors dev into it). 'prod' with
    # an empty block must NOT silently inherit the top-level/dev DB — it returns
    # an empty config so the orchestrator can block with a clear message.
    s = {"db_type": "hana", "hana": {"host": "h-dev"}, "environments": {"prod": {}}}
    assert resolve_db_target(s, "dev")[1]["host"] == "h-dev"
    assert resolve_db_target(s, "prod")[1] == {}


def test_prod_with_no_environments_block_is_unconfigured():
    s = {"db_type": "hana", "hana": {"host": "h-dev"}}
    # No environments at all → prod is unconfigured (empty), dev mirrors top-level.
    assert resolve_db_target(s, "prod")[1] == {}
    assert resolve_db_target(s, "dev")[1]["host"] == "h-dev"


def test_is_db_configured():
    s = {
        "db_type": "hana",
        "hana": {"host": "h-dev"},
        "environments": {"prod": {"db_type": "hana", "hana": {"host": "h-prod"}}},
    }
    assert is_db_configured(s, "dev") is True  # falls back to top-level
    assert is_db_configured(s, "prod") is True  # has its own block
    # prod without its own block is NOT configured (no silent fallback)
    assert is_db_configured({"db_type": "hana", "hana": {"host": "h"}}, "prod") is False
    # nothing configured at all
    assert is_db_configured({}, "dev") is False


def test_env_block_can_switch_db_type():
    s = {
        "db_type": "hana",
        "hana": {"host": "h"},
        "postgresql": {"host": "pg-top"},
        "environments": {"dev": {"db_type": "postgresql", "postgresql": {"host": "pg-dev"}}},
    }
    db_type, cfg = resolve_db_target(s, "dev")
    assert db_type == "postgresql"
    assert cfg["host"] == "pg-dev"


def test_returns_copy_not_reference():
    block = {"host": "h"}
    s = {"db_type": "hana", "hana": block}
    _, cfg = resolve_db_target(s, None)
    cfg["host"] = "mutated"
    assert block["host"] == "h"  # original settings untouched


def test_empty_settings_defaults_to_postgresql():
    assert resolve_db_target({}, None) == ("postgresql", {})

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The standards excerpt must actually carry each layer's rules to the LLM.

``get_standards_excerpt(layer)`` injects the matching ``prompts/standards/``
file WHOLE into the enrichment prompt. That design has two failure modes this
guard pins:

1. A layer file goes missing / gets emptied → its entities silently enrich with
   no standard at all. The loader now raises instead, and
   ``test_standards_are_reachable_wherever_the_process_starts`` pins the
   CWD-independence that the old bare relative path did not have.
2. The folder duplicates shared contracts per layer BY DESIGN (owner decision,
   2026-08-02) — the drift risk of that duplication is checked here by asserting
   the load-bearing shared markers in BOTH carriers (SILVER and GOLD).

The old single-file slicing (``_RELEVANT_SECTIONS`` keeping ``## 4.`` whole) is
gone; so is the test that pinned it.
"""

import pytest

from ask_admin_api.application.system_prompts_service import get_standards_excerpt


@pytest.fixture(scope="module")
def bronze() -> str:
    return get_standards_excerpt("bronze")


@pytest.fixture(scope="module")
def silver() -> str:
    return get_standards_excerpt("silver")


@pytest.fixture(scope="module")
def gold() -> str:
    return get_standards_excerpt("gold")


@pytest.mark.parametrize("layer", ["bronze", "silver", "gold"])
def test_standards_are_reachable_wherever_the_process_starts(layer, tmp_path, monkeypatch):
    """The one guard that would have caught the Docker outage.

    The standards used to be loaded from the bare relative path
    ``docs/semantic-layer``, so they resolved only when the interpreter started
    in ``platform/``. Every container (WORKDIR ``/app``, package installed
    non-editably) got an empty excerpt and enriched with no rules at all. The
    old version of this test skipped in exactly that situation, so nothing ever
    went red. Run it from a directory that contains no ``docs/`` to prove the
    lookup no longer depends on where the process happens to start.
    """
    get_standards_excerpt.cache_clear()
    monkeypatch.chdir(tmp_path)
    try:
        assert get_standards_excerpt(layer).strip()
    finally:
        get_standards_excerpt.cache_clear()


@pytest.mark.parametrize(
    "marker",
    [
        "STRING(n)",  # canonical type vocabulary (single home: BRONZE)
        "DECIMAL(p,s)",
        "What canonical drops",  # the documented information loss
        "MANDT",  # client/tenant key-exclusion rule
        "Bronze isolation",  # no field rows, no embedding
        "primary_key",  # the key contract exists at all
        "key_field",
        "rejected, not repaired",  # hard-reject stance
    ],
)
def test_bronze_rules_reach_the_prompt(bronze, marker):
    assert marker in bronze


@pytest.mark.parametrize(
    "marker",
    [
        "two-axis aggregation contract",
        "non_additive_over",
        "requires_dedup",
        "Never Silver → Gold",
        "entity_grain",
        "self-sufficient",  # fallback-plane rule
        "status_flag",
    ],
)
def test_silver_rules_reach_the_prompt(silver, marker):
    assert marker in silver


@pytest.mark.parametrize(
    "marker",
    [
        "two-axis aggregation contract",
        "Edge vs. denormalization",
        "declare on ONE side only",
        "requires_dedup",
        "traversal_cost",
        "status_flag",
    ],
)
def test_gold_rules_reach_the_prompt(gold, marker):
    assert marker in gold


@pytest.mark.parametrize(
    "marker",
    [
        # Shared contracts duplicated by design — if one carrier loses a marker,
        # that is drift between the twin copies, not a formatting nit.
        "two-axis aggregation contract",
        "non_additive_over",
        "requires_dedup",
        'It is NOT "insert `SELECT DISTINCT`"',
        "attribute",
        "status_flag",
        "The qualifier contract",
        "Every qualifier is the `db_table_name` of its own side",
        "that is **two edges, not one**",
    ],
)
def test_shared_contracts_present_in_both_carriers(silver, gold, marker):
    assert marker in silver
    assert marker in gold


def test_bronze_excerpt_stays_bronze_scoped(bronze):
    """The bronze prompt must not balloon back into the all-layer doc."""
    assert "two-axis aggregation contract" not in bronze
    assert "Edge vs. denormalization" not in bronze


def test_unknown_layer_falls_back_to_all_three(bronze, silver, gold):
    combined = get_standards_excerpt(None)
    assert "Bronze isolation" in combined  # bronze present
    assert "two-axis aggregation contract" in combined  # silver/gold present
    assert "Edge vs. denormalization" in combined  # gold present
    assert len(combined) >= max(len(bronze), len(silver), len(gold))

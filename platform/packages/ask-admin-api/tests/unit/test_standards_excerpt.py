# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The enrichment prompt must carry each layer's rules, and stay a prompt.

``get_standards_excerpt(layer)`` composes the rules injected into the AI
enrichment prompts: `_SHARED.md` for what Silver and Gold have in common, plus
one file per layer. Three things can go wrong, and each has a guard here:

1. **The rules do not arrive.** A path that resolves only in development, an
   empty file, a wheel built without its package data — the model then enriches
   with no rules at all and nothing fails.
2. **A rule is quietly dropped** while editing the prompt down.
3. **The prompt drifts back into a document.** These files replaced 147k
   characters of specification prose that cost ~15k tokens per Silver call. The
   budget ceilings below exist so that regression is loud rather than gradual;
   the normative contract an author reads lives in `definition/docs/`.
"""

import pytest

from ask_admin_api.application.system_prompts_service import get_standards_excerpt

# What each layer's excerpt must still say. Each marker stands for a rule an
# enricher gets wrong without it — not for a turn of phrase. Rewording the
# prose is fine; dropping the rule is what should go red.
SHARED_RULES = [
    "authoritative carrier",  # the principle the whole contract rests on
    "Does it earn its place",  # test 1
    "Is it already carried",  # test 2
    "Do not guess",  # empty beats invented
    "value mapping",  # status_flag description shape
    "never grouped",  # attribute vs dimension
    "load-bearing absence",  # the fact only a description can carry
    "Past 60 words",  # the length symptom
]

LAYER_RULES = {
    "bronze": [
        "never embedded",  # why bronze descriptions stay terse
        "0–1 line",
        "unique within the file",  # alias uniqueness
        "Never normalise aliases",  # the cross-file rule
    ],
    "silver": [
        "Silver preserves codes",  # the layer split
        "enumerate the codes",  # the highest-value silver description
        "when to choose it",  # entity description duty
    ],
    "gold": [
        "business question",  # entity description duty
        "SPARSE",  # sparsity must be stated
        "already denormalized",  # do not join for nothing
    ],
}

# Ceilings, in characters. Roughly 4x the current size of each excerpt, so
# ordinary editing never trips them and pasting a specification back in does.
BUDGET = {"bronze": 8_000, "silver": 20_000, "gold": 20_000}


@pytest.fixture(scope="module")
def excerpts() -> dict[str, str]:
    return {layer: get_standards_excerpt(layer) for layer in ("bronze", "silver", "gold")}


@pytest.mark.parametrize("layer", ["bronze", "silver", "gold"])
def test_standards_are_reachable_wherever_the_process_starts(layer, tmp_path, monkeypatch):
    """The one guard that would have caught the Docker outage.

    The standards used to load from the bare relative path
    ``docs/semantic-layer``, so they resolved only when the interpreter started
    in ``platform/``. Every container (WORKDIR ``/app``, package installed
    non-editably) got an empty excerpt and enriched with no rules at all. The
    old version of this test skipped in exactly that situation, so nothing ever
    went red. Run it from a directory containing no ``docs/`` to prove the
    lookup no longer depends on where the process happens to start.
    """
    get_standards_excerpt.cache_clear()
    monkeypatch.chdir(tmp_path)
    try:
        assert get_standards_excerpt(layer).strip()
    finally:
        get_standards_excerpt.cache_clear()


@pytest.mark.parametrize("layer", ["silver", "gold"])
@pytest.mark.parametrize("marker", SHARED_RULES)
def test_shared_rules_reach_silver_and_gold(excerpts, layer, marker):
    assert marker in excerpts[layer]


@pytest.mark.parametrize("layer", sorted(LAYER_RULES))
def test_layer_rules_reach_their_own_prompt(excerpts, layer):
    missing = [m for m in LAYER_RULES[layer] if m not in excerpts[layer]]
    assert not missing, f"{layer} lost: {missing}"


def test_bronze_does_not_carry_the_silver_gold_contract(excerpts):
    """Bronze writes terse labels; the description contract would only crowd it.

    Scoping is the point of composing per layer — if `_SHARED.md` leaks into
    Bronze, every Bronze enrichment pays for rules it cannot apply.
    """
    assert "authoritative carrier" not in excerpts["bronze"]
    assert "load-bearing absence" not in excerpts["bronze"]


def test_silver_and_gold_do_not_duplicate_each_other(excerpts):
    """What they share is shared, not copied.

    The previous standards repeated ~575 lines across the two files on purpose
    and carried a register of what had to be edited in both. That register was
    drift waiting to happen. Composition replaced it, so any substantial block
    present in both layer-specific files now means the duplication has returned.
    """
    shared = _shared_text()
    assert shared, "silver and gold share no prefix — composition is not happening"

    silver_only = excerpts["silver"].replace(shared, "")
    gold_only = excerpts["gold"].replace(shared, "")

    silver_paras = {p.strip() for p in silver_only.split("\n\n") if len(p.strip()) > 200}
    gold_paras = {p.strip() for p in gold_only.split("\n\n") if len(p.strip()) > 200}
    overlap = silver_paras & gold_paras
    assert not overlap, f"duplicated between silver and gold: {overlap}"


@pytest.mark.parametrize("layer", sorted(BUDGET))
def test_the_prompt_stays_a_prompt(excerpts, layer):
    size = len(excerpts[layer])
    assert size <= BUDGET[layer], (
        f"{layer} excerpt is {size} chars, over its {BUDGET[layer]} ceiling. "
        "Authoring detail belongs in definition/docs/, not in every enrichment call."
    )


def test_unknown_layer_falls_back_to_every_file_once(excerpts):
    combined = get_standards_excerpt(None)
    for layer in ("bronze", "silver", "gold"):
        for marker in LAYER_RULES[layer]:
            assert marker in combined
    # Shared rules appear once, not once per layer that includes them.
    assert combined.count("authoritative carrier") == 1


def _shared_text() -> str:
    """The shared block, recovered as the common prefix of silver and gold."""
    silver, gold = get_standards_excerpt("silver"), get_standards_excerpt("gold")
    end = 0
    for index, (left, right) in enumerate(zip(silver, gold)):
        if left != right:
            break
        end = index + 1
    return silver[:end]

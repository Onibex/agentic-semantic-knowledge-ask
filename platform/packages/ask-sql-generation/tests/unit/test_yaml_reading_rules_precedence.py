"""The structured aggregation keys outrank a field `description`.

Until 2026-08-04 rule 8 closed with the opposite instruction — *"If a field's
`description` states an aggregation OR grouping hazard … obey the description over
the structured keys"*. That was correct when prose was the ONLY carrier: nothing
declared that a stock level repeats on every movement line, so the description had
to. It stopped being correct the moment the fan-out became DERIVED at ingest
(`EntityDeriver.apply_measure_fanout`), because the keys are now computed from the
join graph while the prose is hand-maintained — and the prose was measurably what
kept winning the wrong way (P7 E2E: a curated *"…before summing"* read as
permission, and three rounds of sharper prose moved the failure without closing it).

These tests pin the DIRECTION, not the wording, because the direction is the part a
future prompt edit could silently reverse: a description may TIGHTEN what the keys
allow, never LOOSEN it. The one hazard prose still owns is the technical lifecycle
flag, since no key expresses "filter these rows out".
"""

from __future__ import annotations

import re

from ask_sql_generation.application.freeform_generator import _YAML_READING_RULES

_RULES = _YAML_READING_RULES.lower()


def test_the_structured_keys_are_declared_authoritative() -> None:
    assert "authoritative" in _RULES
    # …and the tie-break is stated explicitly, not left to inference.
    assert "keys win" in _RULES


def test_a_description_may_not_relax_a_key() -> None:
    """The unsafe direction has to be named. A prompt that only says "keys are
    authoritative" leaves a model free to read a permissive sentence as an
    exception, which is exactly how the earlier failures happened."""
    assert "never relax" in _RULES


def test_the_old_description_wins_instruction_is_gone() -> None:
    """Regression guard: the two shapes of the inverted instruction.

    Kept as a literal search because the failure mode is a well-meaning edit that
    re-adds the sentence while "restoring" hazard handling.
    """
    assert "obey the description over" not in _RULES
    assert not re.search(r"description over (?:the )?(?:structured keys|aggregation)", _RULES)


def test_the_lifecycle_flag_exception_survives() -> None:
    """Narrowed, not deleted. `field_role` cannot say "WHERE this out", so the
    deletion/blocking-flag case is the one restriction prose still carries — and
    both standards documents point curators here for it."""
    assert "exclude deleted items" in _RULES


def test_rule_8_still_names_the_four_keys_it_ranks_above_prose() -> None:
    """Authority is only actionable if the keys are named where it is claimed."""
    for key in ("field_role", "aggregation_behavior", "additivity", "non_additive_over"):
        assert key in _RULES, key

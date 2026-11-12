# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: the ClickHouse rules round two decimals, they do not cast.

The bug these pin
─────────────────
Rule 6 asked for CAST(value AS Decimal(18,2)) or toDecimal64(value, 2) for
monetary values. ClickHouse drops the extra digits of a Decimal conversion: in
GONAC's chat of 2026-11-11 (Q04) OXXO's share of DH came out 9.79 where it is
9.80, and ABARROTES MONTERREY's 1.38 where it is 1.39. Measured on ClickHouse
22.1.3.7 with those figures: both casts give 9.79 and 1.38, round() gives 9.8
and 1.39, as the QA's reference SQL (R03) does.
"""

from __future__ import annotations

import re

from ask_sql_generation.application.prompts.registry import get_dialect


def _rule_6() -> str:
    rules = get_dialect("clickhouse").strict_rules
    return re.search(r"^6\. .*?(?=^\d+\. )", rules, re.MULTILINE | re.DOTALL).group(0)


def test_rule_6_rounds_with_round():
    assert "round(value, 2)" in _rule_6()


def test_rule_6_no_longer_offers_a_cast_as_the_way_to_two_decimals():
    rule = _rule_6()
    assert "Never use CAST(... AS Decimal(18,2)) or" in rule
    assert "drops the extra digits instead of rounding them" in rule
    assert not re.search(r"cast with toDecimal64|or CAST\(value AS Decimal", rule)


def test_rule_6_computes_ratios_over_floats_as_the_reference_does():
    assert "over toFloat64(...) of its" in _rule_6()

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The built prompt must carry today's date.

Without it the model invents the year, and a relative window compiles to an
empty interval: `future_date >= today() AND future_date <= toDate('2025-12-31')`
returns zero rows for every question, in silence, because the engine's `today()`
was already 2026. That reads as "no data", never as an error.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from ask_sql_generation.application.freeform_generator import _format_today


def test_carries_today_in_iso_form():
    today = datetime.now(UTC).date().isoformat()
    assert today in _format_today()


def test_marks_the_date_as_utc():
    """The platform keeps every internal timestamp in UTC; say so in the prompt,
    otherwise a model reading a bare date may localise it and shift a day."""
    assert "(UTC)" in _format_today()


def test_forbids_hardcoding_a_year():
    """The failure was a MIX: engine function on one bound, literal year on the
    other. Telling the model to use `today()` was not enough, it already did."""
    text = _format_today().lower()
    assert "never hardcode a year" in text
    assert "both bounds" in text


def test_carries_no_year_literal_of_its_own():
    """A four-digit year anywhere but in today's date would teach the model that
    very year, which is exactly how the IR prompt's `last year` example rotted."""
    text = _format_today()
    today = datetime.now(UTC).date().isoformat()
    assert re.findall(r"\b20\d{2}\b", text.replace(today, "")) == []


def test_computed_per_call_not_frozen_at_import(monkeypatch):
    """The orchestrator process outlives a day, so a module-level constant would
    serve a stale date until the next redeploy."""
    import ask_sql_generation.application.freeform_generator as mod

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2031, 7, 4, tzinfo=tz or UTC)

    monkeypatch.setattr(mod, "datetime", _Frozen)
    assert "2031-07-04" in mod._format_today()

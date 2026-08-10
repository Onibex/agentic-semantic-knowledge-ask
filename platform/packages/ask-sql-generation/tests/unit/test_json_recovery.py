"""Tests for the freeform generator's tolerant JSON recovery.

The LLM occasionally emits invalid JSON whose ``sql`` value contains UNESCAPED
double quotes — SAP HANA identifiers are double-quoted (``"SCHEMA"."TABLE"``)
and the model sometimes forgets to escape them, which prematurely closes the
JSON string ("Unterminated string"). ``_loose_extract_sql_response`` recovers
the SQL by anchoring on the known sibling keys.
"""

from __future__ import annotations

import json

import pytest

from ask_sql_generation.application.freeform_generator import (
    _loose_extract_sql_response,
    _safe_json_loads,
)


def test_recovers_sql_with_unescaped_hana_identifiers():
    # Unescaped double quotes around the HANA schema/table identifiers.
    bad = (
        '{\n  "sql": "SELECT COUNT(*) FROM "MY_SCHEMA"."VBAK" WHERE NETWR > 0",\n'
        '  "explanation": "Counts orders with value"\n}'
    )
    # Both strict + control-char repair must fail (the problem is stray quotes).
    with pytest.raises(json.JSONDecodeError):
        _safe_json_loads(bad)

    recovered = _loose_extract_sql_response(bad)
    assert recovered is not None
    assert recovered["sql"] == 'SELECT COUNT(*) FROM "MY_SCHEMA"."VBAK" WHERE NETWR > 0'
    assert recovered["explanation"] == "Counts orders with value"


def test_recovers_multiline_sql_when_sql_is_last_key():
    bad = '{"sql": "SELECT a,\nb\nFROM "S"."T"", "table_name": "T"}'
    recovered = _loose_extract_sql_response(bad)
    assert recovered is not None
    assert recovered["sql"] == 'SELECT a,\nb\nFROM "S"."T"'


def test_returns_none_on_genuine_truncation():
    # A truncated response (no closing boundary, no sibling key) is NOT
    # recoverable — the caller must still surface a clean parse error.
    truncated = '{\n  "sql": "SELECT COUNT(*) FROM "MY_SCHEMA"."VBAK'
    assert _loose_extract_sql_response(truncated) is None

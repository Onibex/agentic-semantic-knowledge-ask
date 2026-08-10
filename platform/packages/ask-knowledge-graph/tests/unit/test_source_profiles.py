"""Canonical type mapper + source-profile resolution (design §3.1 / OQ#1)."""

import pytest

from ask_knowledge_graph.domain.source_profiles import (
    TypeMapper,
    get_profile,
    list_profiles,
)

_M = TypeMapper()


@pytest.mark.parametrize(
    "raw,expected",
    [
        # SAP inttype + length
        ("C10", "STRING(10)"),
        ("N6", "STRING(6)"),  # numeric text → STRING (preserve leading zeros)
        ("P15", "DECIMAL(15)"),  # packed, no scale in SAP → DECIMAL(15)
        ("D8", "DATE"),
        ("T6", "STRING(6)"),  # time-of-day text (no TIME in the vocab)
        ("I", "INTEGER"),
        ("C", "STRING"),
        # SQL
        ("VARCHAR(20)", "STRING(20)"),
        ("CHAR(3)", "STRING(3)"),
        ("INT", "INTEGER"),
        ("BIGINT", "INTEGER"),
        ("INT4", "INTEGER"),
        ("NUMERIC(15,2)", "DECIMAL(15,2)"),
        ("NUMBER(9,4)", "DECIMAL(9,4)"),
        ("DATETIME", "TIMESTAMP"),
        ("BIT", "BOOLEAN"),
        # Postgres dialect (OneConnect exports) — float8/float4/bpchar/uuid/jsonb
        ("float8", "DECIMAL"),
        ("float4", "DECIMAL"),
        ("bpchar(80)", "STRING(80)"),
        ("bpchar", "STRING"),
        ("int8", "INTEGER"),
        ("int4", "INTEGER"),
        ("varchar(24)", "STRING(24)"),
        ("uuid", "STRING"),
        ("jsonb", "STRING"),
        # canonical (identity)
        ("STRING(10)", "STRING(10)"),
        ("DECIMAL(15,2)", "DECIMAL(15,2)"),
        ("INTEGER", "INTEGER"),
        ("DATE", "DATE"),
        ("TIMESTAMP", "TIMESTAMP"),
        ("BOOLEAN", "BOOLEAN"),
        # unknown / empty → safe STRING fallback
        ("", "STRING"),
        ("weirdtype", "STRING"),
        (None, "STRING"),
    ],
)
def test_canonical(raw, expected):
    assert _M.canonical(raw) == expected


@pytest.mark.parametrize("raw", ["C10", "P15", "VARCHAR(20)", "DECIMAL(15,2)", "DATE", "N6", "BIT"])
def test_idempotent(raw):
    once = _M.canonical(raw)
    assert _M.canonical(once) == once


def test_get_profile_keying():
    assert get_profile("s4h").key == "s4h"
    assert get_profile("s4h_100").key == "s4h"  # first token
    assert get_profile("S4H").key == "s4h"  # case-insensitive
    assert get_profile("ecc").key == "ecc"
    assert get_profile("salesforce").key == "salesforce"
    assert get_profile(None).key == "generic"  # default
    assert get_profile("").key == "generic"
    assert get_profile("oracle").key == "generic"  # unknown → fallback


def test_get_profile_human_label_aliases():
    # Organization.source_system is free text — must still resolve to a profile.
    assert get_profile("SAP S/4HANA 2023").key == "s4h"
    assert get_profile("S/4HANA").key == "s4h"
    assert get_profile("s4hana").key == "s4h"
    assert get_profile("SAP ECC 6.0").key == "ecc"
    assert get_profile("Salesforce Sales Cloud").key == "salesforce"
    assert get_profile("ODOO 17").key == "odoo"
    # exact key still wins over the alias prefixes
    assert get_profile("generic").key == "generic"


def test_list_profiles():
    profs = list_profiles()
    keys = {p["key"] for p in profs}
    assert {"s4h", "ecc", "generic", "salesforce", "odoo"} <= keys
    assert all("label" in p and "key" in p for p in profs)

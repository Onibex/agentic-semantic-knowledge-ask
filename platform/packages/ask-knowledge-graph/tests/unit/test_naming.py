"""domain.naming + infrastructure.naming_config — the column-naming contract.

`normalize_identifier` IS the client-facing rule for ColumnNamingMode.ALIAS
published names (REQ_CURATED_COLUMN_NAMING.md), so its behavior is pinned
here value-by-value; the resolver's precedence (env > settings > default) is
what a misconfigured deployment lives or dies by.
"""

from __future__ import annotations

import pytest

from ask_knowledge_graph.domain.naming import (
    ColumnNamingMode,
    normalize_identifier,
    published_column_name,
)
from ask_knowledge_graph.infrastructure.naming_config import resolve_column_naming_mode

# ── normalize_identifier ─────────────────────────────────────────────────────


def test_accented_spanish_folds_to_ascii():
    assert normalize_identifier("crédito", fallback="f") == "credito"
    assert normalize_identifier("Crédito Total", fallback="f") == "credito_total"
    assert normalize_identifier("año", fallback="f") == "ano"
    assert normalize_identifier("señal", fallback="f") == "senal"
    assert normalize_identifier("Número Documento", fallback="f") == "numero_documento"


def test_clean_snake_case_is_untouched():
    # The contract's happy path: a clean alias passes byte-identical.
    for value in ("documento_ventas", "net_value", "stcd1", "on_", "tel_"):
        assert normalize_identifier(value, fallback="f") == value


def test_punctuation_runs_become_one_underscore():
    assert normalize_identifier("net - value", fallback="f") == "net_value"
    assert normalize_identifier("a/b.c", fallback="f") == "a_b_c"


def test_empty_falls_back_to_fldname():
    assert normalize_identifier("", fallback="NETWR") == "netwr"
    assert normalize_identifier(None, fallback="NETWR") == "netwr"
    assert normalize_identifier("¡¡¡", fallback="NETWR") == "netwr"


def test_idempotent():
    for value in ("Crédito Total", "net value", "año_fiscal"):
        once = normalize_identifier(value, fallback="f")
        assert normalize_identifier(once, fallback="f") == once


def test_upper_variant_for_table_aliases():
    assert normalize_identifier("order header", fallback="VBAK", upper=True) == "ORDER_HEADER"


# ── published_column_name ────────────────────────────────────────────────────


def test_published_column_name_suffixes_lowercased_table():
    assert published_column_name("documento_ventas", "VBAK") == "documento_ventas_vbak"
    assert published_column_name("net_value", "vbak") == "net_value_vbak"


# ── resolve_column_naming_mode ───────────────────────────────────────────────


def test_default_is_technical(monkeypatch):
    monkeypatch.delenv("ASK_COLUMN_NAMING", raising=False)
    assert resolve_column_naming_mode({}) is ColumnNamingMode.TECHNICAL


def test_settings_key_is_read(monkeypatch):
    monkeypatch.delenv("ASK_COLUMN_NAMING", raising=False)
    cfg = {"ingestion": {"column_naming": "alias"}}
    assert resolve_column_naming_mode(cfg) is ColumnNamingMode.ALIAS


def test_env_beats_settings(monkeypatch):
    monkeypatch.setenv("ASK_COLUMN_NAMING", "technical")
    cfg = {"ingestion": {"column_naming": "alias"}}
    assert resolve_column_naming_mode(cfg) is ColumnNamingMode.TECHNICAL


def test_env_value_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("ASK_COLUMN_NAMING", "  ALIAS ")
    assert resolve_column_naming_mode({}) is ColumnNamingMode.ALIAS


def test_invalid_value_raises_instead_of_defaulting(monkeypatch):
    monkeypatch.setenv("ASK_COLUMN_NAMING", "business")
    with pytest.raises(ValueError, match="business"):
        resolve_column_naming_mode({})
    monkeypatch.delenv("ASK_COLUMN_NAMING")
    with pytest.raises(ValueError, match="sap"):
        resolve_column_naming_mode({"ingestion": {"column_naming": "sap"}})

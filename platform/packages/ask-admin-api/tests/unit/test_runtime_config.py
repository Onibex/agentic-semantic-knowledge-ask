"""Tolerant config reading (BACKLOG group 0, P1).

`config/settings.json` is gitignored, so a fresh clone has none. That absence
must degrade to `{}` with one clear warning — it used to surface as
`'NoneType' object has no attribute 'get'` on an unrelated catalog endpoint, and
as a RuntimeError from the PublishService constructor.
"""

from __future__ import annotations

import json

from ask_admin_api.application.runtime_config import (
    config_status,
    load_runtime_config,
    log_config_status,
)


def test_missing_file_returns_empty_dict_not_none(tmp_path):
    cfg = load_runtime_config(tmp_path / "nope.json")
    assert cfg == {}
    # The crash this prevents: a caller doing config.get(...) on the result.
    assert cfg.get("opensearch") is None


def test_valid_file_is_read(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"opensearch": {"host": "os"}, "schema_mode": "yaml"}))
    cfg = load_runtime_config(p)
    assert cfg["opensearch"]["host"] == "os"


def test_malformed_json_degrades_instead_of_raising(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    assert load_runtime_config(p) == {}


def test_non_mapping_root_degrades(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("[1, 2, 3]")
    assert load_runtime_config(p) == {}


def test_status_reports_resolved_path_and_cwd(tmp_path):
    p = tmp_path / "settings.json"
    st = config_status(p)
    assert st["present"] is False
    assert st["parseable"] is False
    # The two facts that make "must run from project root" diagnosable.
    assert st["resolved_path"].endswith("settings.json")
    assert st["cwd"]

    p.write_text(json.dumps({"b": 1, "a": 2}))
    st = config_status(p)
    assert st["present"] is True
    assert st["parseable"] is True
    assert st["sections"] == ["a", "b"]  # sorted


def test_log_config_status_never_raises_and_returns_status(tmp_path, caplog):
    st = log_config_status(tmp_path / "absent.json")
    assert st["present"] is False
    assert any("ABSENT" in r.message or "ABSENT" in str(r.msg) for r in caplog.records)


def test_admin_api_load_config_helpers_tolerate_absence(tmp_path, monkeypatch):
    """Every duplicated `_load_config()` in admin-api must degrade, not raise —
    each one used to be its own 500 on a fresh clone."""
    monkeypatch.chdir(tmp_path)  # no config/ dir here at all
    from ask_admin_api.application import publish_service
    from ask_admin_api.routers import docs, embeddings, yaml_ingestion

    assert yaml_ingestion._load_config() == {}
    assert embeddings._load_config() == {}
    assert docs._load_config() == {}
    assert publish_service._load_config() == {}

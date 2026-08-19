# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for `ask_orchestrator.config.SettingsCache`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ask_orchestrator.config import SettingsCache


@pytest.fixture(autouse=True)
def _isolate_cache():
    SettingsCache.invalidate()
    yield
    SettingsCache.invalidate()


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_get_reads_once_and_caches(tmp_path):
    path = _write(tmp_path, {"db_type": "hana"})

    first = SettingsCache.get(path)
    # Mutate the file on disk; cached read must NOT see the change.
    path.write_text(json.dumps({"db_type": "postgresql"}), encoding="utf-8")
    second = SettingsCache.get(path)

    assert first is second
    assert second["db_type"] == "hana"


def test_invalidate_path_forces_reread(tmp_path):
    path = _write(tmp_path, {"db_type": "hana"})
    SettingsCache.get(path)

    path.write_text(json.dumps({"db_type": "postgresql"}), encoding="utf-8")
    SettingsCache.invalidate(path)

    assert SettingsCache.get(path)["db_type"] == "postgresql"


def test_invalidate_all_clears_every_entry(tmp_path):
    p1 = _write(tmp_path / "a.json" if False else tmp_path, {"v": 1})  # uses default file
    # second cached path
    p2 = tmp_path / "second.json"
    p2.write_text(json.dumps({"v": 2}), encoding="utf-8")

    SettingsCache.get(p1)
    SettingsCache.get(p2)
    SettingsCache.invalidate()

    # Both entries gone — next get re-reads.
    p1.write_text(json.dumps({"v": 11}), encoding="utf-8")
    p2.write_text(json.dumps({"v": 22}), encoding="utf-8")

    assert SettingsCache.get(p1)["v"] == 11
    assert SettingsCache.get(p2)["v"] == 22

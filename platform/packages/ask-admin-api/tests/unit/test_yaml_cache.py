"""Parse-once catalog cache in YAMLFileService.

The read path (list_yamls / get_yaml / get_yamls_by_ids) used to rglob + parse
the WHOLE workspace on every call, so a canvas "+" burst re-scanned every file
many times. The service now parses once and reuses the result until the
workspace changes (a stat-only mtime/size signature) or a local write
invalidates it. These tests pin: (1) reads are correct off the cache, (2) the
cache rebuilds when files are added/removed (signature), and (3) a mutation
(delete_yaml) is reflected immediately.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ask_admin_api.application.yaml_file_service import YAMLFileService, YAMLNotFoundError


def _svc(tmp_path: Path) -> YAMLFileService:
    ws = tmp_path / "workspace" / "ask"
    ws.mkdir(parents=True)
    return YAMLFileService(workspace_path=str(ws), repo_root=str(tmp_path))


def _write_silver(ws: Path, entity_id: str, name: str) -> Path:
    """Write a minimal-but-parseable silver YAML straight to disk (bypassing the
    service) — simulates an external change the cache must detect via signature."""
    p = ws / f"{name}.yaml"
    p.write_text(
        textwrap.dedent(f"""\
            id: {entity_id}
            layer: silver
            module: sd
            name: {name}
            fields: []
        """),
        encoding="utf-8",
    )
    return p


def test_reads_off_cache_and_rebuilds_on_add(tmp_path):
    svc = _svc(tmp_path)
    ws = tmp_path / "workspace" / "ask"
    _write_silver(ws, "silver_a", "a")

    # First read builds the cache.
    assert {s.id for s in svc.list_yamls()} == {"silver_a"}
    assert svc.get_yaml("silver_a").id == "silver_a"

    # A new file changes the workspace signature → next read rebuilds. External
    # changes are only guaranteed visible after the signature TTL; expire the
    # gate to model that window elapsing (local writes invalidate explicitly).
    _write_silver(ws, "silver_b", "b")
    svc._sig_checked_at = 0.0
    assert {s.id for s in svc.list_yamls()} == {"silver_a", "silver_b"}
    assert {n.id for n in svc.get_yamls_by_ids({"silver_a", "silver_b"})} == {
        "silver_a",
        "silver_b",
    }


def test_rebuilds_on_external_removal(tmp_path):
    svc = _svc(tmp_path)
    ws = tmp_path / "workspace" / "ask"
    pa = _write_silver(ws, "silver_a", "a")
    _write_silver(ws, "silver_b", "b")
    assert len(svc.list_yamls()) == 2  # populate cache

    pa.unlink()  # external removal — visible once the signature TTL elapses
    svc._sig_checked_at = 0.0
    assert {s.id for s in svc.list_yamls()} == {"silver_b"}
    with pytest.raises(YAMLNotFoundError):
        svc.get_yaml("silver_a")


def test_delete_yaml_invalidates_immediately(tmp_path):
    svc = _svc(tmp_path)
    ws = tmp_path / "workspace" / "ask"
    _write_silver(ws, "silver_a", "a")
    assert svc.get_yaml("silver_a").id == "silver_a"  # cache built

    removed = svc.delete_yaml("silver_a")
    assert removed is not None
    # The mutator invalidated the cache → the entity is gone without a refresh.
    assert svc.list_yamls() == []
    with pytest.raises(YAMLNotFoundError):
        svc.get_yaml("silver_a")


def test_get_yamls_by_ids_preserves_sorted_order(tmp_path):
    svc = _svc(tmp_path)
    ws = tmp_path / "workspace" / "ask"
    _write_silver(ws, "silver_c", "c")
    _write_silver(ws, "silver_a", "a")
    _write_silver(ws, "silver_b", "b")
    # Asking in arbitrary order returns them in workspace sorted-file order
    # (a, b, c — file names), matching the old single-pass behaviour.
    ids = [n.id for n in svc.get_yamls_by_ids({"silver_b", "silver_c", "silver_a"})]
    assert ids == ["silver_a", "silver_b", "silver_c"]

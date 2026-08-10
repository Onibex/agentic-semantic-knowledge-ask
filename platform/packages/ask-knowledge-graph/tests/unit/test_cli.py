"""Tests for the ask-kg CLI — service factory is monkey-patched."""

from __future__ import annotations

import pytest

from ask_knowledge_graph import cli
from ask_knowledge_graph.domain.models import IngestionResult


class _StubService:
    def __init__(self, *, ingest_results=None, delete_result=None, ingest_raises=None):
        self.ingest_calls: list[str] = []
        self.delete_calls: list[str] = []
        self._ingest_results = ingest_results or [
            IngestionResult(
                entity_id="silver_x",
                layer="silver",
                entities_indexed=1,
                fields_indexed=5,
                edges_indexed=2,
            )
        ]
        self._delete_result = delete_result or IngestionResult(
            entity_id="silver_x",
            entities_indexed=-1,
            fields_indexed=-5,
            edges_indexed=-2,
        )
        self._ingest_raises = ingest_raises
        self._idx = 0

    def ingest_yaml(self, request):
        self.ingest_calls.append(request.yaml_content)
        if self._ingest_raises:
            raise self._ingest_raises
        result = self._ingest_results[self._idx % len(self._ingest_results)]
        self._idx += 1
        return result

    def delete_entity(self, entity_id):
        self.delete_calls.append(entity_id)
        return self._delete_result


def _patch_service(monkeypatch, service):
    monkeypatch.setattr(cli, "_build_service", lambda: service)


# ─────────────────────────────────────────────────────────────────────────────
# argparse smoke
# ─────────────────────────────────────────────────────────────────────────────
def test_help_prints_usage(capsys):
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    out = capsys.readouterr().out
    assert "ask-kg" in out
    assert "ingest" in out
    assert "delete" in out


def test_missing_subcommand_errors(capsys):
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


# ─────────────────────────────────────────────────────────────────────────────
# ingest
# ─────────────────────────────────────────────────────────────────────────────
def test_ingest_happy_path(tmp_path, monkeypatch, capsys):
    yaml_file = tmp_path / "silver_x.yaml"
    yaml_file.write_text("id: silver_x\nlayer: silver\n", encoding="utf-8")
    svc = _StubService()
    _patch_service(monkeypatch, svc)

    rc = cli.main(["ingest", str(yaml_file)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "silver_x" in out
    assert "✅" in out
    assert svc.ingest_calls == ["id: silver_x\nlayer: silver\n"]


def test_ingest_missing_file_returns_2(tmp_path, monkeypatch, capsys):
    _patch_service(monkeypatch, _StubService())
    rc = cli.main(["ingest", str(tmp_path / "doesnotexist.yaml")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "is not a file" in err


def test_ingest_error_returns_1(tmp_path, monkeypatch, capsys):
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text("garbage", encoding="utf-8")
    svc = _StubService(ingest_results=[IngestionResult(error="boom", entity_id=None, layer=None)])
    _patch_service(monkeypatch, svc)

    rc = cli.main(["ingest", str(yaml_file)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "boom" in err


# ─────────────────────────────────────────────────────────────────────────────
# ingest-dir
# ─────────────────────────────────────────────────────────────────────────────
def test_ingest_dir_processes_each_yaml(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.yaml").write_text("id: a\nlayer: silver\n", encoding="utf-8")
    (tmp_path / "b.yml").write_text("id: b\nlayer: gold\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not yaml", encoding="utf-8")

    svc = _StubService(
        ingest_results=[
            IngestionResult(entity_id="a", layer="silver", entities_indexed=1),
            IngestionResult(entity_id="b", layer="gold", entities_indexed=1),
        ]
    )
    _patch_service(monkeypatch, svc)

    rc = cli.main(["ingest-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 succeeded" in out
    assert "0 failed" in out
    assert len(svc.ingest_calls) == 2


def test_ingest_dir_with_no_yamls_warns(tmp_path, monkeypatch, capsys):
    (tmp_path / "readme.txt").write_text("nothing", encoding="utf-8")
    _patch_service(monkeypatch, _StubService())
    rc = cli.main(["ingest-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 0
    assert "no .yaml" in err


def test_ingest_dir_partial_failure_returns_1(tmp_path, monkeypatch, capsys):
    (tmp_path / "ok.yaml").write_text("id: ok", encoding="utf-8")
    (tmp_path / "bad.yaml").write_text("id: bad", encoding="utf-8")
    svc = _StubService(
        ingest_results=[
            IngestionResult(entity_id="ok", layer="silver", entities_indexed=1),
            IngestionResult(error="parse failed"),
        ]
    )
    _patch_service(monkeypatch, svc)
    rc = cli.main(["ingest-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "1 succeeded" in out
    assert "1 failed" in out


def test_ingest_dir_missing_directory_returns_2(monkeypatch, capsys):
    _patch_service(monkeypatch, _StubService())
    rc = cli.main(["ingest-dir", "/nonexistent/path"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "is not a directory" in err


# ─────────────────────────────────────────────────────────────────────────────
# delete
# ─────────────────────────────────────────────────────────────────────────────
def test_delete_happy_path(monkeypatch, capsys):
    svc = _StubService()
    _patch_service(monkeypatch, svc)
    rc = cli.main(["delete", "silver_x"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "silver_x" in out
    assert svc.delete_calls == ["silver_x"]


def test_delete_error_returns_1(monkeypatch, capsys):
    svc = _StubService(delete_result=IngestionResult(error="not found"))
    _patch_service(monkeypatch, svc)
    rc = cli.main(["delete", "ghost"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "not found" in err


# ─────────────────────────────────────────────────────────────────────────────
# backfill-types (file-only; no service)
# ─────────────────────────────────────────────────────────────────────────────
_SILVER_YAML = """\
id: silver_s4h_sd_demo
layer: silver
source_system: s4h
module: sd
name: demo
fields:
  - name: amt
    source: T.AMT
    type: P15
  - name: doc
    source: T.DOC
    type: C10
"""


def test_backfill_types_dry_run_does_not_write(tmp_path, capsys):
    f = tmp_path / "demo.yaml"
    f.write_text(_SILVER_YAML, encoding="utf-8")
    rc = cli.main(["backfill-types", str(f), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "P15 -> DECIMAL(15)" in out
    assert "C10 -> STRING(10)" in out
    assert f.read_text(encoding="utf-8") == _SILVER_YAML  # unchanged


def test_backfill_types_writes_canonical_and_is_idempotent(tmp_path, capsys):
    f = tmp_path / "demo.yaml"
    f.write_text(_SILVER_YAML, encoding="utf-8")
    assert cli.main(["backfill-types", str(f)]) == 0
    written = f.read_text(encoding="utf-8")
    assert "DECIMAL(15)" in written and "STRING(10)" in written
    assert "P15" not in written and "C10" not in written
    # second run is a no-op (idempotent)
    cli.main(["backfill-types", str(f)])
    out = capsys.readouterr().out
    assert "changed 0 field type(s)" in out

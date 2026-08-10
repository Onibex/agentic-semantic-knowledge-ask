"""Full DataProduct delete primitives — workspace YAML removal + business-domain
membership cleanup (so a deleted entity disappears from the catalog + canvases)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

from ask_admin_api.application.workspace_service import WorkspaceService
from ask_admin_api.application.yaml_file_service import YAMLFileService

_SILVER = textwrap.dedent("""\
    id: silver_s4h_sd_demo
    layer: silver
    source_system: s4h
    module: sd
    name: demo
    classification: T
    description: A demo silver
    composed_of: [bronze_s4h_t_t]
    fields:
      - name: doc
        source: T.DOC
        field_role: identifier
        type: C10
        description: doc id
""")


def _svc(tmp_path: Path) -> YAMLFileService:
    ws = tmp_path / "workspace" / "ask"
    ws.mkdir(parents=True)
    return YAMLFileService(workspace_path=str(ws), repo_root=str(tmp_path))


def test_delete_yaml_removes_file(tmp_path):
    svc = _svc(tmp_path)
    svc.import_yaml(_SILVER)
    p = tmp_path / "workspace" / "ask" / "s4h" / "silver" / "sd" / "demo.yaml"
    assert p.exists()

    rel = svc.delete_yaml("silver_s4h_sd_demo")
    assert rel is not None
    assert not p.exists()
    # idempotent — second call is a no-op
    assert svc.delete_yaml("silver_s4h_sd_demo") is None


# ── business-domain membership cleanup ────────────────────────────────────────


def _bd(bd_id: str, dps: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=bd_id,
        workspace_id="ws-1",
        slug=f"slug-{bd_id}",
        name=f"BD {bd_id}",
        description="",
        data_product_ids=dps,
        created_at="t0",
        created_by="u",
        updated_at="t0",
        updated_by="u",
    )


class _FakeWsRepo:
    def __init__(self, bds: list[SimpleNamespace]) -> None:
        self._bds = bds
        self.updates: list[tuple[str, dict]] = []

    def list_all_business_domains(self):
        return self._bds

    def update_business_domain(self, bd_id: str, doc: dict):
        self.updates.append((bd_id, doc))
        return SimpleNamespace(id=bd_id, **doc)


def test_remove_data_product_everywhere():
    bds = [
        _bd("a", ["silver_x", "silver_y"]),
        _bd("b", ["silver_y"]),  # does not contain silver_x → untouched
        _bd("c", ["silver_x"]),
    ]
    repo = _FakeWsRepo(bds)
    n = WorkspaceService(repo).remove_data_product_everywhere("silver_x")

    assert n == 2  # only a + c contained it
    assert {bid for bid, _ in repo.updates} == {"a", "c"}
    for _, doc in repo.updates:
        assert "silver_x" not in doc["data_product_ids"]
    # the unrelated member survives in BD "a"
    a_doc = next(doc for bid, doc in repo.updates if bid == "a")
    assert a_doc["data_product_ids"] == ["silver_y"]

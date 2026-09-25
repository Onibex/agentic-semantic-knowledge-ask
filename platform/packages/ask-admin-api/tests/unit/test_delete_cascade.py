# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Full DataProduct delete primitives — workspace YAML removal + business-domain
membership cleanup (so a deleted entity disappears from the catalog + canvases)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

from git import Repo

from ask_admin_api.application.git_service import GitService
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


# ── the sidecars leave with the YAML ─────────────────────────────────────────


def test_delete_takes_the_sidecars_out_of_git_with_the_yaml(tmp_path):
    """Measured on Kyma on 2026-09-24: a deleted Data Product left its enrichments
    sidecar behind. Imports now commit it, so it would stay on main for good, and
    a later Data Product with the same id would read it back."""
    Repo.init(tmp_path)
    svc = _svc(tmp_path)
    git = GitService(repo_root=str(tmp_path))
    svc.import_yaml(_SILVER, git_service=git, author_email="t@x.com")
    (tmp_path / ".sap_baseline" / "silver_s4h_sd_demo.conflicts.json").write_text("[]")
    git.commit(
        [".sap_baseline/silver_s4h_sd_demo.conflicts.json"],
        "merge(silver_s4h_sd_demo): conflicts found",
        "t",
        "t@x.com",
    )

    svc.delete_yaml("silver_s4h_sd_demo", git_service=git, author_email="t@x.com")

    assert git.repo.head.commit.message == "viz: delete silver_s4h_sd_demo"
    assert sorted(
        git.repo.git.diff_tree("--no-commit-id", "--name-status", "-r", "HEAD").splitlines()
    ) == [
        "D\t.sap_baseline/silver_s4h_sd_demo.conflicts.json",
        "D\t.sap_baseline/silver_s4h_sd_demo.enrichments.json",
        "D\tworkspace/ask/s4h/silver/sd/demo.yaml",
    ]
    assert git.repo.git.status("--porcelain") == ""


def test_delete_commits_the_yaml_removal_when_its_sidecar_was_never_committed(tmp_path):
    """The case left on Kyma: a YAML imported before sidecars were committed has
    an untracked one, and most Data Products have no conflicts sidecar. git rm
    refuses a whole list over one path it never tracked, and the YAML in that
    list would stay committed."""
    Repo.init(tmp_path)
    svc = _svc(tmp_path)
    git = GitService(repo_root=str(tmp_path))
    svc.import_yaml(_SILVER)
    git.commit(
        ["workspace/ask/s4h/silver/sd/demo.yaml"],
        "viz: import silver_s4h_sd_demo from manual upload",
        "t",
        "t@x.com",
    )

    svc.delete_yaml("silver_s4h_sd_demo", git_service=git, author_email="t@x.com")

    assert git.repo.git.ls_tree("-r", "--name-only", "HEAD") == ""
    assert git.repo.git.status("--porcelain") == ""


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

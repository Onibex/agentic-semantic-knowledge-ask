# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""GitService §3.6 branch ops (UX_CHANGES audit, Iter 2) — real tmp git repo.

Proves the publish mechanic (audit §3.2/§3.3): publishing a file onto a release
branch moves ONLY that file and never merges, so unrelated working changes
can't leak across environments. The env branches start empty and are written
without a checkout, so the working tree, the index and HEAD never move.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ask_admin_api.application.git_service import GitService

_FP = "silver/sd/sales_order.yaml"
_PUBLISH_DEV = "publish-dev(silver_sales): by t@x.com"


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _files_on(svc: GitService, branch: str) -> list[str]:
    listing = svc.repo.git.ls_tree("-r", "--name-only", branch)
    return listing.splitlines() if listing else []


def _edit_on_main(svc: GitService, repo: Path, content: str) -> None:
    from git import Actor

    _write(repo, _FP, content)
    svc.repo.index.add([_FP])
    actor = Actor("t", "t@x.com")
    svc.repo.index.commit("edit on main", author=actor, committer=actor)


def _publish_dev(svc: GitService, paths: list[str] | None = None) -> str | None:
    return svc.publish_paths("dev", "main", paths or [_FP], _PUBLISH_DEV, "t", "t@x.com")


@pytest.fixture
def git_repo(tmp_path: Path) -> GitService:
    """A fresh git repo (outside the code tree) with one commit on main."""
    from git import Actor, Repo

    repo = Repo.init(tmp_path)
    _write(tmp_path, _FP, "id: silver_sales\nv: 1\n")
    _write(tmp_path, "bronze/vbak.yaml", "id: bronze_vbak\nv: 1\n")
    _write(tmp_path, "unrelated.yaml", "id: other\nv: 1\n")
    repo.index.add([_FP, "bronze/vbak.yaml", "unrelated.yaml"])
    actor = Actor("t", "t@x.com")
    repo.index.commit("init", author=actor, committer=actor)
    repo.git.branch("-M", "main")  # normalise branch name across git defaults
    return GitService(repo_root=str(tmp_path))


def test_init_release_branches_creates_empty_dev_prod(git_repo):
    created = git_repo.init_release_branches()
    assert set(created) == {"dev", "prod"}
    assert set(git_repo.list_branches()) >= {"main", "dev", "prod"}
    # Born empty: nothing is published yet, so neither holds a file.
    assert _files_on(git_repo, "dev") == []
    assert _files_on(git_repo, "prod") == []
    # Idempotent: a second call creates nothing.
    assert git_repo.init_release_branches() == []


def test_init_release_branches_normalizes_master_to_main(tmp_path):
    """A repo on the git-default ``master`` is renamed to ``main`` at init.

    Reproduces the live finding: ``git init`` yields ``master`` but publish
    hardcodes ``main`` (env_targets.WORKING_BRANCH). init_release_branches must
    self-heal so publish does not fail with ``invalid reference: main``.
    """
    from git import Actor, Repo

    repo = Repo.init(tmp_path)
    _write(tmp_path, _FP, "id: silver_sales\nv: 1\n")
    repo.index.add([_FP])
    actor = Actor("t", "t@x.com")
    repo.index.commit("init", author=actor, committer=actor)
    repo.git.branch("-M", "master")  # force the git-default name regardless of host config

    svc = GitService(repo_root=str(tmp_path))
    assert svc.repo.active_branch.name == "master"

    created = svc.init_release_branches()
    assert set(created) == {"dev", "prod"}
    assert svc.repo.active_branch.name == "main"  # renamed, HEAD followed
    assert "master" not in set(svc.list_branches())


def test_normalize_working_branch_noop_when_main_exists(git_repo):
    """If ``main`` already exists, normalisation never touches branches."""
    git_repo.init_release_branches()
    before = set(git_repo.list_branches())
    git_repo._normalize_working_branch()
    assert set(git_repo.list_branches()) == before
    assert git_repo.repo.active_branch.name == "main"


def test_truly_empty_repo_gets_empty_env_branches_and_keeps_unborn_head(tmp_path):
    """A repo with NO files and NO commits, as a new install's volume is at its
    first boot: nothing to seed on main, but dev/prod exist, empty, so the first
    publish has a branch to land on."""
    from git import Repo

    Repo.init(tmp_path)
    svc = GitService(repo_root=str(tmp_path))
    assert set(svc.init_release_branches()) == {"dev", "prod"}
    assert not svc.repo.head.is_valid()  # still unborn: nothing was committed
    assert _files_on(svc, "dev") == []


def test_auto_init_creates_repo_when_flag_set(tmp_path, monkeypatch):
    """From-zero (BACKLOG B P1): a workspace dir with YAMLs but NO .git at all.

    With SEMANTIC_LAYER_AUTO_INIT on, GitService initialises the repo EXACTLY
    at repo_root and the existing bootstrap chain (seed commit + master→main +
    empty dev/prod) makes it publish-ready in the same boot. Without the flag,
    the old warn-and-no-op behaviour is preserved (host-side safety: never
    surprise-init a workspace nested inside a code checkout).
    """
    _write(tmp_path, "s4h/silver/sd/sales_order.yaml", "id: silver_sales\nv: 1\n")

    # Flag off → old behaviour: no repo, ops no-op.
    monkeypatch.delenv("SEMANTIC_LAYER_AUTO_INIT", raising=False)
    assert GitService(repo_root=str(tmp_path)).repo is None
    assert not (tmp_path / ".git").exists()

    # Flag on → repo initialised at repo_root; full bootstrap follows.
    monkeypatch.setenv("SEMANTIC_LAYER_AUTO_INIT", "true")
    svc = GitService(repo_root=str(tmp_path))
    assert svc.repo is not None
    assert (tmp_path / ".git").is_dir()

    created = svc.init_release_branches()
    assert set(created) == {"dev", "prod"}
    assert svc.repo.active_branch.name == "main"
    assert "v: 1" in svc.get_file_at_commit("s4h/silver/sd/sales_order.yaml", "main")
    assert _files_on(svc, "dev") == []


def test_init_release_branches_auto_seeds_repo_with_files_no_commit(tmp_path):
    """From-zero: a `git init`'d repo with files staged but NO commit (unborn
    HEAD) must auto-seed a root commit on main, so a publish has something to
    read. Reproduces the live EC2 finding."""
    from git import Repo

    repo = Repo.init(tmp_path)
    _write(tmp_path, "s4h/silver/sd/sales_order.yaml", "id: silver_sales\nv: 1\n")
    repo.index.add(["s4h/silver/sd/sales_order.yaml"])  # staged, NOT committed
    assert not repo.head.is_valid()  # unborn HEAD

    svc = GitService(repo_root=str(tmp_path))
    created = svc.init_release_branches()

    assert set(created) == {"dev", "prod"}
    assert svc.repo.active_branch.name == "main"  # seeded commit + master→main normalised
    assert set(svc.list_branches()) >= {"main", "dev", "prod"}
    # the seeded commit carries the staged file; the env branches do not copy it
    assert "v: 1" in svc.get_file_at_commit("s4h/silver/sd/sales_order.yaml", "main")
    assert _files_on(svc, "dev") == []


def test_with_pipe_recovery_retries_once_on_broken_pipe(git_repo):
    """A dead git child (BrokenPipeError) on attempt 1 → the Repo is rebuilt and
    the op runs again. The second attempt succeeds."""
    attempts = {"n": 0}

    def op():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise BrokenPipeError("git cat-file child died")
        return "ok"

    assert git_repo._with_pipe_recovery(op) == "ok"
    assert attempts["n"] == 2  # retried exactly once
    assert git_repo.repo is not None  # Repo was rebuilt, still usable


def test_with_pipe_recovery_swallows_other_errors(git_repo):
    """Non-pipe errors keep the old behaviour: logged + swallowed → None, no retry."""
    attempts = {"n": 0}

    def op():
        attempts["n"] += 1
        raise ValueError("boom")

    assert git_repo._with_pipe_recovery(op) is None
    assert attempts["n"] == 1  # NOT retried


def test_publish_paths_moves_only_listed_paths(git_repo):
    """Publish the silver to dev: unrelated.yaml must NOT reach dev."""
    git_repo.init_release_branches()

    assert _publish_dev(git_repo)
    assert _files_on(git_repo, "dev") == [_FP]
    assert "v: 1" in git_repo.get_file_at_commit(_FP, "dev")


def test_publish_paths_leaves_working_tree_index_and_head_alone(git_repo, tmp_path):
    """No checkout and no stash: an uncommitted edit stays exactly as it was,
    and neither the real index nor HEAD moves."""
    git_repo.init_release_branches()
    _write(tmp_path, "unrelated.yaml", "id: other\nv: draft\n")  # the admin's uncommitted edit
    status_before = git_repo.repo.git.status("--porcelain")
    index_before = (tmp_path / ".git" / "index").read_bytes()

    assert _publish_dev(git_repo)

    assert (tmp_path / ".git" / "index").read_bytes() == index_before
    assert git_repo.repo.git.symbolic_ref("HEAD") == "refs/heads/main"
    assert git_repo.repo.git.status("--porcelain") == status_before
    assert (tmp_path / "unrelated.yaml").read_text(encoding="utf-8") == "id: other\nv: draft\n"


def test_first_publish_of_an_unedited_file_is_recorded(git_repo):
    """The 2026-09-24 Kyma finding: Data Products uploaded, then published with
    no edit in between. That publish must leave its commit, and the dev tab
    must show it."""
    git_repo.init_release_branches()

    assert _publish_dev(git_repo)

    dev_log = git_repo.get_log(_FP, branch="dev", message_prefix="publish-dev(")
    assert [c.message for c in dev_log] == [_PUBLISH_DEV]
    assert dev_log[0].author_email == "t@x.com"


def test_publish_paths_noop_when_identical(git_repo):
    git_repo.init_release_branches()
    first = _publish_dev(git_repo)
    assert first
    # Same content again: no empty commit, and the branch does not move.
    assert _publish_dev(git_repo) is None
    assert git_repo.repo.git.rev_parse("dev") == first


def test_unpublish_paths_removes_only_listed_paths(git_repo):
    git_repo.init_release_branches()
    _publish_dev(git_repo, [_FP, "bronze/vbak.yaml"])

    sha = git_repo.unpublish_paths(
        "dev", [_FP], "unpublish-dev(silver_sales): removed by t@x.com", "t", "t@x.com"
    )

    assert sha
    assert _files_on(git_repo, "dev") == ["bronze/vbak.yaml"]
    assert git_repo.file_sha_on_branch("main", _FP) is not None  # main is untouched


def test_file_sha_on_branch(git_repo):
    git_repo.init_release_branches()
    fp = "bronze/vbak.yaml"
    assert git_repo.file_sha_on_branch("dev", fp) is None  # nothing published yet
    git_repo.publish_paths(
        "dev", "main", [fp], "publish-dev(bronze_vbak): by t@x.com", "t", "t@x.com"
    )
    sha_main = git_repo.file_sha_on_branch("main", fp)
    assert sha_main and sha_main == git_repo.file_sha_on_branch("dev", fp)
    assert git_repo.file_sha_on_branch("main", "does/not/exist.yaml") is None


def test_branch_scoped_history_isolates_publish_commits(git_repo, tmp_path):
    """get_log(branch=dev, message_prefix=publish-dev() shows ONLY the dev
    deploys, one per publish, and never the edits on main (§4.4)."""
    git_repo.init_release_branches()
    _publish_dev(git_repo)
    _edit_on_main(git_repo, tmp_path, "id: silver_sales\nv: 2\n")
    _publish_dev(git_repo)

    # dev tab: the two publish-dev commits, nothing else.
    dev_log = git_repo.get_log(_FP, branch="dev", message_prefix="publish-dev(")
    assert len(dev_log) == 2
    assert git_repo.get_total_count(_FP, branch="dev", message_prefix="publish-dev(") == 2

    # prod tab: nothing published to prod yet.
    assert git_repo.get_log(_FP, branch="prod", message_prefix="publish-prod(") == []

    # working tab: the real edits are present; the publishes live on dev.
    work_log = git_repo.get_log(_FP, branch="main", entity_id="silver_sales")
    assert any("edit on main" in c.message for c in work_log)
    assert not any(c.message.startswith("publish-dev(") for c in work_log)


# ── Repair of env branches cut as copies of main ─────────────────────────────


def _cut_as_copies(svc: GitService) -> None:
    """What init_release_branches did before 2026-09-24: dev/prod at main's tip."""
    main = svc.repo.heads.main.commit
    svc.repo.create_head("dev", main)
    svc.repo.create_head("prod", main)


def test_reset_starts_unrecorded_copies_again_empty_and_keeps_a_backup(git_repo):
    _cut_as_copies(git_repo)
    old_tip = git_repo.repo.git.rev_parse("dev")

    assert set(git_repo.reset_unrecorded_release_branches()) == {"dev", "prod"}

    assert _files_on(git_repo, "dev") == []
    assert _files_on(git_repo, "prod") == []
    backups = git_repo.repo.git.for_each_ref(
        "--format=%(refname) %(objectname)", "refs/backup/"
    ).splitlines()
    assert len(backups) == 2
    assert all(line.endswith(old_tip) for line in backups)
    # Idempotent: an empty branch is left alone.
    assert git_repo.reset_unrecorded_release_branches() == []


def test_reset_never_touches_a_branch_with_a_publish_record(git_repo, tmp_path):
    _cut_as_copies(git_repo)
    _edit_on_main(git_repo, tmp_path, "id: silver_sales\nv: 2\n")
    assert _publish_dev(git_repo)  # a real change onto the copy: recorded
    dev_tip = git_repo.repo.git.rev_parse("dev")

    assert git_repo.reset_unrecorded_release_branches() == ["prod"]
    assert git_repo.repo.git.rev_parse("dev") == dev_tip


def test_reset_leaves_the_checked_out_branch_alone(git_repo):
    _cut_as_copies(git_repo)
    git_repo.repo.git.checkout("dev")

    assert git_repo.reset_unrecorded_release_branches() == ["prod"]
    assert "unrelated.yaml" in _files_on(git_repo, "dev")

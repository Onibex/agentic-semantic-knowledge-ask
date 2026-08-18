# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for GitService using a real temp git repo."""

from __future__ import annotations

from pathlib import Path

import pytest
from git import GitCommandError, Repo

from ask_admin_api.application.git_service import GitService


@pytest.fixture
def git_repo(tmp_path: Path):
    """Initialize a real git repo with an initial commit."""
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    # Need at least one commit for iter_commits to work
    readme = tmp_path / "README.md"
    readme.write_text("init")
    repo.index.add(["README.md"])
    repo.index.commit("init")
    return tmp_path


@pytest.fixture
def svc(git_repo: Path) -> GitService:
    return GitService(repo_root=str(git_repo))


def test_commit_returns_sha(svc, git_repo):
    test_file = git_repo / "test.yaml"
    test_file.write_text("id: test\nlayer: bronze\n")

    sha = svc.commit(
        ["test.yaml"],
        "test: add test yaml",
        "Test User",
        "test@onibex.com",
    )

    assert sha is not None
    assert len(sha) == 40  # full SHA


def test_get_log_returns_commits(svc, git_repo):
    test_file = git_repo / "sample.yaml"
    test_file.write_text("id: sample\nlayer: silver\n")
    svc.commit(["sample.yaml"], "add sample", "User A", "a@onibex.com")

    test_file.write_text("id: sample\nlayer: silver\ndescription: updated\n")
    svc.commit(["sample.yaml"], "update description", "User B", "b@onibex.com")

    log = svc.get_log("sample.yaml")

    assert len(log) == 2
    assert log[0].message == "update description"
    assert log[0].author_email == "b@onibex.com"
    assert log[1].message == "add sample"
    assert len(log[0].short_sha) == 7


def test_get_log_pagination(svc, git_repo):
    test_file = git_repo / "paged.yaml"
    for i in range(5):
        test_file.write_text(f"id: paged\nversion: {i}\n")
        svc.commit(["paged.yaml"], f"commit {i}", "User", "u@onibex.com")

    page1 = svc.get_log("paged.yaml", max_count=2, skip=0)
    page2 = svc.get_log("paged.yaml", max_count=2, skip=2)

    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0].sha != page2[0].sha


def test_get_diff_returns_string(svc, git_repo):
    test_file = git_repo / "diff_test.yaml"
    test_file.write_text("description: original\n")
    sha1 = svc.commit(["diff_test.yaml"], "original", "User", "u@onibex.com")

    test_file.write_text("description: modified\n")
    sha2 = svc.commit(["diff_test.yaml"], "modified", "User", "u@onibex.com")

    diff = svc.get_diff("diff_test.yaml", sha1, sha2)

    assert "original" in diff
    assert "modified" in diff


def test_get_file_at_commit(svc, git_repo):
    test_file = git_repo / "history_test.yaml"
    test_file.write_text("description: v1\n")
    sha_v1 = svc.commit(["history_test.yaml"], "v1", "User", "u@onibex.com")

    test_file.write_text("description: v2\n")
    svc.commit(["history_test.yaml"], "v2", "User", "u@onibex.com")

    content_at_v1 = svc.get_file_at_commit("history_test.yaml", sha_v1)

    assert "v1" in content_at_v1
    assert "v2" not in content_at_v1


def test_get_total_count(svc, git_repo):
    test_file = git_repo / "count_test.yaml"
    for i in range(3):
        test_file.write_text(f"version: {i}\n")
        svc.commit(["count_test.yaml"], f"v{i}", "User", "u@onibex.com")

    assert svc.get_total_count("count_test.yaml") == 3


def test_empty_commit_creates_no_file_change_commit(svc, git_repo):
    """An empty commit records an event (e.g. publish) without touching files."""
    seed = git_repo / "seed.yaml"
    seed.write_text("id: seed\nlayer: bronze\n")
    svc.commit(["seed.yaml"], "seed", "User", "u@onibex.com")

    repo = Repo(git_repo)
    tree_before = repo.head.commit.tree.hexsha

    sha = svc.empty_commit(
        message="publish(silver_x): indexed by admin@example.com",
        author_name="admin",
        author_email="admin@example.com",
    )

    assert sha is not None
    assert len(sha) == 40
    # Tree must be identical (no file changes); only commit metadata differs.
    assert repo.head.commit.tree.hexsha == tree_before
    assert repo.head.commit.message.strip().startswith("publish(silver_x)")
    assert repo.head.commit.author.email == "admin@example.com"


def test_empty_commit_no_op_when_git_unavailable(tmp_path):
    """No git repo at the path → empty_commit must return None and not raise."""
    svc = GitService(repo_root=str(tmp_path))  # not a git repo
    sha = svc.empty_commit(
        message="publish(x): no git",
        author_name="x",
        author_email="x@x.com",
    )
    assert sha is None


def test_find_last_publish_sha_returns_most_recent(svc, git_repo):
    """find_last_publish_sha walks git log HEAD-first and returns the latest
    publish empty commit for the given entity_id, ignoring publishes of
    other entities and unrelated commits."""
    # Seed with two distinct file commits + several publishes interleaved.
    f = git_repo / "x.yaml"
    f.write_text("id: x\n")
    svc.commit(["x.yaml"], "edit x #1", "u", "u@x.com")

    first = svc.empty_commit("publish(silver_a): indexed by u@x.com", "u", "u@x.com")

    svc.empty_commit("publish(silver_b): indexed by u@x.com", "u", "u@x.com")

    f.write_text("id: x\nchanged: 1\n")
    svc.commit(["x.yaml"], "edit x #2", "u", "u@x.com")

    second = svc.empty_commit("publish(silver_a): indexed by u@x.com", "u", "u@x.com")

    # Most-recent publish of silver_a is the second one.
    assert svc.find_last_publish_sha("silver_a") == second
    assert first != second  # sanity
    # Entity that was never published returns None.
    assert svc.find_last_publish_sha("silver_unknown") is None


def test_find_last_publish_sha_env_scoped(svc, git_repo):
    """env="dev"/"prod" looks on that env's branch for ``publish-<env>(<id>)``
    and never falls back to the legacy ``publish(<id>)`` commit — so
    "Diff vs dev" only ever means dev.

    Commits are made via the git CLI on the service's own repo instance:
    ``empty_commit`` detaches HEAD (it sets a direct object reference), which
    would not advance the branch refs this test asserts on. Real env-publish
    commits are file commits on the env branch anyway, not empty commits.
    """
    g = svc.repo.git
    working = svc.repo.active_branch.name

    # Legacy runtime publish on the working branch.
    g.commit("--allow-empty", "-m", "publish(silver_a): indexed by u@x.com", "--author=u <u@x.com>")
    legacy = g.rev_parse("HEAD")

    # Cut a dev branch and record a dev deploy on it.
    g.checkout("-b", "dev")
    g.commit(
        "--allow-empty", "-m", "publish-dev(silver_a): deployed by u@x.com", "--author=u <u@x.com>"
    )
    dev_sha = g.rev_parse("HEAD")
    g.checkout(working)

    # env="dev" finds the dev deploy, NOT the legacy commit.
    assert svc.find_last_publish_sha("silver_a", env="dev") == dev_sha
    # An env with no deploy (no prod branch) → None, never the legacy fallback.
    assert svc.find_last_publish_sha("silver_a", env="prod") is None
    # The no-env path is unchanged (back-compat): still the legacy commit.
    assert svc.find_last_publish_sha("silver_a") == legacy


def test_find_last_publish_sha_returns_none_when_git_unavailable(tmp_path):
    svc = GitService(repo_root=str(tmp_path))  # not a git repo
    assert svc.find_last_publish_sha("any_entity") is None


def test_commit_if_changed_skips_noop(svc, git_repo):
    """commit_if_changed commits real changes but skips when bytes are identical
    (so re-ingesting the same SAP payload does not create empty baseline commits)."""
    f = git_repo / "baseline.json"
    f.write_text('{"v": 1}\n')
    sha1 = svc.commit_if_changed(["baseline.json"], "add baseline", "u", "u@x.com")
    assert sha1 is not None  # new content → committed

    # Re-write identical bytes → nothing to commit.
    f.write_text('{"v": 1}\n')
    assert svc.commit_if_changed(["baseline.json"], "noop", "u", "u@x.com") is None

    # Real change → commits again.
    f.write_text('{"v": 2}\n')
    sha3 = svc.commit_if_changed(["baseline.json"], "update baseline", "u", "u@x.com")
    assert sha3 is not None and sha3 != sha1


def test_stash_unblocks_branch_switch_over_dirty_tracked_file(svc, git_repo):
    """A dirty tracked file that differs on the target branch makes
    ``git checkout <branch>`` abort — exactly the publish .sap_baseline sidecar
    crash. stash_push isolates it so the switch proceeds; stash_pop restores
    the admin's uncommitted change afterwards."""
    g = svc.repo.git
    working = svc.repo.active_branch.name

    sidecar = git_repo / "sidecar.json"
    sidecar.write_text('{"v": 1}\n')
    svc.commit(["sidecar.json"], "add sidecar", "u", "u@x.com")

    # dev branch with a DIFFERENT committed version of the same file.
    g.checkout("-b", "dev")
    sidecar.write_text('{"v": 2}\n')
    svc.commit(["sidecar.json"], "dev sidecar", "u", "u@x.com")
    g.checkout(working)

    # Uncommitted local change that conflicts with dev's version.
    sidecar.write_text('{"v": 99}\n')
    with pytest.raises(GitCommandError):
        g.checkout("dev")  # aborts: would overwrite local changes

    # stash → switch now works → restore on return.
    assert svc.stash_push("publish-autostash test") is True
    svc.checkout_branch("dev")  # no raise
    svc.checkout_branch(working)
    svc.stash_pop()
    assert sidecar.read_text() == '{"v": 99}\n'  # admin's change preserved

    # Clean tree → stash_push is a no-op (nothing to pop later).
    g.checkout("--", "sidecar.json")
    assert svc.stash_push("noop") is False


def test_get_log_includes_empty_publish_commits_by_entity_id(svc, git_repo):
    """publish(<id>) empty commits don't touch any file, so a path-filtered
    git log misses them. ``get_log(file_path, entity_id=...)`` must do a
    union of (file-touching commits) ∪ (commits whose message references
    the entity_id) so publish events surface in the History UI."""
    f = git_repo / "silver_x.yaml"
    f.write_text("id: silver_x\nlayer: silver\n")
    edit_sha = svc.commit(["silver_x.yaml"], "viz: update silver_x", "u", "u@x.com")
    publish_sha = svc.empty_commit(
        "publish(silver_x): indexed by u@x.com",
        "u",
        "u@x.com",
    )
    # Sanity — without entity_id, the publish empty commit is invisible.
    legacy = svc.get_log("silver_x.yaml")
    legacy_shas = [c.sha for c in legacy]
    assert edit_sha in legacy_shas
    assert publish_sha not in legacy_shas

    # With entity_id the publish empty commit shows up, newest-first.
    union = svc.get_log("silver_x.yaml", entity_id="silver_x")
    union_shas = [c.sha for c in union]
    assert union_shas[0] == publish_sha
    assert edit_sha in union_shas

    # get_total_count must include the publish empty commit too.
    assert svc.get_total_count("silver_x.yaml", entity_id="silver_x") == 2
    assert svc.get_total_count("silver_x.yaml") == 1  # legacy path-only


def test_get_log_does_not_double_count_publish_commits_touching_file(svc, git_repo):
    """If a commit touches the file AND its message namespaces the entity
    (hypothetical edge case), the union must de-dupe by sha."""
    f = git_repo / "silver_x.yaml"
    f.write_text("id: silver_x\n")
    sha = svc.commit(["silver_x.yaml"], "viz: update silver_x", "u", "u@x.com")
    union = svc.get_log("silver_x.yaml", entity_id="silver_x")
    shas = [c.sha for c in union]
    assert shas == [sha]  # exactly once


def test_commit_handles_deleted_path_as_remove(svc, git_repo):
    """Regression — clear_resolved deletes a sidecar then GitService.commit
    is called with that path. Old behaviour: index.add tried to lstat the
    missing file and raised FileNotFoundError. Fixed behaviour: missing
    paths are staged via index.remove and the commit succeeds."""
    sidecar_dir = git_repo / ".sap_baseline"
    sidecar_dir.mkdir()
    sidecar = sidecar_dir / "silver_x.conflicts.json"
    sidecar.write_text("[]")

    # First commit puts the sidecar under git's control so a subsequent
    # removal has something to actually delete.
    create_sha = svc.commit(
        [".sap_baseline/silver_x.conflicts.json"],
        "merge(silver_x): conflicts found",
        "u",
        "u@x.com",
    )
    assert create_sha is not None

    # Simulate ConflictStore.clear_resolved: the file is gone from disk
    # before commit runs.
    sidecar.unlink()
    assert not sidecar.exists()

    remove_sha = svc.commit(
        [".sap_baseline/silver_x.conflicts.json"],
        "merge(silver_x): all conflicts resolved",
        "u",
        "u@x.com",
    )

    assert remove_sha is not None, "Commit should succeed even though the file is gone"
    # And the resulting commit must actually be the removal.
    diff = svc.repo.git.show(remove_sha, name_status=True)
    assert "D" in diff and "silver_x.conflicts.json" in diff


def test_commit_with_mixed_add_and_remove(svc, git_repo):
    """A single commit can contain both a YAML edit (file exists) AND a
    sidecar removal (file gone). Both must land in the same commit."""
    # Seed: a YAML and a sidecar tracked by git.
    yaml_f = git_repo / "silver_y.yaml"
    yaml_f.write_text("id: silver_y\nlayer: silver\n")
    sidecar_dir = git_repo / ".sap_baseline"
    sidecar_dir.mkdir()
    sidecar = sidecar_dir / "silver_y.conflicts.json"
    sidecar.write_text("[]")
    svc.commit(
        ["silver_y.yaml", ".sap_baseline/silver_y.conflicts.json"],
        "init silver_y",
        "u",
        "u@x.com",
    )

    # Now modify the YAML and delete the sidecar in the same backend cycle.
    yaml_f.write_text("id: silver_y\nlayer: silver\nalias: Y\n")
    sidecar.unlink()

    sha = svc.commit(
        ["silver_y.yaml", ".sap_baseline/silver_y.conflicts.json"],
        "merge(silver_y): all conflicts resolved",
        "u",
        "u@x.com",
    )
    assert sha is not None

    diff = svc.repo.git.show(sha, name_status=True)
    assert "M" in diff and "silver_y.yaml" in diff
    assert "D" in diff and "silver_y.conflicts.json" in diff


def test_commit_ignores_path_never_tracked(svc, git_repo):
    """If a path was never in git AND no longer on disk (idempotent
    cleanup), commit should not raise — just emit no-op (or a remove that
    GitPython surfaces as ignorable)."""
    # File never existed and isn't on disk now.
    sha = svc.commit(
        [".sap_baseline/never_existed.conflicts.json"],
        "merge: nothing happened",
        "u",
        "u@x.com",
    )
    # The commit call should NOT raise. It may return None (empty commit
    # rejected by git) or a sha for an empty commit — both are acceptable;
    # the contract is "don't blow up on a missing untracked path".
    assert sha is None or len(sha) == 40

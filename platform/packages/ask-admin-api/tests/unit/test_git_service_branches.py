"""GitService §3.6 branch ops (UX_CHANGES audit, Iter 2) — real tmp git repo.

Proves the file-by-file checkout publish mechanic (audit §3.2/§3.3): publishing
a file onto a release branch moves ONLY that file and never merges, so
unrelated working changes can't leak across environments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ask_admin_api.application.git_service import GitService


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


@pytest.fixture
def git_repo(tmp_path: Path) -> GitService:
    """A fresh git repo (outside the code tree) with one commit on main."""
    from git import Actor, Repo

    repo = Repo.init(tmp_path)
    _write(tmp_path, "silver/sd/sales_order.yaml", "id: silver_sales\nv: 1\n")
    _write(tmp_path, "bronze/vbak.yaml", "id: bronze_vbak\nv: 1\n")
    _write(tmp_path, "unrelated.yaml", "id: other\nv: 1\n")
    repo.index.add(["silver/sd/sales_order.yaml", "bronze/vbak.yaml", "unrelated.yaml"])
    actor = Actor("t", "t@x.com")
    repo.index.commit("init", author=actor, committer=actor)
    repo.git.branch("-M", "main")  # normalise branch name across git defaults
    return GitService(repo_root=str(tmp_path))


def test_init_release_branches_creates_dev_prod(git_repo):
    created = git_repo.init_release_branches()
    assert set(created) == {"dev", "prod"}
    assert set(git_repo.list_branches()) >= {"main", "dev", "prod"}
    # Idempotent — second call creates nothing.
    assert git_repo.init_release_branches() == []


def test_init_release_branches_normalizes_master_to_main(tmp_path):
    """A repo on the git-default ``master`` is renamed to ``main`` at init.

    Reproduces the live finding: ``git init`` yields ``master`` but publish
    hardcodes ``main`` (env_targets.WORKING_BRANCH). init_release_branches must
    self-heal so publish does not fail with ``invalid reference: main``.
    """
    from git import Actor, Repo

    repo = Repo.init(tmp_path)
    _write(tmp_path, "silver/sd/sales_order.yaml", "id: silver_sales\nv: 1\n")
    repo.index.add(["silver/sd/sales_order.yaml"])
    actor = Actor("t", "t@x.com")
    repo.index.commit("init", author=actor, committer=actor)
    repo.git.branch("-M", "master")  # force the git-default name regardless of host config

    svc = GitService(repo_root=str(tmp_path))
    assert svc.current_branch() == "master"

    created = svc.init_release_branches()
    assert set(created) == {"dev", "prod"}
    assert svc.current_branch() == "main"  # renamed, HEAD followed
    assert "master" not in set(svc.list_branches())


def test_normalize_working_branch_noop_when_main_exists(git_repo):
    """If ``main`` already exists, normalisation never touches branches."""
    git_repo.init_release_branches()
    before = set(git_repo.list_branches())
    git_repo._normalize_working_branch()
    assert set(git_repo.list_branches()) == before
    assert git_repo.current_branch() == "main"


def test_init_release_branches_skips_truly_empty_repo(tmp_path):
    """A repo with NO files and NO commits has nothing to seed → no branches."""
    from git import Repo

    Repo.init(tmp_path)  # no commits, no files
    svc = GitService(repo_root=str(tmp_path))
    assert svc.init_release_branches() == []  # guarded, no crash, no empty seed
    assert not svc.repo.head.is_valid()  # still unborn — nothing was committed


def test_auto_init_creates_repo_when_flag_set(tmp_path, monkeypatch):
    """From-zero (BACKLOG B P1): a workspace dir with YAMLs but NO .git at all.

    With SEMANTIC_LAYER_AUTO_INIT on, GitService initialises the repo EXACTLY
    at repo_root and the existing bootstrap chain (seed commit + master→main +
    dev/prod cut) makes it publish-ready in the same boot. Without the flag,
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
    assert svc.current_branch() == "main"
    assert "v: 1" in svc.get_file_at_commit("s4h/silver/sd/sales_order.yaml", "main")


def test_init_release_branches_auto_seeds_repo_with_files_no_commit(tmp_path):
    """From-zero: a `git init`'d repo with files staged but NO commit (unborn
    HEAD) must auto-seed a root commit so dev/prod can be cut — otherwise
    publish fails at `git checkout dev`. Reproduces the live EC2 finding."""
    from git import Repo

    repo = Repo.init(tmp_path)
    _write(tmp_path, "s4h/silver/sd/sales_order.yaml", "id: silver_sales\nv: 1\n")
    repo.index.add(["s4h/silver/sd/sales_order.yaml"])  # staged, NOT committed
    assert not repo.head.is_valid()  # unborn HEAD

    svc = GitService(repo_root=str(tmp_path))
    created = svc.init_release_branches()

    assert set(created) == {"dev", "prod"}
    assert svc.current_branch() == "main"  # seeded commit + master→main normalised
    assert set(svc.list_branches()) >= {"main", "dev", "prod"}
    # the seeded commit carries the staged file
    assert "v: 1" in svc.get_file_at_commit("s4h/silver/sd/sales_order.yaml", "main")


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


def test_current_branch_and_checkout(git_repo):
    assert git_repo.current_branch() == "main"
    git_repo.init_release_branches()
    git_repo.checkout_branch("dev")
    assert git_repo.current_branch() == "dev"
    git_repo.checkout_branch("main")
    assert git_repo.current_branch() == "main"


def test_file_by_file_checkout_moves_only_listed_paths(git_repo, tmp_path):
    """Publish silver v2 to dev; unrelated.yaml v2 must NOT leak to dev."""
    from git import Actor

    git_repo.init_release_branches()

    # Advance main: bump BOTH the silver and an unrelated file.
    _write(tmp_path, "silver/sd/sales_order.yaml", "id: silver_sales\nv: 2\n")
    _write(tmp_path, "unrelated.yaml", "id: other\nv: 2\n")
    git_repo.repo.index.add(["silver/sd/sales_order.yaml", "unrelated.yaml"])
    actor = Actor("t", "t@x.com")
    git_repo.repo.index.commit("edit on main", author=actor, committer=actor)

    # Publish ONLY the silver to dev.
    original = git_repo.current_branch()
    git_repo.checkout_branch("dev")
    git_repo.checkout_files_from("main", ["silver/sd/sales_order.yaml"])
    sha = git_repo.commit_on_current_branch("publish-dev(silver_sales): by t@x.com", "t", "t@x.com")
    git_repo.checkout_branch(original)

    assert sha  # a commit landed on dev
    # dev got the silver v2 ...
    assert "v: 2" in git_repo.get_file_at_commit("silver/sd/sales_order.yaml", "dev")
    # ... but unrelated.yaml on dev is STILL v1 (no merge, no leak).
    assert "v: 1" in git_repo.get_file_at_commit("unrelated.yaml", "dev")
    # main is restored as the working branch.
    assert git_repo.current_branch() == "main"


def test_file_sha_on_branch(git_repo):
    git_repo.init_release_branches()
    sha_main = git_repo.file_sha_on_branch("main", "bronze/vbak.yaml")
    sha_dev = git_repo.file_sha_on_branch("dev", "bronze/vbak.yaml")
    assert sha_main and sha_main == sha_dev  # same content at branch point
    assert git_repo.file_sha_on_branch("main", "does/not/exist.yaml") is None


def test_commit_on_current_branch_noop_when_clean(git_repo):
    git_repo.init_release_branches()
    git_repo.checkout_branch("dev")
    # Nothing staged → idempotent no-op (returns None), no empty commit.
    assert git_repo.commit_on_current_branch("noop", "t", "t@x.com") is None
    git_repo.checkout_branch("main")


def test_branch_scoped_history_isolates_publish_commits(git_repo, tmp_path):
    """get_log(branch=dev, message_prefix=publish-dev() shows ONLY the dev
    deploys, not the shared ancestor commits inherited at branch-cut (§4.4)."""
    from git import Actor

    git_repo.init_release_branches()
    fp = "silver/sd/sales_order.yaml"

    # Advance main (an edit), then simulate a publish-dev of the file onto dev.
    _write(tmp_path, fp, "id: silver_sales\nv: 2\n")
    git_repo.repo.index.add([fp])
    git_repo.repo.index.commit(
        "edit on main", author=Actor("t", "t@x.com"), committer=Actor("t", "t@x.com")
    )

    git_repo.checkout_branch("dev")
    git_repo.checkout_files_from("main", [fp])
    git_repo.commit_on_current_branch("publish-dev(silver_sales): by t@x.com", "t", "t@x.com")
    git_repo.checkout_branch("main")

    # dev tab: exactly the one publish-dev commit (init + edit-on-main excluded).
    dev_log = git_repo.get_log(fp, branch="dev", message_prefix="publish-dev(")
    assert len(dev_log) == 1
    assert dev_log[0].message.startswith("publish-dev(silver_sales)")
    assert git_repo.get_total_count(fp, branch="dev", message_prefix="publish-dev(") == 1

    # prod tab: nothing published to prod yet.
    assert git_repo.get_log(fp, branch="prod", message_prefix="publish-prod(") == []

    # working tab: the real edits are present (init + edit on main = 2).
    work_log = git_repo.get_log(fp, branch="main", entity_id="silver_sales")
    assert len(work_log) >= 2
    assert any("edit on main" in c.message for c in work_log)
    # The publish-dev commit lives on dev, not main → absent from the working tab.
    assert not any(c.message.startswith("publish-dev(") for c in work_log)

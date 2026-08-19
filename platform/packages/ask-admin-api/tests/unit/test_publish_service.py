# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""PublishService git-flow + lifecycle wiring (UX_CHANGES audit §3.2, Iter 2).

Uses a real tmp git repo but FAKE indexer / lifecycle / yaml-service so the
risky parts (OpenSearch-first ordering, file-by-file branch promotion, prod
gate, working-tree restore) are exercised without OpenSearch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ask_admin_api.application.git_service import GitService
from ask_admin_api.application.lifecycle_service import PublishNotReadyError
from ask_admin_api.application.publish_service import PublishService
from ask_admin_api.models.viz_models import VizLayer

# ── Fakes ─────────────────────────────────────────────────────────────────────


class _Node:
    def __init__(self, entity_id, file_path, layer, composed_of=None):
        self.id = entity_id
        self.file_path = file_path
        self.layer = layer
        self.composed_of = composed_of or []


class _FakeYamlService:
    def __init__(self, nodes: dict):
        self._nodes = nodes

    def get_yaml(self, entity_id):
        from ask_admin_api.application.yaml_file_service import YAMLNotFoundError

        if entity_id not in self._nodes:
            raise YAMLNotFoundError(entity_id)
        return self._nodes[entity_id]


class _FakeIndexer:
    def __init__(self):
        self.calls = []
        self.unindex_calls = []

    def index(self, env, *, primary_id, primary_content, cascade):
        self.calls.append(
            {
                "env": env,
                "primary_id": primary_id,
                "primary_content": primary_content,
                "cascade": dict(cascade),
            }
        )
        return {
            "entities": 1,
            "fields": 3,
            "edges": 1,
            "rag": 0,
            "cascade_ids": list(cascade.keys()),
            "warnings": [],
        }

    def unindex(self, env, *, primary_id):
        self.unindex_calls.append({"env": env, "primary_id": primary_id})
        return {"entities": 1, "fields": 3, "edges": 1, "rag": 0, "warnings": []}


def _rec(sha, version=1):
    return type("PR", (), {"sha": sha, "version": version})()


class _FakeLifecycle:
    def __init__(self, dev_published_for=(), prod_uptodate_for=()):
        self.dev = list(dev_published_for)
        self.prod_uptodate = list(prod_uptodate_for)
        self.published_dev = []
        self.published_prod = []

    def get(self, entity_id):
        if entity_id in self.prod_uptodate:
            # dev + prod on the same sha → prod already up to date with dev.
            return type(
                "LC", (), {"dev_published": _rec("samesha"), "prod_published": _rec("samesha")}
            )()
        if entity_id in self.dev:
            return type("LC", (), {"dev_published": _rec("devsha"), "prod_published": None})()
        return type("LC", (), {"dev_published": None, "prod_published": None})()

    def on_publish_dev(self, entity_id, *, by):
        self.published_dev.append((entity_id, by))

    def on_publish_prod(self, entity_id, *, by):
        self.published_prod.append((entity_id, by))

    def on_unpublish_dev(self, entity_id, *, by):
        self.unpublished_dev = getattr(self, "unpublished_dev", [])
        self.unpublished_dev.append((entity_id, by))

    def on_unpublish_prod(self, entity_id, *, by):
        self.unpublished_prod = getattr(self, "unpublished_prod", [])
        self.unpublished_prod.append((entity_id, by))


# ── Fixtures ────────────────────────────────────────────────────────────────


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path):
    """Repo where main is AHEAD of the release branches.

    Mirrors the real flow: dev/prod were cut at boot (v1), then the admin edited
    the DP on main (v2). A publish must therefore produce a real divergent commit
    on the env branch — proving the file-by-file checkout actually moved content.
    """
    from git import Actor, Repo

    r = Repo.init(tmp_path)
    a = Actor("t", "t@x.com")
    _write(tmp_path, "silver/sd/sales_order.yaml", "id: silver_sales\nlayer: silver\nv: 1\n")
    _write(tmp_path, "bronze/vbak.yaml", "id: bronze_vbak\nlayer: bronze\nv: 1\n")
    r.index.add(["silver/sd/sales_order.yaml", "bronze/vbak.yaml"])
    r.index.commit("init v1", author=a, committer=a)
    r.git.branch("-M", "main")  # normalise branch name across git defaults

    # Cut the release branches at v1 (like init_release_branches at boot)...
    GitService(repo_root=str(tmp_path)).init_release_branches()

    # ...then advance main to v2 (the admin's edit).
    _write(tmp_path, "silver/sd/sales_order.yaml", "id: silver_sales\nlayer: silver\nv: 2\n")
    r.index.add(["silver/sd/sales_order.yaml"])
    r.index.commit("edit silver to v2 on main", author=a, committer=a)
    return tmp_path


def _make_service(repo: Path, indexer, lifecycle):
    nodes = {
        "silver_sales": _Node(
            "silver_sales", "silver/sd/sales_order.yaml", VizLayer.silver, ["bronze_vbak"]
        ),
        "bronze_vbak": _Node("bronze_vbak", "bronze/vbak.yaml", VizLayer.bronze),
    }
    return PublishService(
        repo_root=str(repo),
        workspace_path=str(repo),
        indexer=indexer,
        lifecycle=lifecycle,
        git=GitService(repo_root=str(repo)),
        yaml_service=_FakeYamlService(nodes),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_publish_dev_indexes_then_commits_on_dev(repo):
    indexer, lifecycle = _FakeIndexer(), _FakeLifecycle()
    svc = _make_service(repo, indexer, lifecycle)

    outcome = svc.publish("silver_sales", "dev", by="a@x.com")

    # OpenSearch-first: indexer saw env=dev + the silver + its cascade bronze.
    assert len(indexer.calls) == 1
    call = indexer.calls[0]
    assert call["env"] == "dev"
    assert call["primary_id"] == "silver_sales"
    assert "bronze_vbak" in call["cascade"]

    # git: committed on dev, dev now carries the v2 content promoted from main.
    assert outcome.committed_sha
    git = GitService(repo_root=str(repo))
    assert "v: 2" in git.get_file_at_commit("silver/sd/sales_order.yaml", "dev")
    assert git.current_branch() == "main"  # working tree restored

    # lifecycle: dev recorded, prod not.
    assert lifecycle.published_dev == [("silver_sales", "a@x.com")]
    assert lifecycle.published_prod == []


def test_publish_prod_before_dev_raises(repo):
    indexer, lifecycle = _FakeIndexer(), _FakeLifecycle()  # no dev published
    svc = _make_service(repo, indexer, lifecycle)
    with pytest.raises(PublishNotReadyError):
        svc.publish("silver_sales", "prod", by="a@x.com")
    # Gate fires BEFORE indexing — no OpenSearch write attempted.
    assert indexer.calls == []


def test_publish_prod_after_dev_promotes_from_dev(repo):
    # First publish to dev so the prod gate opens + dev branch has the file.
    svc_dev = _make_service(repo, _FakeIndexer(), _FakeLifecycle())
    svc_dev.publish("silver_sales", "dev", by="a@x.com")

    indexer = _FakeIndexer()
    lifecycle = _FakeLifecycle(dev_published_for=["silver_sales"])
    svc = _make_service(repo, indexer, lifecycle)

    outcome = svc.publish("silver_sales", "prod", by="b@x.com")

    assert indexer.calls[0]["env"] == "prod"
    assert outcome.committed_sha
    git = GitService(repo_root=str(repo))
    # prod promoted the dev (v2) content, never main's current state.
    assert "v: 2" in git.get_file_at_commit("silver/sd/sales_order.yaml", "prod")
    assert lifecycle.published_prod == [("silver_sales", "b@x.com")]
    assert git.current_branch() == "main"


def test_unknown_env_rejected(repo):
    svc = _make_service(repo, _FakeIndexer(), _FakeLifecycle())
    with pytest.raises(ValueError):
        svc.publish("silver_sales", "staging", by="a@x.com")


def test_prod_when_already_up_to_date_is_gated(repo):
    """Fix (Iter 4): prod is gated when it already matches dev (audit §2.2.3) —
    no wasteful no-op re-publish, and the gate fires before any OpenSearch write."""
    indexer = _FakeIndexer()
    svc = _make_service(repo, indexer, _FakeLifecycle(prod_uptodate_for=["silver_sales"]))
    with pytest.raises(PublishNotReadyError, match="already up to date"):
        svc.publish("silver_sales", "prod", by="a@x.com")
    assert indexer.calls == []


def test_prod_does_not_fall_back_to_main_when_missing_on_dev(tmp_path):
    """Fix A: prod must NEVER index main's content. If the file is absent on the
    dev branch, the publish fails loud instead of silently promoting main."""
    from git import Actor, Repo

    r = Repo.init(tmp_path)
    a = Actor("t", "t@x.com")
    _write(tmp_path, "silver/a.yaml", "id: silver_a\nlayer: silver\nv: 1\n")
    r.index.add(["silver/a.yaml"])
    r.index.commit("init", author=a, committer=a)
    r.git.branch("-M", "main")
    GitService(repo_root=str(tmp_path)).init_release_branches()  # dev/prod have silver_a

    # silver_b is added to main AFTER branching → it exists on main but NOT on dev.
    _write(tmp_path, "silver/b.yaml", "id: silver_b\nlayer: silver\nv: 1\n")
    r.index.add(["silver/b.yaml"])
    r.index.commit("add silver_b on main only", author=a, committer=a)

    nodes = {"silver_b": _Node("silver_b", "silver/b.yaml", VizLayer.silver)}
    indexer = _FakeIndexer()
    svc = PublishService(
        repo_root=str(tmp_path),
        workspace_path=str(tmp_path),
        indexer=indexer,
        lifecycle=_FakeLifecycle(dev_published_for=["silver_b"]),  # gate passes
        git=GitService(repo_root=str(tmp_path)),
        yaml_service=_FakeYamlService(nodes),
    )
    with pytest.raises(RuntimeError, match="no content"):
        svc.publish("silver_b", "prod", by="a@x.com")
    # Crucially: nothing was indexed into prod (the guard fired before OpenSearch).
    assert indexer.calls == []


def test_publish_dev_from_fresh_master_repo_normalizes_and_succeeds(tmp_path, caplog):
    """Regression (from-zero docker-compose): a freshly ``git init``'d
    semantic-layer repo is on ``master`` with no dev/prod branches and no
    ``main``. The FIRST publish must normalise master→main, bootstrap dev/prod,
    read the source from main, commit on dev, and restore the working tree to
    ``main`` — never fail with "invalid object name 'main'" (the source read) or
    "failed to restore branch master" (the working-tree restore)."""
    import logging

    from git import Actor, Repo

    r = Repo.init(tmp_path)
    a = Actor("t", "t@x.com")
    _write(tmp_path, "silver/sd/sales_order.yaml", "id: silver_sales\nlayer: silver\nv: 1\n")
    _write(tmp_path, "bronze/vbak.yaml", "id: bronze_vbak\nlayer: bronze\nv: 1\n")
    r.index.add(["silver/sd/sales_order.yaml", "bronze/vbak.yaml"])
    r.index.commit("init v1", author=a, committer=a)
    # Force the git-default ``master`` so the from-zero scenario is deterministic
    # regardless of the host's init.defaultBranch (no dev/prod, no main yet).
    r.git.branch("-M", "master")
    heads_before = {h.name for h in r.heads}
    assert heads_before == {"master"}

    indexer, lifecycle = _FakeIndexer(), _FakeLifecycle()
    svc = _make_service(tmp_path, indexer, lifecycle)

    with caplog.at_level(logging.ERROR):
        outcome = svc.publish("silver_sales", "dev", by="a@x.com")

    # The source read off main worked (no "invalid object name" raised) → the
    # content reached OpenSearch. (committed_sha is None here by design: the
    # early init_release_branches cuts dev as a full copy of main, so promoting
    # identical content is a git no-op — the Iter-2 limitation. Queryability
    # still lands via the OpenSearch index below.)
    assert outcome.env == "dev"
    assert indexer.calls and indexer.calls[0]["env"] == "dev"
    assert "v: 1" in indexer.calls[0]["primary_content"]
    git = GitService(repo_root=str(tmp_path))
    assert git.file_sha_on_branch("dev", "silver/sd/sales_order.yaml") is not None
    assert "v: 1" in git.get_file_at_commit("silver/sd/sales_order.yaml", "dev")

    # master was normalised to main, dev/prod bootstrapped, working tree restored.
    heads_after = {h.name for h in r.heads}
    assert {"main", "dev", "prod"} <= heads_after
    assert "master" not in heads_after
    assert git.current_branch() == "main"

    # The working-tree restore never failed (no force-fallback error logged).
    assert not [rec for rec in caplog.records if "failed to restore" in rec.getMessage()]


# ── Unpublish (inverse of publish) ────────────────────────────────────────────


def test_unpublish_dev_unindexes_then_removes_on_dev(repo):
    indexer = _FakeIndexer()
    lifecycle = _FakeLifecycle(dev_published_for=["silver_sales"])  # dev only, no prod
    svc = _make_service(repo, indexer, lifecycle)

    outcome = svc.unpublish("silver_sales", "dev", by="a@x.com")

    # OpenSearch-first: unindex saw env=dev + the primary id (NO cascade arg).
    assert indexer.unindex_calls == [{"env": "dev", "primary_id": "silver_sales"}]
    # git: the silver YAML is gone from the dev branch; working tree restored.
    assert outcome.committed_sha
    git = GitService(repo_root=str(repo))
    assert git.file_sha_on_branch("dev", "silver/sd/sales_order.yaml") is None
    assert git.current_branch() == "main"
    # main (working) still has the file — unpublish never touches the source.
    assert git.file_sha_on_branch("main", "silver/sd/sales_order.yaml") is not None
    assert lifecycle.unpublished_dev == [("silver_sales", "a@x.com")]


def test_unpublish_does_not_cascade_to_bronze(repo):
    """Key invariant: unpublish removes ONLY the primary entity. A shared
    composed_of bronze must remain on the env branch (another silver may use it)."""
    indexer = _FakeIndexer()
    svc = _make_service(repo, indexer, _FakeLifecycle(dev_published_for=["silver_sales"]))

    svc.unpublish("silver_sales", "dev", by="a@x.com")

    git = GitService(repo_root=str(repo))
    assert git.file_sha_on_branch("dev", "silver/sd/sales_order.yaml") is None  # removed
    assert git.file_sha_on_branch("dev", "bronze/vbak.yaml") is not None  # bronze kept


def test_unpublish_dev_while_prod_published_is_gated(repo):
    """Inverse gate: cannot unpublish from dev while prod is still published.
    Fires BEFORE any OpenSearch write."""
    indexer = _FakeIndexer()
    # prod_uptodate_for → dev AND prod published.
    svc = _make_service(repo, indexer, _FakeLifecycle(prod_uptodate_for=["silver_sales"]))
    with pytest.raises(PublishNotReadyError, match="unpublish from prod first"):
        svc.unpublish("silver_sales", "dev", by="a@x.com")
    assert indexer.unindex_calls == []


def test_unpublish_when_not_published_raises(repo):
    indexer = _FakeIndexer()
    svc = _make_service(repo, indexer, _FakeLifecycle())  # nothing published
    with pytest.raises(PublishNotReadyError, match="not published"):
        svc.unpublish("silver_sales", "dev", by="a@x.com")
    assert indexer.unindex_calls == []


def test_unpublish_prod_keeps_dev(repo):
    """Unpublishing prod removes the prod-branch copy but leaves dev intact."""
    indexer = _FakeIndexer()
    lifecycle = _FakeLifecycle(prod_uptodate_for=["silver_sales"])  # dev + prod
    svc = _make_service(repo, indexer, lifecycle)

    outcome = svc.unpublish("silver_sales", "prod", by="b@x.com")

    assert indexer.unindex_calls == [{"env": "prod", "primary_id": "silver_sales"}]
    git = GitService(repo_root=str(repo))
    assert git.file_sha_on_branch("prod", "silver/sd/sales_order.yaml") is None  # gone from prod
    assert git.file_sha_on_branch("dev", "silver/sd/sales_order.yaml") is not None  # dev kept
    assert outcome.committed_sha
    assert lifecycle.unpublished_prod == [("silver_sales", "b@x.com")]


def test_unpublish_unknown_env_rejected(repo):
    svc = _make_service(repo, _FakeIndexer(), _FakeLifecycle(dev_published_for=["silver_sales"]))
    with pytest.raises(ValueError):
        svc.unpublish("silver_sales", "staging", by="a@x.com")

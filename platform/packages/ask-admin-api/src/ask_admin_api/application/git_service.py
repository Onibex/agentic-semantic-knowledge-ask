"""GitPython wrapper for YAML versioning in the visualizer.

Every write operation (enrichment save, state transition, merge resolution)
calls commit() so the full history of the semantic layer is in git with
semantic authors:
  - human editor   → their email from the UI author input
  - sap-ingestor   → sap-ingestor@onibex.com  (Iter 5 merge auto-apply)
  - visualizer-bot → visualizer-bot@onibex.com (state machine transitions)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from git import Actor, Commit, InvalidGitRepositoryError, Repo

from ..models.viz_models import CommitEntry

logger = logging.getLogger(__name__)


def _auto_init_enabled() -> bool:
    """`SEMANTIC_LAYER_AUTO_INIT` — from-zero self-serve (BACKLOG group B P1).

    Off by default in code; docker-compose defaults it to true, where
    REPO_ROOT is the dedicated /app/semantic-layer mount. Host-side runs keep
    the old behaviour unless the operator opts in — auto-initting a workspace
    nested inside a code checkout would create a surprise nested repo.
    """
    return os.getenv("SEMANTIC_LAYER_AUTO_INIT", "").strip().lower() in {"1", "true", "yes"}


class GitService:
    def __init__(self, repo_root: str = ".") -> None:
        self._repo_root = repo_root
        self.repo = self._open_repo()

    def _open_repo(self) -> Repo | None:
        # From-zero auto-init: a fresh `docker compose up` mounts an empty
        # semantic-layer dir with no .git. Without it, dev publish silently
        # degrades to OpenSearch-only (no history) and prod publish hard-fails
        # with a misleading "no content on 'dev'". Init EXACTLY at repo_root —
        # never via the parent climb, which is the pre-split nested-repo bug
        # class. Seed commit + master→main + dev/prod cut all happen later in
        # `init_release_branches` (boot + pre-publish), so a bare init is enough.
        root = Path(self._repo_root)
        if _auto_init_enabled() and root.is_dir() and not (root / ".git").exists():
            try:
                Repo.init(self._repo_root)
                logger.warning(
                    "SEMANTIC_LAYER_AUTO_INIT: initialised a fresh git repo at %s (no .git found)",
                    self._repo_root,
                )
            except Exception:  # noqa: BLE001 — fall through to the normal open/warn path
                logger.exception("SEMANTIC_LAYER_AUTO_INIT: git init failed at %s", self._repo_root)
        try:
            return Repo(self._repo_root, search_parent_directories=True)
        except InvalidGitRepositoryError:
            logger.warning(
                "No git repo found at %s — commits will be no-ops. "
                "Run `git init` there, or set SEMANTIC_LAYER_AUTO_INIT=true.",
                self._repo_root,
            )
            return None

    def _reset_repo(self) -> bool:
        """Recreate the Repo after its backing git child process died.

        GitPython attaches long-lived ``git cat-file --batch`` children to the
        Repo; if one dies (OOM / staleness) every later op raises
        ``BrokenPipeError`` until the Repo is rebuilt — and because GitService is
        a process-wide singleton, it stays broken until the service restarts.
        Close the dead handles and re-open so the next attempt gets fresh
        children. Returns True when a usable Repo is back.
        """
        try:
            if self.repo is not None:
                self.repo.close()
        except Exception:  # noqa: BLE001 — closing a broken Repo is best-effort
            pass
        self.repo = self._open_repo()
        return self.repo is not None

    def _with_pipe_recovery(self, op):
        """Run ``op``; on ``BrokenPipeError`` recreate the Repo once and retry.

        A dead git child (the BrokenPipe case) is the one error worth retrying:
        the Repo is rebuilt and the same op runs against fresh subprocesses. Any
        other exception is logged and swallowed (returns None) exactly as before.
        """
        for attempt in (1, 2):
            try:
                return op()
            except BrokenPipeError as exc:
                if attempt == 1 and self._reset_repo():
                    logger.warning("git pipe broken — recreated Repo, retrying: %s", exc)
                    continue
                logger.exception("git op failed (broken pipe, no recovery): %s", exc)
                return None
            except Exception as exc:  # noqa: BLE001
                logger.exception("git op failed: %s", exc)
                return None
        return None

    # ── Write ────────────────────────────────────────────────────────────────

    def commit(
        self,
        file_paths: list[str],
        message: str,
        author_name: str,
        author_email: str,
    ) -> str | None:
        """Stage file_paths and create a commit.  Returns the commit SHA or None
        when git is unavailable.  file_paths must be POSIX paths relative to
        the repo root — and that root is the semantic-layer repo (e.g.
        ``C:/Onibex/python/semantic-layer-s4h``), NOT the code repo. After
        the split, REPO_ROOT points there and file_paths look like
        ``silver/sd/sales_order.yaml`` (no monorepo prefix).

        Each path is classified by what it now looks like on disk:
          - exists  → staged as ADD/MODIFY via ``index.add``
          - missing → staged as REMOVE via ``index.remove`` (so deletions
                      land in the commit too — required for sidecar
                      cleanups like ``clear_resolved`` followed by a commit)
        """
        if self.repo is None:
            logger.warning("git unavailable — skipping commit for %s", file_paths)
            return None

        def _do():
            self._stage(file_paths)
            actor = Actor(author_name, author_email)
            # ``skip_hooks=True`` bypasses pre-commit / commit-msg hooks. These
            # are authored for HUMAN commits (ruff / format / trailing-whitespace
            # / detect-private-key) and assume a working shell environment.
            # Backend writes are deterministic (ruamel round-trip + Pydantic
            # validation already happened upstream); routing them through user
            # hooks just adds a failure surface — e.g. WSL hijacking #!/bin/sh
            # on Windows produces a HookExecutionError and 502s the YAML write.
            c = self.repo.index.commit(message, author=actor, committer=actor, skip_hooks=True)
            logger.info("git commit %s by %s: %s", c.hexsha[:7], author_email, message)
            return c.hexsha

        return self._with_pipe_recovery(_do)

    def commit_if_changed(
        self,
        file_paths: list[str],
        message: str,
        author_name: str,
        author_email: str,
    ) -> str | None:
        """Stage + commit only when the staged paths actually differ from HEAD.

        Avoids empty commits when the content is byte-identical (e.g. re-ingesting
        the SAME SAP payload rewrites the baseline to the same bytes). Returns the
        SHA, or None when git is unavailable / nothing changed.
        """
        if self.repo is None:
            return None

        def _do():
            self._stage(file_paths)
            # Anything staged that differs from HEAD? (index vs HEAD diff)
            if self.repo.head.is_valid() and not self.repo.index.diff(self.repo.head.commit):
                return None
            actor = Actor(author_name, author_email)
            c = self.repo.index.commit(message, author=actor, committer=actor, skip_hooks=True)
            logger.info("git commit %s by %s: %s", c.hexsha[:7], author_email, message)
            return c.hexsha

        return self._with_pipe_recovery(_do)

    def _stage(self, file_paths: list[str]) -> None:
        """Split ``file_paths`` by on-disk existence and stage each side.

        Hidden in a helper so ``commit`` reads as one linear flow. GitPython
        is opinionated here: ``index.add`` calls ``os.lstat`` on each path
        and explodes on missing files; deletions need ``index.remove``
        (which itself errors if the path is unknown to git, so we wrap it).
        """
        from pathlib import Path

        if not file_paths or self.repo is None:
            return

        working_dir = Path(self.repo.working_tree_dir or ".")

        to_add: list[str] = []
        to_remove: list[str] = []
        for path in file_paths:
            if (working_dir / path).exists():
                to_add.append(path)
            else:
                to_remove.append(path)

        if to_add:
            self.repo.index.add(to_add)

        if to_remove:
            try:
                # ``r=False`` keeps the operation strict to the given paths
                # (no recursive directory sweep). ``working_tree=False`` is
                # the default — we do NOT want git to also try to delete
                # the file from disk (it's already gone).
                self.repo.index.remove(to_remove)
            except Exception as exc:  # noqa: BLE001
                # Path may have never been tracked (e.g. a sidecar that
                # was created and removed within a single backend cycle
                # before any commit landed). Log + continue — the rest of
                # the commit (other paths, if any) should still succeed.
                logger.warning(
                    "git index.remove failed for %s (likely never tracked): %s",
                    to_remove,
                    exc,
                )

    def empty_commit(
        self,
        message: str,
        author_name: str,
        author_email: str,
    ) -> str | None:
        """Create an empty commit (no file changes) to record a runtime event.

        Used to stamp publish events on the history without polluting the YAML
        contents — the file stays clean, the audit trail lives in git log.
        Returns the commit SHA or None when git is unavailable.
        """
        if self.repo is None:
            logger.warning("git unavailable — skipping empty commit: %s", message)
            return None
        try:
            # Build the commit via plumbing so we don't depend on git CLI
            # config (user.name / user.email) — Actor is passed explicitly.
            # We reuse HEAD's tree, which yields an empty commit.
            parent = self.repo.head.commit
            actor = Actor(author_name, author_email)
            new_commit = Commit.create_from_tree(
                self.repo,
                parent.tree,
                message,
                parent_commits=[parent],
                author=actor,
                committer=actor,
            )
            self.repo.head.set_reference(new_commit)
            logger.info(
                "git empty commit %s by %s: %s",
                new_commit.hexsha[:7],
                author_email,
                message,
            )
            return new_commit.hexsha
        except Exception as exc:  # noqa: BLE001
            logger.exception("git empty commit failed: %s", exc)
            return None

    # ── Branches (Iter 2 — environment release branches) ──────────────────────
    #
    # The semantic-layer repo has three branches (audit §3):
    #   main  — working definition (admins edit + commit here)
    #   dev   — snapshot of what's published to ask-*-dev   (backend-only writes)
    #   prod  — snapshot of what's published to ask-*-prod  (backend-only writes)
    #
    # Publish to an env never MERGES; it does a file-by-file ``git checkout
    # <source> -- <paths>`` overwrite onto the env branch (audit §3.2/§3.3), so
    # only the published Data Product's files move — unrelated working changes
    # never leak across. Conflicts are structurally impossible.

    def current_branch(self) -> str:
        """Active branch name, or ``""`` when detached / no repo."""
        if self.repo is None:
            return ""
        try:
            return self.repo.active_branch.name
        except TypeError:
            # Detached HEAD — no symbolic branch.
            return ""

    def list_branches(self) -> list[str]:
        if self.repo is None:
            return []
        return [h.name for h in self.repo.heads]

    def init_release_branches(self, names: tuple[str, ...] = ("dev", "prod")) -> list[str]:
        """Create the release branches from the current HEAD if absent. Idempotent.

        Returns the list of branches actually created (empty when all existed).
        Guards the bootstrap edge cases the audit + understand-phase flagged:
          - no repo            → no-op
          - 0 commits (invalid HEAD) → auto-seed a root commit, then branch
            (a freshly ``git init``'d repo has no base to cut dev/prod from, so
            publish would fail at ``git checkout dev``).

        KNOWN LIMITATION (Iter 2): on a populated repo, ``dev``/``prod`` are cut
        as FULL copies of ``main`` — so the git branch initially contains every
        YAML even though ``ask-*-{env}`` starts empty (nothing published yet).
        The git branch therefore overstates what's actually deployed until the
        first publish of each DP. This is reconciled at the Iter-4 read cutover
        (re-index + branch reseed); for the Iter-2 write capability it's benign
        (publishes still target the correct env index + commit only real diffs).
        """
        if self.repo is None:
            return []
        if not self.repo.head.is_valid():
            # From-zero gap: a freshly `git init`'d semantic-layer repo has no
            # commit yet, so there is no base to cut dev/prod from and publish
            # would fail at `git checkout dev`. Seed a root commit from whatever
            # is in the working tree; the publish's real content commits (with
            # the JWT author) land on top.
            self._seed_initial_commit()
            if not self.repo.head.is_valid():
                logger.warning(
                    "init_release_branches: repo still has no commits after seeding — "
                    "release branches not created"
                )
                return []
        self._normalize_working_branch()
        base = self.repo.head.commit
        existing = {h.name for h in self.repo.heads}
        created: list[str] = []
        for name in names:
            if name in existing:
                continue
            try:
                self.repo.create_head(name, base)
                created.append(name)
                logger.info("Created release branch %s at %s", name, base.hexsha[:7])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not create release branch %s: %s", name, exc)
        return created

    def _seed_initial_commit(self) -> None:
        """Create the very first commit in an empty repo (unborn HEAD).

        A freshly ``git init``'d semantic-layer repo has files staged/untracked
        but no commit, so there is no base for the release branches. Stage the
        whole working tree and commit it as a root commit with a fixed bootstrap
        identity (real content commits use the JWT author). Uses ``index.commit``
        with an explicit ``Actor`` so it works without any git user.* config and
        does not leak that identity into later commits. Never raises — the seed
        is best-effort and the caller re-checks ``head.is_valid()``.
        """
        if self.repo is None:
            return
        try:
            from git import Actor

            self.repo.git.add(A=True)  # stage everything to .git/index
            idx = self.repo.index
            if not idx.entries:
                # Truly empty repo (no files at all) — nothing to seed. Leave
                # HEAD unborn; the caller skips branch creation.
                logger.info("empty semantic-layer repo (no files) — not seeding a commit")
                return
            actor = Actor("ask-platform", "seed@onibex.com")
            # parent_commits=[] → root commit (default None would deref the
            # unborn HEAD and raise); head=True moves the current branch ref.
            idx.commit(
                "Seed semantic layer (auto-init)",
                parent_commits=[],
                author=actor,
                committer=actor,
            )
            logger.info("Seeded initial commit in empty semantic-layer repo")
        except Exception as exc:  # noqa: BLE001 — never block publish on the seed
            logger.warning("Could not seed initial commit: %s", exc)

    def _normalize_working_branch(self, working: str = "main") -> None:
        """Rename a git-default ``master`` working branch to ``main`` (audit Q13).

        The runbook's bare ``git init`` yields ``master`` on most git installs,
        but the publish flow hardcodes ``main`` as the working branch
        (``env_targets.WORKING_BRANCH``) — so a freshly-created semantic-layer
        repo fails publish with ``fatal: invalid reference: main`` until someone
        runs ``git branch -M main`` by hand. Normalising here (called on boot +
        before every publish) closes that gap automatically.

        Only the unambiguous ``master``→``main`` case is touched: if ``main``
        already exists, or there is no ``master``, this is a no-op. Any other
        working-branch name is left alone (a deliberate non-standard setup).
        """
        if self.repo is None:
            return
        heads = {h.name for h in self.repo.heads}
        if working in heads or "master" not in heads:
            return
        try:
            self.repo.git.branch("-M", "master", working)
            logger.info("Normalised working branch master → %s (git-default mismatch)", working)
        except Exception as exc:  # noqa: BLE001 — never block boot/publish on this
            logger.warning("Could not normalise working branch master → %s: %s", working, exc)

    def checkout_branch(self, name: str) -> None:
        """Switch the working tree to ``name``. Raises on dirty/unknown branch."""
        if self.repo is None:
            return
        self.repo.git.checkout(name)

    def stash_push(self, message: str = "") -> bool:
        """Stash uncommitted tracked changes so a branch switch can proceed.

        The publish flow switches to the env branch (``git checkout dev``); any
        uncommitted tracked change whose content differs on that branch (e.g. a
        ``.sap_baseline/*.json`` sidecar rewritten by ingest) makes git ABORT
        the switch. Stashing isolates those changes during the promote; the
        caller pops them after returning to the working branch, so the admin's
        uncommitted edits are preserved, not lost.

        Returns True iff a stash was created (tree was dirty). False when the
        tree is already clean (nothing to pop later).
        """
        if self.repo is None:
            return False
        try:
            if not self.repo.is_dirty(untracked_files=False):
                return False
            args = ["push"]
            if message:
                args += ["-m", message]
            self.repo.git.stash(*args)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("git stash push failed: %s", exc)
            return False

    def stash_pop(self) -> None:
        """Restore the most recently stashed working-tree changes (best-effort)."""
        if self.repo is None:
            return
        try:
            self.repo.git.stash("pop")
        except Exception as exc:  # noqa: BLE001
            logger.warning("git stash pop failed: %s", exc)

    def checkout_files_from(self, source_branch: str, paths: list[str]) -> None:
        """Overwrite ``paths`` in the working tree + index from ``source_branch``.

        ``git checkout <source_branch> -- <paths>`` — an overwrite, NOT a merge.
        The listed paths are replaced with the source branch's content and
        staged; everything else on the current branch is untouched. Conflicts
        are impossible (audit §3.3).
        """
        if self.repo is None or not paths:
            return
        self.repo.git.checkout(source_branch, "--", *paths)

    def remove_files(self, paths: list[str]) -> list[str]:
        """Remove ``paths`` from the working tree + index on the current branch.

        ``git rm`` (staged for the next commit). Used by the per-env unpublish to
        delete a Data Product's YAML from the env branch — the inverse of
        ``checkout_files_from``. Tolerant: a path not tracked on this branch is
        skipped (never aborts the whole unpublish). Returns the paths actually
        removed so the caller can decide whether there is anything to commit.
        """
        if self.repo is None or not paths:
            return []
        branch = self.current_branch()
        removed: list[str] = []
        for p in paths:
            # Only touch paths actually tracked on this branch — skip untracked
            # (e.g. a sidecar that never landed here) so it is neither rm'd nor
            # counted as removed.
            if self.file_sha_on_branch(branch, p) is None:
                continue
            try:
                self.repo.git.rm("--ignore-unmatch", "--", p)
                removed.append(p)
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning("remove_files: could not rm %s: %s", p, exc)
        return removed

    def file_sha_on_branch(self, branch: str, path: str) -> str | None:
        """Blob SHA of ``path`` on ``branch``'s tip, or ``None`` if absent."""
        if self.repo is None:
            return None
        try:
            return self.repo.git.rev_parse(f"{branch}:{path}").strip()
        except Exception:  # noqa: BLE001 — path/branch may not exist
            return None

    def commit_on_current_branch(
        self,
        message: str,
        author_name: str,
        author_email: str,
    ) -> str | None:
        """Commit whatever is currently staged on the active branch.

        Used after ``checkout_files_from`` stages the published files onto the
        env branch. Returns the commit SHA, or ``None`` when git is unavailable
        or there is nothing to commit (a re-publish of identical content).
        """
        if self.repo is None:
            return None
        try:
            if not self.repo.index.diff("HEAD"):
                # Nothing staged differs from HEAD — idempotent re-publish.
                logger.info("commit_on_current_branch: no staged changes — skipping (%s)", message)
                return None
            actor = Actor(author_name, author_email)
            c = self.repo.index.commit(message, author=actor, committer=actor, skip_hooks=True)
            logger.info(
                "git commit %s on %s by %s: %s",
                c.hexsha[:7],
                self.current_branch(),
                author_email,
                message,
            )
            return c.hexsha
        except Exception as exc:  # noqa: BLE001
            logger.exception("commit_on_current_branch failed: %s", exc)
            return None

    # ── Read ─────────────────────────────────────────────────────────────────

    def _history_commits(
        self,
        file_path: str,
        *,
        entity_id: str | None,
        branch: str | None,
        message_prefix: str | None,
    ) -> list:
        """Ordered (HEAD-first) commits for a file on a given ref, after filters.

        Shared by ``get_log`` (paginates) + ``get_total_count`` (counts) so the
        two stay in lockstep.

        ``branch``  — which ref to walk (``"main"``/``"dev"``/``"prod"``);
                      ``None`` → the current HEAD (legacy behaviour).
        ``entity_id`` — when set AND no ``message_prefix``, also include commits
                      whose message namespaces the entity (surfaces the legacy
                      ``publish(<id>)`` empty commits on main — Working tab).
        ``message_prefix`` — keep only commits whose message starts with it
                      (``"publish-dev("`` / ``"publish-prod("`` for the env tabs)
                      so shared ancestor commits inherited at branch-cut time are
                      excluded — the env tabs show ONLY their own deploys.
        """
        rev = (branch,) if branch else ()
        candidate_shas: set = {
            c.hexsha for c in self.repo.iter_commits(*rev, paths=file_path, max_count=5000)
        }
        if entity_id and not message_prefix:
            for c in self.repo.iter_commits(*rev, max_count=5000):
                if entity_id in c.message:
                    candidate_shas.add(c.hexsha)
        # Walk the ref HEAD-first once, keep candidates → preserves git's
        # topological order (committed_date ties are unsafe to sort on).
        ordered = [
            c for c in self.repo.iter_commits(*rev, max_count=5000) if c.hexsha in candidate_shas
        ]
        if message_prefix:
            ordered = [c for c in ordered if c.message.strip().startswith(message_prefix)]
        return ordered

    def get_log(
        self,
        file_path: str,
        max_count: int = 50,
        skip: int = 0,
        entity_id: str | None = None,
        branch: str | None = None,
        message_prefix: str | None = None,
    ) -> list[CommitEntry]:
        """Return the commit history for an entity (optionally scoped to a branch).

        Working tab → ``branch="main"`` + ``entity_id`` (all edits + publishes).
        Env tabs    → ``branch="dev"/"prod"`` + ``message_prefix="publish-dev("/
        "publish-prod("`` (only that env's deploys of the file). A non-existent
        branch yields an empty log (caught below).
        """
        if self.repo is None:
            return []
        try:
            ordered = self._history_commits(
                file_path, entity_id=entity_id, branch=branch, message_prefix=message_prefix
            )
            page = ordered[skip : skip + max_count]
            return [
                CommitEntry(
                    sha=c.hexsha,
                    short_sha=c.hexsha[:7],
                    message=c.message.strip(),
                    author_name=c.author.name or "",
                    author_email=c.author.email or "",
                    timestamp=datetime.fromtimestamp(c.committed_date, tz=UTC),
                )
                for c in page
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("git log failed for %s (branch=%s): %s", file_path, branch, exc)
            return []

    def get_diff(self, file_path: str, from_sha: str, to_sha: str) -> str:
        """Return unified diff text for a file between two commits."""
        if self.repo is None:
            return ""
        try:
            return self.repo.git.diff(from_sha, to_sha, "--", file_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("git diff failed: %s", exc)
            return ""

    def get_file_at_commit(self, file_path: str, sha: str) -> str:
        """Return the raw file content at a specific commit SHA."""
        if self.repo is None:
            return ""
        try:
            return self.repo.git.show(f"{sha}:{file_path}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("git show failed for %s@%s: %s", file_path, sha, exc)
            return ""

    def find_last_publish_sha(self, entity_id: str, env: str | None = None) -> str | None:
        """Return the SHA of the most recent publish of ``entity_id``.

        ``env=None`` → the legacy ``publish(<id>)`` runtime-index commit on the
        current HEAD (back-compat). ``env="dev"/"prod"`` → the most recent
        ``publish-<env>(<id>)`` commit on that environment's branch, so
        "Diff vs dev/prod" compares the workspace against exactly what is
        deployed there.

        Returns ``None`` when the entity was never published to the requested
        target (the UI renders a per-env empty state). Env requests do NOT fall
        back to the legacy commit — "diff vs dev" only ever means dev.
        """
        if self.repo is None:
            return None
        if env:
            rev = (env,)  # branch name == env (main/dev/prod, per init_release_branches)
            needle = f"publish-{env}({entity_id})"
        else:
            rev = ()
            needle = f"publish({entity_id})"
        try:
            # An entity may have many publishes over its lifetime; iter_commits
            # is HEAD-first, so the first match is the most recent. A missing
            # env branch raises → caught below → None (never published there).
            for c in self.repo.iter_commits(*rev, max_count=10_000):
                if needle in c.message:
                    return c.hexsha
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("find_last_publish_sha failed for %s (env=%s): %s", entity_id, env, exc)
            return None

    def get_total_count(
        self,
        file_path: str,
        entity_id: str | None = None,
        branch: str | None = None,
        message_prefix: str | None = None,
    ) -> int:
        """Total commits visible in ``get_log`` for this file/entity/branch.

        Mirrors get_log's filter semantics so pagination math stays correct.
        """
        if self.repo is None:
            return 0
        try:
            return len(
                self._history_commits(
                    file_path, entity_id=entity_id, branch=branch, message_prefix=message_prefix
                )
            )
        except Exception:  # noqa: BLE001
            return 0

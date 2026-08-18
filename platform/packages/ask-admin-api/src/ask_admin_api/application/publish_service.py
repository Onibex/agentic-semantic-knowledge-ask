# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Atomic per-environment publish (UX_CHANGES audit §3.2 / Q14, Iter 2).

Publishing a Data Product to an environment is a two-step atomic sequence:

  1. OpenSearch FIRST — index the YAML (+ cascade bronzes + RAG) into the
     env-suffixed indices (``ask-*-dev`` / ``ask-*-prod``). If this fails, we
     stop: no git mutation lands, lifecycle is untouched (Q14).
  2. git file-by-file checkout — overwrite ONLY this DP's files onto the env
     branch from the source branch (``dev`` ← ``main``, ``prod`` ← ``dev``) and
     commit. This is an overwrite, never a merge, so unrelated working changes
     never leak and conflicts are structurally impossible (audit §3.2/§3.3).
  3. lifecycle — record dev_published / prod_published.

The git branch dance (checkout env → checkout files → commit → checkout back)
mutates the shared working tree, so it is serialized under a process lock.
Concurrency across processes is out of scope for v1 (audit Q15, last-write-wins).

Iter 2 scope: this is the env-write CAPABILITY. The legacy un-suffixed publish
(``/index/{id}``) and the orchestrator read path are untouched; the read-side
cutover + re-index land in Iter 4.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..models.viz_models import VizLayer
from .env_targets import (
    WORKING_BRANCH,
    branch_for,
    normalize_env,
    source_branch_for,
)
from .git_service import GitService
from .lifecycle_service import LifecycleService, PublishNotReadyError
from .yaml_file_service import YAMLFileService, YAMLNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class PublishOutcome:
    entity_id: str
    env: str
    committed_sha: str | None
    indexed_paths: list[str] = field(default_factory=list)
    cascade_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entities_indexed: int = 0
    fields_indexed: int = 0
    edges_indexed: int = 0
    rag_chunks_indexed: int = 0


@dataclass
class UnpublishOutcome:
    entity_id: str
    env: str
    committed_sha: str | None
    entities_removed: int = 0
    fields_removed: int = 0
    edges_removed: int = 0
    rag_chunks_removed: int = 0
    warnings: list[str] = field(default_factory=list)


class EnvIndexer(Protocol):
    """Indexes resolved YAML content into an environment's OpenSearch indices.

    Injectable so the git-flow + lifecycle wiring is unit-testable without a
    live OpenSearch (tests pass a fake; production uses ``DefaultEnvIndexer``).
    """

    def index(
        self, env: str, *, primary_id: str, primary_content: str, cascade: dict[str, str]
    ) -> dict[str, Any]:
        """Index ``primary_content`` (+ each ``cascade`` {entity_id: content})
        into the env-suffixed registry + RAG indices. Returns a totals dict
        with keys: entities, fields, edges, rag, cascade_ids, warnings.
        Raises on a hard OpenSearch failure (publish aborts before git)."""
        ...

    def unindex(self, env: str, *, primary_id: str) -> dict[str, Any]:
        """Remove ONLY the primary entity (entity + fields + its edges + its RAG
        chunks) from the env-suffixed indices — the inverse of ``index``. NEVER
        cascades to composed_of bronzes (they may be shared by another published
        entity). Returns a totals dict: entities, fields, edges, rag, warnings."""
        ...


class DefaultEnvIndexer:
    """Production indexer — wraps the env-targeted KG factory."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def index(
        self, env: str, *, primary_id: str, primary_content: str, cascade: dict[str, str]
    ) -> dict[str, Any]:
        from ask_knowledge_graph.application.factory import build_default_ingestion_service
        from ask_knowledge_graph.domain.models import IngestionRequest

        ingestion = build_default_ingestion_service(self._config, env=env)
        totals = {"entities": 0, "fields": 0, "edges": 0, "rag": 0}
        cascade_ids: list[str] = []
        warnings: list[str] = []

        def _ingest(content: str) -> Any:
            return ingestion.ingest_yaml(IngestionRequest(yaml_content=content))

        # Primary entity (OpenSearch first — a failure here raises before git).
        primary = _ingest(primary_content)
        if primary.error:
            raise RuntimeError(f"index {primary_id} into {env} failed: {primary.error}")
        totals["entities"] += primary.entities_indexed
        totals["fields"] += primary.fields_indexed
        totals["edges"] += primary.edges_indexed

        # Cascade bronzes — best-effort (a missing/failed bronze warns, doesn't
        # abort the publish; the primary already landed).
        for cid, content in cascade.items():
            try:
                r = _ingest(content)
                if r.error:
                    warnings.append(f"cascade index '{cid}' failed: {r.error}")
                    continue
                cascade_ids.append(cid)
                totals["entities"] += r.entities_indexed
                totals["fields"] += r.fields_indexed
                totals["edges"] += r.edges_indexed
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"cascade index '{cid}' failed: {exc}")

        # RAG cascade for the primary Silver — best-effort (no embedder/OpenSearch
        # in some envs → 0, never aborts).
        totals["rag"] += self._cascade_rag(env, primary_id, primary_content, warnings)

        return {**totals, "cascade_ids": cascade_ids, "warnings": warnings}

    def _cascade_rag(self, env: str, entity_id: str, content: str, warnings: list[str]) -> int:
        try:
            from ask_knowledge_graph.application.factory import (
                build_default_rag_indexing_service,
            )
            from ask_knowledge_graph.application.rag_chunking import build_chunks
            from ask_knowledge_graph.application.rag_text_renderer import (
                render_yaml_for_embedding,
            )

            text, base_meta = render_yaml_for_embedding(content)
            if base_meta.get("layer") == "bronze":
                return 0
            base_meta = dict(base_meta)
            base_meta["source_file"] = f"{entity_id}.yaml"
            chunks = build_chunks(text, base_meta)
            rag = build_default_rag_indexing_service(self._config, env=env)
            return int(rag.index_chunks("rag_schema", chunks).indexed)
        except Exception as exc:  # noqa: BLE001 — RAG is best-effort
            warnings.append(f"RAG cascade for '{entity_id}' skipped: {exc}")
            return 0

    def unindex(self, env: str, *, primary_id: str) -> dict[str, Any]:
        from ask_knowledge_graph.infrastructure.opensearch_repository import (
            OpenSearchAskRepository,
        )

        repo = OpenSearchAskRepository(env=env)
        totals = {"entities": 0, "fields": 0, "edges": 0, "rag": 0}
        warnings: list[str] = []

        # Entity + fields (env-aware, layer-guarded to silver/gold, plus the
        # legacy `metric` layer kept deletable until the registry purge runs —
        # see REQ_METRICS_PURGE.md. A missing entity or a bronze raises
        # ValueError, which we treat as "nothing on the registry side" and
        # still clear edges + RAG).
        try:
            stats = repo.delete_entity_and_fields(primary_id)
            totals["entities"] += int(stats.get("entities_deleted", 0))
            totals["fields"] += int(stats.get("fields_deleted", 0))
        except ValueError as exc:
            warnings.append(f"entity delete '{primary_id}': {exc}")

        # Edges where this entity is an endpoint (best-effort, env-aware).
        totals["edges"] += repo.delete_edges_for_entity(primary_id)

        # RAG chunks for this entity (best-effort — no embedder/OpenSearch → 0).
        try:
            from ask_knowledge_graph.application.factory import (
                build_default_rag_indexing_service,
            )

            rag = build_default_rag_indexing_service(self._config, env=env)
            res = rag.delete_documents("rag_schema", entity_ids=[primary_id])
            totals["rag"] += res if isinstance(res, int) else int(getattr(res, "deleted", 0) or 0)
        except Exception as exc:  # noqa: BLE001 — RAG is best-effort
            warnings.append(f"RAG delete for '{primary_id}' skipped: {exc}")

        return {**totals, "warnings": warnings}


# Serializes the working-tree branch dance across all PublishService instances
# in the process (each router request builds its own instance).
_GIT_LOCK = threading.Lock()


class PublishService:
    """Publishes a Data Product to ``dev`` or ``prod`` atomically."""

    def __init__(
        self,
        *,
        repo_root: str,
        workspace_path: str,
        baseline_path: str = ".sap_baseline",
        indexer: EnvIndexer | None = None,
        lifecycle: LifecycleService | None = None,
        git: GitService | None = None,
        yaml_service: YAMLFileService | None = None,
    ) -> None:
        self._repo_root = Path(repo_root)
        self._baseline_path = baseline_path
        self._yaml = yaml_service or YAMLFileService(
            workspace_path=workspace_path, repo_root=repo_root
        )
        self._git = git or GitService(repo_root=repo_root)
        self._lifecycle = lifecycle or LifecycleService()
        self._indexer = indexer or DefaultEnvIndexer(_load_config())

    # ── Public API ────────────────────────────────────────────────────────────

    def publish(self, entity_id: str, env: str, *, by: str) -> PublishOutcome:
        norm = normalize_env(env)
        if norm is None:
            raise ValueError(f"publish requires env dev/prod, got {env!r}.")

        # Prod gate (audit §2.2 rule 3): prod is publishable iff a dev publish
        # exists AND prod is not already on that same dev version.
        if norm == "prod":
            lc = self._lifecycle.get(entity_id)
            if lc is None or lc.dev_published is None:
                raise PublishNotReadyError(
                    f"Cannot publish '{entity_id}' to prod before a dev publish exists."
                )
            if lc.prod_published is not None and lc.prod_published.sha == lc.dev_published.sha:
                raise PublishNotReadyError(
                    f"'{entity_id}' prod is already up to date with dev "
                    f"(v{lc.prod_published.version}) — nothing to promote."
                )

        try:
            node = self._yaml.get_yaml(entity_id)
        except YAMLNotFoundError as exc:
            raise YAMLNotFoundError(str(exc)) from exc

        # Normalise master→main + bootstrap dev/prod BEFORE reading from the
        # source branch. On a freshly `git init`'d semantic-layer repo the
        # working branch is `master` and dev/prod don't exist yet, so the
        # source-branch reads below (`git show main:<file>` for dev,
        # `dev:<file>` for prod) would fail with "invalid object name". Doing
        # it here — idempotent, lock-serialized — makes the FIRST publish on a
        # brand-new repo succeed (_promote_on_git calls it again, harmlessly).
        with _GIT_LOCK:
            self._git.init_release_branches()

        source = source_branch_for(norm)
        paths = self._collect_paths(node, source)
        # Read each path's content FROM THE SOURCE BRANCH (dev←main, prod←dev),
        # so prod promotes exactly what's on dev — never main's current state.
        contents = self._read_contents(paths, source)
        primary_path = self._rel(node.file_path)
        primary_content = contents.get(primary_path) or ""
        if not primary_content and source == WORKING_BRANCH:
            # dev publishes from main, whose tip == the working tree, so a
            # working-tree fallback is safe. NEVER for prod: there the working
            # tree is main, not the dev content we must promote — falling back
            # would index main's content into ask-*-prod.
            primary_content = self._read_working(primary_path)
        if not primary_content:
            raise RuntimeError(
                f"publish {entity_id} to {norm}: no content for {primary_path} on '{source}'."
            )
        cascade_contents = {
            cid: contents[p]
            for cid, p in self._cascade_path_by_id(node, source).items()
            if contents.get(p)
        }

        # 1. OpenSearch FIRST (Q14). A hard failure raises here → no git mutation.
        totals = self._indexer.index(
            norm,
            primary_id=entity_id,
            primary_content=primary_content,
            cascade=cascade_contents,
        )

        # 2. git file-by-file checkout onto the env branch (serialized).
        committed_sha = self._promote_on_git(norm, source, paths, entity_id, by)

        # 3. lifecycle — best-effort (OpenSearch + git already landed; the
        # lifecycle index is a denormalized cache recoverable via rebuild).
        try:
            if norm == "dev":
                self._lifecycle.on_publish_dev(entity_id, by=by)
            else:
                self._lifecycle.on_publish_prod(entity_id, by=by)
        except Exception:  # noqa: BLE001
            logger.warning("lifecycle on_publish_%s failed for %s", norm, entity_id, exc_info=True)

        return PublishOutcome(
            entity_id=entity_id,
            env=norm,
            committed_sha=committed_sha,
            indexed_paths=paths,
            cascade_ids=list(totals.get("cascade_ids", [])),
            warnings=list(totals.get("warnings", [])),
            entities_indexed=int(totals.get("entities", 0)),
            fields_indexed=int(totals.get("fields", 0)),
            edges_indexed=int(totals.get("edges", 0)),
            rag_chunks_indexed=int(totals.get("rag", 0)),
        )

    def unpublish(self, entity_id: str, env: str, *, by: str) -> UnpublishOutcome:
        """Remove ONE Data Product from an environment — the inverse of publish.

        Makes the entity no longer answerable in ``env`` (it drops out of the
        env entity registry → Option B's scope intersection excludes it) while
        keeping it in dev/working. Physical + reversible: re-publish restores it.

        Same atomic ordering as publish (OpenSearch first, then git, then
        lifecycle). NO cascade — only the primary entity is removed; composed_of
        bronzes stay (they may be shared by another published entity).
        """
        norm = normalize_env(env)
        if norm is None:
            raise ValueError(f"unpublish requires env dev/prod, got {env!r}.")

        lc = self._lifecycle.get(entity_id)
        current = None if lc is None else (lc.dev_published if norm == "dev" else lc.prod_published)
        if current is None:
            raise PublishNotReadyError(
                f"'{entity_id}' is not published to {norm} — nothing to unpublish."
            )
        # Inverse gate (mirror of publish's dev→prod): unpublish prod before dev.
        if norm == "dev" and lc is not None and lc.prod_published is not None:
            raise PublishNotReadyError(
                f"Cannot unpublish '{entity_id}' from dev while it is published to "
                f"prod — unpublish from prod first."
            )

        # Resolve the primary YAML path for git removal (the entity still exists
        # in the workspace — we only remove it from the ENV branch + indices).
        primary_path: str | None = None
        try:
            node = self._yaml.get_yaml(entity_id)
            primary_path = self._rel(node.file_path)
        except YAMLNotFoundError:
            pass  # gone from workspace already — env-branch/index cleanup still runs

        # 1. OpenSearch FIRST (mirror publish). Primary entity only — no cascade.
        totals = self._indexer.unindex(norm, primary_id=entity_id)

        # 2. git: remove the primary YAML + its enrichments sidecar from the env
        # branch (NOT the composed_of bronzes — shared). Sidecar path computed
        # unconditionally; remove_files tolerates a path not tracked on the branch.
        paths = [
            p for p in (primary_path, f"{self._baseline_path}/{entity_id}.enrichments.json") if p
        ]
        committed_sha = self._demote_on_git(norm, paths, entity_id, by)

        # 3. lifecycle — best-effort (OpenSearch + git already landed).
        try:
            if norm == "dev":
                self._lifecycle.on_unpublish_dev(entity_id, by=by)
            else:
                self._lifecycle.on_unpublish_prod(entity_id, by=by)
        except Exception:  # noqa: BLE001
            logger.warning(
                "lifecycle on_unpublish_%s failed for %s", norm, entity_id, exc_info=True
            )

        return UnpublishOutcome(
            entity_id=entity_id,
            env=norm,
            committed_sha=committed_sha,
            entities_removed=int(totals.get("entities", 0)),
            fields_removed=int(totals.get("fields", 0)),
            edges_removed=int(totals.get("edges", 0)),
            rag_chunks_removed=int(totals.get("rag", 0)),
            warnings=list(totals.get("warnings", [])),
        )

    # ── Internals ───────────────────────────────────────────────────────────────

    def _restore_working_branch(self, original: str, entity_id: str) -> None:
        """Best-effort return to the pre-publish branch after the env-branch dance.

        Tries ``original`` first, then the canonical working branch (``main``)
        in case ``original`` no longer resolves (e.g. it was a pre-normalize
        ``master`` that ``init_release_branches`` renamed away). A force checkout
        is the last resort: if a mid-dance failure left the env branch dirty a
        plain checkout can refuse, and env branches are backend-only so
        discarding their uncommitted state is safe. Never raises — the caller
        runs this in a ``finally``.
        """
        for branch in (original, WORKING_BRANCH):
            try:
                self._git.checkout_branch(branch)
                return
            except Exception:  # noqa: BLE001
                continue
        try:
            if self._git.repo is not None:
                self._git.repo.git.checkout(WORKING_BRANCH, "--force")
                return
        except Exception:  # noqa: BLE001
            logger.exception(
                "publish/unpublish %s: failed to restore working branch (tried %s, %s)",
                entity_id,
                original,
                WORKING_BRANCH,
            )

    def _demote_on_git(self, env: str, paths: list[str], entity_id: str, by: str) -> str | None:
        """Remove ``paths`` from the env branch + commit. Inverse of
        ``_promote_on_git`` (git rm instead of checkout-from-source)."""
        if self._git.repo is None:
            logger.warning("unpublish %s from %s: git unavailable — index-only", entity_id, env)
            return None
        target = branch_for(env)
        msg = f"unpublish-{env}({entity_id}): removed by {by}"
        with _GIT_LOCK:
            # Normalise master→main + ensure dev/prod exist BEFORE capturing the
            # branch to restore (see _promote_on_git for the from-zero rationale).
            self._git.init_release_branches()
            original = self._git.current_branch() or WORKING_BRANCH
            stashed = self._git.stash_push(f"unpublish-autostash {entity_id}")
            try:
                self._git.checkout_branch(target)
                removed = self._git.remove_files(paths)
                if not removed:
                    logger.info(
                        "unpublish %s from %s: no tracked paths on '%s' to remove",
                        entity_id,
                        env,
                        target,
                    )
                    return None
                return self._git.commit_on_current_branch(msg, by.split("@")[0] or "publisher", by)
            finally:
                self._restore_working_branch(original, entity_id)
                if stashed:
                    self._git.stash_pop()

    def _promote_on_git(
        self, env: str, source: str, paths: list[str], entity_id: str, by: str
    ) -> str | None:
        if self._git.repo is None:
            logger.warning("publish %s to %s: git unavailable — OpenSearch-only", entity_id, env)
            return None
        target = branch_for(env)
        msg = (
            f"publish-dev({entity_id}): by {by}"
            if env == "dev"
            else f"publish-prod({entity_id}): promoted from dev by {by}"
        )
        with _GIT_LOCK:
            # Normalise master→main + ensure dev/prod exist BEFORE capturing the
            # branch to restore. On a from-zero repo `current_branch()` is still
            # `master` until this runs; capturing it first and then renaming it
            # away would leave the finally trying to restore a branch that no
            # longer resolves ("failed to restore branch master").
            self._git.init_release_branches()
            original = self._git.current_branch() or WORKING_BRANCH
            # Isolate any uncommitted tracked changes (e.g. .sap_baseline/*.json
            # sidecars rewritten by ingest) so `git checkout <env>` does not
            # abort with "local changes would be overwritten". Restored after.
            stashed = self._git.stash_push(f"publish-autostash {entity_id}")
            try:
                self._git.checkout_branch(target)
                # Only cherry-pick paths that actually exist on the source branch.
                # A cascade file never committed to `source` (e.g. an untracked
                # bronze) must NOT abort the whole publish with a git pathspec
                # error — skip it (the indexer already drops empty cascade
                # content) and warn so the gap is visible.
                present = [p for p in paths if self._git.file_sha_on_branch(source, p) is not None]
                missing = [p for p in paths if p not in set(present)]
                if missing:
                    logger.warning(
                        "publish %s to %s: %d path(s) not on '%s' (untracked?) — skipped: %s",
                        entity_id,
                        env,
                        len(missing),
                        source,
                        missing,
                    )
                self._git.checkout_files_from(source, present)
                return self._git.commit_on_current_branch(msg, by.split("@")[0] or "publisher", by)
            finally:
                # Return the working tree to the branch we started on so the
                # admin's editing context (main) is restored.
                self._restore_working_branch(original, entity_id)
                # Restore the admin's uncommitted changes on the working branch
                # (popped here, back on the working branch, so it applies cleanly).
                if stashed:
                    self._git.stash_pop()

    def _collect_paths(self, node: Any, source_branch: str) -> list[str]:
        """The files this publish moves: the entity YAML + its sidecar + (for a
        Silver) its composed_of bronzes + their sidecars. Deduped, POSIX rel."""
        paths: list[str] = []
        seen: set[str] = set()

        def add(p: str | None) -> None:
            if p and p not in seen:
                seen.add(p)
                paths.append(p)

        add(self._rel(node.file_path))
        add(self._sidecar_path(node.id))
        for cid, cpath in self._cascade_path_by_id(node, source_branch).items():
            add(cpath)
            add(self._sidecar_path(cid))
        return paths

    def _cascade_path_by_id(self, node: Any, source_branch: str) -> dict[str, str]:
        """{bronze_id: rel_file_path} for a Silver's composed_of bronzes.

        Silver-only, and now trivially so: ``composed_of`` was removed from the Gold
        contract entirely (see ``GoldNode``), so a Gold has no lineage refs to cascade
        over. The layer guard below stays as the explicit statement of that rule —
        same shape as the legacy ``_cascade_publish``.
        """
        out: dict[str, str] = {}
        if getattr(node, "layer", None) != VizLayer.silver:
            return out
        for ref_id in node.composed_of or []:
            try:
                child = self._yaml.get_yaml(ref_id)
            except YAMLNotFoundError:
                continue
            out[child.id] = self._rel(child.file_path)
        return out

    def _read_contents(self, paths: list[str], source_branch: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in paths:
            content = self._git.get_file_at_commit(p, source_branch)
            if content:
                out[p] = content
        return out

    def _read_working(self, rel_path: str) -> str:
        try:
            return (self._repo_root / rel_path).read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return ""

    def _sidecar_path(self, entity_id: str) -> str | None:
        rel = f"{self._baseline_path}/{entity_id}.enrichments.json"
        return rel if (self._repo_root / rel).exists() else None

    def _rel(self, file_path: str) -> str:
        # YAMLFileService already stores POSIX rel paths; normalise defensively.
        return file_path.replace("\\", "/")


def _load_config() -> dict[str, Any]:
    """Absent file degrades to ``{}`` — see ``application/runtime_config.py``.

    This raiser was the second face of the same defect: a gitignored file
    missing on a fresh clone made every business-domain publish 500 from the
    PublishService constructor (BACKLOG group 0, P1). The indexer it feeds
    reads OpenSearch through env-first settings, so ``{}`` is a working config.
    """
    from .runtime_config import load_runtime_config

    return load_runtime_config()

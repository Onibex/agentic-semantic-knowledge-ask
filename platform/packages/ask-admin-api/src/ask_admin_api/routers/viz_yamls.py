"""/v1/viz/yamls — YAML file management for the YAML Visualizer.

Distinct from /v1/admin/yaml/ (which handles OpenSearch ingestion).
This router reads and writes the YAML files on disk and versions them
with git.  Every successful PUT creates a git commit.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

from ..application.git_service import GitService
from ..application.lifecycle_triggers import fire_on_edit
from ..application.yaml_file_service import YAMLFileService, YAMLNotFoundError
from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.viz_models import (
    RestoreRequest,
    VizLayer,
    VizYAMLNode,
    VizYAMLSummary,
    VizYAMLUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/viz", tags=["viz"])

# ── Lazy singletons (re-created when settings change) ───────────────────────

_yaml_svc_lock = threading.Lock()
_yaml_svc: YAMLFileService | None = None
_git_svc_lock = threading.Lock()
_git_svc: GitService | None = None


def _get_yaml_service() -> YAMLFileService:
    global _yaml_svc
    if _yaml_svc is not None:
        return _yaml_svc
    with _yaml_svc_lock:
        if _yaml_svc is not None:
            return _yaml_svc
        s = get_settings()
        _yaml_svc = YAMLFileService(
            workspace_path=s.workspace_path,
            repo_root=s.repo_root,
        )
    return _yaml_svc


def _get_git_service() -> GitService:
    global _git_svc
    if _git_svc is not None:
        return _git_svc
    with _git_svc_lock:
        if _git_svc is not None:
            return _git_svc
        s = get_settings()
        _git_svc = GitService(repo_root=s.repo_root)
    return _git_svc


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/yamls", response_model=list[VizYAMLSummary])
async def list_yamls(
    layer: Annotated[VizLayer | None, Query(description="Filter by layer")] = None,
    workspace: Annotated[
        str | None,
        Query(
            description=(
                "Optional workspace UUID or slug. When set, the response is "
                "scoped to the entities of the workspace's Data Products plus "
                "their one-hop neighbors (composed_of bronzes + relationship "
                "targets). Omit to list everything in the workspace folder."
            )
        ),
    ] = None,
    business_domain: Annotated[
        str | None,
        Query(
            description=(
                "Optional Business Domain id. When set, the response is scoped to "
                "that single domain's Data Products plus their one-hop neighbors "
                "(the domain canvas, design-spec §03). Narrower than `workspace`; "
                "takes precedence when both are supplied."
            )
        ),
    ] = None,
    _user: TokenClaims = Depends(validate_token),
) -> list[VizYAMLSummary]:
    """List YAML nodes — globally, or scoped to a workspace or a Business Domain.

    Returns lightweight summaries (no fields). Use GET /v1/viz/yamls/{id}
    for the full node including fields and join_graph.
    """
    yaml_svc = _get_yaml_service()
    try:
        summaries = yaml_svc.list_yamls(layer=layer)
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_yamls failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not workspace and not business_domain:
        return summaries

    # Scoped filter — strict server-side intersection. business_domain (one BD,
    # the domain canvas) is narrower than workspace and wins when both are set.
    from ..application.workspace_scope_resolver import (
        WorkspaceScopeError,
        resolve_domain_scope,
        resolve_workspace_scope,
    )

    try:
        scope_ids = (
            resolve_domain_scope(business_domain, yaml_svc)
            if business_domain
            else resolve_workspace_scope(workspace, yaml_svc)
        )
    except WorkspaceScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("scope resolution failed")
        raise HTTPException(status_code=500, detail=f"Scope resolution failed: {exc}") from exc

    return [s for s in summaries if s.id in scope_ids]


@router.get("/yamls/scoped", response_model=list[VizYAMLNode])
async def list_scoped_yamls(
    business_domain: Annotated[
        str | None,
        Query(description="Business Domain id — full nodes for that domain's scope (canvas)."),
    ] = None,
    workspace: Annotated[
        str | None,
        Query(description="Workspace id/slug — full nodes for the workspace scope."),
    ] = None,
    _user: TokenClaims = Depends(validate_token),
) -> list[VizYAMLNode]:
    """Full nodes for a domain/workspace scope in a SINGLE workspace pass.

    The graph/canvas needs each in-scope node's ``composed_of`` + ``relationships``
    (for the edges) — summaries don't carry those. The SPA used to fetch the
    summaries then call GET /yamls/{id} per node, but each of those rglobs and
    parses the WHOLE workspace (O(N x files)). This endpoint resolves the scope
    and returns the full nodes in one pass (``get_yamls_by_ids``), so the canvas
    loads in O(files) instead of O(N x files). ``business_domain`` wins when both
    are supplied (narrower).
    """
    if not business_domain and not workspace:
        raise HTTPException(
            status_code=400, detail="Provide business_domain or workspace to scope the nodes."
        )
    yaml_svc = _get_yaml_service()
    from ..application.workspace_scope_resolver import (
        WorkspaceScopeError,
        resolve_domain_scope,
        resolve_workspace_scope,
    )

    try:
        scope_ids = (
            resolve_domain_scope(business_domain, yaml_svc)
            if business_domain
            else resolve_workspace_scope(workspace, yaml_svc)
        )
    except WorkspaceScopeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("scoped node resolution failed")
        raise HTTPException(status_code=500, detail=f"Scope resolution failed: {exc}") from exc

    return yaml_svc.get_yamls_by_ids(scope_ids)


@router.get("/yamls/search", response_model=list[VizYAMLSummary])
async def search_yamls(
    q: Annotated[str, Query(description="Search query (min length 1)")],
    _user: TokenClaims = Depends(validate_token),
) -> list[VizYAMLSummary]:
    """Search YAML nodes by id, name, or alias."""
    if not q:
        raise HTTPException(status_code=400, detail="q must not be empty")
    q_lower = q.lower()
    try:
        summaries = _get_yaml_service().list_yamls()
    except Exception as exc:  # noqa: BLE001
        logger.exception("search_yamls failed")
        raise HTTPException(status_code=500, detail=str(exc))

    scored: list[tuple[int, VizYAMLSummary]] = []
    for s in summaries:
        score = 0
        if q_lower == s.id.lower():
            score = 100
        elif q_lower == (s.name or "").lower() or q_lower == (s.alias or "").lower():
            score = 80
        elif (
            q_lower in s.id.lower()
            or q_lower in (s.name or "").lower()
            or q_lower in (s.alias or "").lower()
        ):
            score = 60
        if score > 0:
            scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:20]]


@router.get("/yamls/{yaml_id}", response_model=VizYAMLNode)
async def get_yaml(
    yaml_id: str,
    _user: TokenClaims = Depends(validate_token),
) -> VizYAMLNode:
    """Return the full VizYAMLNode for a given id (fields, join_graph, _meta)."""
    try:
        return _get_yaml_service().get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_yaml failed for %s", yaml_id)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/yamls/{yaml_id}", response_model=VizYAMLNode)
async def update_yaml(
    yaml_id: str,
    req: VizYAMLUpdateRequest,
    _user: TokenClaims = Depends(validate_token),
) -> VizYAMLNode:
    """Update a YAML node and commit to git.

    Enrichment props (any layer): description, alias, per-field role / agg /
    synonyms / description; plus join_graph + relationships (Silver/Gold).

    FULL structural edit (edit-in-full parity with Create): send ``fields_full``
    (add/remove/rename/retype/key/source), ``composed_of``, ``grain`` and/or
    ``module`` to replace those sections wholesale — the body is then
    re-normalized by the EntityDeriver and re-validated. id / layer / version /
    internal_id / source_system stay system-managed.
    """
    try:
        node = _get_yaml_service().update_yaml(
            yaml_id=yaml_id,
            req=req,
            git_service=_get_git_service(),
            author_name=_user.email.split("@")[0],
            author_email=_user.email,
        )
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        # Structural edit produced an invalid body (failed node validation).
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("update_yaml failed for %s", yaml_id)
        raise HTTPException(status_code=500, detail=str(exc))

    # Lifecycle trigger: an edit moves the DP back to "In Review" (audit §5.3).
    fire_on_edit(yaml_id)
    return node


# Maps the History tab → (git branch, message-prefix filter) — UX_CHANGES §4.4.
#   working → current HEAD (the working branch, normally "main"), all edits +
#             publishes. We pass None (HEAD) rather than a literal "main" so the
#             tab is robust to the repo's actual working-branch name and stays
#             byte-identical to the pre-Iter-3 behaviour.
#   dev     → dev branch, only publish-dev(<id>) commits
#   prod    → prod branch, only publish-prod(<id>) commits
_HISTORY_BRANCHES: dict[str, tuple[str | None, str | None]] = {
    "working": (None, None),
    "dev": ("dev", "publish-dev("),
    "prod": ("prod", "publish-prod("),
}


@router.get("/yamls/{yaml_id}/history")
async def get_yaml_history(
    yaml_id: str,
    page: int = 1,
    per_page: int = 20,
    branch: str = "working",
    _user: TokenClaims = Depends(validate_token),
) -> dict:
    """Return paginated git commit history for a YAML file (UX_CHANGES §4.4).

    ``branch`` selects the History tab: ``working`` (default, the main branch —
    every edit / AI Assist / merge / publish), ``dev`` or ``prod`` (only that
    env's publish commits). Restore from any tab writes back to main.
    """
    if branch not in _HISTORY_BRANCHES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown history branch '{branch}' — expected working/dev/prod.",
        )
    git_branch, message_prefix = _HISTORY_BRANCHES[branch]

    try:
        node = _get_yaml_service().get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    git_svc = _get_git_service()
    skip = (page - 1) * per_page
    # entity_id (for the publish empty-commit union) only applies to the working
    # tab; the env tabs isolate via message_prefix.
    entity_id = node.id if message_prefix is None else None
    commits = git_svc.get_log(
        node.file_path,
        max_count=per_page,
        skip=skip,
        entity_id=entity_id,
        branch=git_branch,
        message_prefix=message_prefix,
    )
    total = git_svc.get_total_count(
        node.file_path,
        entity_id=entity_id,
        branch=git_branch,
        message_prefix=message_prefix,
    )

    return {
        "yaml_id": yaml_id,
        "file_path": node.file_path,
        "branch": branch,
        "commits": [c.model_dump() for c in commits],
        "page": page,
        "per_page": per_page,
        "total_count": total,
        "has_more": (skip + len(commits)) < total,
    }


@router.get("/yamls/{yaml_id}/history/{sha}", response_model=VizYAMLNode)
async def get_yaml_at_commit(
    yaml_id: str,
    sha: str,
    _user: TokenClaims = Depends(validate_token),
) -> VizYAMLNode:
    """Return the YAML content as a VizYAMLNode at the given commit SHA."""
    yaml_svc = _get_yaml_service()
    git_svc = _get_git_service()

    try:
        node = yaml_svc.get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    text = git_svc.get_file_at_commit(node.file_path, sha)
    if not text:
        raise HTTPException(
            status_code=422,
            detail=f"Could not retrieve content for '{yaml_id}' at SHA '{sha}' — SHA may be invalid",
        )

    try:
        raw = load_yaml_text(text)
        if not isinstance(raw, dict):
            raise ValueError("YAML did not parse to a dict")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"YAML parse error at SHA {sha}: {exc}")

    try:
        return yaml_svc._raw_to_node(raw, Path(node.file_path))
    except Exception as exc:
        logger.exception("_raw_to_node failed for %s@%s", yaml_id, sha)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/yamls/{yaml_id}/diff")
async def get_yaml_diff(
    yaml_id: str,
    from_sha: Annotated[str, Query(description="Start commit SHA")],
    to_sha: Annotated[str, Query(description="End commit SHA")],
    _user: TokenClaims = Depends(validate_token),
) -> dict:
    """Return unified diff text for a YAML file between two commit SHAs."""
    yaml_svc = _get_yaml_service()
    git_svc = _get_git_service()

    try:
        node = yaml_svc.get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        diff_text = git_svc.get_diff(node.file_path, from_sha, to_sha)
        # Also return both blobs so the SPA can render a Monaco DiffEditor
        # (side-by-side, syntax-aware). Unified diff stays in the response
        # for callers that still consume the legacy line-by-line viewer.
        content_from = git_svc.get_file_at_commit(node.file_path, from_sha)
        content_to = git_svc.get_file_at_commit(node.file_path, to_sha)
    except Exception as exc:
        logger.exception("get_diff failed for %s", yaml_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "yaml_id": yaml_id,
        "from_sha": from_sha,
        "to_sha": to_sha,
        "unified_diff": diff_text,
        "content_from": content_from,
        "content_to": content_to,
    }


@router.get("/yamls/{yaml_id}/diff-with-last-publish")
async def get_yaml_diff_with_last_publish(
    yaml_id: str,
    env: str | None = None,
    _user: TokenClaims = Depends(validate_token),
) -> dict:
    """Return the unified diff between what is published to ``env`` and the
    current HEAD content of the YAML.

    ``env="dev"/"prod"`` compares against the last ``publish-<env>(<id>)`` commit
    on that environment's branch — i.e. exactly what is deployed there. ``env``
    omitted falls back to the legacy ``publish(<id>)`` runtime-index commit.
    Returns ``last_publish_sha = None`` when the entity was never published to
    the requested target — the UI uses that to render a per-env empty state.
    """
    if env is not None and env not in ("dev", "prod"):
        raise HTTPException(status_code=400, detail=f"env must be 'dev' or 'prod', got '{env}'")

    yaml_svc = _get_yaml_service()
    git_svc = _get_git_service()

    try:
        node = yaml_svc.get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    last_sha = git_svc.find_last_publish_sha(yaml_id, env=env)
    if last_sha is None:
        return {
            "yaml_id": yaml_id,
            "env": env,
            "last_publish_sha": None,
            "unified_diff": "",
        }

    try:
        diff_text = git_svc.get_diff(node.file_path, last_sha, "HEAD")
    except Exception as exc:
        logger.exception("get_diff (last-publish) failed for %s", yaml_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "yaml_id": yaml_id,
        "env": env,
        "last_publish_sha": last_sha,
        "unified_diff": diff_text,
    }


@router.post("/yamls/{yaml_id}/restore/{sha}", response_model=VizYAMLNode)
async def restore_yaml_at_commit(
    yaml_id: str,
    sha: str,
    req: RestoreRequest,
    _user: TokenClaims = Depends(validate_token),
) -> VizYAMLNode:
    """Restore a YAML file to its content at a specific commit SHA."""
    yaml_svc = _get_yaml_service()
    git_svc = _get_git_service()
    settings = get_settings()
    repo_root = Path(settings.repo_root).resolve()

    try:
        node = yaml_svc.get_yaml(yaml_id)
    except YAMLNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    content = git_svc.get_file_at_commit(node.file_path, sha)
    if not content:
        raise HTTPException(
            status_code=422,
            detail=f"Could not retrieve content for '{yaml_id}' at SHA '{sha}' — SHA may be invalid",
        )

    abs_path = repo_root / node.file_path
    try:
        abs_path.write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.exception("Failed to write restored content for %s", yaml_id)
        raise HTTPException(status_code=500, detail=f"File write failed: {exc}")

    commit_message = f"restore({yaml_id}): revert to {sha[:7]}"
    if req.reason:
        commit_message += f" — {req.reason}"

    git_svc.commit(
        [node.file_path],
        commit_message,
        _user.email.split("@")[0],
        _user.email,
    )

    # A restore rewrites the working definition → back to "In Review" (audit §5.3).
    fire_on_edit(yaml_id)

    try:
        return yaml_svc.get_yaml(yaml_id)
    except Exception as exc:
        logger.exception("get_yaml failed after restore for %s", yaml_id)
        raise HTTPException(status_code=500, detail=str(exc))

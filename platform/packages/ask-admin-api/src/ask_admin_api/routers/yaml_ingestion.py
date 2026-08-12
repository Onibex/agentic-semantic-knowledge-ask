"""``/v1/admin/yaml/*`` — Knowledge Graph ingestion + catalog browsing.

Backed by:
  - ``ask_knowledge_graph.application.factory.build_default_ingestion_service``
  - ``ask_knowledge_graph.application.factory.build_default_reader``

The admin SPA Ingestor page drives these endpoints over REST; no UI holds a
direct typed-package dependency.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..application.ddl_import_service import DdlImportService, validate_ddl_input
from ..application.env_targets import ALL_ENVIRONMENTS, normalize_env
from ..application.git_service import GitService
from ..application.lifecycle_service import PublishNotReadyError
from ..application.lifecycle_triggers import fire_on_create, fire_on_publish_dev
from ..application.publish_service import PublishService
from ..application.yaml_file_service import YAMLFileService, YAMLNotFoundError
from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.viz_models import VizLayer
from ..models.yaml_ingestion import (
    CatalogResponse,
    DdlImportItem,
    DdlImportRequest,
    DdlImportResult,
    DeletionResult,
    DerivedFieldFlag,
    DeriveYamlRequest,
    DeriveYamlResult,
    EntityDetailResponse,
    FullIngestRequest,
    ImportYamlRequest,
    ImportYamlResult,
    IndexWorkspaceItem,
    IndexWorkspaceRequest,
    IndexWorkspaceResult,
    IngestionResult,
    LightweightEntity,
    PublishEnvResult,
    ResetIndicesResult,
    SapJsonIngestRequest,
    UnpublishEnvResult,
    YamlIngestRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/yaml", tags=["admin/yaml"])


# ── Lazy singletons ─────────────────────────────────────────────────────────
_service_lock = threading.Lock()
_service_singleton: Any = None
_reader_lock = threading.Lock()
# Per-env reader cache: key None = legacy un-suffixed registry, "dev"/"prod" =
# env-suffixed registries (deployment queries). Curation browse does NOT use a
# reader — it reads the working YAMLs (see list_catalog).
_reader_singletons: dict[str | None, Any] = {}
_rag_service_lock = threading.Lock()
_rag_service_singleton: Any = None


def reset_singletons() -> list[str]:
    """Drop the cached IngestionService + Reader + RagIndexingService so
    the next request rebuilds them from a fresh ``settings.json``."""
    global _service_singleton, _rag_service_singleton
    cleared: list[str] = []
    if _service_singleton is not None:
        cleared.append("ingestion_service")
    if _reader_singletons:
        cleared.append("kg_reader")
    if _rag_service_singleton is not None:
        cleared.append("rag_indexing_service")
    _service_singleton = None
    _reader_singletons.clear()
    _rag_service_singleton = None
    return cleared


def _load_config() -> dict[str, Any]:
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        raise RuntimeError("config/settings.json not found — service must run from project root")
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _get_service() -> Any:
    global _service_singleton
    if _service_singleton is not None:
        return _service_singleton
    with _service_lock:
        if _service_singleton is not None:
            return _service_singleton
        from ask_knowledge_graph.application.factory import (
            build_default_ingestion_service,
        )

        # `with_file_storage=True` so SAP JSON ingestion writes the parsed
        # Bronze + Silver YAMLs to the workspace dir (Iter 8 parity with the
        # previous 6_Ingestor behaviour).
        _service_singleton = build_default_ingestion_service(_load_config(), with_file_storage=True)
        return _service_singleton


def _get_reader(env: str | None = None) -> Any:
    """Return a KG reader over the OpenSearch registry for ``env``.

    ``env`` ("dev"/"prod") targets the env-suffixed registry (a DEPLOYMENT
    query — "what is published to that env"); ``None`` keeps the legacy
    un-suffixed registry. Readers are cached per-env. NOTE: curation browse
    (``/catalog``) must NOT use this — it reads the working YAMLs so unpublished
    entities are visible; env indices only hold what's been deployed.
    """
    cached = _reader_singletons.get(env)
    if cached is not None:
        return cached
    with _reader_lock:
        cached = _reader_singletons.get(env)
        if cached is not None:
            return cached
        from ask_knowledge_graph.application.factory import build_default_reader

        reader = build_default_reader(env)
        _reader_singletons[env] = reader
        return reader


def _get_rag_service() -> Any:
    """Lazy RagIndexingService used by the unified ingest-full endpoint.

    Kept separate from the singleton in ``routers/embeddings.py`` because
    the two endpoints reset independently (an embedder problem isolated to
    the documentation flow shouldn't blow up the YAML ingest path).
    """
    global _rag_service_singleton
    if _rag_service_singleton is not None:
        return _rag_service_singleton
    with _rag_service_lock:
        if _rag_service_singleton is not None:
            return _rag_service_singleton
        from ask_knowledge_graph.application.factory import (
            build_default_rag_indexing_service,
        )

        _rag_service_singleton = build_default_rag_indexing_service(_load_config())
        return _rag_service_singleton


def cascade_silver_to_rag(
    silver_yaml: str | None,
    entity_id: str | None,
    *,
    trace_id: str,
) -> int:
    """Render + chunk + index a Silver YAML into ``rag_schema``.

    Reusable across the SAP JSON ingestion endpoints (admin + Kafka) so
    Silvers created via parser-based ingestion behave the same as
    YAML-uploaded Silvers from the unified endpoint. **Best-effort**:
    returns 0 on any failure (logged), never raises. The catalog write
    has already committed at this point — surfacing an exception here
    would mask the successful catalog result.

    Returns the chunk count actually indexed (0 when no Silver, when the
    layer is Bronze, or when any step explodes).
    """
    if not silver_yaml or not entity_id:
        return 0
    try:
        from ask_knowledge_graph.application.rag_chunking import build_chunks
        from ask_knowledge_graph.application.rag_text_renderer import (
            render_yaml_for_embedding,
        )

        text, base_meta = render_yaml_for_embedding(silver_yaml)
        if base_meta.get("layer") == "bronze":
            return 0
        base_meta = dict(base_meta)
        base_meta["source_file"] = f"{entity_id}.yaml"
        chunks = build_chunks(text, base_meta)
        result = _get_rag_service().index_chunks("rag_schema", chunks)
        return int(result.indexed)
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.warning(
            "RAG cascade for SAP JSON Silver failed",
            extra={
                "trace_id": trace_id,
                "entity_id": entity_id,
                "error": str(exc),
            },
        )
        return 0


# ── Ingestion ───────────────────────────────────────────────────────────────


@router.post("/ingest-sap-json", response_model=None, status_code=410)
async def ingest_sap_json_deprecated(
    req: SapJsonIngestRequest,
    user: TokenClaims = Depends(validate_token),
) -> None:
    """DEPRECATED — Pass B (2026-05).

    SAP JSON ingestion is consolidated under a single canonical path:
      * Human-driven  → POST /v1/viz/ingest/sap-json   (JWT + SPA SAP Updates)
      * Machine-driven → POST /v1/ingest/sap-json      (X-API-Key + Kafka)

    Both share the same merge engine, the same first-ingest semantics
    (everything lands as draft), and the same conflict resolution flow.
    This direct-to-catalog admin endpoint bypassed all of that — it is
    intentionally retired to remove the inconsistency surface.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "POST /v1/admin/yaml/ingest-sap-json was deprecated in Pass B. "
            "Use POST /v1/viz/ingest/sap-json (JWT) or POST /v1/ingest/sap-json "
            "(X-API-Key) — both route through the merge engine so SAP changes "
            "land as draft and surface conflicts for manual resolution."
        ),
    )


@router.post("/ingest", response_model=None, status_code=410)
async def ingest_yaml_deprecated(
    req: YamlIngestRequest,
    user: TokenClaims = Depends(validate_token),
) -> None:
    """DEPRECATED — Pass I (2026-06).

    The direct YAML → OpenSearch path bypassed the workspace + git audit +
    Publish governance, producing silent divergence between workspace and
    runtime. Use ``POST /v1/admin/yaml/import`` to land the YAML in the
    workspace, then ``POST /v1/admin/yaml/index/{id}`` (or the Publish
    button in Graph) to push it to runtime.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "POST /v1/admin/yaml/ingest was deprecated in Pass I (2026-06). "
            "Use POST /v1/admin/yaml/import to land the YAML in the workspace, "
            "then publish via POST /v1/admin/yaml/index/{entity_id} or the "
            "Graph UI Publish button."
        ),
    )


@router.post("/ingest-full", response_model=None, status_code=410)
async def ingest_yaml_full_deprecated(
    req: FullIngestRequest,
    user: TokenClaims = Depends(validate_token),
) -> None:
    """DEPRECATED — Pass I (2026-06). See ``/ingest`` deprecation note."""
    raise HTTPException(
        status_code=410,
        detail=(
            "POST /v1/admin/yaml/ingest-full was deprecated in Pass I (2026-06). "
            "Use POST /v1/admin/yaml/import to land the YAML in the workspace, "
            "then publish via POST /v1/admin/yaml/index/{entity_id} (Publish "
            "button in Graph)."
        ),
    )


@router.post("/import", response_model=ImportYamlResult)
async def import_yaml_to_workspace(
    req: ImportYamlRequest,
    user: TokenClaims = Depends(validate_token),
) -> ImportYamlResult:
    """Pass I — land a hand-authored YAML in the workspace.

    Validates the YAML against the layer-specific Pydantic schema
    (BronzeNode / SilverNode / GoldNode), writes it to the workspace at the
    canonical path derived from the entity's ``source_system`` / ``layer``
    / ``module`` / ``name``, and commits to git so the import shows up in
    the History timeline. Does NOT touch the runtime index — the admin
    must explicitly Publish via the Graph UI (or the per-entity index
    endpoint) once they're happy with the imported state.

    Primary use case: seeding new Gold entities (no SAP source) and
    restoring offline-authored YAMLs without going through SAP Updates.

    409 if the target file already exists; pass ``force=true`` to
    overwrite. 422 if the YAML body fails Pydantic validation.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "yaml import requested",
        extra={
            "trace_id": trace_id,
            "force": req.force,
            "size_bytes": len(req.yaml_content),
            "auth_email": user.email,
        },
    )

    svc = _yaml_file_service()
    repo_root = Path(get_settings().repo_root).resolve()
    git_svc = GitService(repo_root=str(repo_root))
    try:
        node = svc.import_yaml(
            req.yaml_content,
            force=req.force,
            git_service=git_svc,
            author_name=user.email.split("@")[0],
            author_email=user.email,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        # YAML parse / shape errors → 422 (client-side fixable).
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — boundary
        # Pydantic ValidationError surfaces here. Re-raise as 422 with the
        # validator's own message so the SPA can display it inline.
        logger.exception("yaml import failed", extra={"trace_id": trace_id})
        raise HTTPException(status_code=422, detail=f"YAML validation failed: {exc}")

    # Lifecycle: a manual import creates/edits the DP → "In Review" (audit §5.3).
    fire_on_create(node.id)

    return ImportYamlResult(
        entity_id=node.id,
        layer=node.layer.value,
        file_path=node.file_path,
        overwritten=req.force,
    )


@router.post("/derive", response_model=DeriveYamlResult)
async def derive_yaml(
    req: DeriveYamlRequest,
    user: TokenClaims = Depends(validate_token),
) -> DeriveYamlResult:
    """Preview the EntityDeriver normalization on a draft YAML — NO write.

    Powers the Manual form's auto-fill: returns the assembled node + which
    entity-/field-level keys were derived, plus any residual validation error
    so the SPA can flag still-missing *semantic* fields (e.g. description).
    Runs the SAME deriver as ``/import`` (DIP).
    """
    from ask_knowledge_graph.domain.entity_deriver import EntityDeriver
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    try:
        raw = load_yaml_text(req.yaml_content)
    except Exception as exc:  # noqa: BLE001 — boundary
        raise HTTPException(status_code=422, detail=f"Could not parse YAML: {exc}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="YAML root must be a mapping")

    layer = (raw.get("layer") or "").lower()
    if layer not in {"bronze", "silver", "gold"}:
        raise HTTPException(
            status_code=400, detail=f"Unsupported layer '{layer}'. Expected bronze/silver/gold."
        )

    completed = EntityDeriver().complete(dict(raw), layer=layer)

    def _is_empty(v: Any) -> bool:
        return v in (None, "", [])

    entity_derived = [
        k for k, v in completed.items() if k != "fields" and (k not in raw or _is_empty(raw.get(k)))
    ]

    def _field_diff(orig: dict, cur: dict) -> list[str]:
        out: list[str] = []
        for k, v in cur.items():
            if k == "type" and orig.get("type") != v:
                out.append(k)
            elif k not in orig or _is_empty(orig.get(k)):
                out.append(k)
        return out

    field_flags: list[DerivedFieldFlag] = []
    cf = completed.get("fields")
    bf = raw.get("fields")
    if isinstance(cf, list):
        bf_list = bf if isinstance(bf, list) else []
        for i, fd in enumerate(cf):
            if not isinstance(fd, dict):
                continue
            orig = bf_list[i] if i < len(bf_list) and isinstance(bf_list[i], dict) else {}
            diff = _field_diff(orig, fd)
            if diff:
                field_flags.append(DerivedFieldFlag(name=str(fd.get("name") or i), derived=diff))
    elif isinstance(cf, dict):
        bf_map = bf if isinstance(bf, dict) else {}
        for name, fd in cf.items():
            if not isinstance(fd, dict):
                continue
            orig = bf_map.get(name) if isinstance(bf_map.get(name), dict) else {}
            diff = _field_diff(orig, fd)
            if diff:
                field_flags.append(DerivedFieldFlag(name=str(name), derived=diff))

    validation_error: str | None = None
    try:
        from ask_knowledge_graph.domain.nodes import BronzeNode, GoldNode, SilverNode

        {"bronze": BronzeNode, "silver": SilverNode, "gold": GoldNode}[layer].model_validate(
            completed
        )
    except Exception as exc:  # noqa: BLE001 — surfaced to the SPA, not fatal
        validation_error = str(exc)

    # Surface the semantic gap (D1 hybrid) the Pydantic model can't catch — e.g.
    # an empty `composed_of` list validates but is semantically incomplete. Only
    # when the model itself didn't already flag a problem.
    if validation_error is None:
        try:
            EntityDeriver().assert_semantic_complete(completed, layer=layer)
        except ValueError as exc:
            validation_error = str(exc)

    return DeriveYamlResult(
        layer=layer,
        node=dict(completed),
        entity_derived=entity_derived,
        fields=field_flags,
        validation_error=validation_error,
    )


@router.post("/import/ddl", response_model=DdlImportResult)
async def import_ddl(
    req: DdlImportRequest,
    user: TokenClaims = Depends(validate_token),
) -> DdlImportResult:
    """Map SQL DDL → ASK YAML via the AI, then import each entity (UX_CHANGES CH-6).

    The AI maps the DDL to the requested ``layer`` (Q11); one entity per table.
    Each generated YAML is landed in the workspace (like ``/import``) and fires
    the create lifecycle trigger so it surfaces as "In Review" in the catalog.
    Returns the generated YAML (for transparency) + per-entity outcomes.
    """
    if req.layer not in ("bronze", "silver", "gold"):
        raise HTTPException(
            status_code=400, detail=f"layer must be bronze/silver/gold, got '{req.layer}'."
        )
    # Fail-fast pre-validator (§7.1): reject garbage / non-DDL / oversized input
    # BEFORE spending an LLM call on it.
    try:
        validate_ddl_input(req.ddl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Wire the editable prompt registry in — without it the service always ran
    # the hardcoded defaults and the admin's `ddl_mapping` override was ignored.
    from ..application.system_prompts_service import SystemPromptsService

    try:
        prompts_service = SystemPromptsService()
    except Exception:  # noqa: BLE001 — degraded OpenSearch must not block imports
        logger.exception("prompts registry unavailable — DDL import uses default prompts")
        prompts_service = None

    module = (req.module or "").strip().lower() or "gen"
    try:
        yaml_docs, tokens, warnings = DdlImportService(
            prompts_service=prompts_service
        ).generate_yaml(
            req.ddl,
            layer=req.layer,
            source_system=req.source_system,
            context=req.context,
            module=module,
        )
    except Exception as exc:  # noqa: BLE001 — LLM boundary
        logger.exception("DDL mapping LLM call failed")
        raise HTTPException(status_code=502, detail=f"DDL → YAML mapping failed: {exc}")

    if not yaml_docs:
        raise HTTPException(status_code=422, detail="The model produced no YAML for this DDL.")

    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    svc = _yaml_file_service()
    repo_root = Path(get_settings().repo_root).resolve()
    git_svc = GitService(repo_root=str(repo_root))
    items: list[DdlImportItem] = []
    seen_ids: set[str] = set()
    for doc in yaml_docs:
        # Peek the id to catch a duplicate WITHIN this paste (two CREATE TABLEs the
        # model mapped to the same id) — without it the second silently overwrites
        # the first under force=true. Best-effort: a doc we can't parse falls
        # through to import_yaml, which raises a clear error below.
        doc_id: str | None = None
        try:
            parsed = load_yaml_text(doc)
            if isinstance(parsed, dict) and parsed.get("id"):
                doc_id = str(parsed["id"])
        except Exception:  # noqa: BLE001 — parse handled by import_yaml
            doc_id = None
        if doc_id and doc_id in seen_ids:
            items.append(
                DdlImportItem(
                    entity_id=doc_id, outcome="error", reason="duplicate id in this batch"
                )
            )
            continue
        try:
            node = svc.import_yaml(
                doc,
                force=req.force,
                git_service=git_svc,
                author_name=user.email.split("@")[0],
                author_email=user.email,
            )
            seen_ids.add(node.id)
            fire_on_create(node.id)
            items.append(
                DdlImportItem(
                    entity_id=node.id,
                    layer=node.layer.value,
                    file_path=node.file_path,
                    outcome="overwritten" if req.force else "created",
                )
            )
        except FileExistsError:
            items.append(
                DdlImportItem(
                    entity_id=doc_id,
                    outcome="error",
                    reason="already exists in workspace (use force)",
                )
            )
        except Exception as exc:  # noqa: BLE001 — one bad doc must not drop the rest
            items.append(
                DdlImportItem(entity_id=doc_id, outcome="error", reason=f"invalid YAML: {exc}")
            )

    return DdlImportResult(
        generated_yaml="\n---\n".join(yaml_docs),
        tokens_used=tokens,
        items=items,
        warnings=warnings,
    )


# ── Publish workspace files → runtime index ──────────────────────────────────


def _yaml_file_service() -> YAMLFileService:
    s = get_settings()
    return YAMLFileService(workspace_path=s.workspace_path, repo_root=s.repo_root)


def _index_one(yaml_content: str, *, trace_id: str) -> IngestionResult:
    """Index one YAML's content into the catalog and cascade its Silver/Gold to RAG.

    Reuses the same KG ingestion + RAG render/chunk pipeline as the manual
    upload path; bronze layers are skipped from RAG by the cascade.
    """
    from ask_knowledge_graph.domain.models import IngestionRequest as DomainIngestionRequest

    kg_result = _get_service().ingest_yaml(DomainIngestionRequest(yaml_content=yaml_content))
    rag_chunks = 0
    if not kg_result.error:
        rag_chunks = cascade_silver_to_rag(
            silver_yaml=yaml_content,
            entity_id=kg_result.entity_id,
            trace_id=trace_id,
        )
    return IngestionResult(
        entities_indexed=kg_result.entities_indexed,
        fields_indexed=kg_result.fields_indexed,
        edges_indexed=kg_result.edges_indexed,
        rag_chunks_indexed=rag_chunks,
        error=kg_result.error,
    )


def _cascade_publish(
    node,
    *,
    svc: YAMLFileService,
    repo_root: Path,
    trace_id: str,
) -> tuple[list[str], list[str], dict[str, int]]:
    """Publish ancillary YAMLs needed for runtime coherence of ``node``.

    A published Silver MUST have its referenced Bronces in the runtime index,
    otherwise the join graph in OpenSearch has dead edges. Cross-entity
    relationships only emit a warning if the target YAML doesn't exist at all
    — once states are out of the picture, there is no in-workspace way to tell
    whether the target has been published to runtime separately.

    Returns ``(indexed_ids, warnings, totals)``.
    """
    indexed_ids: list[str] = []
    warnings: list[str] = []
    totals = {"entities": 0, "fields": 0, "edges": 0, "rag": 0}

    # 1. composed_of → publish referenced Bronces (Silver layer only).
    # ``composed_of`` carries two different meanings in this codebase:
    #   * Silver: list of Bronce workspace YAML ids (e.g. bronze_s4h_vbak_*)
    #   * Gold:   the physical SQL table the Gold represents
    #             (e.g. MY_SCHEMA.GOLD_INVENTORY_SITUATION) — NOT a YAML id.
    # Treating both the same way produces a false-positive orphan warning on
    # every Gold publish. Skip the cascade entirely for non-Silver layers.
    if node.layer == VizLayer.silver:
        for ref_id in node.composed_of or []:
            try:
                child = svc.get_yaml(ref_id)
            except YAMLNotFoundError:
                warnings.append(f"composed_of '{ref_id}' not in workspace (orphan reference)")
                continue
            try:
                content = (repo_root / child.file_path).read_text(encoding="utf-8")
                r = _index_one(content, trace_id=trace_id)
                if r.error:
                    warnings.append(f"cascade publish failed for '{child.id}': {r.error}")
                    continue
                indexed_ids.append(child.id)
                totals["entities"] += r.entities_indexed
                totals["fields"] += r.fields_indexed
                totals["edges"] += r.edges_indexed
                totals["rag"] += r.rag_chunks_indexed
            except Exception as exc:  # noqa: BLE001 — best-effort
                warnings.append(f"cascade publish failed for '{child.id}': {exc}")

    # 2. relationships → warn only when the target isn't in the workspace
    for rel in node.relationships or []:
        target = getattr(rel, "target_entity", None)
        if not target:
            continue
        try:
            svc.get_yaml(target)
        except YAMLNotFoundError:
            warnings.append(f"relationship target '{target}' not in workspace")

    return indexed_ids, warnings, totals


@router.post("/index/{entity_id}", response_model=IngestionResult)
async def index_entity(
    entity_id: str,
    user: TokenClaims = Depends(validate_token),
) -> IngestionResult:
    """Publish ONE workspace YAML (by id) into the runtime index (catalog + RAG).

    Pass C cascade: when a Silver is published, its ``composed_of`` Bronces
    are auto-published so the runtime join graph stays coherent. Cross-entity
    relationships missing from the workspace are surfaced as warnings.

    Audit: a successful publish writes an empty git commit
    ``publish(<id>): indexed by <email>`` so the act of publishing shows
    up in the History timeline without modifying the YAML body.
    """
    trace_id = uuid.uuid4().hex
    svc = _yaml_file_service()
    try:
        node = svc.get_yaml(entity_id)
    except YAMLNotFoundError:
        raise HTTPException(status_code=404, detail=f"YAML '{entity_id}' not found in workspace")

    repo_root = Path(get_settings().repo_root).resolve()
    try:
        content = (repo_root / node.file_path).read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — boundary
        raise HTTPException(status_code=500, detail=f"Could not read {node.file_path}: {exc}")

    try:
        result = _index_one(content, trace_id=trace_id)
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("index entity failed", extra={"trace_id": trace_id})
        raise HTTPException(status_code=500, detail=f"Index failed: {exc}")

    if result.error:
        return result

    # Pass C cascade — only when the primary publish succeeded.
    cascade_ids, warnings, totals = _cascade_publish(
        node, svc=svc, repo_root=repo_root, trace_id=trace_id
    )
    result = IngestionResult(
        entities_indexed=result.entities_indexed + totals["entities"],
        fields_indexed=result.fields_indexed + totals["fields"],
        edges_indexed=result.edges_indexed + totals["edges"],
        rag_chunks_indexed=result.rag_chunks_indexed + totals["rag"],
        error=None,
        cascade_indexed=cascade_ids,
        cascade_warnings=warnings,
    )

    try:
        git = GitService(repo_root=str(repo_root))
        cascade_suffix = f" (+{len(cascade_ids)} cascade)" if cascade_ids else ""
        git.empty_commit(
            message=f"publish({entity_id}){cascade_suffix}: indexed by {user.email}",
            author_name=user.email.split("@")[0],
            author_email=user.email,
        )
    except Exception:  # noqa: BLE001 — audit-only, never blocks publish
        logger.warning(
            "publish empty commit failed",
            extra={"trace_id": trace_id, "entity_id": entity_id},
        )

    # Lifecycle trigger: publishing to the runtime index cuts the working
    # version + deploys it to dev → status "Released" (audit §5.3, default dev
    # target for Iter 1). Cascade-published bronzes promote with their parent.
    fire_on_publish_dev(entity_id, by=user.email)
    for cascade_id in cascade_ids:
        fire_on_publish_dev(cascade_id, by=user.email)
    return result


@router.post("/index/{entity_id}/{env}", response_model=PublishEnvResult)
async def index_entity_env(
    entity_id: str,
    env: str,
    user: TokenClaims = Depends(validate_token),
) -> PublishEnvResult:
    """Publish ONE workspace YAML into a specific ENVIRONMENT (UX_CHANGES Iter 2).

    ``env`` is ``dev`` or ``prod``. Atomic sequence (audit §3.2 / Q14):
      1. index the YAML (+ composed_of bronzes + RAG) into ``ask-*-{env}``;
      2. file-by-file ``git checkout`` of just this DP's files onto the env
         branch from its source (``dev`` ← ``main``, ``prod`` ← ``dev``) + commit;
      3. record dev_published / prod_published in the lifecycle index.

    The legacy ``POST /index/{entity_id}`` (un-suffixed, dev-default lifecycle)
    is untouched — the SPA still uses it. Prod requires a prior dev publish.
    """
    if env not in ALL_ENVIRONMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown environment '{env}' — expected one of {list(ALL_ENVIRONMENTS)}.",
        )
    settings = get_settings()
    svc = PublishService(repo_root=settings.repo_root, workspace_path=settings.workspace_path)
    try:
        outcome = svc.publish(entity_id, env, by=user.email)
    except YAMLNotFoundError:
        raise HTTPException(status_code=404, detail=f"YAML '{entity_id}' not found in workspace")
    except PublishNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("env publish failed", extra={"entity_id": entity_id, "env": env})
        raise HTTPException(status_code=500, detail=f"Publish to {env} failed: {exc}")

    return PublishEnvResult(
        entity_id=outcome.entity_id,
        env=outcome.env,
        committed_sha=outcome.committed_sha,
        entities_indexed=outcome.entities_indexed,
        fields_indexed=outcome.fields_indexed,
        edges_indexed=outcome.edges_indexed,
        rag_chunks_indexed=outcome.rag_chunks_indexed,
        indexed_paths=outcome.indexed_paths,
        cascade_indexed=outcome.cascade_ids,
        cascade_warnings=outcome.warnings,
    )


@router.delete("/index/{entity_id}/{env}", response_model=UnpublishEnvResult)
async def unpublish_entity_env(
    entity_id: str,
    env: str,
    user: TokenClaims = Depends(validate_token),
) -> UnpublishEnvResult:
    """UNpublish ONE workspace YAML from a specific ENVIRONMENT — inverse of the
    POST. Removes the entity (+ its fields, edges, RAG chunks) from ``ask-*-{env}``
    and deletes its YAML from the env branch, so it is no longer answerable when
    the chat targets ``env`` (queryable scope = membership ∩ entities published
    to env). It stays in dev/working and can be re-published.

    NO cascade: composed_of bronzes are left intact (they may be shared). The
    prod-before-dev gate applies: unpublishing from dev while prod is still
    published returns 409.
    """
    if env not in ALL_ENVIRONMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown environment '{env}' — expected one of {list(ALL_ENVIRONMENTS)}.",
        )
    settings = get_settings()
    svc = PublishService(repo_root=settings.repo_root, workspace_path=settings.workspace_path)
    try:
        outcome = svc.unpublish(entity_id, env, by=user.email)
    except PublishNotReadyError as exc:
        # not published to env, or dev-while-prod gate
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("env unpublish failed", extra={"entity_id": entity_id, "env": env})
        raise HTTPException(status_code=500, detail=f"Unpublish from {env} failed: {exc}")

    return UnpublishEnvResult(
        entity_id=outcome.entity_id,
        env=outcome.env,
        committed_sha=outcome.committed_sha,
        entities_removed=outcome.entities_removed,
        fields_removed=outcome.fields_removed,
        edges_removed=outcome.edges_removed,
        rag_chunks_removed=outcome.rag_chunks_removed,
        warnings=outcome.warnings,
    )


@router.post("/index-workspace", response_model=IndexWorkspaceResult)
async def index_workspace(
    req: IndexWorkspaceRequest,
    user: TokenClaims = Depends(validate_token),
) -> IndexWorkspaceResult:
    """Bulk-publish workspace YAMLs into the runtime index.

    Publishes every YAML by default. Pass ``layers`` to restrict the run
    (e.g. ``["silver", "gold"]`` to publish only curated entities and let
    the per-entity cascade sweep the referenced Bronces).
    """
    trace_id = uuid.uuid4().hex
    layers = {l.lower() for l in req.layers} if req.layers else None
    svc = _yaml_file_service()
    repo_root = Path(get_settings().repo_root).resolve()
    git = GitService(repo_root=str(repo_root))
    try:
        summaries = svc.list_yamls()
    except Exception as exc:  # noqa: BLE001 — boundary
        raise HTTPException(status_code=500, detail=f"Workspace scan failed: {exc}")

    items: list[IndexWorkspaceItem] = []
    tot_e = tot_f = tot_ed = tot_rag = 0
    n_indexed = n_skipped = n_failed = 0

    for s in summaries:
        layer_val = s.layer.value
        if layers is not None and layer_val not in layers:
            items.append(IndexWorkspaceItem(entity_id=s.id, layer=layer_val, status="skipped"))
            n_skipped += 1
            continue
        try:
            content = (repo_root / s.file_path).read_text(encoding="utf-8")
            r = _index_one(content, trace_id=trace_id)
            if r.error:
                n_failed += 1
                status = "error"
            else:
                n_indexed += 1
                status = "indexed"
                tot_e += r.entities_indexed
                tot_f += r.fields_indexed
                tot_ed += r.edges_indexed
                tot_rag += r.rag_chunks_indexed
                # Per-entity empty commit so the entity's History timeline
                # surfaces the publish event — same convention as the
                # per-entity Publish button. Without this, bulk-published
                # entities never showed a "publish" line on their own
                # timeline, only the workspace-wide summary commit.
                try:
                    git.empty_commit(
                        message=f"publish({s.id}): indexed by {user.email} (via workspace bulk)",
                        author_name=user.email.split("@")[0],
                        author_email=user.email,
                    )
                except Exception:  # noqa: BLE001 — audit-only, never blocks publish
                    logger.warning(
                        "bulk per-entity publish commit failed",
                        extra={"trace_id": trace_id, "entity_id": s.id},
                    )
                # Lifecycle: same as the per-entity Publish — status → Released.
                fire_on_publish_dev(s.id, by=user.email)
            items.append(
                IndexWorkspaceItem(
                    entity_id=s.id,
                    layer=layer_val,
                    status=status,
                    entities_indexed=r.entities_indexed,
                    fields_indexed=r.fields_indexed,
                    edges_indexed=r.edges_indexed,
                    rag_chunks_indexed=r.rag_chunks_indexed,
                    error=r.error,
                )
            )
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.exception(
                "index-workspace item failed",
                extra={"trace_id": trace_id, "entity_id": s.id},
            )
            items.append(
                IndexWorkspaceItem(
                    entity_id=s.id,
                    layer=layer_val,
                    status="error",
                    error=str(exc),
                )
            )
            n_failed += 1

    if n_indexed > 0:
        try:
            layer_label = f" (layers={sorted(layers)})" if layers else ""
            git.empty_commit(
                message=(
                    f"publish-workspace: indexed {n_indexed} entities{layer_label} by {user.email}"
                ),
                author_name=user.email.split("@")[0],
                author_email=user.email,
            )
        except Exception:  # noqa: BLE001 — audit-only, never blocks publish
            logger.warning(
                "publish-workspace summary commit failed",
                extra={"trace_id": trace_id},
            )

    return IndexWorkspaceResult(
        total=len(summaries),
        indexed=n_indexed,
        skipped=n_skipped,
        failed=n_failed,
        layers=sorted(layers) if layers else [],
        items=items,
        entities_indexed=tot_e,
        fields_indexed=tot_f,
        edges_indexed=tot_ed,
        rag_chunks_indexed=tot_rag,
    )


@router.delete("/{entity_id}", response_model=DeletionResult)
async def delete_entity(
    entity_id: str,
    user: TokenClaims = Depends(validate_token),
) -> DeletionResult:
    """Delete an entity from every index it touches.

    Cascade (in order):
      0. Unpublish from every environment it is published to (``dev`` / ``prod``)
         FIRST — otherwise the entity stays in the env-suffixed indices the chat
         reads (``ask-*-{env}``) and remains answerable after a "delete". The
         plain catalog delete below only touches the legacy un-suffixed registry,
         which the chat no longer reads (Option B), so without this step a
         deleted-but-published entity would silently keep answering in prod.
      1. Catalog write (``ask-entity-registry-v1``, ``ask-field-registry-v1``,
         ``ask-edge-registry-v1``) — performed by the typed IngestionService.
      2. RAG chunks in ``rag_schema`` whose ``metadata.entity_id`` equals
         the deleted entity. Failure here is logged but does NOT roll back
         the catalog write — the catalog is the source of truth and the
         RAG entries become orphans that the next reindex will clean up.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "yaml delete received",
        extra={
            "trace_id": trace_id,
            "entity_id": entity_id,
            "auth_email": user.email,
        },
    )

    # 0. Env cleanup — unpublish from each env it is published to (prod first to
    # satisfy the unpublish gate). Best-effort: a not-published env is a no-op
    # (PublishNotReadyError), and missing env infra (local/test) is skipped so
    # the catalog delete is never blocked on it.
    try:
        settings = get_settings()
        publisher = PublishService(
            repo_root=settings.repo_root, workspace_path=settings.workspace_path
        )
    except Exception:  # noqa: BLE001 — env publish infra unavailable → skip cleanly
        publisher = None
        logger.warning(
            "delete: env-unpublish unavailable for %s — skipping", entity_id, exc_info=True
        )
    unpublished_envs: list[str] = []
    if publisher is not None:
        for env in ("prod", "dev"):
            try:
                publisher.unpublish(entity_id, env, by=user.email)
                unpublished_envs.append(env)
            except PublishNotReadyError:
                pass  # not published to this env — nothing to remove
            except Exception:  # noqa: BLE001 — never block the catalog delete
                logger.warning("delete: unpublish %s from %s failed", entity_id, env, exc_info=True)
    if unpublished_envs:
        logger.info("delete: also unpublished %s from %s", entity_id, unpublished_envs)

    # Catalog/registry delete — BEST-EFFORT. The registry is a derived runtime
    # index; an entity that was never published (or a fresh env whose indices
    # don't exist yet) legitimately isn't there, so a not-found here must NOT
    # 500. The workspace YAML + lifecycle + business-domain cleanup below is
    # what actually removes the data product from the user's view.
    raw: dict[str, Any] = {}
    try:
        raw = _get_service().delete_entity(entity_id).raw_stats or {}
    except Exception as exc:  # noqa: BLE001 — not-found / missing index is fine
        logger.warning(
            "delete: catalog/registry removal skipped for %s (%s)",
            entity_id,
            exc,
            extra={"trace_id": trace_id},
        )

    rag_chunks_deleted = 0
    try:
        rag_del = _get_rag_service().delete_documents("rag_schema", entity_ids=[entity_id])
        rag_chunks_deleted = rag_del.deleted
    except Exception as exc:  # noqa: BLE001 — boundary
        # Cascade failure must not poison the response — catalog deletion
        # already succeeded. Surface to logs so ops can chase orphans.
        logger.warning(
            "RAG cascade delete failed",
            extra={"trace_id": trace_id, "entity_id": entity_id, "error": str(exc)},
        )

    # Full removal — beyond the runtime registry/RAG, drop the entity from the
    # places that keep it visible: the workspace YAML, the lifecycle index (the
    # Semantic Knowledge list reads it), and every business-domain membership.
    # Each step best-effort + logged so a partial failure never poisons the
    # already-committed catalog delete.
    settings = get_settings()
    try:
        ysvc = YAMLFileService(workspace_path=settings.workspace_path, repo_root=settings.repo_root)
        git = GitService(repo_root=str(Path(settings.repo_root).resolve()))
        ysvc.delete_yaml(
            entity_id,
            git_service=git,
            author_name=user.email.split("@")[0],
            author_email=user.email,
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("delete: workspace YAML removal failed for %s", entity_id, exc_info=True)
    try:
        from ..application.lifecycle_repository import LifecycleRepository

        LifecycleRepository().delete(entity_id)
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("delete: lifecycle record removal failed for %s", entity_id, exc_info=True)
    try:
        from ..application.workspace_repository import WorkspaceRepository
        from ..application.workspace_service import WorkspaceService

        removed_from = WorkspaceService(WorkspaceRepository()).remove_data_product_everywhere(
            entity_id
        )
        if removed_from:
            logger.info("delete: removed %s from %d business domain(s)", entity_id, removed_from)
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("delete: BD membership cleanup failed for %s", entity_id, exc_info=True)

    return DeletionResult(
        entities_deleted=int(raw.get("entities_deleted", 0)),
        fields_deleted=int(raw.get("fields_deleted", 0)),
        rag_chunks_deleted=rag_chunks_deleted,
        # Best-effort cascade above; the delete as a whole succeeded (workspace
        # YAML + lifecycle + memberships handled). Per-step issues are logged.
        error=None,
    )


# ── Index maintenance ────────────────────────────────────────────────────────


@router.post("/reset-indices", response_model=ResetIndicesResult)
async def reset_registry_indices(
    user: TokenClaims = Depends(validate_token),
) -> ResetIndicesResult:
    """Drop the 3 ask-* registry indices so they are recreated on the next ingest.

    Use this when switching embedder providers that produce a different vector
    dimension (e.g. Bedrock Titan Text Embeddings V2 at 1024 dims →
    text-embedding-3-large at 3072 dims). After calling this endpoint you must
    re-ingest all YAMLs — the catalog is empty until then.

    The current ``embedding_dim`` comes from ``OpenSearchAskRepository`` —
    env ``OPENSEARCH_EMBEDDING_DIM``, else legacy ``settings.json``
    ``opensearch.embedding_dim``, else the platform default 1024 — and is
    reported in the response.
    """
    trace_id = uuid.uuid4().hex
    logger.info(
        "reset-indices requested",
        extra={"trace_id": trace_id, "auth_email": user.email},
    )
    try:
        from ask_knowledge_graph.infrastructure.opensearch_repository import (
            OpenSearchAskRepository,
        )

        repo = OpenSearchAskRepository()
        result = repo.drop_all_registry_indices()
        # Force a fresh repo on next ingest so the new indices are created
        # with the correct embedding_dim from the reloaded config.
        reset_singletons()
        logger.info(
            "reset-indices complete",
            extra={
                "trace_id": trace_id,
                "dropped": result["dropped"],
                "errors": result["errors"],
                "dim": repo.embedding_dim,
            },
        )
        return ResetIndicesResult(
            dropped=result["dropped"],
            errors=result["errors"],
            embedding_dim=repo.embedding_dim,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("reset-indices failed", extra={"trace_id": trace_id})
        raise HTTPException(status_code=500, detail=f"Reset failed: {exc}")


# ── Catalog browsing ────────────────────────────────────────────────────────


@router.get("/published-ids", response_model=dict)
async def list_published_ids(
    env: str | None = Query(
        None,
        description="Deployment env to query: 'dev' / 'prod' (env-suffixed "
        "registry). Omit for the legacy un-suffixed registry.",
    ),
    user: TokenClaims = Depends(validate_token),
) -> dict:
    """Return the set of entity ids currently published to ``env``.

    A DEPLOYMENT query (unlike ``GET /catalog``, which lists the working
    YAMLs): it reads the env-suffixed runtime registry
    (``ask-entity-registry-v1-{env}``) so the Graph page's per-node
    "● Published" / "○ Unpublished" chips reflect what's actually deployed
    to that environment. ``env=None`` falls back to the legacy un-suffixed
    registry (pre-env-suffix deploys).
    """
    try:
        norm = normalize_env(env) if env else None
    except ValueError:
        # normalize_env fails loud on a typo (never the wrong index); surface
        # it as a 400 rather than a 500.
        raise HTTPException(
            status_code=400, detail=f"env must be one of {ALL_ENVIRONMENTS}, got {env!r}."
        )
    try:
        rows = _get_reader(norm).get_lightweight_entities() or []
    except Exception as exc:  # noqa: BLE001 — boundary
        raise HTTPException(status_code=500, detail=f"Published-ids lookup failed: {exc}")

    ids = [str(r.get("id", "")) for r in rows if r.get("id")]
    return {"ids": ids, "count": len(ids), "env": norm}


@router.get("/catalog", response_model=CatalogResponse)
async def list_catalog(
    user: TokenClaims = Depends(validate_token),
) -> CatalogResponse:
    """Return the lightweight catalog (id + name + layer) for browsing UIs.

    Reads the WORKING YAMLs (the git workspace), NOT a published env index:
    the SPA is the curation tool, so it must surface unpublished / just-created
    entities — which only exist in the workspace until published. This also
    decouples curation browse from the deployment indices (``ask-*-{env}``),
    whose only consumer is the chat read path. Use ``GET /published-ids?env=``
    for the orthogonal "is it deployed" signal.
    """
    try:
        summaries = _yaml_file_service().list_yamls()
    except Exception as exc:  # noqa: BLE001 — boundary
        raise HTTPException(status_code=500, detail=f"Catalog list failed: {exc}")

    return CatalogResponse(
        entities=[
            LightweightEntity(
                id=s.id,
                name=s.name,
                layer=s.layer.value if hasattr(s.layer, "value") else str(s.layer),
            )
            for s in summaries
            if s.id
        ]
    )


@router.get("/{entity_id}", response_model=EntityDetailResponse)
async def get_entity(
    entity_id: str,
    user: TokenClaims = Depends(validate_token),
) -> EntityDetailResponse:
    """Return the full entity document (raw_yaml + metadata) for one id."""
    try:
        entity = _get_reader().get_entity_by_id(entity_id)
    except Exception as exc:  # noqa: BLE001 — boundary
        raise HTTPException(status_code=500, detail=f"Get entity failed: {exc}")

    if not entity:
        return EntityDetailResponse(entity=None, found=False)
    return EntityDetailResponse(entity=entity, found=True)

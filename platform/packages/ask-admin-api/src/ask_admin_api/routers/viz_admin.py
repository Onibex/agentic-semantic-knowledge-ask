"""/v1/viz — stats + export endpoints.

The state machine was retired (the YAMLs no longer carry draft/review/
production); these endpoints used to also host ``bulk-state`` — that
route is gone with the rest of the machine.
"""

from __future__ import annotations

import io
import logging
import threading
import zipfile
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..application.yaml_file_service import YAMLFileService
from ..auth.validator import TokenClaims, validate_token
from ..config import get_settings
from ..models.viz_models import StatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/viz", tags=["viz-admin"])

_yaml_svc_lock = threading.Lock()
_yaml_svc: YAMLFileService | None = None


def _get_yaml_service() -> YAMLFileService:
    global _yaml_svc
    if _yaml_svc is not None:
        return _yaml_svc
    with _yaml_svc_lock:
        if _yaml_svc is not None:
            return _yaml_svc
        s = get_settings()
        _yaml_svc = YAMLFileService(workspace_path=s.workspace_path, repo_root=s.repo_root)
    return _yaml_svc


@router.get("/stats", response_model=StatsResponse)
async def get_stats(_user: TokenClaims = Depends(validate_token)) -> StatsResponse:
    """Aggregate counts of the semantic layer workspace."""
    yaml_svc = _get_yaml_service()

    try:
        summaries = yaml_svc.list_yamls()
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_stats: list_yamls failed")
        raise HTTPException(status_code=500, detail=str(exc))

    total_yamls = len(summaries)
    by_layer = dict(Counter(s.layer.value for s in summaries))

    pending_conflicts = 0
    for summary in summaries:
        try:
            node = yaml_svc.get_yaml(summary.id)
        except Exception:  # noqa: BLE001
            continue
        pending_conflicts += sum(1 for c in node.meta.conflicts if not c.get("resolved", False))

    return StatsResponse(
        total_yamls=total_yamls,
        by_layer=by_layer,
        pending_conflicts=pending_conflicts,
        recently_updated=0,
    )


@router.get("/export")
async def export_yamls(_user: TokenClaims = Depends(validate_token)) -> StreamingResponse:
    """Download a ZIP archive of all YAML files in the workspace."""
    settings = get_settings()
    workspace = Path(settings.workspace_path)

    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            yaml_files = [*workspace.rglob("*.yaml"), *workspace.rglob("*.yml")]
            for yaml_file in sorted(yaml_files):
                arcname = yaml_file.relative_to(workspace).as_posix()
                zf.write(yaml_file, arcname)
    except Exception as exc:  # noqa: BLE001
        logger.exception("export_yamls failed")
        raise HTTPException(status_code=500, detail=str(exc))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=semantic-layer-export.zip"},
    )

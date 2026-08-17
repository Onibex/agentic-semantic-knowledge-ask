"""Liveness/readiness probes — unauthenticated by design."""

from typing import Any

from fastapi import APIRouter

from ..application.runtime_config import config_status
from ..application.warmup import get_warmup_status

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness + the config-file state.

    ``config`` reports whether ``config/settings.json`` was found, with the
    RESOLVED path and the process cwd. The service is ``ok`` either way (env
    vars carry every key that matters), but a missing file used to be invisible
    until an unrelated endpoint 500'd with ``'NoneType' object has no attribute
    'get'`` — this makes it a one-request answer (BACKLOG group 0, P1).
    """
    return {"status": "ok", "service": "ask-admin-api", "config": config_status()}


@router.get("/health/warmup")
async def warmup_status() -> dict[str, Any]:
    """Background-warmup progress for the embedder / ingestion service.

    States:
      * ``pending``  — startup happened but the warmup hasn't begun yet
      * ``loading``  — embedder is being built (downloading weights /
        validating credentials)
      * ``ready``    — first publish will be fast
      * ``skipped``  — no embedder configured; warmup intentionally no-op
      * ``error``    — warmup failed; first publish will still try (cold)

    The HTTP server is healthy regardless of this state — the publish
    path just runs cold until ``ready`` is reached.
    """
    return get_warmup_status()

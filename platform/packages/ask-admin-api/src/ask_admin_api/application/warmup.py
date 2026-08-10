"""Background warmup for the ingestion service + embedder.

The first publish (per-entity or bulk) used to be visibly slow because
it triggered the embedder construction inline: connecting to SAP AI
Core, downloading HuggingFace model weights (a few hundred MB for
``BAAI/bge-base-en-v1.5``), validating credentials, etc. Subsequent
calls hit the in-process cache and were fast, but the first user
publish paid the full cold-start tax (~30-60s).

This module fires that cold start as a background task during the
FastAPI ``lifespan`` startup hook. Subsequent publish calls hit the
already-warm singleton. The HTTP server starts serving immediately —
warmup happens in parallel — so the healthcheck doesn't block.

Status is exposed at ``GET /v1/health/warmup`` so ops + the SPA can
display a "warming up" badge while the embedder is still loading.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Module-level state — single tracker per process.
_status_lock = threading.Lock()
_status: dict[str, Any] = {
    "state": "pending",  # pending | loading | ready | error | skipped
    "error": None,
    "started_at": None,
    "ready_at": None,
    "duration_s": None,
}


def get_warmup_status() -> dict[str, Any]:
    """Snapshot of the current warmup state. Safe to call any time."""
    with _status_lock:
        return dict(_status)


def _set(**fields: Any) -> None:
    with _status_lock:
        _status.update(fields)


def warmup_embedder_sync() -> None:
    """Force-construct the ingestion service and fire one probe embedding.

    Runs synchronously in the caller thread — designed to be wrapped in
    ``run_in_executor`` from the FastAPI lifespan handler so the event loop
    stays free. Safe to call multiple times: subsequent calls hit the
    cached singletons and complete in <1ms.

    Best-effort by design: catches every exception and reports through
    the status struct rather than raising. The HTTP server keeps running
    even if the embedder failed to load — only the publish path will be
    cold on the next request.
    """
    _set(state="loading", started_at=time.time(), error=None)
    try:
        # Lazy import — avoid pulling KG factory into module load order.
        from ..routers import yaml_ingestion

        svc = yaml_ingestion._get_service()  # noqa: SLF001 — module-internal warmup

        # Trigger an actual embed call to flush the lazy model download.
        # SAP AI Core embedder validates credentials on first call; HF
        # embedder downloads weights here.
        embedder = getattr(getattr(svc, "_legacy", None), "embedder", None)
        if embedder is not None and hasattr(embedder, "embed_query"):
            try:
                embedder.embed_query("warmup probe")
            except Exception as exc:  # noqa: BLE001
                # Embedder *constructed* but probe failed — record it but
                # don't mark the whole warmup failed; the service singleton
                # still exists.
                logger.warning("embedder warmup probe failed: %s", exc)
                _set(error=f"probe failed: {exc}")
        elif embedder is None:
            logger.info("warmup: no embedder configured — skipping probe")
            _set(state="skipped")
            return

        now = time.time()
        with _status_lock:
            started = _status.get("started_at") or now
            _status["state"] = "ready"
            _status["ready_at"] = now
            _status["duration_s"] = round(now - started, 2)
        logger.info("embedder warmup complete in %.2fs", _status["duration_s"])
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("embedder warmup failed")
        _set(state="error", error=str(exc), ready_at=time.time())

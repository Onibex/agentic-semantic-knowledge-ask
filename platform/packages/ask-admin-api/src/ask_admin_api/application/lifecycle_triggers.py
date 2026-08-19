# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Best-effort lifecycle trigger helpers for the YAML edit / merge / publish flows.

The lifecycle index is a denormalized cache (UX_CHANGES audit §5). Keeping it in
sync must never block the primary operation (a save / merge / publish): a stale
doc is recoverable via ``POST /v1/admin/lifecycle/rebuild``. So every trigger
here swallows its own errors and logs them.

Routers call these instead of touching ``LifecycleService`` directly, so the
try/except + lazy-singleton boilerplate lives in one place.
"""

from __future__ import annotations

import logging

from .lifecycle_service import LifecycleService

logger = logging.getLogger(__name__)

_svc: LifecycleService | None = None


def _service() -> LifecycleService:
    global _svc
    if _svc is None:
        _svc = LifecycleService()
    return _svc


def fire_on_create(
    entity_id: str,
    *,
    workspace_id: str = "",
    business_domain_ids: list[str] | None = None,
) -> None:
    try:
        _service().on_create(
            entity_id,
            workspace_id=workspace_id,
            business_domain_ids=business_domain_ids,
        )
    except Exception:  # noqa: BLE001 — denormalization upkeep, never blocks the write
        logger.warning("lifecycle on_create failed for %s", entity_id, exc_info=True)


def fire_on_edit(entity_id: str) -> None:
    try:
        _service().on_edit(entity_id)
    except Exception:  # noqa: BLE001
        logger.warning("lifecycle on_edit failed for %s", entity_id, exc_info=True)


def fire_on_sap_merge(entity_id: str) -> None:
    try:
        _service().on_sap_merge(entity_id)
    except Exception:  # noqa: BLE001
        logger.warning("lifecycle on_sap_merge failed for %s", entity_id, exc_info=True)


def fire_on_merge(
    *,
    created_entities: list[str],
    silver_id: str,
    working_changed: bool,
) -> None:
    """Lifecycle triggers for a SAP-JSON merge outcome.

    Shared by the SPA path (``/v1/viz/merge/sap-json``) and the M2M path
    (``/v1/ingest/sap-json``) so both stay in lockstep. Every first-ingest
    entity (Bronze and/or Silver) gets a lifecycle doc so it surfaces in the
    catalog — mirrors ``/admin/yaml/import``'s per-YAML ``fire_on_create``. A
    merge that changed a PRE-EXISTING Silver's working YAML moves it back to
    "In Review" (audit §5.3).
    """
    created = set(created_entities)
    for entity_id in created_entities:
        fire_on_create(entity_id)
    if silver_id and silver_id not in created and working_changed:
        fire_on_sap_merge(silver_id)


def fire_on_publish_dev(entity_id: str, *, by: str) -> None:
    try:
        _service().on_publish_dev(entity_id, by=by)
    except Exception:  # noqa: BLE001
        logger.warning("lifecycle on_publish_dev failed for %s", entity_id, exc_info=True)

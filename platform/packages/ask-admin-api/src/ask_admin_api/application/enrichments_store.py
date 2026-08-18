# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Sidecar JSON store for `_meta.field_enrichments` provenance.

History: `field_enrichments` used to live inline in each YAML at
`_meta.field_enrichments`, which polluted every git diff with framework
metadata. This store moves the data out — one JSON file per `yaml_id`
under `.sap_baseline/<yaml_id>.enrichments.json` — exactly mirroring
`ConflictStore`'s discipline.

File shape:

    {
      "entity_enrichments": ["description", "alias"],
      "field_enrichments": {
        "vorue_afko": ["field_role", "description"],
        "aufnr_afko": ["field_role", "description"]
      }
    }

Both keys are optional — an entity-only edit produces just `entity_enrichments`,
a field-only edit produces just `field_enrichments`.

Consumers (yaml_file_service, sap_merge_service) hydrate the
`VizMeta.field_enrichments` field from this sidecar at read time so the
public SPA contract stays unchanged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class EnrichmentsStore:
    SUFFIX = ".enrichments.json"

    def __init__(self, baseline_root: Path) -> None:
        self.root = Path(baseline_root)

    # ── Path helper ─────────────────────────────────────────────────────────

    def _path(self, yaml_id: str) -> Path:
        return self.root / f"{yaml_id}{self.SUFFIX}"

    # ── Read ────────────────────────────────────────────────────────────────

    def read(self, yaml_id: str) -> tuple[list[str], dict[str, list[str]]]:
        """Return ``(entity_enrichments, field_enrichments)`` for ``yaml_id``.

        Returns ``([], {})`` when the sidecar does not exist or is malformed.
        Read is the only access path used by ``yaml_file_service._extract_meta``
        for hydrating ``VizMeta.field_enrichments`` for the SPA.
        """
        path = self._path(yaml_id)
        if not path.exists():
            return [], {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read enrichments sidecar %s: %s", path, exc)
            return [], {}
        if not isinstance(data, dict):
            return [], {}

        entity_raw = data.get("entity_enrichments") or []
        entity = (
            sorted({str(p) for p in entity_raw if isinstance(p, str)})
            if isinstance(entity_raw, list)
            else []
        )

        fields_raw = data.get("field_enrichments") or {}
        fields = (
            {
                str(k): [str(p) for p in v if isinstance(p, str)]
                for k, v in fields_raw.items()
                if isinstance(v, list)
            }
            if isinstance(fields_raw, dict)
            else {}
        )
        return entity, fields

    # ── Write ───────────────────────────────────────────────────────────────

    def write(
        self,
        yaml_id: str,
        *,
        entity_enrichments: list[str] | None = None,
        field_enrichments: dict[str, list[str]] | None = None,
    ) -> None:
        """Persist both maps. When both are empty the sidecar is removed so
        git diffs stay clean."""
        path = self._path(yaml_id)
        entity = sorted(set(entity_enrichments or []))
        fields = dict(field_enrichments or {})
        if not entity and not fields:
            if path.exists():
                try:
                    path.unlink()
                except OSError as exc:
                    logger.warning("Could not delete empty enrichments sidecar %s: %s", path, exc)
            return

        payload: dict = {}
        if entity:
            payload["entity_enrichments"] = entity
        if fields:
            payload["field_enrichments"] = fields

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def delete(self, yaml_id: str) -> bool:
        """Remove the sidecar entirely. Returns True if a file was removed."""
        path = self._path(yaml_id)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError as exc:
            logger.warning("Could not delete enrichments sidecar %s: %s", path, exc)
            return False

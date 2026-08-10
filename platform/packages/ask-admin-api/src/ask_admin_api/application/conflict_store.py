"""File-based store for SAP-vs-curation conflicts (Pass H).

Before this module, every conflict raised by the SAP merge engine was
serialised into the host YAML's ``_meta.conflicts`` array. That mixed
two unrelated concerns in one file: semantic contract (fields, joins,
relationships) and operational queue (pending decisions). Every SAP
push, every resolve, every clear created a noisy git diff on the YAML
even when no semantic change had happened.

The store moves conflicts out of the YAML and into a sidecar JSON file
per ``yaml_id`` under ``.sap_baseline/<yaml_id>.conflicts.json``. The
sidecar is still git-tracked — so the audit trail survives container
rebuilds — but it lives alongside the baseline file rather than inside
the curated YAML, keeping the YAML's git diff pure semantic.

The store is intentionally file-based (not OpenSearch) for now:
* It mirrors the existing ``.sap_baseline/`` discipline.
* It needs zero new infrastructure.
* Cross-entity queries ("all pending") are a tree walk — fine at the
  current scale (hundreds of YAMLs).
When the workspace grows past that, swap the backend for an OpenSearch
index (``ask-yaml-conflicts-v1``) — every caller of this module talks
through the ConflictStore class, so the migration is contained.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ConflictStore:
    """One JSON file per yaml_id under ``.sap_baseline/``.

    File shape:
        [
          { conflict_dict },
          ...
        ]

    Each dict matches the ``ConflictBlock`` Pydantic model — fields:
    id, yaml_id, field_name, conflict_type, sap_value, current_value,
    enriched_properties, resolved, resolution, resolved_by, resolved_at.
    """

    SUFFIX = ".conflicts.json"

    def __init__(self, baseline_root: Path) -> None:
        self.root = Path(baseline_root)

    # ── Per-entity API ──────────────────────────────────────────────────────

    def _path(self, yaml_id: str) -> Path:
        return self.root / f"{yaml_id}{self.SUFFIX}"

    def list_for(self, yaml_id: str, *, include_resolved: bool = False) -> list[dict]:
        """Return the conflict list for a single yaml_id."""
        path = self._path(yaml_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read conflict sidecar %s: %s", path, exc)
            return []
        if include_resolved:
            return data
        return [c for c in data if not c.get("resolved", False)]

    def append(self, yaml_id: str, new_conflicts: list[dict]) -> None:
        """Append new conflict blocks to the sidecar for ``yaml_id``."""
        if not new_conflicts:
            return
        existing = self.list_for(yaml_id, include_resolved=True)
        combined = existing + list(new_conflicts)
        self._write(yaml_id, combined)

    def update_conflict(self, yaml_id: str, conflict_id: str, patch: dict) -> dict | None:
        """Find a conflict by id, merge ``patch`` into it, persist. Returns
        the updated dict or None if the conflict didn't exist."""
        items = self.list_for(yaml_id, include_resolved=True)
        for i, c in enumerate(items):
            if c.get("id") == conflict_id:
                items[i] = {**c, **patch}
                self._write(yaml_id, items)
                return items[i]
        return None

    def clear_resolved(self, yaml_id: str) -> None:
        """Drop every resolved conflict for ``yaml_id``. When nothing is
        left, the sidecar file is removed entirely so git diffs are clean."""
        items = [
            c for c in self.list_for(yaml_id, include_resolved=True) if not c.get("resolved", False)
        ]
        if items:
            self._write(yaml_id, items)
            return
        path = self._path(yaml_id)
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not delete empty conflict sidecar %s: %s", path, exc)

    # ── Workspace-wide API ──────────────────────────────────────────────────

    def list_all_pending(self) -> list[dict]:
        """Walk every sidecar and return the union of unresolved conflicts."""
        out: list[dict] = []
        if not self.root.exists():
            return out
        for path in sorted(self.root.glob(f"*{self.SUFFIX}")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read conflict sidecar %s: %s", path, exc)
                continue
            for c in data:
                if not c.get("resolved", False):
                    out.append(c)
        return out

    def entity_ids_with_pending(self) -> list[str]:
        """Return the set of yaml_ids that have at least one unresolved
        conflict. Used by FilterPanel / HealthPage to render badges."""
        ids: set[str] = set()
        if not self.root.exists():
            return []
        for path in sorted(self.root.glob(f"*{self.SUFFIX}")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
            except Exception:  # noqa: BLE001
                continue
            for c in data:
                if not c.get("resolved", False):
                    fname = c.get("yaml_id") or path.stem.removesuffix(".conflicts")
                    ids.add(fname)
                    break
        return sorted(ids)

    # ── Internals ───────────────────────────────────────────────────────────

    def _write(self, yaml_id: str, items: list[dict]) -> None:
        path = self._path(yaml_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

"""SAP JSON → workspace merge service (Pass B unification).

One canonical flow for every SAP JSON payload, regardless of entry point:
  - ``/v1/viz/ingest/sap-json``  (JWT, human-driven via SPA)
  - ``/v1/ingest/sap-json``      (X-API-Key, Kafka Connect / webhook)

Behaviour:
  1. Parse SAP JSON to domain (Bronze + Silver nodes).
  2. For every missing entity in the workspace → create as ``state: draft``.
     The visualizer state machine is the ONLY way to promote anything past
     draft; no SAP push ever produces a production YAML.
  3. For every pre-existing entity → run the structural diff against the
     stored baseline + enrichment rules. Safe field changes auto-apply;
     enriched ones produce conflict blocks for human resolution.
  4. Update the baseline on disk only when zero conflicts remain.
  5. Commit every mutation to git so the History timeline reflects the merge.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ask_knowledge_graph.infrastructure.sap_json_parser import SapJsonParser
from ask_knowledge_graph.infrastructure.yaml_serializer import (
    AskYamlSerializer,
    load_yaml_text,
)

from ..models.viz_models import VizLayer
from .conflict_store import ConflictStore
from .git_service import GitService
from .merge_engine import (
    entity_diff,
    process_diff,
    process_entity_diff,
    structural_diff,
)
from .yaml_file_service import YAMLFileService, YAMLNotFoundError

logger = logging.getLogger(__name__)


class MergeError(Exception):
    """Raised when SAP JSON cannot be processed (parse error, Gold target, etc.)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class MergeOutcome:
    silver_id: str
    auto_applied: list[dict]
    conflicts: list[dict]
    baseline_updated: bool
    created_entities: list[str]  # entity_ids that were first-ingest


def merge_sap_payload(
    payload: dict[str, Any],
    *,
    yaml_svc: YAMLFileService,
    git_svc: GitService,
    repo_root: Path,
    baseline_root: Path,
    author_name: str,
    author_email: str,
    source_label: str,  # "viz" | "kafka" | "webhook" — appears in commit messages
) -> MergeOutcome:
    """Single canonical SAP JSON merge. Used by both JWT and M2M endpoints."""
    # 1. Parse
    try:
        parser = SapJsonParser()
        bronze_nodes, silver_node = parser.parse_to_domain(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SAP JSON parse failed: %s", exc)
        raise MergeError(f"SAP JSON parse error: {exc}", status_code=422) from exc

    silver_id = silver_node.id
    created_entities: list[str] = []
    modified_paths: list[str] = []
    all_auto_applied: list[dict] = []
    all_conflicts: list[dict] = []
    # Pass H — conflicts live in a sidecar JSON under .sap_baseline/, not
    # inside the YAML's _meta.conflicts. Diffs stay clean.
    conflict_store = ConflictStore(baseline_root)

    # Pre-check: cannot re-ingest while previous conflicts are still pending.
    # The check uses the store, since _meta.conflicts no longer exists on
    # the YAML.
    unresolved = conflict_store.list_for(silver_id, include_resolved=False)
    if unresolved:
        raise MergeError(
            f"Silver YAML '{silver_id}' has {len(unresolved)} unresolved conflict(s). "
            f"Resolve them before re-ingesting.",
            status_code=409,
        )

    # 2. Resolve / create Silver
    silver_was_created = False
    try:
        silver_yaml_node = yaml_svc.get_yaml(silver_id)
    except YAMLNotFoundError:
        rel = yaml_svc.create_yaml_from_parsed(silver_node)
        modified_paths.append(rel)
        created_entities.append(silver_id)
        silver_was_created = True
        silver_yaml_node = yaml_svc.get_yaml(silver_id)

    # Gold YAMLs are never merged from SAP.
    if silver_yaml_node.layer == VizLayer.gold:
        raise MergeError("Gold YAMLs are never touched by SAP ingest", status_code=422)

    # 3. Load baseline (always — even for first-ingest, since we update it later)
    baseline_file = baseline_root / f"{silver_id}.json"
    baseline = _load_baseline(baseline_file)

    # 4. Silver merge (only when Silver existed already — first-ingest writes the
    #    parsed contents verbatim; merging against an empty baseline would just
    #    re-add the same fields).
    if not silver_was_created:
        silver_abs_path = repo_root / silver_yaml_node.file_path
        silver_raw = load_yaml_text(silver_abs_path.read_text(encoding="utf-8")) or {}

        # 4a. Field-level diff
        baseline_silver_fields = baseline.get("silver_fields") or {}
        new_silver_fields = _silver_fields_from_parsed(silver_node)
        silver_diff = structural_diff(
            silver_id,
            baseline_silver_fields,
            new_silver_fields,
            is_bronze=False,
        )
        s_auto, s_conf = process_diff(
            silver_diff,
            silver_raw,
            silver_yaml_node.meta.field_enrichments,
            silver_id,
            is_bronze=False,
        )

        # 4b. Entity-level (header) diff — description / alias
        baseline_entity = baseline.get("silver_entity") or {}
        new_entity = _silver_entity_payload(silver_node)
        changed_entity_props = entity_diff(baseline_entity, new_entity)
        e_auto, e_conf = process_entity_diff(
            changed_entity_props,
            silver_raw,
            new_entity,
            silver_yaml_node.meta.entity_enrichments,
            silver_id,
        )

        s_auto = s_auto + e_auto
        s_conf = s_conf + e_conf
        all_auto_applied.extend(s_auto)
        all_conflicts.extend(s_conf)
        if s_conf:
            conflict_store.append(silver_id, s_conf)
        if s_auto:
            silver_abs_path.write_text(AskYamlSerializer().to_yaml(silver_raw), encoding="utf-8")
            modified_paths.append(silver_yaml_node.file_path)

    # 5. Bronze merge (first-ingest creates missing bronzes, merge runs on the rest)
    for bronze_node in bronze_nodes:
        bronze_id = bronze_node.id
        try:
            bronze_yaml_node = yaml_svc.get_yaml(bronze_id)
            bronze_was_created = False
        except YAMLNotFoundError:
            rel = yaml_svc.create_yaml_from_parsed(bronze_node)
            modified_paths.append(rel)
            created_entities.append(bronze_id)
            bronze_was_created = True
            bronze_yaml_node = yaml_svc.get_yaml(bronze_id)

        if bronze_was_created:
            continue  # nothing to merge against — file was just written

        bronze_abs_path = repo_root / bronze_yaml_node.file_path
        bronze_raw = load_yaml_text(bronze_abs_path.read_text(encoding="utf-8")) or {}

        # Field-level diff
        baseline_bronze_fields = (baseline.get("bronze_fields") or {}).get(bronze_node.name) or {}
        new_bronze_fields = _bronze_fields_from_parsed(bronze_node)
        bronze_diff = structural_diff(
            bronze_id,
            baseline_bronze_fields,
            new_bronze_fields,
            is_bronze=True,
        )
        b_auto, b_conf = process_diff(
            bronze_diff,
            bronze_raw,
            bronze_yaml_node.meta.field_enrichments,
            bronze_id,
            is_bronze=True,
        )

        # Entity-level (header) diff for the Bronce too
        baseline_bronze_entity = (baseline.get("bronze_entities") or {}).get(bronze_node.name) or {}
        new_bronze_entity = _bronze_entity_payload(bronze_node)
        changed_bronze_entity_props = entity_diff(baseline_bronze_entity, new_bronze_entity)
        be_auto, be_conf = process_entity_diff(
            changed_bronze_entity_props,
            bronze_raw,
            new_bronze_entity,
            bronze_yaml_node.meta.entity_enrichments,
            bronze_id,
        )

        b_auto = b_auto + be_auto
        b_conf = b_conf + be_conf
        all_auto_applied.extend(b_auto)
        all_conflicts.extend(b_conf)
        if b_conf:
            conflict_store.append(bronze_id, b_conf)
        if b_auto:
            bronze_abs_path.write_text(AskYamlSerializer().to_yaml(bronze_raw), encoding="utf-8")
            modified_paths.append(bronze_yaml_node.file_path)

    # 6. Commits — group by intent for readable History
    if created_entities and modified_paths:
        git_svc.commit(
            modified_paths,
            f"ingest({source_label}, {silver_id}): first-ingest "
            f"{len(created_entities)} entities as draft",
            author_name,
            author_email,
        )
    elif all_auto_applied and modified_paths:
        git_svc.commit(
            modified_paths,
            f"merge({source_label}, {silver_id}): auto-apply {len(all_auto_applied)} field changes",
            author_name,
            author_email,
        )

    if all_conflicts and not created_entities:
        # Pass H — conflict blocks now live in ``.sap_baseline/<id>.conflicts.json``
        # sidecar files; the merge already wrote them. Commit the sidecars
        # so the History timeline still shows pending work (separately from
        # the YAML's auto-apply commit).
        conflict_yaml_ids = list({c["yaml_id"] for c in all_conflicts})
        sidecar_paths: list[str] = []
        for yid in conflict_yaml_ids:
            p = ConflictStore(baseline_root)._path(yid)  # noqa: SLF001 — same module
            try:
                rel = p.relative_to(repo_root).as_posix()
                sidecar_paths.append(rel)
            except ValueError:
                # Sidecar lives outside the repo root — skip the commit, the
                # file is still written and will be picked up next time.
                pass
        if sidecar_paths:
            git_svc.commit(
                sidecar_paths,
                f"merge({source_label}, {silver_id}): {len(all_conflicts)} conflicts pending",
                author_name,
                author_email,
            )

    # 7. Baseline always reflects the latest SAP state. Conflicts carry
    # their own ``sap_value`` copies, so the conflict resolver does NOT
    # need to consult the baseline to know what SAP last sent for a
    # specific conflicted property. Writing the baseline only on
    # conflict-free merges (previous behaviour) caused two issues:
    #   * Field-level: ``_handle_all_conflicts_resolved`` had to
    #     reconstruct the baseline from the YAML + resolved-conflict
    #     sap_value overrides — workable but duplicative.
    #   * Entity-level: when only field conflicts existed, the resolved
    #     baseline write fell back to the workspace value for entity
    #     props (admin's enrichment) instead of SAP's actual value,
    #     producing a spurious entity_modified conflict on the next ingest.
    # Unifying to "always write" eliminates both classes of drift.
    new_baseline = _build_baseline_from_parsed(bronze_nodes, silver_node)
    _save_baseline(baseline_file, new_baseline)
    baseline_updated = True

    # Commit the baseline so it does not linger as an uncommitted tracked change.
    # Previously the baseline was written here but never committed, leaving
    # .sap_baseline/<id>.json dirty on main — which later aborted the publish
    # branch switch ("local changes would be overwritten by checkout").
    # commit_if_changed is idempotent: identical re-ingest → no empty commit.
    try:
        baseline_rel = baseline_file.relative_to(repo_root).as_posix()
        git_svc.commit_if_changed(
            [baseline_rel],
            f"merge({source_label}, {silver_id}): update SAP baseline",
            author_name,
            author_email,
        )
    except ValueError:
        pass  # baseline lives outside the repo root — nothing to commit

    return MergeOutcome(
        silver_id=silver_id,
        auto_applied=all_auto_applied,
        conflicts=all_conflicts,
        baseline_updated=baseline_updated,
        created_entities=created_entities,
    )


# ── Baseline + parsed-node helpers (moved from viz_ingest.py for reuse) ────────


def _load_baseline(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load baseline %s: %s", path, exc)
        return {}


def _save_baseline(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _silver_entity_payload(silver_node) -> dict:
    """Project the SAP-parsed Silver header to the dict shape ``entity_diff``
    expects. Carries every entity-level property SAP supplies AND that the
    engine can diff (see ENTITY_LEVEL_TRACKED_PROPS)."""
    # SilverNode does not have an alias attribute today (SAP doesn't supply
    # one at the entity level). We still emit the key so the diff produces
    # ``alias: None`` consistently — and so when SAP eventually starts
    # carrying it, no engine change is required.
    return {
        "description": getattr(silver_node, "description", None),
        "alias": getattr(silver_node, "alias", None),
    }


def _bronze_entity_payload(bronze_node) -> dict:
    return {
        "description": getattr(bronze_node, "description", None),
        "alias": getattr(bronze_node, "alias", None),
    }


def _silver_field_dict(f) -> dict:
    """Project a SAP-parsed SilverField to the dict shape the merge engine
    expects. Carries every property SAP supplies AND that the engine can
    diff (see SILVER_FIELD_TRACKED_PROPS)."""
    return {
        "type": f.type,
        "source": f.source,
        "description": f.description,
        "field_role": f.field_role,
        "aggregation_behavior": f.aggregation_behavior,
    }


def _bronze_field_dict(fdata) -> dict:
    return {
        "type": fdata.type,
        "description": fdata.description,
        "alias": fdata.alias,
        "key_field": fdata.key_field,
    }


def _build_baseline_from_parsed(bronze_nodes, silver_node) -> dict:
    silver_fields = {f.name: _silver_field_dict(f) for f in silver_node.fields}
    bronze_fields = {
        b.name: {fname: _bronze_field_dict(fdata) for fname, fdata in b.fields.items()}
        for b in bronze_nodes
    }
    bronze_entities = {b.name: _bronze_entity_payload(b) for b in bronze_nodes}
    return {
        "silver_id": silver_node.id,
        "silver_fields": silver_fields,
        "silver_entity": _silver_entity_payload(silver_node),
        "bronze_fields": bronze_fields,
        "bronze_entities": bronze_entities,
    }


def _silver_fields_from_parsed(silver_node) -> dict[str, dict]:
    return {f.name: _silver_field_dict(f) for f in silver_node.fields}


def _bronze_fields_from_parsed(bronze_node) -> dict[str, dict]:
    return {fname: _bronze_field_dict(fdata) for fname, fdata in bronze_node.fields.items()}

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ask_knowledge_graph.domain.entity_deriver import EntityDeriver
from ask_knowledge_graph.infrastructure.sap_json_parser import SapJsonParser
from ask_knowledge_graph.infrastructure.yaml_serializer import (
    AskYamlSerializer,
    load_yaml_text,
)

from ..models.viz_models import VizLayer
from .conflict_store import ConflictStore
from .enrichments_store import EnrichmentsStore
from .git_service import GitService
from .merge_engine import (
    BRONZE_FIELD_TRACKED_PROPS,
    ENTITY_LEVEL_TRACKED_PROPS,
    SILVER_FIELD_TRACKED_PROPS,
    entity_diff,
    merge_structure,
    normalise_bronze_fields,
    normalise_silver_fields,
    process_diff,
    process_entity_diff,
    reconcile_renames,
    rename_field_in_raw,
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
    # Identifier-hygiene warnings from the parser (normalized alias values,
    # in-table alias collisions). Ingestion proceeds; the caller surfaces them —
    # under column naming mode `alias` a changed value is a mismatch risk
    # against the client's physical column names.
    naming_warnings: list[str] = field(default_factory=list)


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
    merge_warnings: list[str] = []
    if not silver_was_created:
        silver_abs_path = repo_root / silver_yaml_node.file_path
        silver_raw = load_yaml_text(silver_abs_path.read_text(encoding="utf-8")) or {}

        # 4a. Field-level diff. Removed+added pairs sharing a `source` are
        # RENAMES (an upstream alias edit under column naming mode `alias`):
        # applied in place so the field's enrichments survive, with the
        # provenance sidecar key moved along.
        new_silver_fields = _silver_fields_from_parsed(silver_node)
        # NO baseline (pre-packed YAML uploaded first, JSON arrives after): the
        # LIVE YAML is the diff base. A JSON must NEVER overwrite curated YAML
        # content silently — differing props gate on the (import-seeded)
        # enrichments, and live fields absent from the export surface as
        # removals (conflict when enriched). With a baseline this is the
        # normal 3-way and only SAP-side deltas move.
        baseline_silver_fields = baseline.get("silver_fields") or _live_fields_projection(
            normalise_silver_fields(silver_raw), new_silver_fields, SILVER_FIELD_TRACKED_PROPS
        )
        silver_diff = structural_diff(
            silver_id,
            baseline_silver_fields,
            new_silver_fields,
            is_bronze=False,
        )
        rename_audit: list[dict] = []
        renames = reconcile_renames(silver_diff)
        if renames:
            enr_store = EnrichmentsStore(baseline_root)
            entity_enr, field_enr = enr_store.read(silver_id)
            enr_moved = False
            for op in renames:
                if not rename_field_in_raw(silver_raw, op.old_name, op.new_name):
                    continue
                rename_audit.append(
                    {
                        "yaml_id": silver_id,
                        "field_name": op.new_name,
                        "change_type": "renamed",
                        "old_value": {"name": op.old_name},
                        "new_value": {"name": op.new_name},
                    }
                )
                merge_warnings.append(
                    f"{silver_id}: field '{op.old_name}' renamed upstream to "
                    f"'{op.new_name}' (same source) — enrichments preserved"
                )
                if op.old_name in field_enr:
                    field_enr[op.new_name] = field_enr.pop(op.old_name)
                    enr_moved = True
            if enr_moved:
                enr_store.write(
                    silver_id, entity_enrichments=entity_enr, field_enrichments=field_enr
                )

        s_auto, s_conf = process_diff(
            silver_diff,
            silver_raw,
            silver_yaml_node.meta.field_enrichments,
            silver_id,
            is_bronze=False,
        )

        # 4b. Entity-level (header) diff — description / alias
        new_entity = _silver_entity_payload(silver_node)
        baseline_entity = baseline.get("silver_entity") or _live_entity_projection(
            silver_raw, new_entity
        )
        changed_entity_props = entity_diff(baseline_entity, new_entity)
        e_auto, e_conf = process_entity_diff(
            changed_entity_props,
            silver_raw,
            new_entity,
            silver_yaml_node.meta.entity_enrichments,
            silver_id,
        )

        # 4c. Structure merge — composed_of / join_graph. Membership follows the
        # export; edge props merge 3-way vs the baseline. Removals are deferred
        # while field-removed conflicts are pending, so a kept (enriched) field
        # never points at a table the structure no longer declares.
        defer_removals = any(c.get("conflict_type") == "field_removed" for c in s_conf)
        st_audit, st_changed = merge_structure(
            baseline_structure=baseline.get("silver_structure"),
            current_raw=silver_raw,
            incoming=_structure_from_parsed(silver_node),
            yaml_id=silver_id,
            defer_removals=defer_removals,
        )

        # 4d. Re-derive grain + measure fan-out whenever fields or structure
        # moved — the SAME derivation the admin save path runs, so the two
        # write paths cannot disagree (and merge-added measures get their
        # additivity instead of silently reading as additive).
        rederived = False
        if s_auto or renames or st_changed:
            rederived = _rederive_grain_and_fanout(
                silver_raw, silver_yaml_node.meta.field_enrichments
            )

        # 4e. Normalization sweep: strip literal-None axis keys (the empty
        # `aggregation_behavior:` defect) and restore the canonical per-field
        # key order that older merges scrambled.
        normalized = _normalize_silver_fields(silver_raw)

        s_auto = rename_audit + s_auto + e_auto + st_audit
        s_conf = s_conf + e_conf
        all_auto_applied.extend(s_auto)
        all_conflicts.extend(s_conf)
        if s_conf:
            conflict_store.append(silver_id, s_conf)
        if s_auto or st_changed or rederived or normalized:
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

        # Field-level diff (same no-baseline rule as Silver: the live YAML is
        # the base, so an uploaded Bronze is never silently overwritten).
        new_bronze_fields = _bronze_fields_from_parsed(bronze_node)
        baseline_bronze_fields = (
            (baseline.get("bronze_fields") or {}).get(bronze_node.name)
            or _live_fields_projection(
                normalise_bronze_fields(bronze_raw), new_bronze_fields, BRONZE_FIELD_TRACKED_PROPS
            )
        )
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

        # Entity-level (header) diff for the Bronze too
        new_bronze_entity = _bronze_entity_payload(bronze_node)
        baseline_bronze_entity = (
            (baseline.get("bronze_entities") or {}).get(bronze_node.name)
            or _live_entity_projection(bronze_raw, new_bronze_entity)
        )
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
            # A merged key_field flip must keep the top-level primary_key list
            # coherent — BronzeNode demands agreement in both directions, so
            # leaving it stale makes the admin's NEXT save 422 on a file they
            # never broke (and the Silver grain derives from these keys).
            _resync_bronze_primary_key(bronze_raw)
            bronze_abs_path.write_text(AskYamlSerializer().to_yaml(bronze_raw), encoding="utf-8")
            modified_paths.append(bronze_yaml_node.file_path)

    # 5b. The merge writes YAML files directly (not through the service's write
    # methods), so the read cache must be dropped or the SPA's next read within
    # the signature TTL serves the pre-merge file.
    if modified_paths:
        yaml_svc.invalidate_cache()

    # 6. Commits — group by intent for readable History
    if created_entities and modified_paths:
        git_svc.commit(
            modified_paths,
            f"ingest({source_label}, {silver_id}): first-ingest "
            f"{len(created_entities)} entities as draft",
            author_name,
            author_email,
        )
    elif modified_paths:
        # A normalization-only pass modifies the file with zero audit entries —
        # it must still be committed or the working tree stays dirty and the
        # next publish branch-switch aborts.
        summary = (
            f"auto-apply {len(all_auto_applied)} field changes"
            if all_auto_applied
            else "normalize field shape"
        )
        git_svc.commit(
            modified_paths,
            f"merge({source_label}, {silver_id}): {summary}",
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
        naming_warnings=parser.naming_warnings + merge_warnings,
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
    expects — exactly SILVER_FIELD_TRACKED_PROPS, nothing else.

    `aggregation_behavior` is deliberately absent: SAP never authors it, and
    projecting its default None used to write a literal empty key into every
    merge-added field (the defect SILVER_LAYER.md §4.1 forbids). The
    axis-1/axis-2 pair is owned by the post-merge fan-out re-derivation."""
    return {
        "type": f.type,
        "source": f.source,
        "description": f.description,
        "field_role": f.field_role,
    }


def _bronze_field_dict(fdata) -> dict:
    return {
        "type": fdata.type,
        "description": fdata.description,
        "alias": fdata.alias,
        "key_field": fdata.key_field,
    }


def _structure_from_parsed(silver_node) -> dict:
    """`composed_of` + `join_graph` in the plain-dict shape `merge_structure`
    diffs. Grain is NOT here — it is re-derived, never diffed."""
    return {
        "composed_of": [str(c) for c in (silver_node.composed_of or [])],
        "join_graph": [jc.model_dump() for jc in (silver_node.join_graph or [])],
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
        # Structure snapshot — the 3-way arbiter for merge_structure. Old
        # baselines lack the key (first-sighting: structure merge skips
        # removals/prop-diffs once, this write catches up).
        "silver_structure": _structure_from_parsed(silver_node),
        "bronze_fields": bronze_fields,
        "bronze_entities": bronze_entities,
    }


def _silver_fields_from_parsed(silver_node) -> dict[str, dict]:
    return {f.name: _silver_field_dict(f) for f in silver_node.fields}


def _bronze_fields_from_parsed(bronze_node) -> dict[str, dict]:
    return {fname: _bronze_field_dict(fdata) for fname, fdata in bronze_node.fields.items()}


# ── No-baseline diff bases (pre-packed YAML uploaded first) ─────────────────

# String props where an EMPTY incoming value is "SAP has nothing to say", not a
# change proposal — they are excluded from the live-projection base so a terse
# export can never challenge curated text just by omitting it.
_EMPTY_IS_NO_PROPOSAL = ("description", "alias")


def _live_fields_projection(
    live_fields: dict[str, dict],
    incoming_fields: dict[str, dict],
    tracked_props: tuple[str, ...],
) -> dict[str, dict]:
    """The live YAML's fields projected to the tracked props — the diff base
    when no SAP baseline exists. Only props the field actually carries are
    included (first-sighting semantics for the rest), and text props the
    incoming export leaves empty are skipped (see _EMPTY_IS_NO_PROPOSAL)."""
    base: dict[str, dict] = {}
    for name, live in live_fields.items():
        inc = incoming_fields.get(name)
        props: dict = {}
        for p in tracked_props:
            if p not in live:
                continue
            if (
                p in _EMPTY_IS_NO_PROPOSAL
                and inc is not None
                and not str(inc.get(p) or "").strip()
            ):
                continue
            props[p] = live.get(p)
        base[name] = props
    return base


def _live_entity_projection(raw: dict, new_entity: dict) -> dict:
    """Entity-header diff base when no baseline exists: the live values, but
    only for props the incoming payload actually proposes (non-empty)."""
    return {
        p: raw.get(p)
        for p in ENTITY_LEVEL_TRACKED_PROPS
        if str(new_entity.get(p) or "").strip()
    }


# ── Post-merge derivation + normalization ────────────────────────────────────

# The DERIVED additivity shapes the fan-out re-derivation owns. A measure whose
# provenance records an admin edit on ANY of these keys is untouchable.
_DERIVED_AXIS_PROPS = ("additivity", "non_additive_over", "aggregation_behavior")


def _rederive_grain_and_fanout(
    silver_raw: dict, field_enrichments: dict[str, list[str]]
) -> bool:
    """Re-run the grain + measure-fan-out derivation on the merged YAML.

    The SAME derivation the admin save path runs unconditionally
    (`yaml_file_service` → `recompute_entity_grain`), so a merge and an edit
    can never disagree about the grain. Fan-out: the derived shapes
    (`semi_additive` + `non_additive_over`, and the `non_additive` +
    `aggregation_behavior: none` pair) are reset on every measure the admin
    did not curate, then re-derived against the new grain — this both updates
    stale `non_additive_over` lists and fills merge-added measures that would
    otherwise silently read as additive. An authored bare
    `aggregation_behavior` (SUM…) is never touched.
    """
    fields = silver_raw.get("fields") if isinstance(silver_raw.get("fields"), list) else []
    join_graph = (
        silver_raw.get("join_graph") if isinstance(silver_raw.get("join_graph"), list) else None
    )
    deriver = EntityDeriver()
    changed = False

    entity_grain = deriver.recompute_entity_grain(fields, join_graph=join_graph)
    if entity_grain:
        grain = silver_raw.get("grain") if isinstance(silver_raw.get("grain"), dict) else {}
        if list(grain.get("entity_grain") or []) != entity_grain:
            business = (
                grain.get("business_grain") or f"{silver_raw.get('name') or 'entity'}_item"
            )
            if grain:
                grain["entity_grain"] = entity_grain
                grain["business_grain"] = business
                silver_raw["grain"] = grain
            else:
                silver_raw["grain"] = {"entity_grain": entity_grain, "business_grain": business}
            changed = True
    else:
        grain = silver_raw.get("grain") if isinstance(silver_raw.get("grain"), dict) else {}
        entity_grain = list(grain.get("entity_grain") or [])

    def _axis_state(fd: dict) -> tuple:
        return (
            fd.get("additivity"),
            list(fd.get("non_additive_over") or []),
            fd.get("aggregation_behavior"),
        )

    before = [
        _axis_state(f) for f in fields if isinstance(f, dict) and f.get("field_role") == "measure"
    ]
    for f in fields:
        if not isinstance(f, dict) or f.get("field_role") != "measure":
            continue
        enriched = set(field_enrichments.get(str(f.get("name")), []))
        if enriched & set(_DERIVED_AXIS_PROPS):
            continue  # curator recorded — author wins
        if f.get("additivity") == "semi_additive":
            f.pop("additivity", None)
            f.pop("non_additive_over", None)
        elif f.get("additivity") == "non_additive" and f.get("aggregation_behavior") == "none":
            f.pop("additivity", None)
            f.pop("aggregation_behavior", None)
            f.pop("non_additive_over", None)

    deriver.apply_measure_fanout(fields, entity_grain=entity_grain, join_graph=join_graph)
    after = [
        _axis_state(f) for f in fields if isinstance(f, dict) and f.get("field_role") == "measure"
    ]
    return changed or before != after


# Canonical per-field key order (what first-ingest writes) + the keys whose
# literal-None presence is the historical "empty aggregation_behavior:" defect.
_CANONICAL_FIELD_KEYS = (
    "name",
    "source",
    "type",
    "description",
    "field_role",
    "aggregation_behavior",
    "additivity",
    "non_additive_over",
    "synonyms",
)
_NULLABLE_FIELD_KEYS = ("aggregation_behavior", "additivity", "non_additive_over", "synonyms")


def _normalize_silver_fields(silver_raw: dict) -> bool:
    """Strip literal-None axis keys and restore the canonical key order.

    Repairs the damage older merges left behind (fields appended as
    ``type…name`` with an empty ``aggregation_behavior:``) as a side effect of
    the next re-ingest — no manual YAML surgery. Untouched fields keep their
    original objects, so a clean file round-trips unchanged.
    """
    fields = silver_raw.get("fields") if isinstance(silver_raw.get("fields"), list) else []
    changed = False
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            continue
        dropped = [k for k in _NULLABLE_FIELD_KEYS if k in f and f[k] is None]
        keys = [k for k in f if k not in dropped]
        desired = [k for k in _CANONICAL_FIELD_KEYS if k in keys] + [
            k for k in keys if k not in _CANONICAL_FIELD_KEYS
        ]
        if not dropped and keys == desired:
            continue
        fields[i] = {k: f[k] for k in desired}
        changed = True
    return changed


def _resync_bronze_primary_key(bronze_raw: dict) -> bool:
    """Rebuild the Bronze ``primary_key`` list from the ``key_field`` flags.

    The merge applies ``key_field`` per field; without this the top-level list
    drifts and BronzeNode's two-way agreement validator rejects the file on the
    next admin save. Order follows the fields mapping (the parser's column
    order), same as first-ingest.
    """
    fields = bronze_raw.get("fields")
    if not isinstance(fields, dict):
        return False
    pks = [n for n, fd in fields.items() if isinstance(fd, dict) and fd.get("key_field")]
    if list(bronze_raw.get("primary_key") or []) != pks:
        bronze_raw["primary_key"] = pks
        return True
    return False

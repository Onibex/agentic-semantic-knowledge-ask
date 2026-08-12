"""SAP JSON merge engine — property-level diff (Pass G).

Compares an incoming SAP JSON (parsed to domain, then converted to field
dicts) against the current YAML state, property by property. Properties
that changed are auto-applied OR raised as conflicts depending on
whether the admin enriched that specific property.

Field format conventions:
  Bronze: raw["fields"] is a dict {field_name: {type, alias, key_field, description}}
  Silver: raw["fields"] is a list [{name, source, field_role, type, ...}]

What we diff per layer (SAP-supplied, admin-enrichable):
  Silver fields:  type, source, description, field_role, aggregation_behavior
  Bronze fields:  type, description, alias, key_field

Admin-only properties (never in SAP payload, never compared, never produce
conflicts but ARE recognised as enrichment by provenance_engine):
  synonyms, normalization_flag, additivity, non_additive_over
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

# Properties that SAP supplies AND we therefore can diff. Admin-only props
# (synonyms, normalization_flag) are intentionally not here — SAP never
# carries them so they can't change between baseline and incoming.
#
# `aggregation_behavior` is deliberately NOT tracked: SAP never authors it
# (only the fan-out derivation stamps `none`, paired with `additivity`), so
# diffing it produced two defects — auto-applying a literal None (the empty
# `aggregation_behavior:` key SILVER_LAYER.md §4.1 exists to forbid) and
# splitting the axis-1/axis-2 pair. The post-merge fan-out re-derivation in
# ``sap_merge_service`` is the single owner of that pair.
SILVER_FIELD_TRACKED_PROPS: tuple[str, ...] = (
    "type",
    "source",
    "description",
    "field_role",
)
BRONZE_FIELD_TRACKED_PROPS: tuple[str, ...] = (
    "type",
    "description",
    "alias",
    "key_field",
)


# Entity-level (header) properties that SAP supplies AND we therefore can
# diff. These live at the top of the YAML, not inside fields[].
ENTITY_LEVEL_TRACKED_PROPS: tuple[str, ...] = ("description", "alias")


# Sentinel used as ``field_name`` on ConflictBlock entries that describe
# entity-level (header) conflicts. The frontend / resolution router check
# against this constant when rendering / applying.
ENTITY_LEVEL_SENTINEL = "__entity__"


# Kept for backward compat with provenance_engine.ENRICHABLE_PROPS — those
# include admin-only props (synonyms, normalization_flag, additivity,
# non_additive_over) that this engine does NOT diff against.
ENRICHABLE_PROPS = {"alias", "description", "field_role", "aggregation_behavior"}


@dataclass
class FieldChange:
    field_name: str
    change_type: Literal["added", "removed", "modified", "unchanged"]
    old_value: dict | None
    new_value: dict | None
    # Property names that differ between old and new — populated for
    # change_type == "modified". Empty for added/removed/unchanged.
    changed_properties: list[str] = field(default_factory=list)


@dataclass
class StructuralDiff:
    silver_id: str
    field_changes: list[FieldChange]


def _diff_properties(old: dict, new: dict, props: Iterable[str]) -> list[str]:
    """Return the subset of ``props`` whose values differ between old and new.

    A property is only diffed when it's PRESENT in ``old``. Properties absent
    from the baseline are treated as "first sighting" and skipped — this
    handles the upgrade path when new tracked properties are added (e.g.
    Pass G full added field_role and aggregation_behavior to the tracked
    set; pre-existing baselines lack those keys so without this guard the
    first ingest after upgrade would flag every field as ``modified`` for
    those props). The end-of-merge baseline rewrite catches up by snapshotting
    the new props alongside the old ones.
    """
    return [p for p in props if p in old and old.get(p) != new.get(p)]


def structural_diff(
    silver_id: str,
    baseline_fields: dict,
    new_fields: dict,
    *,
    is_bronze: bool = False,
) -> StructuralDiff:
    """Compare two field dicts (Bronze key→dict or Silver name→dict).

    Returns a per-field summary. Modified fields carry the list of changed
    properties so process_diff can split them into auto-apply (per-property)
    and conflicts (per-property, by enrichment).
    """
    props = BRONZE_FIELD_TRACKED_PROPS if is_bronze else SILVER_FIELD_TRACKED_PROPS
    changes: list[FieldChange] = []
    for name in set(baseline_fields) | set(new_fields):
        old = baseline_fields.get(name)
        new = new_fields.get(name)
        if old is None:
            changes.append(FieldChange(name, "added", None, new))
        elif new is None:
            changes.append(FieldChange(name, "removed", old, None))
        else:
            diff_props = _diff_properties(old, new, props)
            if diff_props:
                changes.append(
                    FieldChange(name, "modified", old, new, changed_properties=diff_props)
                )
            else:
                changes.append(FieldChange(name, "unchanged", old, new))
    return StructuralDiff(silver_id=silver_id, field_changes=changes)


def process_diff(
    diff: StructuralDiff,
    current_raw: dict,
    field_enrichments: dict[str, list[str]],
    yaml_id: str,
    is_bronze: bool,
) -> tuple[list[dict], list[dict]]:
    """Process a StructuralDiff and return (auto_applied_changes, conflict_blocks).

    Per-property semantics:
      * Each changed property on an enriched field becomes part of a conflict.
      * Each changed property on a non-enriched field (or one enriched on
        DIFFERENT props) is auto-applied in place, preserving sibling
        properties.
    """
    auto_applied: list[dict] = []
    conflicts: list[dict] = []
    tracked_props = BRONZE_FIELD_TRACKED_PROPS if is_bronze else SILVER_FIELD_TRACKED_PROPS

    for fc in diff.field_changes:
        if fc.change_type == "unchanged":
            continue

        # ── Reconcile "added" against the live YAML ──────────────────────
        # A missing or stale baseline marks every field as "added", but the
        # field may already exist in the workspace (often with enrichments).
        # If everything matches → no change. Otherwise reclassify as
        # "modified" with the actual delta.
        if fc.change_type == "added":
            existing = _get_field_value(current_raw, fc.field_name, is_bronze)
            if existing is not None:
                diff_props = _diff_properties(existing, fc.new_value or {}, tracked_props)
                if not diff_props:
                    continue  # baseline gap only — workspace already matches
                fc = FieldChange(
                    fc.field_name,
                    "modified",
                    existing,
                    fc.new_value,
                    changed_properties=diff_props,
                )

        # ── Removed ────────────────────────────────────────────────────────
        if fc.change_type == "removed":
            enrichments = field_enrichments.get(fc.field_name, [])
            if enrichments:
                # Conflict: SAP wants to remove an admin-curated field.
                conflicts.append(
                    {
                        "id": str(uuid.uuid4()),
                        "yaml_id": yaml_id,
                        "field_name": fc.field_name,
                        "conflict_type": "field_removed",
                        "sap_value": fc.new_value or {},
                        "current_value": _get_field_value(current_raw, fc.field_name, is_bronze)
                        or {},
                        "enriched_properties": list(enrichments),
                        "resolved": False,
                        "resolution": None,
                        "resolved_by": None,
                        "resolved_at": None,
                    }
                )
            else:
                _remove_field(current_raw, fc.field_name, is_bronze)
                auto_applied.append(
                    {
                        "yaml_id": yaml_id,
                        "field_name": fc.field_name,
                        "change_type": "removed",
                        "old_value": fc.old_value,
                        "new_value": None,
                    }
                )
            continue

        # ── Added (genuine — workspace does NOT have the field) ──────────
        if fc.change_type == "added":
            _add_field(current_raw, fc.field_name, fc.new_value or {}, is_bronze)
            auto_applied.append(
                {
                    "yaml_id": yaml_id,
                    "field_name": fc.field_name,
                    "change_type": "added",
                    "old_value": None,
                    "new_value": fc.new_value,
                }
            )
            continue

        # ── Modified — split per property by enrichment ──────────────────
        if fc.change_type == "modified":
            enrichments = field_enrichments.get(fc.field_name, [])
            conflicted_props = [p for p in fc.changed_properties if p in enrichments]
            auto_apply_props = [p for p in fc.changed_properties if p not in enrichments]

            new_payload = fc.new_value or {}
            for prop in auto_apply_props:
                _apply_property_change(
                    current_raw,
                    fc.field_name,
                    prop,
                    new_payload.get(prop),
                    is_bronze,
                )
                auto_applied.append(
                    {
                        "yaml_id": yaml_id,
                        "field_name": fc.field_name,
                        "change_type": f"{prop}_changed",
                        "old_value": fc.old_value,
                        "new_value": fc.new_value,
                    }
                )

            if conflicted_props:
                # Keep "field_type_changed" for type conflicts (legacy UI
                # expectation); every other property uses "field_modified".
                ctype = "field_type_changed" if "type" in conflicted_props else "field_modified"
                conflicts.append(
                    {
                        "id": str(uuid.uuid4()),
                        "yaml_id": yaml_id,
                        "field_name": fc.field_name,
                        "conflict_type": ctype,
                        "sap_value": new_payload,
                        "current_value": _get_field_value(current_raw, fc.field_name, is_bronze)
                        or {},
                        "enriched_properties": conflicted_props,
                        "resolved": False,
                        "resolution": None,
                        "resolved_by": None,
                        "resolved_at": None,
                    }
                )

    return auto_applied, conflicts


# ── Mutators ────────────────────────────────────────────────────────────────


# The canonical Silver field key order — what first-ingest writes. Merge-added
# fields follow it too, so a merged file stays uniform (`name` first, never a
# trailing `name` after the payload props).
_SILVER_FIELD_KEY_ORDER: tuple[str, ...] = ("name", "source", "type", "description", "field_role")


def _add_field(raw: dict, field_name: str, sap_payload: dict, is_bronze: bool) -> None:
    # None values are never written: an absent key already means "not curated"
    # (SILVER_LAYER.md §4.1) and a literal empty key is the historical defect.
    payload = {
        k: v for k, v in (sap_payload if isinstance(sap_payload, dict) else {}).items()
        if v is not None
    }
    if is_bronze:
        fields = raw.setdefault("fields", {})
        fields[field_name] = payload
    else:
        fields_list = raw.get("fields") or []
        ordered: dict = {"name": field_name}
        for key in _SILVER_FIELD_KEY_ORDER[1:]:
            if key in payload:
                ordered[key] = payload.pop(key)
        ordered.update(payload)  # any remaining props keep their relative order
        fields_list.append(ordered)
        raw["fields"] = fields_list


def _remove_field(raw: dict, field_name: str, is_bronze: bool) -> None:
    if is_bronze:
        fields = raw.get("fields") or {}
        if isinstance(fields, dict):
            fields.pop(field_name, None)
    else:
        fields_list = raw.get("fields") or []
        for i, f in enumerate(fields_list):
            if isinstance(f, dict) and f.get("name") == field_name:
                fields_list.pop(i)
                break
        raw["fields"] = fields_list


def _apply_property_change(
    raw: dict,
    field_name: str,
    prop: str,
    new_value,
    is_bronze: bool,
) -> None:
    """Update a single property of an existing field without replacing the
    whole field dict. Used by the property-level auto-apply path so that
    SAP overwriting one property (e.g. description) does not blow away the
    admin's other in-field edits (alias, synonyms, etc.).
    """
    if is_bronze:
        fields = raw.setdefault("fields", {})
        target = fields.get(field_name)
        if isinstance(target, dict):
            target[prop] = new_value
    else:
        for f in raw.get("fields") or []:
            if isinstance(f, dict) and f.get("name") == field_name:
                f[prop] = new_value
                return


def _get_field_value(raw: dict, field_name: str, is_bronze: bool) -> dict | None:
    if is_bronze:
        return (raw.get("fields") or {}).get(field_name)
    else:
        for f in raw.get("fields") or []:
            if isinstance(f, dict) and f.get("name") == field_name:
                return f
    return None


# ── Entity-level (header) diff ──────────────────────────────────────────────
# A YAML carries top-level admin-curated properties (description, alias)
# that are NOT inside the fields list. SAP can change them too on a re-ingest.
# Same conflict-vs-auto-apply semantics as field-level: enriched property →
# conflict; non-enriched property → auto-apply onto the live YAML.


def entity_diff(baseline_entity: dict, new_entity: dict) -> list[str]:
    """Return the entity-level property names that differ between
    baseline and incoming SAP payload.

    Skips properties that are not present in the baseline — same
    "first-sighting" semantic as ``_diff_properties`` for fields. Handles
    both:
      * Pre-Pass-G-header baselines with no ``silver_entity`` /
        ``bronze_entities`` key at all (base == {}).
      * Partially populated baselines that lack a single tracked prop
        (e.g. ``{description: "X"}`` without ``alias``).
    """
    base = baseline_entity or {}
    inc = new_entity or {}
    return [p for p in ENTITY_LEVEL_TRACKED_PROPS if p in base and base.get(p) != inc.get(p)]


def process_entity_diff(
    changed_props: list[str],
    current_raw: dict,
    new_entity: dict,
    entity_enrichments: list[str],
    yaml_id: str,
) -> tuple[list[dict], list[dict]]:
    """Apply or conflict each changed entity-level property.

    Returns ``(auto_applied, conflicts)`` in the same shape as
    ``process_diff`` so the caller can fold them into the same audit
    trail. Conflicts carry ``field_name=ENTITY_LEVEL_SENTINEL`` and
    ``conflict_type="entity_modified"``.
    """
    auto_applied: list[dict] = []
    conflicts: list[dict] = []
    if not changed_props:
        return auto_applied, conflicts

    new = new_entity or {}
    conflicted_props = [p for p in changed_props if p in entity_enrichments]
    auto_apply_props = [p for p in changed_props if p not in entity_enrichments]

    for prop in auto_apply_props:
        old_value = current_raw.get(prop)
        current_raw[prop] = new.get(prop)
        auto_applied.append(
            {
                "yaml_id": yaml_id,
                "field_name": ENTITY_LEVEL_SENTINEL,
                "change_type": f"entity_{prop}_changed",
                "old_value": {prop: old_value},
                "new_value": {prop: new.get(prop)},
            }
        )

    if conflicted_props:
        # sap_value + current_value carry every entity-level tracked prop so
        # the resolution UI can show a per-property diff even when only one
        # of them is the actual conflict.
        sap_payload = {p: new.get(p) for p in ENTITY_LEVEL_TRACKED_PROPS}
        current_payload = {p: current_raw.get(p) for p in ENTITY_LEVEL_TRACKED_PROPS}
        conflicts.append(
            {
                "id": str(uuid.uuid4()),
                "yaml_id": yaml_id,
                "field_name": ENTITY_LEVEL_SENTINEL,
                "conflict_type": "entity_modified",
                "sap_value": sap_payload,
                "current_value": current_payload,
                "enriched_properties": conflicted_props,
                "resolved": False,
                "resolution": None,
                "resolved_by": None,
                "resolved_at": None,
            }
        )

    return auto_applied, conflicts


# ── Renames (same source, different published name) ─────────────────────────
# Under column naming mode `alias` an upstream edit to `alias_fldname` changes
# the PUBLISHED name of the same source column, which a name-keyed diff can only
# see as removed+added — losing the field's enrichments to a remove-conflict.
# `source` is the stable identity (raw SAP codes in every naming mode), so a
# removed+added pair sharing one source IS a rename and is treated as one.


@dataclass
class RenameOp:
    old_name: str
    new_name: str
    new_payload: dict


def reconcile_renames(diff: StructuralDiff) -> list[RenameOp]:
    """Collapse removed+added pairs that share a ``source`` into renames.

    Mutates ``diff.field_changes``: the ``removed`` half is dropped and the
    ``added`` half is kept (after the caller renames the live field, the
    added-reconcile path in :func:`process_diff` degrades it to a plain
    property diff). Silver only — Bronze fields carry no ``source``.
    """
    removed_by_source: dict[str, FieldChange] = {}
    for fc in diff.field_changes:
        src = (fc.old_value or {}).get("source") if fc.change_type == "removed" else None
        if src:
            removed_by_source.setdefault(str(src), fc)

    renames: list[RenameOp] = []
    consumed: set[int] = set()
    for fc in diff.field_changes:
        if fc.change_type != "added":
            continue
        src = str((fc.new_value or {}).get("source") or "")
        old_fc = removed_by_source.pop(src, None) if src else None
        if old_fc is not None:
            renames.append(RenameOp(old_fc.field_name, fc.field_name, fc.new_value or {}))
            consumed.add(id(old_fc))

    if consumed:
        diff.field_changes = [fc for fc in diff.field_changes if id(fc) not in consumed]
    return renames


def rename_field_in_raw(raw: dict, old_name: str, new_name: str) -> bool:
    """In-place rename of a Silver field, preserving every other property
    (synonyms, additivity, descriptions — the enrichments a remove+add would
    have destroyed). Returns True when the field was found."""
    for f in raw.get("fields") or []:
        if isinstance(f, dict) and f.get("name") == old_name:
            f["name"] = new_name
            return True
    return False


# ── Structure merge (composed_of / join_graph) ──────────────────────────────
# Membership follows the export (SAP is the lineage authority: a table it adds
# appears, a table it retires leaves); edge PROPERTIES (join_type, condition)
# merge 3-way against the baseline because the admin legitimately hand-fixes
# predicates (JoinConditionEditor). When both sides changed an edge property,
# the admin's version is KEPT and the divergence is reported in the audit
# trail — a conflict block would dead-lock re-ingests (the resolution UI has
# no structure renderer) — see REQ_CURATED_COLUMN_NAMING.md's merge notes.

STRUCTURE_SENTINEL = "__structure__"

_EDGE_PROPS: tuple[str, ...] = ("join_type", "condition")


def _edge_key(edge: dict) -> tuple:
    return (
        str(edge.get("left_table") or ""),
        str(edge.get("right_table") or ""),
        int(edge.get("sequence") or 0),
    )


def merge_structure(
    *,
    baseline_structure: dict | None,
    current_raw: dict,
    incoming: dict,
    yaml_id: str,
    defer_removals: bool = False,
) -> tuple[list[dict], bool]:
    """Merge ``composed_of`` + ``join_graph`` from the parsed export into the
    live YAML. Returns ``(audit_entries, changed)``.

    Rules:
      * additions (new bronze / new edge) — always applied; no baseline needed.
      * removals — applied only when the entry WAS in the baseline (SAP sent it
        before and stopped) so an admin-added entry survives; and skipped
        entirely when ``defer_removals`` (pending field-removed conflicts must
        resolve first, or the file would reference tables its fields still use).
      * edge props — 3-way: SAP changed + admin untouched → apply; both
        changed → admin wins, divergence audited; baseline missing the edge
        (first sighting after upgrade) → skip, the end-of-merge baseline
        rewrite catches up.
    """
    audit: list[dict] = []
    changed = False
    base = baseline_structure or {}

    def _note(change_type: str, old, new) -> None:
        audit.append(
            {
                "yaml_id": yaml_id,
                "field_name": STRUCTURE_SENTINEL,
                "change_type": change_type,
                "old_value": old,
                "new_value": new,
            }
        )

    # ── composed_of ──────────────────────────────────────────────────────────
    cur_composed = [str(c) for c in (current_raw.get("composed_of") or [])]
    inc_composed = [str(c) for c in (incoming.get("composed_of") or [])]
    base_composed = {str(c) for c in (base.get("composed_of") or [])}

    added_members = [c for c in inc_composed if c not in cur_composed]
    removed_members = (
        []
        if defer_removals
        else [c for c in cur_composed if c not in inc_composed and c in base_composed]
    )
    if added_members or removed_members:
        new_composed = [c for c in cur_composed if c not in removed_members] + added_members
        current_raw["composed_of"] = new_composed
        changed = True
        _note("composed_of_changed", {"composed_of": cur_composed}, {"composed_of": new_composed})

    # ── join_graph ───────────────────────────────────────────────────────────
    cur_edges = [e for e in (current_raw.get("join_graph") or []) if isinstance(e, dict)]
    inc_edges = [e for e in (incoming.get("join_graph") or []) if isinstance(e, dict)]
    base_edges = {
        _edge_key(e): e for e in (base.get("join_graph") or []) if isinstance(e, dict)
    }
    cur_by_key = {_edge_key(e): e for e in cur_edges}
    inc_by_key = {_edge_key(e): e for e in inc_edges}

    new_graph: list[dict] = []
    for edge in cur_edges:
        key = _edge_key(edge)
        if key not in inc_by_key:
            # Removal candidate — only when SAP previously sent this edge.
            if not defer_removals and key in base_edges:
                changed = True
                _note("join_edge_removed", dict(edge), None)
                continue
            new_graph.append(edge)
            continue
        # Common edge — 3-way per property.
        inc_edge, base_edge = inc_by_key[key], base_edges.get(key)
        for prop in _EDGE_PROPS:
            if base_edge is None or prop not in base_edge:
                continue  # first sighting — snapshot catches up at merge end
            if base_edge.get(prop) == inc_edge.get(prop):
                continue  # SAP did not change it
            if edge.get(prop) == base_edge.get(prop):
                _note(
                    f"join_edge_{prop}_changed",
                    {**{k: edge.get(k) for k in ("left_table", "right_table")}, prop: edge.get(prop)},
                    {prop: inc_edge.get(prop)},
                )
                edge[prop] = inc_edge.get(prop)
                changed = True
            else:
                # Both changed — admin wins, divergence surfaced (not silent).
                _note(
                    f"join_edge_{prop}_divergence_kept",
                    {prop: edge.get(prop)},
                    {prop: inc_edge.get(prop)},
                )
        new_graph.append(edge)

    for key, inc_edge in inc_by_key.items():
        if key not in cur_by_key:
            new_graph.append(dict(inc_edge))
            changed = True
            _note("join_edge_added", None, dict(inc_edge))

    if changed:
        current_raw["join_graph"] = new_graph

    return audit, changed


# ── Normalisers (kept for callers that consume the helpers directly) ────────


def normalise_bronze_fields(raw: dict) -> dict[str, dict]:
    """Convert Bronze fields dict to {name: field_dict}."""
    return {k: v for k, v in (raw.get("fields") or {}).items() if isinstance(v, dict)}


def normalise_silver_fields(raw: dict) -> dict[str, dict]:
    """Convert Silver/Gold fields list to {name: field_dict}."""
    result = {}
    for f in raw.get("fields") or []:
        if isinstance(f, dict) and "name" in f:
            result[f["name"]] = f
    return result

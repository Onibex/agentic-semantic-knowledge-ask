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
SILVER_FIELD_TRACKED_PROPS: tuple[str, ...] = (
    "type",
    "source",
    "description",
    "field_role",
    "aggregation_behavior",
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


def _add_field(raw: dict, field_name: str, sap_payload: dict, is_bronze: bool) -> None:
    payload = dict(sap_payload) if isinstance(sap_payload, dict) else {}
    if is_bronze:
        fields = raw.setdefault("fields", {})
        fields[field_name] = payload
    else:
        fields_list = raw.get("fields") or []
        payload["name"] = field_name  # safety belt
        fields_list.append(payload)
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

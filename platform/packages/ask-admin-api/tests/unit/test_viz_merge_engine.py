"""Unit tests for the SAP JSON merge engine (Pass G — property-level diff).

The engine compares baseline → SAP payload property by property. Per-field
changes carry a ``changed_properties`` list. Each changed property is then
either auto-applied OR raised as a conflict depending on whether the admin
enriched that specific property.
"""

from __future__ import annotations

from ask_admin_api.application.merge_engine import (
    FieldChange,
    StructuralDiff,
    normalise_bronze_fields,
    normalise_silver_fields,
    process_diff,
    structural_diff,
)

# ── structural_diff ────────────────────────────────────────────────────────────


def test_structural_diff_detects_added():
    diff = structural_diff(
        "silver_x",
        baseline_fields={},
        new_fields={"net_value": {"type": "P15"}},
    )
    fc = diff.field_changes[0]
    assert fc.field_name == "net_value"
    assert fc.change_type == "added"


def test_structural_diff_detects_removed():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"net_value": {"type": "P15"}},
        new_fields={},
    )
    fc = diff.field_changes[0]
    assert fc.change_type == "removed"


def test_structural_diff_detects_type_change_via_modified():
    """In Pass G a type change is modified + changed_properties=['type']."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={"net_value": {"type": "P15"}},
        new_fields={"net_value": {"type": "P31"}},
    )
    fc = diff.field_changes[0]
    assert fc.change_type == "modified"
    assert fc.changed_properties == ["type"]


def test_structural_diff_detects_description_change_via_modified():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"client": {"type": "C3", "description": "Old desc"}},
        new_fields={"client": {"type": "C3", "description": "New desc from SAP"}},
    )
    fc = diff.field_changes[0]
    assert fc.change_type == "modified"
    assert fc.changed_properties == ["description"]


def test_structural_diff_multi_property_modification():
    """When BOTH type and description differ, the modified change carries
    both in changed_properties — no information is lost the way the old
    single-change_type cascade dropped one side."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "description": "Old"}},
        new_fields={"f": {"type": "C5", "description": "New"}},
    )
    fc = diff.field_changes[0]
    assert fc.change_type == "modified"
    assert set(fc.changed_properties) == {"type", "description"}


def test_structural_diff_detects_unchanged():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"net_value": {"type": "P15"}},
        new_fields={"net_value": {"type": "P15"}},
    )
    assert diff.field_changes[0].change_type == "unchanged"


def test_structural_diff_silver_tracks_field_role_and_agg():
    """Pass G full: field_role and aggregation_behavior are now part of the
    Silver diff — SAP can rename them, conflicts fire if enriched."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={
            "f": {"type": "C3", "field_role": "dimension", "aggregation_behavior": "none"}
        },
        new_fields={
            "f": {"type": "C3", "field_role": "identifier", "aggregation_behavior": "none"}
        },
    )
    fc = diff.field_changes[0]
    assert fc.change_type == "modified"
    assert fc.changed_properties == ["field_role"]


def test_structural_diff_bronze_tracks_alias():
    """Pass G full: alias is tracked for Bronces (it's a SAP-supplied prop
    there, unlike Silvers where alias is admin-only)."""
    diff = structural_diff(
        "bronze_x",
        baseline_fields={"VBELN": {"type": "C10", "alias": "old_alias"}},
        new_fields={"VBELN": {"type": "C10", "alias": "new_alias"}},
        is_bronze=True,
    )
    fc = diff.field_changes[0]
    assert fc.change_type == "modified"
    assert fc.changed_properties == ["alias"]


def test_structural_diff_mixed_changeset():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"a": {"type": "C10"}, "b": {"type": "P15"}, "c": {"type": "D8"}},
        new_fields={"a": {"type": "C10"}, "b": {"type": "P31"}, "d": {"type": "N4"}},
    )
    by_name = {fc.field_name: fc.change_type for fc in diff.field_changes}
    assert by_name == {
        "a": "unchanged",
        "b": "modified",
        "c": "removed",
        "d": "added",
    }


# ── process_diff: auto-apply (no enrichments) ────────────────────────────────────


def test_process_diff_autoapplies_non_enriched_silver_added():
    diff = StructuralDiff(
        "silver_x",
        [FieldChange("new_col", "added", None, {"type": "C10"})],
    )
    raw = {"fields": [{"name": "existing", "type": "P15"}]}

    auto, conflicts = process_diff(
        diff, raw, field_enrichments={}, yaml_id="silver_x", is_bronze=False
    )

    assert conflicts == []
    assert len(auto) == 1
    assert auto[0]["change_type"] == "added"
    names = {f["name"] for f in raw["fields"]}
    assert names == {"existing", "new_col"}


def test_process_diff_autoapplies_non_enriched_bronze_type_change_preserves_alias():
    """Property-level auto-apply MERGES SAP's value, so admin-curated
    siblings (here: alias was already non-enriched but present) survive."""
    diff = StructuralDiff(
        "bronze_x",
        [
            FieldChange(
                "NETWR", "modified", {"type": "P15"}, {"type": "P31"}, changed_properties=["type"]
            )
        ],
    )
    raw = {"fields": {"NETWR": {"type": "P15", "alias": "net_value"}}}

    auto, conflicts = process_diff(
        diff, raw, field_enrichments={}, yaml_id="bronze_x", is_bronze=True
    )

    assert conflicts == []
    assert len(auto) == 1
    # type updated; alias preserved.
    assert raw["fields"]["NETWR"] == {"type": "P31", "alias": "net_value"}


def test_process_diff_autoapplies_removal_when_not_enriched():
    diff = StructuralDiff(
        "bronze_x",
        [FieldChange("OBSOLETE", "removed", {"type": "C1"}, None)],
    )
    raw = {"fields": {"OBSOLETE": {"type": "C1"}, "KEEP": {"type": "C2"}}}

    auto, conflicts = process_diff(
        diff, raw, field_enrichments={}, yaml_id="bronze_x", is_bronze=True
    )

    assert conflicts == []
    assert "OBSOLETE" not in raw["fields"]
    assert "KEEP" in raw["fields"]


def test_process_diff_skips_unchanged():
    diff = StructuralDiff(
        "silver_x",
        [FieldChange("net_value", "unchanged", {"type": "P15"}, {"type": "P15"})],
    )
    raw = {"fields": [{"name": "net_value", "type": "P15"}]}

    auto, conflicts = process_diff(
        diff, raw, field_enrichments={}, yaml_id="silver_x", is_bronze=False
    )

    assert auto == []
    assert conflicts == []


# ── process_diff: conflicts (enriched fields) ────────────────────────────────────


def test_process_diff_enriched_type_change_is_conflict():
    diff = StructuralDiff(
        "silver_x",
        [
            FieldChange(
                "net_value",
                "modified",
                {"type": "P15"},
                {"type": "P31"},
                changed_properties=["type"],
            )
        ],
    )
    raw = {"fields": [{"name": "net_value", "type": "P15", "field_role": "measure"}]}
    # Field is enriched on field_role; the change is on type → still
    # produces a conflict because "type" IS in field_enrichments (admin
    # touched something on the field). Wait — for type to conflict the
    # enrichment must list a touched-by-admin property; the merge engine
    # only conflicts if the CHANGED property is in the enrichment list.
    # For backward-compat with old tests we mark `type` as enriched here:
    enrichments = {"net_value": ["type"]}

    auto, conflicts = process_diff(diff, raw, enrichments, yaml_id="silver_x", is_bronze=False)

    assert auto == []
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["conflict_type"] == "field_type_changed"
    assert c["enriched_properties"] == ["type"]


def test_process_diff_enriched_removed_is_conflict():
    diff = StructuralDiff(
        "silver_x",
        [FieldChange("net_value", "removed", {"type": "P15"}, None)],
    )
    raw = {"fields": [{"name": "net_value", "type": "P15", "description": "x"}]}
    enrichments = {"net_value": ["description"]}

    auto, conflicts = process_diff(diff, raw, enrichments, yaml_id="silver_x", is_bronze=False)

    assert auto == []
    assert len(conflicts) == 1
    assert conflicts[0]["conflict_type"] == "field_removed"
    assert any(f["name"] == "net_value" for f in raw["fields"])


def test_process_diff_each_conflict_gets_unique_id():
    diff = StructuralDiff(
        "silver_x",
        [
            FieldChange(
                "a", "modified", {"type": "C1"}, {"type": "C2"}, changed_properties=["type"]
            ),
            FieldChange(
                "b", "modified", {"type": "C1"}, {"type": "C2"}, changed_properties=["type"]
            ),
        ],
    )
    raw = {"fields": [{"name": "a", "type": "C1"}, {"name": "b", "type": "C1"}]}
    enrichments = {"a": ["type"], "b": ["type"]}

    _, conflicts = process_diff(diff, raw, enrichments, yaml_id="silver_x", is_bronze=False)

    ids = {c["id"] for c in conflicts}
    assert len(ids) == 2


# ── added-reconciliation: baseline gap vs genuine new vs hidden type-change ─────


def test_first_ingest_enriched_field_same_shape_is_noop():
    """Empty baseline marks every field 'added'; an enriched field whose
    SAP-supplied tracked props match the workspace value is a baseline gap,
    not a conflict. SAP would supply field_role in a real ingest (SilverField
    requires it) so we include it here too."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={},
        new_fields={"net_value": {"type": "P15", "description": "same", "field_role": "measure"}},
    )
    raw = {
        "fields": [
            {"name": "net_value", "type": "P15", "description": "same", "field_role": "measure"}
        ]
    }
    enrichments = {"net_value": ["field_role"]}

    auto, conflicts = process_diff(diff, raw, enrichments, "silver_x", is_bronze=False)
    assert conflicts == []
    assert auto == []
    assert len(raw["fields"]) == 1


def test_first_ingest_genuinely_new_field_is_autoapplied_without_duplicate():
    diff = structural_diff(
        "silver_x",
        baseline_fields={},
        new_fields={
            "net_value": {"type": "P15"},
            "brand_new": {"type": "C4"},
        },
    )
    raw = {"fields": [{"name": "net_value", "type": "P15"}]}

    auto, conflicts = process_diff(
        diff, raw, field_enrichments={}, yaml_id="silver_x", is_bronze=False
    )

    assert conflicts == []
    names = [f["name"] for f in raw["fields"]]
    assert sorted(names) == ["brand_new", "net_value"]
    assert names.count("net_value") == 1  # existing field not duplicated
    assert {a["field_name"] for a in auto} == {"brand_new"}


def test_stale_baseline_existing_field_diff_type_enriched_is_conflict():
    """Stale baseline + workspace's type differs from SAP → real type
    change. SAP keeps the field_role unchanged, so the only diff is on
    type, which is enriched → conflict."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={},
        new_fields={"net_value": {"type": "P31", "field_role": "measure"}},
    )
    raw = {"fields": [{"name": "net_value", "type": "P15", "field_role": "measure"}]}
    enrichments = {"net_value": ["type"]}

    auto, conflicts = process_diff(diff, raw, enrichments, "silver_x", is_bronze=False)

    assert auto == []
    assert len(conflicts) == 1
    assert conflicts[0]["conflict_type"] == "field_type_changed"


def test_first_ingest_bronze_existing_field_same_shape_is_noop():
    """Same as the Silver test but for Bronces; SAP includes alias since
    BronzeField requires it (parser always populates)."""
    diff = structural_diff(
        "bronze_x",
        baseline_fields={},
        new_fields={"NETWR": {"type": "P15", "alias": "net_value"}},
        is_bronze=True,
    )
    raw = {"fields": {"NETWR": {"type": "P15", "alias": "net_value"}}}
    enrichments = {"NETWR": ["alias"]}

    auto, conflicts = process_diff(diff, raw, enrichments, "bronze_x", is_bronze=True)
    assert conflicts == []
    assert auto == []
    assert raw["fields"]["NETWR"]["alias"] == "net_value"


# ── description-level paths (Pass G MVP — still relevant under property model)


def test_process_diff_description_change_autoapplied_when_not_enriched():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "description": "Old"}},
        new_fields={"f": {"type": "C3", "description": "New from SAP"}},
    )
    raw = {"fields": [{"name": "f", "type": "C3", "description": "Old", "field_role": "dimension"}]}
    auto, conflicts = process_diff(diff, raw, {}, "silver_x", is_bronze=False)
    assert conflicts == []
    assert len(auto) == 1
    assert auto[0]["change_type"] == "description_changed"
    f = raw["fields"][0]
    assert f["description"] == "New from SAP"
    assert f["field_role"] == "dimension"
    assert f["type"] == "C3"


def test_process_diff_description_change_is_conflict_when_enriched():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"client": {"type": "C3", "description": "Old SAP desc"}},
        new_fields={"client": {"type": "C3", "description": "Newer SAP desc"}},
    )
    raw = {"fields": [{"name": "client", "type": "C3", "description": "Admin-enriched"}]}
    enrichments = {"client": ["description"]}
    auto, conflicts = process_diff(diff, raw, enrichments, "silver_x", is_bronze=False)
    assert auto == []
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["conflict_type"] == "field_modified"
    assert c["enriched_properties"] == ["description"]
    assert c["sap_value"]["description"] == "Newer SAP desc"
    assert c["current_value"]["description"] == "Admin-enriched"
    assert raw["fields"][0]["description"] == "Admin-enriched"


def test_process_diff_description_change_autoapplied_when_enriched_on_other_property():
    """A field enriched on alias (not description) → SAP description update
    is safe to auto-apply because description was never touched by admin."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "description": "Old", "source": "T.F"}},
        new_fields={"f": {"type": "C3", "description": "New", "source": "T.F"}},
    )
    raw = {"fields": [{"name": "f", "type": "C3", "description": "Old", "alias": "my_alias"}]}
    enrichments = {"f": ["alias"]}
    auto, conflicts = process_diff(diff, raw, enrichments, "silver_x", is_bronze=False)
    assert conflicts == []
    assert len(auto) == 1
    f = raw["fields"][0]
    assert f["description"] == "New"
    assert f["alias"] == "my_alias"


def test_process_diff_description_change_bronze_autoapply():
    diff = structural_diff(
        "bronze_x",
        baseline_fields={"MANDT": {"type": "C3", "description": "Client"}},
        new_fields={"MANDT": {"type": "C3", "description": "Client or mandt"}},
        is_bronze=True,
    )
    raw = {
        "fields": {
            "MANDT": {"type": "C3", "alias": "client", "description": "Client", "key_field": True}
        }
    }
    auto, conflicts = process_diff(diff, raw, {}, "bronze_x", is_bronze=True)
    assert conflicts == []
    assert len(auto) == 1
    assert raw["fields"]["MANDT"]["description"] == "Client or mandt"
    assert raw["fields"]["MANDT"]["alias"] == "client"
    assert raw["fields"]["MANDT"]["key_field"] is True


# ── Pass G full coverage: alias / field_role / aggregation_behavior ────────────


def test_process_diff_field_role_change_auto_apply_when_not_enriched():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "field_role": "dimension"}},
        new_fields={"f": {"type": "C3", "field_role": "attribute"}},
    )
    raw = {"fields": [{"name": "f", "type": "C3", "field_role": "dimension"}]}
    auto, conflicts = process_diff(diff, raw, {}, "silver_x", is_bronze=False)
    assert conflicts == []
    assert len(auto) == 1
    assert raw["fields"][0]["field_role"] == "attribute"


def test_process_diff_field_role_change_is_conflict_when_enriched():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "field_role": "dimension"}},
        new_fields={"f": {"type": "C3", "field_role": "identifier"}},
    )
    raw = {"fields": [{"name": "f", "type": "C3", "field_role": "dimension"}]}
    enrichments = {"f": ["field_role"]}
    auto, conflicts = process_diff(diff, raw, enrichments, "silver_x", is_bronze=False)
    assert auto == []
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["conflict_type"] == "field_modified"
    assert c["enriched_properties"] == ["field_role"]
    # NOT mutated until resolved
    assert raw["fields"][0]["field_role"] == "dimension"


def test_process_diff_bronze_alias_change_is_conflict_when_enriched():
    diff = structural_diff(
        "bronze_x",
        baseline_fields={"VBELN": {"type": "C10", "alias": "doc"}},
        new_fields={"VBELN": {"type": "C10", "alias": "sales_doc"}},
        is_bronze=True,
    )
    raw = {"fields": {"VBELN": {"type": "C10", "alias": "doc_curated"}}}
    enrichments = {"VBELN": ["alias"]}
    auto, conflicts = process_diff(diff, raw, enrichments, "bronze_x", is_bronze=True)
    assert auto == []
    assert len(conflicts) == 1
    assert conflicts[0]["enriched_properties"] == ["alias"]


def test_process_diff_mixed_some_enriched_some_not():
    """A single field changes BOTH type (enriched) and description (not).
    The type change goes to conflicts, the description goes to auto_applied
    — the engine splits per-property by enrichment instead of bundling all
    or nothing into one bucket."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "description": "Old"}},
        new_fields={"f": {"type": "C5", "description": "New"}},
    )
    raw = {"fields": [{"name": "f", "type": "C3", "description": "Old"}]}
    enrichments = {"f": ["type"]}  # only type is enriched
    auto, conflicts = process_diff(diff, raw, enrichments, "silver_x", is_bronze=False)
    # description auto-applied
    assert any(a["change_type"] == "description_changed" for a in auto)
    assert raw["fields"][0]["description"] == "New"
    # type-change goes to conflict
    assert len(conflicts) == 1
    assert conflicts[0]["conflict_type"] == "field_type_changed"
    assert conflicts[0]["enriched_properties"] == ["type"]
    # type itself NOT applied yet — pending resolution.
    assert raw["fields"][0]["type"] == "C3"


# ── existing apply / safety regression tests ──────────────────────────────────


def test_apply_field_change_adds_silver_field_with_name_key():
    diff = structural_diff(
        "silver_x",
        baseline_fields={},
        new_fields={"client": {"type": "C3", "source": "AFKO.MANDT", "description": "Client"}},
    )
    raw = {"fields": []}
    auto, conflicts = process_diff(diff, raw, {}, "silver_x", is_bronze=False)
    assert len(auto) == 1
    assert conflicts == []
    assert len(raw["fields"]) == 1
    appended = raw["fields"][0]
    assert appended["name"] == "client"
    assert appended["type"] == "C3"
    assert appended["source"] == "AFKO.MANDT"
    assert appended["description"] == "Client"


def test_apply_field_change_type_change_preserves_silver_field_name_and_role():
    """Auto-applying a type change MERGES SAP's payload onto the existing
    field, preserving name + field_role + alias + synonyms etc."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={"client": {"type": "C3", "source": "AFKO.MANDT", "description": "Client"}},
        new_fields={"client": {"type": "C5", "source": "AFKO.MANDT", "description": "Client"}},
    )
    raw = {
        "fields": [
            {
                "name": "client",
                "type": "C3",
                "source": "AFKO.MANDT",
                "description": "Client",
                "field_role": "identifier",
                "alias": "mandt",
                "synonyms": ["customer_no"],
            }
        ]
    }
    auto, conflicts = process_diff(diff, raw, {}, "silver_x", is_bronze=False)
    assert conflicts == []
    assert len(auto) == 1
    f = raw["fields"][0]
    assert f["type"] == "C5"
    assert f["name"] == "client"
    assert f["field_role"] == "identifier"
    assert f["alias"] == "mandt"
    assert f["synonyms"] == ["customer_no"]


def test_apply_field_change_tolerates_silver_entries_without_name():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"good": {"type": "P15", "description": "old"}},
        new_fields={"good": {"type": "DEC", "description": "old"}},
    )
    raw = {
        "fields": [
            {"some_other_key": "no name here"},
            {"name": "good", "type": "P15", "description": "old"},
        ]
    }
    auto, conflicts = process_diff(diff, raw, {}, "silver_x", is_bronze=False)
    assert conflicts == []
    assert len(auto) == 1
    assert raw["fields"][0] == {"some_other_key": "no name here"}
    assert raw["fields"][1]["type"] == "DEC"


def test_process_diff_description_unchanged_skipped():
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "description": "same"}},
        new_fields={"f": {"type": "C3", "description": "same"}},
    )
    raw = {"fields": [{"name": "f", "type": "C3", "description": "same"}]}
    auto, conflicts = process_diff(diff, raw, {}, "silver_x", is_bronze=False)
    assert auto == []
    assert conflicts == []


# ── Pass G header-level: entity description / alias ───────────────────────────


from ask_admin_api.application.merge_engine import (
    ENTITY_LEVEL_SENTINEL,
    entity_diff,
    process_entity_diff,
)


def test_entity_diff_detects_description_change():
    diff = entity_diff(
        {"description": "Old entity desc", "alias": "x"},
        {"description": "New entity desc", "alias": "x"},
    )
    assert diff == ["description"]


def test_entity_diff_detects_no_change():
    diff = entity_diff(
        {"description": "same", "alias": "x"},
        {"description": "same", "alias": "x"},
    )
    assert diff == []


def test_entity_diff_detects_alias_change():
    diff = entity_diff(
        {"description": "same", "alias": "old"},
        {"description": "same", "alias": "new"},
    )
    assert diff == ["alias"]


def test_entity_diff_empty_baseline_is_noop():
    """Pre-Pass-G-header baselines have no silver_entity / bronze_entities
    key. The first ingest after upgrade must NOT fabricate spurious diffs
    against the empty baseline — same migration semantics as the field-
    level Bug #2 reconciliation."""
    diff = entity_diff({}, {"description": "anything", "alias": "x"})
    assert diff == []


def test_entity_diff_partial_baseline_skips_missing_props():
    """Baseline that has description but lacks alias must NOT flag alias
    as 'changed' on the first ingest after upgrade — alias just got added
    to the tracked set. Mirrors _diff_properties for fields."""
    diff = entity_diff(
        {"description": "same"},  # alias missing
        {"description": "same", "alias": "new_alias"},
    )
    assert diff == []


def test_structural_diff_skips_props_not_in_baseline():
    """Field-level analog of the entity migration: when the baseline pre-
    dates Pass G full and lacks field_role / aggregation_behavior, the
    diff must NOT report every field as modified just because SAP now
    supplies those props."""
    diff = structural_diff(
        "silver_x",
        baseline_fields={"f": {"type": "C3", "source": "T.F", "description": "X"}},
        # No field_role / aggregation_behavior in baseline ↑
        new_fields={
            "f": {
                "type": "C3",
                "source": "T.F",
                "description": "X",
                "field_role": "dimension",
                "aggregation_behavior": "none",
            },
        },
    )
    assert diff.field_changes[0].change_type == "unchanged"


def test_process_entity_diff_autoapplies_non_enriched_description():
    """SAP changes the entity description; admin never touched it →
    auto-apply, no conflict, YAML's top-level description updates."""
    raw = {"description": "Old", "alias": "x"}
    auto, conflicts = process_entity_diff(
        changed_props=["description"],
        current_raw=raw,
        new_entity={"description": "New from SAP", "alias": "x"},
        entity_enrichments=[],  # nothing enriched
        yaml_id="silver_x",
    )
    assert conflicts == []
    assert len(auto) == 1
    assert auto[0]["field_name"] == ENTITY_LEVEL_SENTINEL
    assert auto[0]["change_type"] == "entity_description_changed"
    assert raw["description"] == "New from SAP"


def test_process_entity_diff_conflicts_when_description_enriched():
    """SAP changes the entity description but the admin previously edited it
    → conflict (entity_modified). The top-level description is NOT
    overwritten while the conflict is pending."""
    raw = {"description": "Admin-curated", "alias": "x"}
    auto, conflicts = process_entity_diff(
        changed_props=["description"],
        current_raw=raw,
        new_entity={"description": "Newer SAP desc", "alias": "x"},
        entity_enrichments=["description"],
        yaml_id="silver_x",
    )
    assert auto == []
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["conflict_type"] == "entity_modified"
    assert c["field_name"] == ENTITY_LEVEL_SENTINEL
    assert c["sap_value"]["description"] == "Newer SAP desc"
    assert c["current_value"]["description"] == "Admin-curated"
    assert c["enriched_properties"] == ["description"]
    # Not yet applied — pending resolution.
    assert raw["description"] == "Admin-curated"


def test_process_entity_diff_splits_per_property():
    """Both description AND alias differ; description is enriched, alias
    is not. The engine splits: description → conflict, alias → auto-apply."""
    raw = {"description": "Admin desc", "alias": "old_alias"}
    auto, conflicts = process_entity_diff(
        changed_props=["description", "alias"],
        current_raw=raw,
        new_entity={"description": "SAP desc", "alias": "new_alias"},
        entity_enrichments=["description"],
        yaml_id="silver_x",
    )
    # alias was auto-applied
    assert any(a["change_type"] == "entity_alias_changed" for a in auto)
    assert raw["alias"] == "new_alias"
    # description went to conflict
    assert len(conflicts) == 1
    assert conflicts[0]["enriched_properties"] == ["description"]
    # description still untouched (pending resolution)
    assert raw["description"] == "Admin desc"


# ── normalisers ──────────────────────────────────────────────────────────────────


def test_normalise_bronze_fields_keeps_only_dict_values():
    raw = {"fields": {"A": {"type": "C1"}, "B": "not-a-dict", "C": {"type": "P15"}}}
    out = normalise_bronze_fields(raw)
    assert set(out) == {"A", "C"}


def test_normalise_bronze_fields_empty():
    assert normalise_bronze_fields({}) == {}


def test_normalise_silver_fields_keys_by_name():
    raw = {"fields": [{"name": "a", "type": "C1"}, {"type": "no-name"}, {"name": "b"}]}
    out = normalise_silver_fields(raw)
    assert set(out) == {"a", "b"}
    assert out["a"] == {"name": "a", "type": "C1"}


def test_normalise_silver_fields_empty():
    assert normalise_silver_fields({}) == {}

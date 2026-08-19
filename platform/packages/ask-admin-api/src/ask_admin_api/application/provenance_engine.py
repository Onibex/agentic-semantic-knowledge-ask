# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Compute and update _meta.field_enrichments after each save.

Rule: an enrichable property is tracked if its value is non-None and non-empty.
Enrichable properties: alias, description, field_role, aggregation_behavior,
additivity, non_additive_over.
SAP-structural (never tracked): type, source, key_field, primary_key.
"""

from __future__ import annotations

ENRICHABLE_PROPS = {
    "alias",
    "description",
    "field_role",
    "aggregation_behavior",
    # Axis 2 of the aggregation contract (REQ_ADDITIVITY_CONTRACT.md). Curator
    # judgement that SAP cannot supply, so it is enrichment — and it must be
    # conflict-protected: a re-ingest silently reverting a `semi_additive` back
    # to the additive default is exactly the double-count this contract exists
    # to prevent.
    "additivity",
    "non_additive_over",
    "synonyms",
    "normalization_flag",
}


def compute_enrichments_bronze(
    fields_dict: dict,
    existing: dict[str, list[str]],
    updated: set[str],
) -> dict[str, list[str]]:
    """Recompute field_enrichments for Bronze YAMLs (fields keyed by field name).

    Only fields in ``updated`` are recomputed; the rest keep their existing entries.
    """
    result = dict(existing)
    for fname in updated:
        fdata = fields_dict.get(fname)
        if not isinstance(fdata, dict):
            result.pop(fname, None)
            continue
        enriched = [p for p in ENRICHABLE_PROPS if fdata.get(p) not in (None, "", [])]
        if enriched:
            result[fname] = enriched
        else:
            result.pop(fname, None)
    return result


def compute_enrichments_silver(
    fields_list: list,
    existing: dict[str, list[str]],
    updated: set[str],
) -> dict[str, list[str]]:
    """Recompute field_enrichments for Silver/Gold YAMLs (fields as list of dicts with 'name').

    Only fields in ``updated`` are recomputed; the rest keep their existing entries.
    """
    result = dict(existing)
    by_name: dict[str, dict] = {
        f["name"]: f for f in fields_list if isinstance(f, dict) and "name" in f
    }
    for fname in updated:
        fdata = by_name.get(fname)
        if not isinstance(fdata, dict):
            result.pop(fname, None)
            continue
        enriched = [p for p in ENRICHABLE_PROPS if fdata.get(p) not in (None, "", [])]
        if enriched:
            result[fname] = enriched
        else:
            result.pop(fname, None)
    return result

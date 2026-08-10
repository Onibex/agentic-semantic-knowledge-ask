"""
Unit tests for Smart mode entity selection mechanics.

Validates:
1. CatalogService._doc_to_entry — module normalization (list and comma-string)
2. CatalogService.render_as_prompt_context — Gold entity grouping and visibility
3. EntitySelectorService system prompt — "prefer Gold" rule present
4. Catalog rendered text — Gold and Silver are distinguishable by layer tag
"""

from __future__ import annotations

from ask_intent_resolution.smart.application.catalog_service import CatalogService
from ask_intent_resolution.smart.application.entity_selector import _SYSTEM_RULES
from ask_intent_resolution.smart.domain.catalog import Catalog

# ── Fixtures ──────────────────────────────────────────────────────────────────

GOLD_DOC_COMMA_MODULE = {
    "id": "gold_s4h_open_order_tracker",
    "name": "open_order_tracker",
    "layer": "gold",
    "module": "SD,MM",  # saved as comma-string by save_gold_node
    "entity_role": "fact",
    "description": "Denormalized sales order item snapshot for OTC analytics.",
    "business_process": "OTC",
}

GOLD_DOC_LIST_MODULE = {
    "id": "gold_s4h_open_order_tracker",
    "name": "open_order_tracker",
    "layer": "gold",
    "module": ["SD", "MM"],  # raw list (edge case if OpenSearch returns array)
    "entity_role": "fact",
    "description": "Denormalized sales order item snapshot for OTC analytics.",
    "business_process": "OTC",
}

SILVER_DOC = {
    "id": "silver_s4h_sd_sales_order",
    "name": "sales_order",
    "layer": "silver",
    "module": "SD",
    "entity_role": "fact",
    "description": "Raw sales order transactional data from VBAK/VBAP. "
    "Use for historical order analysis and document flow tracing.",
    "business_process": None,
}


def _make_service() -> CatalogService:
    """CatalogService instance with no real OpenSearch dependency."""
    svc = CatalogService.__new__(CatalogService)
    svc._repo = None
    svc._cache = None
    return svc


# ── 1. Module normalization ────────────────────────────────────────────────────


class TestDocToEntryModuleNormalization:
    def test_comma_string_module_takes_first(self):
        svc = _make_service()
        entry = svc._doc_to_entry(GOLD_DOC_COMMA_MODULE)
        assert entry is not None, "Gold entity must not be dropped"
        assert entry.module == "SD", f"Expected 'SD', got {entry.module!r}"

    def test_list_module_takes_first(self):
        svc = _make_service()
        entry = svc._doc_to_entry(GOLD_DOC_LIST_MODULE)
        assert entry is not None, "Gold entity must not be dropped"
        assert entry.module == "SD", f"Expected 'SD', got {entry.module!r}"

    def test_silver_single_module_unchanged(self):
        svc = _make_service()
        entry = svc._doc_to_entry(SILVER_DOC)
        assert entry is not None
        assert entry.module == "SD"

    def test_gold_layer_preserved(self):
        svc = _make_service()
        entry = svc._doc_to_entry(GOLD_DOC_COMMA_MODULE)
        assert entry is not None
        assert entry.layer == "gold"

    def test_gold_entity_role_preserved(self):
        svc = _make_service()
        entry = svc._doc_to_entry(GOLD_DOC_COMMA_MODULE)
        assert entry is not None
        assert entry.entity_role == "fact"


# ── 2. Catalog grouping ────────────────────────────────────────────────────────


class TestCatalogGrouping:
    def _build_catalog(self, gold_doc: dict) -> Catalog:
        svc = _make_service()
        gold = svc._doc_to_entry(gold_doc)
        silver = svc._doc_to_entry(SILVER_DOC)
        assert gold is not None
        assert silver is not None
        return Catalog(entries=[gold, silver])

    def test_gold_grouping_key_is_sd_not_comma_string(self):
        """Gold with module='SD,MM' must group under 'SD', not 'SD,MM'."""
        svc = _make_service()
        entry = svc._doc_to_entry(GOLD_DOC_COMMA_MODULE)
        assert entry is not None
        assert entry.grouping_key == "SD", (
            f"Gold entity appears under '{entry.grouping_key}' — "
            "expected 'SD'. It would be invisible next to Silver entities."
        )

    def test_gold_and_silver_share_same_group(self):
        """Both entities must land in the same 'SD' group so the LLM sees them together."""
        catalog = self._build_catalog(GOLD_DOC_COMMA_MODULE)
        keys = {e.grouping_key for e in catalog.entries}
        assert keys == {"SD"}, f"Groups found: {keys}. Gold and Silver must share the same group."

    def test_gold_visible_in_rendered_catalog(self):
        svc = _make_service()
        catalog = self._build_catalog(GOLD_DOC_COMMA_MODULE)
        rendered = svc.render_as_prompt_context(catalog)
        assert "gold_s4h_open_order_tracker" in rendered, (
            "Gold entity ID must appear in the catalog rendered for the LLM"
        )

    def test_silver_visible_in_rendered_catalog(self):
        svc = _make_service()
        catalog = self._build_catalog(GOLD_DOC_COMMA_MODULE)
        rendered = svc.render_as_prompt_context(catalog)
        assert "silver_s4h_sd_sales_order" in rendered, (
            "Silver entity ID must appear in the catalog rendered for the LLM"
        )

    def test_layer_tags_distinguish_gold_from_silver(self):
        """Both 'layer: gold' and 'layer: silver' must appear so the LLM can differentiate."""
        svc = _make_service()
        catalog = self._build_catalog(GOLD_DOC_COMMA_MODULE)
        rendered = svc.render_as_prompt_context(catalog)
        assert "layer: gold" in rendered, "Gold layer tag missing from catalog"
        assert "layer: silver" in rendered, "Silver layer tag missing from catalog"

    def test_gold_description_does_not_hint_to_use_silver(self):
        """Gold description must NOT tell the LLM to fall back to Silver."""
        svc = _make_service()
        entry = svc._doc_to_entry(GOLD_DOC_COMMA_MODULE)
        assert entry is not None
        desc_lower = entry.description.lower()
        assert "use silver" not in desc_lower, (
            "Gold description contains 'use silver' — this redirects the LLM away from Gold"
        )
        assert "silver_s4h" not in desc_lower, (
            "Gold description references a Silver entity ID — LLM will follow that hint"
        )


# ── 3. System prompt — "prefer Gold" rule ─────────────────────────────────────


class TestSystemPromptGoldPreference:
    def test_prefer_gold_rule_present(self):
        """The system prompt must explicitly instruct the LLM to prefer Gold over Silver."""
        assert "gold" in _SYSTEM_RULES.lower(), (
            "System prompt has no mention of 'gold' — LLM has no tier preference"
        )
        assert "prefer" in _SYSTEM_RULES.lower(), (
            "System prompt has no 'prefer' instruction for Gold"
        )

    def test_prefer_gold_rule_is_before_fact_rule(self):
        """Gold preference must appear before the fact-entity rule so it takes priority."""
        gold_pos = _SYSTEM_RULES.lower().find("prefer gold")
        fact_pos = _SYSTEM_RULES.lower().find("prefer `fact`")
        assert gold_pos != -1, "No 'prefer gold' rule found in system prompt"
        assert gold_pos < fact_pos, (
            "The 'prefer gold' rule appears AFTER the 'prefer fact' rule — "
            "ordering matters for LLM attention"
        )

    def test_gold_rule_mentions_silver_fallback(self):
        """The Gold rule should mention Silver as the fallback, not as the default."""
        section = _SYSTEM_RULES[
            _SYSTEM_RULES.lower().find("prefer gold") : _SYSTEM_RULES.lower().find("prefer gold")
            + 300
        ]
        assert "silver" in section.lower(), (
            "Gold preference rule doesn't mention Silver as a fallback"
        )


# ── 4. Catalog valid_ids — Gold ID must be selectable ─────────────────────────


class TestCatalogValidIds:
    def test_gold_id_in_valid_ids(self):
        svc = _make_service()
        gold = svc._doc_to_entry(GOLD_DOC_COMMA_MODULE)
        silver = svc._doc_to_entry(SILVER_DOC)
        catalog = Catalog(entries=[gold, silver])
        valid = catalog.valid_ids()
        assert "gold_s4h_open_order_tracker" in valid, (
            "Gold ID not in valid_ids — EntitySelector would reject it as hallucination"
        )
        assert "silver_s4h_sd_sales_order" in valid

    def test_gold_id_in_valid_ids_list_module(self):
        svc = _make_service()
        gold = svc._doc_to_entry(GOLD_DOC_LIST_MODULE)
        catalog = Catalog(entries=[gold])
        assert "gold_s4h_open_order_tracker" in catalog.valid_ids()

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Unit tests for the enrichment service — no LLM, no OpenSearch.

The service plugs into ``build_llm`` at runtime; we monkeypatch it with a
fake that returns a deterministic YAML so we can verify:

  * scope-defaults logic (priority, technical exclusion)
  * prompt composition (roles + standards + org context)
  * diff computation (entity-level + per-field)
  * field flow (JSON output parser)
"""

from __future__ import annotations

from typing import Any

import pytest

# Sample raw YAMLs (round-trip-compatible mappings) ─────────────────────────


SILVER_RAW: dict[str, Any] = {
    "id": "silver_s4h_sd_sales_order",
    "layer": "silver",
    "module": "sd",
    "name": "sales_order",
    "alias": "ORDER",
    "description": "Sales order header",
    "fields": [
        {
            "name": "netwr_vbak",
            "source": "VBAK.NETWR",
            "type": "P15",
            "field_role": "measure",
            "description": "Net value",
            "synonyms": [],
        },
        {
            "name": "kunnr_vbak",
            "source": "VBAK.KUNNR",
            "type": "C10",
            "field_role": "dimension",
            "description": "",
            "synonyms": [],
        },
        {
            "name": "mandt_vbak",
            "source": "VBAK.MANDT",
            "type": "C3",
            "field_role": "identifier",
            "description": "Client",
        },
        {
            "name": "created_at",
            "source": "VBAK.ERDAT",
            "type": "DATE",
            "field_role": "timestamp",
            "description": "Creation timestamp",
        },
    ],
}


# ── scope-defaults ──────────────────────────────────────────────────────────


def test_compute_scope_defaults_excludes_technical_fields():
    from ask_admin_api.application.enrichment_service import compute_scope_defaults

    enrichable, technical, _, defaults = compute_scope_defaults(SILVER_RAW)

    enrichable_names = {row.name for row in enrichable}
    assert "netwr_vbak" in enrichable_names
    assert "kunnr_vbak" in enrichable_names
    # mandt + audit suffixes get filtered
    assert "mandt_vbak" in technical
    assert "created_at" in technical
    assert "mandt_vbak" not in enrichable_names


def test_is_technical_field_catches_sap_system_indicators():
    """loekz / lvorm / xchpf etc. are SAP system flags — never enriched."""
    from ask_admin_api.application.enrichment_service import is_technical_field

    assert is_technical_field("loekz") is True
    assert is_technical_field("loekz_vbak") is True
    assert is_technical_field("lvorm_vbap") is True
    assert is_technical_field("xchpf_vbak") is True
    # Business fields still enrichable
    assert is_technical_field("netwr_vbak") is False
    assert is_technical_field("kunnr_kna1") is False


def test_is_likely_flag_or_status_detects_patterns():
    """Flag-like fields stay in scope but are NOT auto-selected."""
    from ask_admin_api.application.enrichment_service import is_likely_flag_or_status

    # Prefix patterns
    assert is_likely_flag_or_status({"name": "is_active"}) is True
    assert is_likely_flag_or_status({"name": "has_inventory"}) is True
    assert is_likely_flag_or_status({"name": "kennz_blocked"}) is True
    # Suffix patterns
    assert is_likely_flag_or_status({"name": "deletion_flag"}) is True
    assert is_likely_flag_or_status({"name": "credit_status"}) is True
    assert is_likely_flag_or_status({"name": "priority_indicator"}) is True
    # SAP C1 type → boolean by convention
    assert is_likely_flag_or_status({"name": "xfeld_vbak", "type": "C1"}) is True
    # Exact names
    assert is_likely_flag_or_status({"name": "aktiv"}) is True
    # Regular business fields → False
    assert is_likely_flag_or_status({"name": "netwr_vbak", "type": "P15"}) is False
    assert is_likely_flag_or_status({"name": "kunnr_kna1", "type": "C10"}) is False


def test_compute_scope_defaults_only_auto_selects_empty_descriptions():
    """Short-but-clear descriptions no longer auto-checked; flags never auto-checked."""
    from ask_admin_api.application.enrichment_service import compute_scope_defaults

    raw = {
        "id": "silver_x",
        "layer": "silver",
        "fields": [
            # Empty description → AUTO-SELECT
            {"name": "kunnr_vbak", "type": "C10", "description": ""},
            # Short but clear → NOT auto-selected anymore
            {"name": "netwr_vbak", "type": "P15", "description": "Net value"},
            # Empty BUT flag-like → NOT auto-selected (would be over-enriched)
            {"name": "is_active", "type": "C1", "description": ""},
        ],
    }
    _, _, _, defaults = compute_scope_defaults(raw)
    assert "kunnr_vbak" in defaults.field_names
    assert "netwr_vbak" not in defaults.field_names  # short doesn't auto-pick
    assert "is_active" not in defaults.field_names  # flag-like doesn't auto-pick


def test_compute_scope_defaults_marks_flag_like_rows():
    """The SPA needs `is_likely_flag` per row to render the badge."""
    from ask_admin_api.application.enrichment_service import compute_scope_defaults

    raw = {
        "id": "silver_x",
        "layer": "silver",
        "fields": [
            {"name": "is_active", "type": "C1", "description": ""},
            {"name": "kunnr_vbak", "type": "C10", "description": "Customer"},
        ],
    }
    enrichable, _, _, _ = compute_scope_defaults(raw)
    by_name = {r.name: r for r in enrichable}
    assert by_name["is_active"].is_likely_flag is True
    assert by_name["kunnr_vbak"].is_likely_flag is False


def test_compute_scope_defaults_priority_bucketing():
    """Priority is bucketed independently of auto-selection (separate concern)."""
    from ask_admin_api.application.enrichment_service import compute_scope_defaults

    enrichable, _, _, defaults = compute_scope_defaults(SILVER_RAW)
    rows_by_name = {r.name: r for r in enrichable}

    # Bucketing still works the same way.
    assert rows_by_name["kunnr_vbak"].priority == "empty"
    assert rows_by_name["netwr_vbak"].priority == "short"
    # ONLY ``empty`` auto-selects — ``short`` is no longer auto-selected
    # because short-but-clear descriptions ("Net value") are perfectly fine
    # and don't need an LLM rewrite. Admin can still tick them manually.
    assert "kunnr_vbak" in defaults.field_names
    assert "netwr_vbak" not in defaults.field_names


# ── Diff computation ────────────────────────────────────────────────────────


def test_diff_entity_level_returns_only_changed_keys():
    from ask_admin_api.application.enrichment_service import diff_entity_level

    original = {"description": "Sales order header", "alias": "ORDER"}
    enriched = {
        "description": "Sales order header with billing and customer context",
        "alias": "ORDER",  # unchanged
        "business_process": "OTC",  # net-new
    }
    diff = diff_entity_level(original, enriched)
    assert diff.description is not None
    assert diff.description.new.startswith("Sales order header with")
    assert diff.alias is None  # unchanged
    assert diff.business_process is not None
    assert diff.business_process.new == "OTC"


def test_diff_fields_respects_scope_and_skips_technical():
    from ask_admin_api.application.enrichment_service import diff_fields

    enriched_raw = {
        **SILVER_RAW,
        "fields": [
            {
                "name": "netwr_vbak",
                "source": "VBAK.NETWR",
                "type": "P15",
                "field_role": "measure",
                "description": "Net monetary amount of the sales order at line level",
                "synonyms": ["amount", "value", "revenue"],
            },
            {
                "name": "kunnr_vbak",
                "source": "VBAK.KUNNR",
                "type": "C10",
                "field_role": "dimension",
                "description": "Customer that placed the sales order",
                "synonyms": ["customer", "buyer"],
            },
            # Technical field: LLM "tried" to change it, must be ignored.
            {
                "name": "mandt_vbak",
                "source": "VBAK.MANDT",
                "type": "C3",
                "field_role": "identifier",
                "description": "LLM-rewritten — must be skipped",
            },
        ],
    }

    changes, unchanged = diff_fields(SILVER_RAW, enriched_raw, scope_field_names={"netwr_vbak"})
    # Scope restricts to a single field; only netwr_vbak should appear.
    assert len(changes) == 1
    assert changes[0].field_name == "netwr_vbak"
    assert changes[0].description is not None
    assert changes[0].synonyms is not None
    # kunnr_vbak's change is real but out-of-scope; mandt is technical.
    assert "kunnr_vbak" not in {c.field_name for c in changes}


def test_diff_fields_without_scope_diffs_everything_non_technical():
    from ask_admin_api.application.enrichment_service import diff_fields

    enriched_raw = {
        **SILVER_RAW,
        "fields": [
            {
                **f,
                "description": f["description"] + " (enriched)"
                if f.get("description")
                else "now described",
            }
            for f in SILVER_RAW["fields"]
        ],
    }
    changes, _ = diff_fields(SILVER_RAW, enriched_raw, scope_field_names=None)
    names = {c.field_name for c in changes}
    assert "netwr_vbak" in names
    assert "kunnr_vbak" in names
    # Technical fields stay out even when scope is None.
    assert "mandt_vbak" not in names
    assert "created_at" not in names


# ── Response parsers ────────────────────────────────────────────────────────


def test_parse_yaml_response_accepts_fenced_block():
    from ask_admin_api.application.enrichment_service import parse_yaml_response

    text = "```yaml\nid: foo\ndescription: bar\n```"
    parsed = parse_yaml_response(text)
    assert parsed["id"] == "foo"
    assert parsed["description"] == "bar"


def test_parse_yaml_response_tolerates_prose_and_trailing_text():
    """Real-world Nova / Claude outputs often wrap with prose around the fence."""
    from ask_admin_api.application.enrichment_service import parse_yaml_response

    text = (
        "Here is the enriched YAML:\n\n"
        "```yaml\n"
        "id: silver_x\n"
        "description: enriched\n"
        "```\n\n"
        "Let me know if you need anything else."
    )
    parsed = parse_yaml_response(text)
    assert parsed["id"] == "silver_x"
    assert parsed["description"] == "enriched"


def test_parse_yaml_response_handles_missing_lang_tag_and_no_closing_fence():
    """Some models drop the language tag or never close the fence."""
    from ask_admin_api.application.enrichment_service import parse_yaml_response

    text = "```\nid: silver_y\ndescription: tolerant\n"
    parsed = parse_yaml_response(text)
    assert parsed["id"] == "silver_y"


def test_parse_json_response_strips_prose_prefix():
    from ask_admin_api.application.enrichment_service import parse_json_response

    text = 'Here is the result:\n{"description": "x", "synonyms": ["a", "b"]}'
    parsed = parse_json_response(text)
    assert parsed["description"] == "x"
    assert parsed["synonyms"] == ["a", "b"]


def test_parse_json_response_handles_fenced_with_prose():
    from ask_admin_api.application.enrichment_service import parse_json_response

    text = 'Sure, here you go:\n\n```json\n{"description": "x", "synonyms": ["a"]}\n```\n'
    parsed = parse_json_response(text)
    assert parsed["description"] == "x"


def test_parse_json_response_strips_reasoning_block():
    """Reasoning models (e.g. Qwen) emit a <think>…</think> trace — which itself
    contains stray braces — before the JSON. The parser must skip it."""
    from ask_admin_api.application.enrichment_service import parse_json_response

    text = (
        "<think>Let me reason: maybe {source} joins {target} on matnr…</think>\n"
        '{"relationship": null, "confidence": "low", "no_match_reason": "x"}'
    )
    parsed = parse_json_response(text)
    assert parsed["confidence"] == "low"
    assert parsed["relationship"] is None


def test_parse_json_response_skips_stray_brace_and_trailing_prose():
    """A stray '{' in prose before the object must not derail parsing, and
    trailing prose after the object must be ignored (balanced-brace extraction)."""
    from ask_admin_api.application.enrichment_service import parse_json_response

    text = 'Note: use {placeholder}. Result:\n{"confidence": "high"}\nHope that helps!'
    parsed = parse_json_response(text)
    assert parsed["confidence"] == "high"


# ── End-to-end with mocked LLM ──────────────────────────────────────────────


class _FakeLLM:
    """Returns a canned response — captures the prompt for assertions."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_messages: list[Any] = []

    def invoke(self, messages):
        self.last_messages = list(messages)

        class _Result:
            content = self.response_text
            usage_metadata = {"total_tokens": 123}

        return _Result()


@pytest.fixture
def patched_llm(monkeypatch):
    """Swap ``build_llm`` for the fake; tests configure the response per case."""
    fake = _FakeLLM("")

    def _build_llm(_cfg):
        return fake

    monkeypatch.setattr(
        "ask_admin_api.application.enrichment_service.build_llm",
        _build_llm,
    )
    return fake


def _service(prompt_body: str = "TEST PROMPT", standards: str = "TEST STANDARDS"):
    from ask_admin_api.application.enrichment_service import EnrichmentService

    class _Provider:
        def get_prompt(self, _key):
            return prompt_body

        def get_standards_excerpt(self, layer=None):
            return standards

    return EnrichmentService(
        system_prompt_provider=_Provider(),
        organization_context_provider=lambda: "Company: ACME",
    )


def test_preview_entity_uses_lean_input_and_json_output(patched_llm):
    """End-to-end: input slimmed to header + in-scope fields, output is JSON."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    # Model returns ONLY the changes — strict JSON, no markdown fence.
    patched_llm.response_text = (
        "{"
        '"entity": {"description": "Sales order header with billing context"},'
        '"fields": {'
        '"netwr_vbak": {'
        '"description": "Net monetary amount of the sales order at line level",'
        '"synonyms": ["amount", "value", "total"]'
        "}"
        "}"
        "}"
    )

    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=True, field_names=["netwr_vbak"]),
    )

    assert result.entity_diff.description is not None
    assert "billing context" in result.entity_diff.description.new
    assert len(result.field_diffs) == 1
    assert result.field_diffs[0].field_name == "netwr_vbak"
    assert result.field_diffs[0].synonyms is not None
    assert "amount" in result.field_diffs[0].synonyms.new
    # Technical fields still surface in the response so the SPA renders the badge.
    assert "mandt_vbak" in result.fields_skipped_technical
    # System prompt + standards + org context all appear in the LLM input.
    sys_text = patched_llm.last_messages[0].content
    assert "TEST PROMPT" in sys_text
    assert "TEST STANDARDS" in sys_text
    assert "ACME" in sys_text


def test_preview_entity_input_excludes_out_of_scope_field_definitions(patched_llm):
    """The slim prompt sends FULL defs only for in-scope fields, names only for others."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    patched_llm.response_text = "{}"  # model says "no changes" — we only assert on the input
    svc = _service()
    svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=False, field_names=["netwr_vbak"]),
    )
    user_text = patched_llm.last_messages[1].content
    # In-scope field's full definition is present (source / type / role).
    assert "netwr_vbak" in user_text
    assert "VBAK.NETWR" in user_text
    # The OTHER non-technical field (kunnr_vbak) should appear ONLY as a bare
    # name in the "OTHER FIELDS" list — not with its full def.
    assert "kunnr_vbak" in user_text
    assert "VBAK.KUNNR" not in user_text  # source line for kunnr_vbak NOT in input
    # Technical fields are filtered out of the "other fields" hint as well.
    assert "mandt_vbak" not in user_text or "C3" not in user_text


def test_preview_entity_drops_out_of_scope_and_hallucinated_field_changes(patched_llm):
    """Model can return extra/renamed fields; only in-scope known fields apply."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    patched_llm.response_text = (
        "{"
        '"fields": {'
        '"netwr_vbak": {"description": "in-scope"},'
        '"kunnr_vbak": {"description": "out-of-scope (admin did not select)"},'
        '"ghost_field": {"description": "model hallucinated this"}'
        "}"
        "}"
    )
    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=False, field_names=["netwr_vbak"]),
    )
    field_names = {fd.field_name for fd in result.field_diffs}
    assert field_names == {"netwr_vbak"}
    # Out-of-scope + hallucinated are dropped silently — no errors raised.


def test_preview_field_returns_json_diff(patched_llm):
    patched_llm.response_text = (
        '{"description": "Net monetary amount of the sales order", '
        '"synonyms": ["amount", "value", "revenue"]}'
    )
    svc = _service()
    result = svc.preview_field(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        field_name="netwr_vbak",
    )
    assert result.field_name == "netwr_vbak"
    assert result.diff.description is not None
    assert result.diff.description.new.startswith("Net monetary amount")
    assert result.diff.synonyms is not None
    assert "revenue" in result.diff.synonyms.new


def test_preview_field_preservation_guard_cancels_critical_rewrite(patched_llm):
    """BACKLOG I: preview_field runs the SAME preservation guard as
    preview_entity — a rewrite that drops value mappings / TABLE.FIELD
    citations is cancelled and explained via the (new) `caveats` field,
    instead of silently proposing to erase curated semantics."""
    raw_with_flag = {
        **SILVER_RAW,
        "fields": SILVER_RAW["fields"]
        + [
            {
                "name": "order_status",
                "field_role": "status_flag",
                "type": "TEXT",
                "description": (
                    "Derived OPEN/CLOSE from ovrll_sts (VBUK.GBSTK). Rule: 'C' -> "
                    "'CLOSE'; else (A, B, NULL) -> 'OPEN'."
                ),
            }
        ],
    }
    # Generic rewrite — values and citation gone (the guarded failure mode).
    patched_llm.response_text = (
        '{"description": "Binary classification indicating order open or closed status.", '
        '"synonyms": ["status"]}'
    )
    svc = _service()
    result = svc.preview_field(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=raw_with_flag,
        field_name="order_status",
    )
    assert result.diff.description is None, "critical rewrite should have been cancelled"
    # Synonyms are not description-critical — they survive the guard.
    assert result.diff.synonyms is not None
    assert any("order_status" in c for c in result.caveats), (
        f"Expected an order_status caveat; got: {result.caveats}"
    )


def test_preview_field_guard_passes_benign_rewrite(patched_llm):
    """A rewrite on a field with no critical tokens flows through unchanged
    (regression guard for the wrap — same behaviour as before the guard)."""
    patched_llm.response_text = (
        '{"description": "Net monetary amount of the sales order line", "synonyms": ["amount"]}'
    )
    svc = _service()
    result = svc.preview_field(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        field_name="netwr_vbak",
    )
    assert result.diff.description is not None
    assert result.caveats == []


def test_preview_field_rejects_technical_field(patched_llm):
    svc = _service()
    with pytest.raises(ValueError, match="excluded"):
        svc.preview_field(
            entity_id="silver_s4h_sd_sales_order",
            raw_yaml=SILVER_RAW,
            field_name="mandt_vbak",
        )


def test_preview_entity_filters_out_technical_from_scope(patched_llm):
    """Technical field names must not leak into the diff even if the model returns them."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    patched_llm.response_text = (
        '{"fields": {"mandt_vbak": {"description": "LLM rewrote it but it should not stick"}}}'
    )
    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=False, field_names=["mandt_vbak"]),
    )
    assert all(d.field_name != "mandt_vbak" for d in result.field_diffs)


def test_preview_entity_parse_error_returns_diagnostic_not_422(patched_llm):
    """Malformed JSON output returns 200 + parse-error diagnostic (not 422)."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    patched_llm.response_text = "this is not json at all, just prose from the model"
    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=True, field_names=["netwr_vbak"]),
    )
    assert result.field_diffs == []
    assert result.diagnostic is not None
    assert result.diagnostic.parse_error is not None
    assert "this is not json" in result.diagnostic.response_preview


def test_sap_origin_uses_explicit_source_when_present():
    from ask_admin_api.application.enrichment_service import _sap_origin_for

    assert _sap_origin_for({"name": "netwr_vbak", "source": "VBAK.NETWR"}) == "VBAK.NETWR"


def test_sap_origin_falls_back_to_name_pattern_for_gold():
    """Gold fields without `source` still expose their SAP origin via name convention."""
    from ask_admin_api.application.enrichment_service import _sap_origin_for

    # `<sap_field>_<sap_table>` (lowercase) is the project convention.
    assert _sap_origin_for({"name": "netwr_vbak"}) == "VBAK.NETWR"
    assert _sap_origin_for({"name": "kunnr_kna1"}) == "KNA1.KUNNR"
    # Heuristic uses `rpartition('_')`, so a name with multiple underscores
    # treats the LAST segment as the table. That's the right call for
    # patterns like `business_process_vbak`.
    assert _sap_origin_for({"name": "business_process_vbak"}) == "VBAK.BUSINESS_PROCESS"


def test_sap_origin_returns_empty_for_unparseable_names():
    """No source and no `_` → no hint emitted; the prompt skips `sap_origin`."""
    from ask_admin_api.application.enrichment_service import _sap_origin_for

    assert _sap_origin_for({"name": "computedmetric"}) == ""
    assert _sap_origin_for({}) == ""


def test_preview_entity_includes_sap_origin_in_prompt(patched_llm):
    """In-scope fields ship a `sap_origin` hint so the LLM anchors on SAP semantics."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    patched_llm.response_text = "{}"
    svc = _service()
    svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=False, field_names=["netwr_vbak"]),
    )
    user_text = patched_llm.last_messages[1].content
    assert "sap_origin" in user_text
    assert "VBAK.NETWR" in user_text


def test_preview_entity_does_not_leak_internal_flag_heuristic_to_prompt(patched_llm):
    """`field_role` is the canonical role contract — the runtime flag heuristic
    must NOT show up as a parallel signal in the prompt (it would compete with
    `field_role` and confuse the model).

    The heuristic is still allowed to drive the SPA badge + scope auto-select
    rule — that's internal UX, not prompt content.
    """
    from ask_admin_api.models.enrichment import EnrichEntityScope

    raw = {
        "id": "silver_x",
        "layer": "silver",
        "fields": [
            {
                # GBSTK — a genuine business status flag. Deliberately NOT a
                # technical-list column (LVORM would now be excluded by the
                # source-anchored is_technical_field, emptying the scope).
                "name": "deletion_flag",
                "source": "VBAK.GBSTK",
                "type": "C1",
                "field_role": "indicator",
                "description": "",
            },
            {
                "name": "netwr_vbak",
                "source": "VBAK.NETWR",
                "type": "P15",
                "field_role": "measure",
                "description": "",
            },
        ],
    }
    patched_llm.response_text = "{}"
    svc = _service()
    svc.preview_entity(
        entity_id="silver_x",
        raw_yaml=raw,
        scope=EnrichEntityScope(entity_level=False, field_names=["deletion_flag", "netwr_vbak"]),
    )
    user_text = patched_llm.last_messages[1].content
    # No runtime-only key is leaked — `field_role` carries the classification.
    assert "is_likely_flag" not in user_text
    # Both fields' field_role values DO reach the LLM (canonical taxonomy).
    assert "indicator" in user_text
    assert "measure" in user_text


def test_preview_entity_workspace_context_provider_injected_when_present(patched_llm):
    from ask_admin_api.application.enrichment_service import EnrichmentService
    from ask_admin_api.models.enrichment import EnrichEntityScope

    class _Prov:
        def get_prompt(self, _k):
            return "ROLE PROMPT"

        def get_standards_excerpt(self, layer=None):
            return ""

    captured: dict[str, str] = {}

    def _workspace_ctx(workspace_id: str, entity_id: str) -> str:
        captured["ws"] = workspace_id
        captured["ent"] = entity_id
        return 'Workspace: "sales-perf"\nDP: monthly-billing\nSiblings: a, b, c'

    patched_llm.response_text = "{}"
    svc = EnrichmentService(
        system_prompt_provider=_Prov(),
        organization_context_provider=lambda: None,
        workspace_context_provider=_workspace_ctx,
    )
    svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=False, field_names=["netwr_vbak"]),
        workspace_id="sales-perf",
    )
    assert captured["ws"] == "sales-perf"
    assert captured["ent"] == "silver_s4h_sd_sales_order"
    user_text = patched_llm.last_messages[1].content
    assert "WORKSPACE CONTEXT" in user_text
    assert "sales-perf" in user_text
    assert "monthly-billing" in user_text


def test_preview_entity_zero_changes_includes_diagnostic(patched_llm):
    """Empty JSON object = model said 'nothing to change' — diagnostic surfaces."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    patched_llm.response_text = "{}"
    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=True, field_names=["netwr_vbak"]),
    )
    assert result.field_diffs == []
    assert result.diagnostic is not None
    assert result.diagnostic.parse_error is None
    # Diagnostic counts ALL fields in the entity (4 in SILVER_RAW), not just
    # enrichable ones. Technical fields show up in `fields_skipped_technical`
    # for the UI, but the diagnostic snapshot is intentionally unfiltered.
    assert result.diagnostic.original_field_count == 4


# ── Relationship suggest (Modo 2 — Complete) ────────────────────────────────


# Target entity used across the relationship-suggest tests.
TARGET_RAW: dict[str, Any] = {
    "id": "silver_s4h_sd_trading_goods",
    "layer": "silver",
    "module": "sd",
    "name": "trading_goods",
    "primary_key": ["matnr_mara"],
    "fields": [
        {"name": "matnr_mara", "source": "MARA.MATNR", "type": "C18"},
        {"name": "mtart_mara", "source": "MARA.MTART", "type": "C4"},
        {"name": "mandt_mara", "source": "MARA.MANDT", "type": "C3"},
    ],
}


def test_is_likely_fk_recognises_sap_master_data_suffixes():
    """Field-name suffixes ARE the FK signal — that's what the prompt also leans on."""
    from ask_admin_api.application.enrichment_service import _is_likely_fk

    assert _is_likely_fk("matnr_vbap") is True
    assert _is_likely_fk("kunnr_kna1") is True
    assert _is_likely_fk("ebeln_ekko") is True
    # MANDT / client / audit fields are NEVER FKs in a join sense
    assert _is_likely_fk("mandt_vbak") is False
    assert _is_likely_fk("ernam_vbak") is False
    assert _is_likely_fk("erdat_vbak") is False
    # Business fields without master-data suffix are excluded — they may be
    # measures, descriptions, etc. We want a precise FK signal, not a broad sweep.
    assert _is_likely_fk("netwr_vbak") is False


def test_is_likely_fk_is_source_anchored_for_alias_named_fields():
    """Under column naming mode `alias` the published name prefix is a business
    word ('material_pedido'), so the SAP key signal must come from `source` —
    which stays raw SAP codes in every mode."""
    from ask_admin_api.application.enrichment_service import _is_likely_fk

    assert _is_likely_fk("material_pedido_vbap", "VBAP.MATNR") is True
    assert _is_likely_fk("cliente_vbak", "VBAK.KUNNR") is True
    # `source` also vetoes: an alias that happens to start with an FK word
    # but originates from a system column is still excluded.
    assert _is_likely_fk("kunnr_like_alias", "VBAK.MANDT") is False
    # And a non-key origin is excluded even if the name would have matched.
    assert _is_likely_fk("vbeln_texto", "VBAP.ARKTX") is False


def test_is_technical_field_is_source_anchored_for_alias_named_fields():
    """MANDT/ERDAT exclusion must survive alias-based names."""
    from ask_admin_api.application.enrichment_service import is_technical_field

    assert is_technical_field("cliente_sap", "VBAK.MANDT") is True
    assert is_technical_field("fecha_creacion", "VBAK.ERDAT") is True
    # A business origin stays enrichable whatever the name says.
    assert is_technical_field("valor_neto_vbak", "VBAK.NETWR") is False


def test_project_for_relationship_drops_non_FK_fields_and_descriptions():
    """The slim projection is what gates token spend on the prompt."""
    from ask_admin_api.application.enrichment_service import _project_for_relationship

    view = _project_for_relationship(SILVER_RAW, side="source")
    # Header preserved
    assert view["id"] == "silver_s4h_sd_sales_order"
    assert view["module"] == "sd"
    # Fields slimmed: only FK candidates remain; descriptions stripped
    names = {f["name"] for f in view["fields"]}
    # kunnr_vbak matches the kna1 suffix? No — kunnr_vbak has suffix _vbak,
    # which IS one of our FK suffixes (sales doc header references customer)
    assert "kunnr_vbak" in names
    # MANDT explicitly excluded
    assert "mandt_vbak" not in names
    # Audit timestamps excluded
    assert "created_at" not in names
    # Descriptions removed — only name + type (+ source, the SAP key signal
    # that keeps FK detection working under alias-based names) travels.
    for f in view["fields"]:
        assert "description" not in f
        assert "synonyms" not in f
        assert {"name", "type"} <= set(f.keys()) <= {"name", "type", "source"}


def test_suggest_relationship_complete_happy_path(patched_llm):
    """The model returns a clean suggestion → SPA gets a high-confidence response."""
    patched_llm.response_text = (
        "{"
        '"relationship": {'
        '"target_entity": "silver_s4h_sd_trading_goods",'
        '"relationship_type": "many_to_one",'
        '"join_condition": "ORDER.matnr_vbap = TRADING_GOODS.matnr_mara",'
        '"semantic_label": "material_of",'
        '"traversal_cost": 1,'
        '"aggregation_safety": "safe",'
        '"cross_module": false,'
        '"description": "Lookup of material master for SD line items."'
        "},"
        '"confidence": "high",'
        '"caveats": [],'
        '"no_match_reason": null'
        "}"
    )
    svc = _service()
    source_with_fk = {
        **SILVER_RAW,
        "fields": SILVER_RAW["fields"]
        + [{"name": "matnr_vbap", "source": "VBAP.MATNR", "type": "C18"}],
    }
    out = svc.suggest_relationship_complete(
        source_entity_id="silver_s4h_sd_sales_order",
        target_entity_id="silver_s4h_sd_trading_goods",
        source_raw_yaml=source_with_fk,
        target_raw_yaml=TARGET_RAW,
    )
    assert out.relationship is not None
    assert out.relationship.target_entity == "silver_s4h_sd_trading_goods"
    assert out.relationship.relationship_type == "many_to_one"
    assert out.relationship.aggregation_safety == "safe"
    assert out.confidence == "high"
    assert out.caveats == []
    assert out.no_match_reason is None


def test_suggest_relationship_complete_no_match_path(patched_llm):
    """Model says relationship: null → SPA gets the no-match outcome verbatim."""
    patched_llm.response_text = (
        "{"
        '"relationship": null,'
        '"confidence": "low",'
        '"caveats": [],'
        '"no_match_reason": "Source uses SD keys; target uses FI keys. No direct overlap."'
        "}"
    )
    svc = _service()
    out = svc.suggest_relationship_complete(
        source_entity_id="silver_s4h_sd_sales_order",
        target_entity_id="silver_s4h_fi_journal_entry",
        source_raw_yaml=SILVER_RAW,
        target_raw_yaml=TARGET_RAW,
    )
    assert out.relationship is None
    assert out.confidence == "low"
    assert "Source uses SD keys" in (out.no_match_reason or "")


def test_suggest_relationship_strips_mandt_from_join_condition(patched_llm):
    """Hard rule: even if the LLM puts mandt in the join, we strip it."""
    patched_llm.response_text = (
        "{"
        '"relationship": {'
        '"target_entity": "silver_s4h_sd_trading_goods",'
        '"relationship_type": "many_to_one",'
        '"join_condition": "ORDER.mandt_vbak = TG.mandt_mara AND ORDER.matnr_vbap = TG.matnr_mara",'
        '"semantic_label": "material_of",'
        '"traversal_cost": 1,'
        '"aggregation_safety": "safe",'
        '"cross_module": false,'
        '"description": "Material lookup."'
        "},"
        '"confidence": "high",'
        '"caveats": [],'
        '"no_match_reason": null'
        "}"
    )
    svc = _service()
    out = svc.suggest_relationship_complete(
        source_entity_id="silver_s4h_sd_sales_order",
        target_entity_id="silver_s4h_sd_trading_goods",
        source_raw_yaml=SILVER_RAW,
        target_raw_yaml=TARGET_RAW,
    )
    assert out.relationship is not None
    # The mandt clause is gone; the material clause stays.
    cond = out.relationship.join_condition or ""
    assert "mandt" not in cond.lower()
    assert "matnr_vbap" in cond
    assert "matnr_mara" in cond


def test_suggest_relationship_invalid_enum_defaults_with_caveat(patched_llm):
    """Unknown cardinality from the model is downgraded, not propagated raw."""
    patched_llm.response_text = (
        "{"
        '"relationship": {'
        '"target_entity": "silver_s4h_sd_trading_goods",'
        '"relationship_type": "TOTALLY_INVENTED",'
        '"join_condition": "ORDER.matnr_vbap = TG.matnr_mara",'
        '"semantic_label": "material_of",'
        '"traversal_cost": 1,'
        '"aggregation_safety": "safe",'
        '"cross_module": false,'
        '"description": "..."'
        "},"
        '"confidence": "medium",'
        '"caveats": [],'
        '"no_match_reason": null'
        "}"
    )
    svc = _service()
    out = svc.suggest_relationship_complete(
        source_entity_id="silver_s4h_sd_sales_order",
        target_entity_id="silver_s4h_sd_trading_goods",
        source_raw_yaml=SILVER_RAW,
        target_raw_yaml=TARGET_RAW,
    )
    assert out.relationship is not None
    assert out.relationship.relationship_type == "many_to_one"  # safe default
    # A caveat was injected explaining the fallback.
    assert any("relationship_type" in c.lower() for c in out.caveats)


def test_suggest_relationship_parse_failure_returns_diagnostic_not_502(patched_llm):
    """Malformed JSON → no_match outcome with diagnostic, NOT a 502."""
    patched_llm.response_text = "this is not json at all, just prose"
    svc = _service()
    out = svc.suggest_relationship_complete(
        source_entity_id="silver_s4h_sd_sales_order",
        target_entity_id="silver_s4h_sd_trading_goods",
        source_raw_yaml=SILVER_RAW,
        target_raw_yaml=TARGET_RAW,
    )
    assert out.relationship is None
    assert out.diagnostic is not None
    assert out.diagnostic.parse_error is not None
    assert "not valid JSON" in (out.no_match_reason or "")


def test_commit_message_for_ai_suggest_relationship_includes_caveats(tmp_path):
    """Source 'ai_suggest_relationship' + commit_notes → caveats in commit body."""
    from ask_admin_api.application.yaml_file_service import _build_commit_message
    from ask_admin_api.models.viz_models import VizYAMLUpdateRequest

    req = VizYAMLUpdateRequest(
        source="ai_suggest_relationship",
        relationships=[],  # signals "relationships changed"
        commit_notes=[
            "Cardinality assumed many_to_one — uniqueness unverified.",
            "Multiple FK candidates found; picked matnr_vbap.",
        ],
    )
    msg = _build_commit_message("silver_s4h_sd_sales_order", "ai_suggest_relationship", req)
    assert msg.startswith("ai-suggest-rel(silver_s4h_sd_sales_order):")
    assert "Caveats:" in msg
    assert "Cardinality assumed" in msg
    assert "Multiple FK candidates" in msg


def test_commit_message_for_ai_suggest_relationship_without_notes_stays_one_line(tmp_path):
    from ask_admin_api.application.yaml_file_service import _build_commit_message
    from ask_admin_api.models.viz_models import VizYAMLUpdateRequest

    req = VizYAMLUpdateRequest(source="ai_suggest_relationship", relationships=[])
    msg = _build_commit_message("silver_s4h_sd_sales_order", "ai_suggest_relationship", req)
    assert "\n" not in msg
    assert msg.startswith("ai-suggest-rel(silver_s4h_sd_sales_order):")


# ── Description preservation guard ──────────────────────────────────────────


def test_extract_critical_tokens_pulls_quoted_values():
    from ask_admin_api.application.enrichment_service import _extract_critical_tokens

    text = "Rule: 'C' (fully processed) -> 'CLOSE', anything else -> 'OPEN'."
    toks = _extract_critical_tokens(text)
    assert "C" in toks
    assert "CLOSE" in toks
    assert "OPEN" in toks


def test_extract_critical_tokens_pulls_bare_mappings():
    from ask_admin_api.application.enrichment_service import _extract_critical_tokens

    text = "1 = active, 0 = inactive"
    toks = _extract_critical_tokens(text)
    assert "1" in toks
    assert "0" in toks


def test_extract_critical_tokens_pulls_table_field_citations():
    from ask_admin_api.application.enrichment_service import _extract_critical_tokens

    text = "Derived from VBUK.GBSTK; see also VBAK.NETWR for amounts."
    toks = _extract_critical_tokens(text)
    assert "VBUK.GBSTK" in toks
    assert "VBAK.NETWR" in toks


def test_description_preserves_critical_info_ok_when_old_is_simple():
    from ask_admin_api.application.enrichment_service import (
        _description_preserves_critical_info,
    )

    ok, missing = _description_preserves_critical_info(
        "Sales document number", "Unique sales document identifier"
    )
    assert ok is True
    assert missing == set()


def test_description_preserves_critical_info_flags_dropped_values():
    """The order_status case from the user's screenshot — a rewrite that drops the value mapping is rejected."""
    from ask_admin_api.application.enrichment_service import (
        _description_preserves_critical_info,
    )

    old = (
        "Derived OPEN/CLOSE classification from ovrll_sts (VBUK.GBSTK). Rule: "
        "'C' (fully processed) -> 'CLOSE', anything else (A=open, B=partial, "
        "NULL) -> 'OPEN'. For partial-vs-fully-open distinction use "
        "ovrll_sts instead."
    )
    new = (
        "Derived binary classification indicating whether the order is open "
        "or closed, based on the overall processing status."
    )
    ok, missing = _description_preserves_critical_info(old, new)
    assert ok is False
    # Critical losses include the value tokens AND the TABLE.FIELD citation.
    assert "C" in missing
    assert "CLOSE" in missing
    assert "VBUK.GBSTK" in missing


def test_preview_entity_preservation_guard_cancels_status_flag_rewrite(patched_llm):
    """End-to-end: the order_status case lands in caveats, not in field_diffs."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    # Source YAML has a status_flag with value mappings + citation.
    raw_with_flag = {
        **SILVER_RAW,
        "fields": SILVER_RAW["fields"]
        + [
            {
                "name": "order_status",
                "field_role": "status_flag",
                "type": "TEXT",
                "description": (
                    "Derived OPEN/CLOSE from ovrll_sts (VBUK.GBSTK). Rule: 'C' -> "
                    "'CLOSE'; else (A, B, NULL) -> 'OPEN'. Use ovrll_sts for partial detail."
                ),
            }
        ],
    }

    # LLM responds with a generic rewrite — exactly the failure mode we want
    # to guard against. Values and citation gone.
    patched_llm.response_text = (
        "{"
        '"fields": {'
        '"order_status": {'
        '"description": "Binary classification indicating order open or closed status."'
        "}"
        "}"
        "}"
    )

    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=raw_with_flag,
        scope=EnrichEntityScope(entity_level=False, field_names=["order_status"]),
    )

    # The field_diffs should NOT contain the order_status description change.
    order_status_changes = [fd for fd in result.field_diffs if fd.field_name == "order_status"]
    assert order_status_changes == [], "Description change should have been cancelled"

    # The caveat list should explain the cancellation.
    assert any("order_status" in c for c in result.caveats), (
        f"Expected an order_status caveat; got: {result.caveats}"
    )


def test_preview_entity_preservation_guard_passes_when_tokens_preserved(patched_llm):
    """An AI rewrite that KEEPS the value mappings + citation IS accepted."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    raw_with_flag = {
        **SILVER_RAW,
        "fields": SILVER_RAW["fields"]
        + [
            {
                "name": "order_status",
                "field_role": "status_flag",
                "type": "TEXT",
                "description": "'C' = CLOSE, else (A, B, NULL) = OPEN. From VBUK.GBSTK.",
            }
        ],
    }

    # Same critical tokens preserved, only the wrapper prose changes.
    patched_llm.response_text = (
        "{"
        '"fields": {'
        '"order_status": {'
        '"description": "Open/close flag. \'C\' = CLOSE; else (A, B, NULL) = OPEN (VBUK.GBSTK)."'
        "}"
        "}"
        "}"
    )

    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=raw_with_flag,
        scope=EnrichEntityScope(entity_level=False, field_names=["order_status"]),
    )

    order_status_changes = [fd for fd in result.field_diffs if fd.field_name == "order_status"]
    assert len(order_status_changes) == 1, "Description change should have survived the guard"
    assert result.caveats == []


def test_strip_added_table_field_citation_removes_when_new_adds_one():
    """If the LLM adds `(VBAK.VBELN)` to a description that didn't have one,
    strip it server-side. Rule 4 of the system prompt forbids this but
    Nova-class models keep doing it — defense in depth."""
    from ask_admin_api.application.enrichment_service import (
        _strip_added_table_field_citation,
    )

    cleaned, stripped = _strip_added_table_field_citation(
        "Sales document",
        "Unique sales document number (VBAK.VBELN)",
    )
    assert stripped is True
    assert cleaned == "Unique sales document number"


def test_strip_added_table_field_citation_preserves_when_original_had_one():
    """Preservation rule wins: if the original already had a citation, the
    new one stays — even if it's now in a different prose wrapper."""
    from ask_admin_api.application.enrichment_service import (
        _strip_added_table_field_citation,
    )

    cleaned, stripped = _strip_added_table_field_citation(
        "Net value from VBAK.NETWR",
        "Net monetary value (VBAK.NETWR)",
    )
    assert stripped is False
    assert cleaned == "Net monetary value (VBAK.NETWR)"


def test_strip_added_table_field_citation_no_op_when_no_citation():
    """Plain description → plain description. No false positives."""
    from ask_admin_api.application.enrichment_service import (
        _strip_added_table_field_citation,
    )

    cleaned, stripped = _strip_added_table_field_citation(
        "Sales document",
        "Unique sales document identifier",
    )
    assert stripped is False
    assert cleaned == "Unique sales document identifier"


def test_preview_entity_strips_added_citations_silently(patched_llm):
    """End-to-end: LLM adds (VBAK.VBELN), backend cleans it, no caveat
    needed (rule violation isn't worth surfacing — just clean and move on)."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    patched_llm.response_text = (
        '{"fields": {"netwr_vbak": {"description": "Net monetary amount (VBAK.NETWR)"}}}'
    )
    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=SILVER_RAW,
        scope=EnrichEntityScope(entity_level=False, field_names=["netwr_vbak"]),
    )
    netwr_diff = next((fd for fd in result.field_diffs if fd.field_name == "netwr_vbak"), None)
    assert netwr_diff is not None
    assert netwr_diff.description is not None
    # Citation stripped — the new description must not contain VBAK.NETWR.
    assert "VBAK.NETWR" not in netwr_diff.description.new
    assert netwr_diff.description.new == "Net monetary amount"


def test_preview_entity_drops_cosmetic_only_changes(patched_llm):
    """If after the scrub the new description equals the old verbatim, the
    change is dropped entirely — no point showing a no-op diff card."""
    from ask_admin_api.models.enrichment import EnrichEntityScope

    raw_with_field = {
        **SILVER_RAW,
        "fields": SILVER_RAW["fields"]
        + [
            {
                "name": "augru_vbak",
                "source": "VBAK.AUGRU",
                "type": "C3",
                "field_role": "dimension",
                "description": "Order reason",
            }
        ],
    }
    # LLM proposes "Order reason (VBAK.AUGRU)" — after the scrub strips the
    # citation it becomes literally identical to the original. Drop it.
    patched_llm.response_text = (
        '{"fields": {"augru_vbak": {"description": "Order reason (VBAK.AUGRU)"}}}'
    )
    svc = _service()
    result = svc.preview_entity(
        entity_id="silver_s4h_sd_sales_order",
        raw_yaml=raw_with_field,
        scope=EnrichEntityScope(entity_level=False, field_names=["augru_vbak"]),
    )
    augru_changes = [fd for fd in result.field_diffs if fd.field_name == "augru_vbak"]
    assert augru_changes == [], "Cosmetic-only change should have been dropped"

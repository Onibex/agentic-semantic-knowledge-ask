# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""AI-assisted enrichment for semantic-layer YAMLs.

Three public operations:

  * ``compute_scope_defaults(yaml_id)`` — pre-computes the SPA's Step-1
    checklist: enrichable fields with priority hints, technical fields the
    admin cannot pick.

  * ``preview_entity(yaml_id, scope)`` — sends the FULL YAML to the LLM with
    a structured prompt, parses the response, computes the diff, returns it.
    Atomic: any malformed LLM output / decode failure → ValueError, nothing
    persisted.

  * ``preview_field(yaml_id, field_name)`` — single-field convenience: same
    flow with a tighter prompt that only enriches description + synonyms of
    the target field.

Persistence is OUT of scope here — the SPA accepts the diff and calls the
existing ``PATCH /v1/viz/yamls/{id}`` to commit. Keeps the enrichment
service free of git / file IO concerns.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from ask_knowledge_graph.infrastructure.yaml_serializer import (
    AskYamlSerializer,
    load_yaml_text,
)
from ask_llm_gateway.application.factory import build_llm
from ask_llm_gateway.infrastructure.response_utils import content_to_text

from ..models.enrichment import (
    DefaultSelection,
    EnrichEntityResponse,
    EnrichEntityScope,
    EnrichFieldResponse,
    EnrichmentDiagnostic,
    EntityDiff,
    EntityLevelScope,
    FieldDiff,
    FieldScopeRow,
    RelationshipSuggestResponse,
    SuggestedRelationship,
    SynonymsDiff,
    ValueDiff,
)

logger = logging.getLogger(__name__)


# Technical / system / audit fields that NEVER get enriched. Two buckets:
#
#   1. ``_TECHNICAL_FIELD_NAMES``  → SAP system + audit columns. Enrichment
#      always skips them. The wording would be wrong + noisy in retrieval.
#   2. ``_FLAG_LIKE_NAMES`` / ``_FLAG_PATTERNS`` → boolean / status / flag
#      indicators. Still enrichable (admin may want "1 = active") but they
#      should NOT be pre-selected (they're short by design, not by neglect).
_TECHNICAL_FIELD_NAMES = frozenset(
    {
        # Audit columns
        "mandt",
        "ersys",
        "ernam",
        "erdat",
        "ernum",
        "aedat",
        "aenam",
        "laeda",
        # SAP system / deletion / change indicators (descriptions for these
        # are framework metadata, never business semantics)
        "loekz",
        "lvorm",
        "xchpf",
        "xfeld",
    }
)
_TECHNICAL_SUFFIXES = ("_at", "_by")

# Flag-like indicators. SAP one-character types are usually here, plus the
# common Gold / Silver naming conventions (`is_*`, `has_*`, `*_flag`, etc.).
# Admin can still enrich these — they just don't get auto-checked.
_FLAG_LIKE_NAMES = frozenset(
    {
        "aktiv",
        "inaktiv",
        "kennzeichen",
    }
)
_FLAG_PREFIXES = ("is_", "has_", "kennz_", "stat_")
_FLAG_SUFFIXES = ("_flag", "_status", "_indicator", "_ind", "_kennz")


def is_technical_field(name: str, source: str | None = None) -> bool:
    """Heuristic: skip audit / system fields. Excludes them entirely.

    Keys on the SAP origin column first when the field carries ``source``
    (``VBAK.MANDT``): under column naming mode ``alias`` the published name
    prefix is a business word (``cliente_vbak``), so a name-only check would
    silently stop excluding MANDT/ERDAT & co. The name checks still run —
    suffix conventions (``_flag``, ``_status`` …) live on the name.
    """
    token = str(source or "").partition(".")[2].strip().lower()
    if token and token in _TECHNICAL_FIELD_NAMES:
        return True
    if not name:
        return False
    low = name.lower()
    base = low.split("_", 1)[0]
    if base in _TECHNICAL_FIELD_NAMES:
        return True
    if any(low == n or low.startswith(n + "_") for n in _TECHNICAL_FIELD_NAMES):
        return True
    return any(low.endswith(suf) for suf in _TECHNICAL_SUFFIXES)


def is_likely_flag_or_status(field: dict[str, Any]) -> bool:
    """Heuristic for fields that should carry ``field_role: status_flag``.

    The CANONICAL classification lives in the YAML's ``field_role`` —
    ``status_flag`` is one of the six roles defined in
    ``SEMANTIC_LAYER_STANDARDS.md`` §5. This heuristic is the runtime fallback
    used ONLY for SPA UX (badge in the checklist, no-auto-select rule). It
    does NOT leak into the LLM prompt; the LLM keys on ``field_role`` itself
    via the BREVITY RULES.

    Returns True for the common patterns:
      * Name starts with ``is_`` / ``has_`` / ``kennz_`` / ``stat_``
      * Name ends with ``_flag`` / ``_status`` / ``_indicator`` / ``_ind`` / ``_kennz``
      * Name is exactly one of ``aktiv`` / ``inaktiv`` / ``kennzeichen``
      * Field ``type`` is ``C1`` (single-char SAP types — overwhelmingly boolean)

    Used to **deprioritize** in the scope checklist — admin can still pick
    them, but they're not auto-selected because their descriptions are short
    by design ("1 = active, 0 = inactive"), not by neglect. When the admin
    classifies these fields properly with ``field_role: status_flag``, the
    heuristic stops being load-bearing for that field.
    """
    name = str(field.get("name") or "").lower()
    if not name:
        return False
    if name in _FLAG_LIKE_NAMES:
        return True
    if any(name.startswith(p) for p in _FLAG_PREFIXES):
        return True
    if any(name.endswith(s) for s in _FLAG_SUFFIXES):
        return True
    # SAP C1 single-char types are overwhelmingly boolean flags ('X'/' ').
    # Both encodings must be accepted: newly written entities carry the canonical
    # `STRING(1)`, while entities written before the canonical-type rule still
    # carry the raw SAP `C1` until they are regenerated or re-saved.
    if str(field.get("type") or "").strip().upper() in ("C1", "STRING(1)"):
        return True
    return False


# ── Field iteration ─────────────────────────────────────────────────────────


def _iter_fields(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a flat list of field dicts regardless of bronze/silver shape.

    Bronze stores ``fields`` as a mapping ``{FNAME: {…}}``; silver / gold as a
    list of dicts with a ``name`` key. We always emit list-of-dicts with a
    ``name`` key so the rest of the pipeline does not branch on layer.
    """
    fields_node = raw.get("fields")
    if isinstance(fields_node, list):
        result = []
        for f in fields_node:
            if isinstance(f, dict) and f.get("name"):
                result.append(dict(f))
        return result
    if isinstance(fields_node, dict):
        result = []
        for fname, body in fields_node.items():
            if not isinstance(body, dict):
                continue
            row = dict(body)
            row["name"] = fname
            result.append(row)
        return result
    return []


def _field_priority(field: dict[str, Any]) -> str:
    desc = (field.get("description") or "").strip()
    if not desc:
        return "empty"
    if len(desc) < 25:
        return "short"
    return "good"


# ── Scope defaults ──────────────────────────────────────────────────────────


def compute_scope_defaults(
    raw: dict[str, Any],
) -> tuple[list[FieldScopeRow], list[str], EntityLevelScope, DefaultSelection]:
    """Inspect a raw YAML dict and return the Step-1 checklist payload."""
    enrichable: list[FieldScopeRow] = []
    technical: list[str] = []
    default_field_names: list[str] = []

    for field in _iter_fields(raw):
        name = str(field.get("name") or "")
        if not name:
            continue
        if is_technical_field(name, field.get("source")):
            technical.append(name)
            continue
        desc = str(field.get("description") or "")
        priority = _field_priority(field)
        synonyms = field.get("synonyms")
        has_syn = bool(synonyms)
        flag_like = is_likely_flag_or_status(field)
        enrichable.append(
            FieldScopeRow(
                name=name,
                current_description=desc,
                has_description=bool(desc.strip()),
                has_synonyms=has_syn,
                priority=priority,  # type: ignore[arg-type]
                is_likely_flag=flag_like,
            )
        )
        # Tighter default selection — only ``empty`` is auto-checked:
        #   * ``short`` no longer auto-selects (lots of perfectly-fine concise
        #     descriptions like "Sales document number" got pre-picked under
        #     the old rule, leading the admin to enrich what was already good).
        #   * Flag-like fields never auto-select even if empty — admin must
        #     opt in (their natural description is 5-10 words and the LLM
        #     tends to over-write here).
        if priority == "empty" and not flag_like:
            default_field_names.append(name)

    entity_desc = str(raw.get("description") or "").strip()
    entity_alias = str(raw.get("alias") or "").strip()
    entity_bp = str(raw.get("business_process") or "").strip()

    # Same priority bucketing as fields, applied to the entity description.
    if not entity_desc:
        entity_priority: str = "empty"
    elif len(entity_desc) < 40:
        entity_priority = "short"
    else:
        entity_priority = "good"

    entity_level = EntityLevelScope(
        has_description=bool(entity_desc),
        has_alias=bool(entity_alias),
        has_business_process=bool(entity_bp),
        current_description=entity_desc,
        current_alias=entity_alias,
        current_business_process=entity_bp,
        priority=entity_priority,  # type: ignore[arg-type]
    )
    default_entity_level = entity_priority in ("empty", "short")

    return (
        enrichable,
        technical,
        entity_level,
        DefaultSelection(
            entity_level=default_entity_level,
            field_names=default_field_names,
        ),
    )


# ── Prompt building ─────────────────────────────────────────────────────────


def _sap_origin_for(field: dict[str, Any]) -> str:
    """Best-effort SAP table.field hint for the LLM.

    Order of preference:
      1. ``source`` is set as "TABLE.FIELD" (silver/bronze norm)         → use it
      2. ``source`` is set as just "TABLE" or "FIELD"                    → use it
      3. Field name follows the ``<field>_<table>`` convention (gold)    → split
      4. Nothing → return ""

    The result is a hint, not a fact — the system prompt warns the model to
    treat it as a clue when source is missing.
    """
    source = field.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip()
    name = field.get("name")
    if isinstance(name, str) and "_" in name:
        # Pattern <sap_field>_<sap_table>, lowercase by convention. Example:
        # "netwr_vbak" → "VBAK.NETWR".
        head, _, tail = name.rpartition("_")
        if head and tail:
            return f"{tail.upper()}.{head.upper()}"
    return ""


def _describe_field_for_prompt(field: dict[str, Any]) -> dict[str, Any]:
    """Project a field row into the compact dict the prompt ships to the LLM.

    Adds one explicit hint on top of the raw YAML keys:

      * ``sap_origin``  — TABLE.FIELD parsed from ``source`` or inferred
                          from the ``<field>_<table>`` name convention.

    Critically we do NOT inject runtime-computed classifications (like a
    flag/boolean heuristic). ``field_role`` is the canonical role taxonomy —
    it lives in the YAML, it's the contract, and the LLM keys on it via
    the BREVITY RULES in the system prompt. The backend heuristic stays
    internal (drives the SPA badge + scope auto-select rules) but never
    leaks into the prompt as a parallel signal that would compete with
    ``field_role``.
    """
    keep_keys = (
        "name",
        "alias",
        "type",
        "field_role",
        "aggregation_behavior",
        # Read-only context (the system prompt forbids touching them). Projected so
        # the model does not write a description that CONTRADICTS them — NOT so it
        # restates them. These keys are derived at ingest and the SQL prompt now
        # treats them as authoritative, so re-narrating the reduce mechanics in prose
        # duplicates an authoritative fact into a carrier that goes stale. It also
        # costs retrieval: a description is EMBEDDED text, so mechanical instructions
        # displace the business meaning in that field's vector.
        "additivity",
        "non_additive_over",
        "key_field",
        "description",
        "synonyms",
        "normalization_flag",
    )
    projected = {k: field[k] for k in keep_keys if k in field}
    origin = _sap_origin_for(field)
    if origin:
        projected["sap_origin"] = origin
    return projected


def _language_block() -> str:
    """The deployment's authoring-language directive, appended to both enrichment
    prompts.

    Injected at CALL time rather than written into the editable prompt body so
    the flag stays authoritative: an admin editing the `enrichment` prompt cannot
    accidentally drop it, and switching `ASK_SEMANTIC_LANGUAGE` needs no prompt
    edit. Enrichment used to say nothing about language, so the output language
    was emergent — a mixed-language corpus stayed mixed
    (PLAN_SEMANTIC_LANGUAGE.md W1).
    """
    from ask_knowledge_graph.domain.language import authoring_directive
    from ask_knowledge_graph.infrastructure.language_config import resolve_semantic_language

    return "=" * 60 + "\n" + authoring_directive(resolve_semantic_language())


def build_entity_prompt(
    *,
    system_prompt: str,
    standards_excerpt: str,
    organization_context: str | None,
    workspace_context: str | None,
    scope: EnrichEntityScope,
    raw_yaml: dict[str, Any],
    serializer: AskYamlSerializer,
) -> tuple[str, str]:
    """Compose system + user messages for the entity enrichment call.

    Input shape is INTENTIONALLY slim + SAP-aware:

      * Entity header (id, layer, module, entity_role, business_process,
        description, alias, grain, composed_of, relationships) — always.
      * Workspace context block (workspace + DPs + sibling entities) when
        provided. Lets the LLM frame the description around how the entity
        is consumed in this specific data product, not just generically.
      * Full definitions of the IN-SCOPE fields, each one decorated with a
        ``sap_origin`` hint parsed from ``source`` (or inferred from the
        ``<field>_<table>`` naming convention when source is missing —
        common in Gold entities).
      * Names of OTHER (non-scope, non-technical) fields.

    Output shape is a strict JSON object — see system prompt OUTPUT FORMAT.
    """
    sys_parts = [system_prompt.strip(), _language_block()]
    if standards_excerpt.strip():
        sys_parts.append(
            "=" * 60
            + "\nSEMANTIC LAYER STANDARDS (reference)\n"
            + "=" * 60
            + "\n"
            + standards_excerpt.strip()
        )
    if organization_context and organization_context.strip():
        sys_parts.append(
            "=" * 60 + "\nCUSTOMER CONTEXT\n" + "=" * 60 + "\n" + organization_context.strip()
        )

    # --- INPUT: slim view of the entity --------------------------------------

    header_keys = (
        "id",
        "layer",
        "module",
        "entity_role",
        "business_process",
        "description",
        "alias",
        "grain",
        "composed_of",
        "relationships",
    )
    entity_header = {k: raw_yaml[k] for k in header_keys if k in raw_yaml}

    all_fields = _iter_fields(raw_yaml)
    scope_set = set(scope.field_names)
    in_scope_fields = [
        _describe_field_for_prompt(f) for f in all_fields if f.get("name") in scope_set
    ]
    other_field_names = [
        f.get("name")
        for f in all_fields
        if f.get("name")
        and f.get("name") not in scope_set
        and not is_technical_field(f["name"], f.get("source"))
    ]

    user_parts: list[str] = []
    user_parts.append("ENTITY HEADER (context — do not modify, do not echo back):")
    user_parts.append(serializer.to_yaml(entity_header))

    if workspace_context and workspace_context.strip():
        user_parts.append(
            "WORKSPACE CONTEXT (how this entity is consumed):\n" + workspace_context.strip()
        )

    user_parts.append(
        f"ENRICH ENTITY-LEVEL: {scope.entity_level}\n"
        f"FIELDS TO ENRICH ({len(in_scope_fields)}):\n"
        "Each in-scope field carries a `sap_origin` hint (TABLE.FIELD) — use it as\n"
        "your primary anchor when writing the description. If sap_origin is missing,\n"
        "the field name still encodes it as `<sap_field>_<sap_table>` (e.g.\n"
        "`netwr_vbak` ≈ VBAK.NETWR)."
    )
    if in_scope_fields:
        user_parts.append(serializer.to_yaml(in_scope_fields))
    else:
        user_parts.append("(none — only entity-level requested)")

    if other_field_names:
        user_parts.append(
            "OTHER FIELDS IN THIS ENTITY (names only — do NOT enrich, listed so you can "
            "avoid description overlap with these):\n"
            + ", ".join(str(n) for n in other_field_names)
        )

    user_parts.append(
        "Return a JSON object with only the keys you want to change, per the "
        "OUTPUT FORMAT in the system prompt."
    )

    return "\n\n".join(sys_parts), "\n\n".join(user_parts)


def build_field_prompt(
    *,
    system_prompt: str,
    standards_excerpt: str,
    organization_context: str | None,
    yaml_text: str,
    field_name: str,
) -> tuple[str, str]:
    """Single-field flow — the LLM only returns description + synonyms.

    We still send the full YAML so the LLM has context about other fields,
    the module, the business_process, etc. but the OUTPUT is a JSON object
    instead of the full YAML.
    """
    sys_parts = [system_prompt.strip(), _language_block()]
    if standards_excerpt.strip():
        sys_parts.append(
            "=" * 60
            + "\nSEMANTIC LAYER STANDARDS (reference)\n"
            + "=" * 60
            + "\n"
            + standards_excerpt.strip()
        )
    if organization_context and organization_context.strip():
        sys_parts.append(
            "=" * 60 + "\nCUSTOMER CONTEXT\n" + "=" * 60 + "\n" + organization_context.strip()
        )
    sys_parts.append(
        "OUTPUT FORMAT — strict JSON object, no markdown fences:\n"
        '{ "description": "<one-to-two sentences>", '
        '"synonyms": ["term1", "term2", ...] }'
    )

    user_msg = (
        f"Target field: {field_name}\n\n"
        "Use the YAML below as context. Return ONLY enriched values for this field.\n\n"
        "BEGIN YAML\n----------\n" + yaml_text + "\nEND YAML"
    )
    return "\n\n".join(sys_parts), user_msg


# ── LLM invocation ──────────────────────────────────────────────────────────


def _invoke_llm_chat(llm: Any, system: str, user: str) -> tuple[str, int]:
    """Run a single chat completion. Returns (text, tokens_used).

    Wrapped to be tolerant of LangChain Message objects + reasoning-model
    list-of-blocks responses (uses ``content_to_text`` from the gateway).
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    result = llm.invoke(messages)
    text = content_to_text(result.content if hasattr(result, "content") else result)
    tokens = 0
    usage = getattr(result, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        tokens = int(usage.get("total_tokens", 0) or 0)
    return text, tokens


# ── Diff computation ────────────────────────────────────────────────────────


def _norm_synonyms(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def diff_entity_level(original: dict[str, Any], enriched: dict[str, Any]) -> EntityDiff:
    def _diff(key: str) -> ValueDiff | None:
        old = str(original.get(key) or "").strip()
        new = str(enriched.get(key) or "").strip()
        if not new or new == old:
            return None
        return ValueDiff(old=old, new=new)

    return EntityDiff(
        description=_diff("description"),
        alias=_diff("alias"),
        business_process=_diff("business_process"),
    )


def diff_fields(
    original: dict[str, Any],
    enriched: dict[str, Any],
    *,
    scope_field_names: set[str] | None = None,
) -> tuple[list[FieldDiff], list[str]]:
    """Return (changes, unchanged_in_scope)."""
    orig_by_name = {f["name"]: f for f in _iter_fields(original) if f.get("name")}
    enr_by_name = {f["name"]: f for f in _iter_fields(enriched) if f.get("name")}

    changes: list[FieldDiff] = []
    unchanged: list[str] = []

    for name, orig_field in orig_by_name.items():
        if scope_field_names is not None and name not in scope_field_names:
            continue
        if is_technical_field(name, orig_field.get("source")):
            continue
        new_field = enr_by_name.get(name)
        if not new_field:
            unchanged.append(name)
            continue

        old_desc = str(orig_field.get("description") or "").strip()
        new_desc = str(new_field.get("description") or "").strip()
        desc_diff = (
            ValueDiff(old=old_desc, new=new_desc) if new_desc and new_desc != old_desc else None
        )

        old_syn = _norm_synonyms(orig_field.get("synonyms"))
        new_syn = _norm_synonyms(new_field.get("synonyms"))
        syn_diff = (
            SynonymsDiff(old=old_syn, new=new_syn) if new_syn and new_syn != old_syn else None
        )

        if desc_diff or syn_diff:
            changes.append(FieldDiff(field_name=name, description=desc_diff, synonyms=syn_diff))
        else:
            unchanged.append(name)

    return changes, unchanged


# ── Response parsers ────────────────────────────────────────────────────────


# Opener pattern is INTENTIONALLY strict on the trailing newline — using `\s*`
# instead would let the regex eat past the fence into the first line of content
# when the model omits the lang tag (e.g. "```\nid: foo" → without the
# explicit \n the engine would consume \n + "id" as the optional lang token).
_FENCE_OPEN_RE = re.compile(r"```[ \t]*([A-Za-z0-9_-]+)?[ \t]*\r?\n")


def _strip_code_fence(text: str) -> str:
    """Strip a Markdown code fence wrapper from ``text``, tolerant of:

      * leading prose before the opening fence ("Here is the YAML:\\n```yaml\\n...")
      * any language tag (yaml / yml / json) or none at all
      * trailing whitespace after the opening fence's language tag
      * trailing prose after the closing fence
      * trailing newlines / whitespace before the closing fence
      * absence of the closing fence entirely (returns everything after the opener)

    Returns the inner content stripped of surrounding whitespace.
    When no fence is present, returns the original text trimmed.
    """
    s = text.strip()
    open_match = _FENCE_OPEN_RE.search(s)
    if open_match is None:
        return s
    start = open_match.end()
    close_idx = s.find("```", start)
    inner = s[start:close_idx] if close_idx != -1 else s[start:]
    return inner.strip()


def parse_yaml_response(text: str) -> dict[str, Any]:
    """Tolerant parser: accepts raw YAML OR a fenced ```yaml block."""
    payload = _strip_code_fence(text)
    parsed = load_yaml_text(payload)
    if not isinstance(parsed, dict):
        raise ValueError("LLM did not return a YAML mapping at the root.")
    return dict(parsed)


def _extract_json_object(s: str) -> str | None:
    """Return the first substring of ``s`` that is a parseable JSON object.

    Brace-balanced scan (string/escape aware) starting at each ``{``: the first
    one that closes into valid JSON wins. This beats a naive ``find("{")`` when
    the model emits prose/reasoning that itself contains ``{`` before the real
    object (common with reasoning models that leak a ``<think>`` trace or
    examples), and it also tolerates trailing text AFTER the JSON.
    """
    import json

    for start in (i for i, ch in enumerate(s) if ch == "{"):
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start : i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break  # this start didn't parse — try the next "{"
    return None


def parse_json_response(text: str) -> dict[str, Any]:
    """Tolerant parser: accepts raw JSON, a fenced ```json block, or JSON
    embedded in prose / reasoning-model output (``<think>…</think>`` + text)."""
    import json
    import re

    payload = _strip_code_fence(text)
    # Reasoning models (e.g. Qwen "thinking") emit a <think>…</think> trace
    # before the answer; strip it so its stray braces don't fool the scan.
    payload = re.sub(r"<think>.*?</think>", "", payload, flags=re.DOTALL | re.IGNORECASE).strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        obj = _extract_json_object(payload)
        if obj is not None:
            return json.loads(obj)
        raise


def _build_diagnostic(
    *,
    raw_yaml: dict[str, Any],
    enriched_yaml: dict[str, Any],
    raw_response: str,
    field_diffs: list[FieldDiff],
    entity_diff: EntityDiff,
) -> EnrichmentDiagnostic | None:
    """Return diagnostic info ONLY when the diff is empty.

    Empty diff with substantial LLM output is suspicious — the admin needs
    to see whether the model copied the YAML verbatim, hallucinated field
    names, or got truncated. We surface enough state to tell those apart
    without leaking the entire raw response (a 21k-token YAML is too big
    for a UI toast).
    """
    if entity_diff.description or entity_diff.alias or entity_diff.business_process:
        return None
    if field_diffs:
        return None

    orig_names = {f["name"] for f in _iter_fields(raw_yaml) if f.get("name")}
    enr_names = {f["name"] for f in _iter_fields(enriched_yaml) if f.get("name")}
    matched = orig_names & enr_names
    return EnrichmentDiagnostic(
        original_field_count=len(orig_names),
        enriched_field_count=len(enr_names),
        matched_field_count=len(matched),
        fields_only_in_enriched=sorted(enr_names - orig_names)[:20],
        fields_only_in_original=sorted(orig_names - enr_names)[:20],
        response_chars=len(raw_response),
        # Head + tail previews. Head shows whether the model framed the
        # output correctly (code fence vs prose). Tail catches "model
        # truncated mid-YAML" — the tail will be a half-line + EOF.
        response_preview=raw_response[:600],
        response_tail=raw_response[-300:] if len(raw_response) > 900 else "",
    )


def diff_from_json(
    *,
    raw_yaml: dict[str, Any],
    enrichment: dict[str, Any],
    apply_entity_level: bool,
    scope_field_names: set[str] | None,
) -> tuple[EntityDiff, list[FieldDiff], list[str]]:
    """Compute the diff directly from the JSON enrichment shape.

    Strict on what it accepts — keeps hallucinations from leaking into the
    PATCH that follows:

      * Entity-level diffs are computed only when ``apply_entity_level`` is
        True. Out-of-scope changes are dropped silently.
      * Field diffs require the field name to exist in the original YAML
        AND match ``scope_field_names`` (when provided). New / renamed
        field names are ignored — surfaced only via the diagnostic.
      * Technical fields are always excluded regardless of scope.
    """
    # ── Entity-level ────────────────────────────────────────────────────────
    entity_diff = EntityDiff()
    if apply_entity_level:
        ent = enrichment.get("entity") or {}
        if isinstance(ent, dict):
            for key in ("description", "alias", "business_process"):
                new_val = str(ent.get(key) or "").strip()
                old_val = str(raw_yaml.get(key) or "").strip()
                if new_val and new_val != old_val:
                    setattr(entity_diff, key, ValueDiff(old=old_val, new=new_val))

    # ── Field-level ─────────────────────────────────────────────────────────
    orig_by_name = {f["name"]: f for f in _iter_fields(raw_yaml) if f.get("name")}
    enriched_fields = enrichment.get("fields") or {}
    if not isinstance(enriched_fields, dict):
        enriched_fields = {}

    field_diffs: list[FieldDiff] = []
    in_scope_seen: set[str] = set()

    for name, payload in enriched_fields.items():
        if not isinstance(payload, dict):
            continue
        if scope_field_names is not None and name not in scope_field_names:
            # Out-of-scope edit — model went beyond what the admin selected.
            # Skip silently; the admin can re-run with a wider scope if they
            # want those changes.
            continue
        if name not in orig_by_name:
            # Hallucinated field name — surfaced in the diagnostic, not applied.
            continue
        if is_technical_field(name, orig_by_name[name].get("source")):
            continue

        in_scope_seen.add(name)
        orig = orig_by_name[name]

        old_desc = str(orig.get("description") or "").strip()
        new_desc = str(payload.get("description") or "").strip()
        desc_diff = (
            ValueDiff(old=old_desc, new=new_desc) if new_desc and new_desc != old_desc else None
        )

        old_syn = _norm_synonyms(orig.get("synonyms"))
        new_syn = _norm_synonyms(payload.get("synonyms"))
        # An explicit `synonyms` key with at least one item triggers a diff;
        # if it equals old, we treat it as a no-op.
        syn_diff = (
            SynonymsDiff(old=old_syn, new=new_syn) if new_syn and new_syn != old_syn else None
        )

        if desc_diff or syn_diff:
            field_diffs.append(FieldDiff(field_name=name, description=desc_diff, synonyms=syn_diff))

    # `fields_unchanged_in_scope` = the admin asked for these but the model
    # didn't return them (or returned identical values). Useful UX signal.
    if scope_field_names is not None:
        fields_unchanged = sorted(scope_field_names - {fd.field_name for fd in field_diffs})
    else:
        fields_unchanged = []

    return entity_diff, field_diffs, fields_unchanged


def _build_json_diagnostic(
    *,
    raw_yaml: dict[str, Any],
    enrichment: dict[str, Any],
    raw_response: str,
    field_diffs: list[FieldDiff],
    entity_diff: EntityDiff,
) -> EnrichmentDiagnostic | None:
    """Diagnostic helper for the JSON-output flow.

    Returns None when at least one change made it through; otherwise builds
    a snapshot of the response shape so the SPA can render a verdict.
    """
    if entity_diff.description or entity_diff.alias or entity_diff.business_process:
        return None
    if field_diffs:
        return None

    orig_names = {f["name"] for f in _iter_fields(raw_yaml) if f.get("name")}
    enriched_fields = enrichment.get("fields") or {}
    enr_names = (
        {str(k) for k in enriched_fields.keys()} if isinstance(enriched_fields, dict) else set()
    )
    matched = orig_names & enr_names
    return EnrichmentDiagnostic(
        original_field_count=len(orig_names),
        enriched_field_count=len(enr_names),
        matched_field_count=len(matched),
        fields_only_in_enriched=sorted(enr_names - orig_names)[:20],
        fields_only_in_original=sorted(orig_names - enr_names)[:20],
        response_chars=len(raw_response),
        response_preview=raw_response[:600],
        response_tail=raw_response[-300:] if len(raw_response) > 900 else "",
    )


def _build_parse_error_diagnostic(
    *,
    raw_yaml: dict[str, Any],
    raw_response: str,
    parse_error: str,
) -> EnrichmentDiagnostic:
    """Diagnostic for the parse-failure path.

    Strictly weaker than ``_build_diagnostic``: we cannot extract enriched
    field counts (the response did not parse), so we only fill cardinality
    on the original side + the raw-response previews + the parse error.
    """
    orig_names = {f["name"] for f in _iter_fields(raw_yaml) if f.get("name")}
    return EnrichmentDiagnostic(
        original_field_count=len(orig_names),
        enriched_field_count=0,
        matched_field_count=0,
        fields_only_in_enriched=[],
        fields_only_in_original=sorted(orig_names)[:20],
        response_chars=len(raw_response),
        response_preview=raw_response[:600],
        response_tail=raw_response[-600:] if len(raw_response) > 1200 else "",
        parse_error=parse_error[:500],
    )


# ── High-level entry points ─────────────────────────────────────────────────


class EnrichmentService:
    """Stateless wrapper that wires LLM + prompts + diff for the router."""

    def __init__(
        self,
        *,
        system_prompt_provider,
        organization_context_provider=None,
        workspace_context_provider=None,
    ) -> None:
        self._prompt_provider = system_prompt_provider
        self._org_provider = organization_context_provider
        # workspace_context_provider(workspace_id, entity_id) -> str | None.
        # Returns plain-text framing for the prompt or None if unavailable.
        self._workspace_provider = workspace_context_provider
        self._serializer = AskYamlSerializer()

    # ─ entity ───────────────────────────────────────────────────────────────

    def _clean_scope(
        self,
        *,
        raw_yaml: dict[str, Any],
        scope: EnrichEntityScope,
    ) -> EnrichEntityScope:
        """Drop technical / non-existent field names from the admin's checklist.

        Returns a fresh ``EnrichEntityScope`` with only enrichable fields the
        entity actually has. Used by both ``build_prompt_pair`` (so the LLM
        sees a clean scope) and ``preview_entity`` (so the diff filter uses
        the same set after the LLM call).
        """
        eligible = {
            f["name"]
            for f in _iter_fields(raw_yaml)
            if f.get("name") and not is_technical_field(f["name"], f.get("source"))
        }
        return EnrichEntityScope(
            entity_level=bool(scope.entity_level),
            field_names=[n for n in scope.field_names if n in eligible],
        )

    def _compose_messages(
        self,
        *,
        entity_id: str,
        raw_yaml: dict[str, Any],
        scope_clean: EnrichEntityScope,
        workspace_id: str | None,
    ) -> tuple[str, str]:
        """Inner helper: build (system, user) from an ALREADY-cleaned scope."""
        system_prompt = self._prompt_provider.get_prompt("enrichment")
        entity_layer = str(raw_yaml.get("layer") or "").lower() or None
        standards = self._prompt_provider.get_standards_excerpt(entity_layer)
        org_context = self._resolve_org_context()
        workspace_context = self._resolve_workspace_context(workspace_id, entity_id)

        return build_entity_prompt(
            system_prompt=system_prompt,
            standards_excerpt=standards,
            organization_context=org_context,
            workspace_context=workspace_context,
            scope=scope_clean,
            raw_yaml=raw_yaml,
            serializer=self._serializer,
        )

    def build_prompt_pair(
        self,
        *,
        entity_id: str,
        raw_yaml: dict[str, Any],
        scope: EnrichEntityScope,
        workspace_id: str | None = None,
    ) -> tuple[str, str]:
        """Compose the (system, user) messages WITHOUT invoking the LLM.

        Used by the prompt-preview endpoint so admins can inspect the exact
        text the model will see before they spend tokens. Shares the same
        path as ``preview_entity`` so there's no risk of preview / real run
        drift — they call the same builder with the same inputs.
        """
        scope_clean = self._clean_scope(raw_yaml=raw_yaml, scope=scope)
        return self._compose_messages(
            entity_id=entity_id,
            raw_yaml=raw_yaml,
            scope_clean=scope_clean,
            workspace_id=workspace_id,
        )

    def preview_entity(
        self,
        *,
        entity_id: str,
        raw_yaml: dict[str, Any],
        scope: EnrichEntityScope,
        workspace_id: str | None = None,
    ) -> EnrichEntityResponse:
        scope_clean = self._clean_scope(raw_yaml=raw_yaml, scope=scope)
        system_msg, user_msg = self._compose_messages(
            entity_id=entity_id,
            raw_yaml=raw_yaml,
            scope_clean=scope_clean,
            workspace_id=workspace_id,
        )

        provider, model = _peek_active_provider()
        started = time.monotonic()
        llm = build_llm({})
        text, tokens = _invoke_llm_chat(llm, system_msg, user_msg)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "enrich.entity model=%s tokens=%s elapsed_ms=%s entity_id=%s",
            model,
            tokens,
            elapsed_ms,
            entity_id,
        )

        try:
            enrichment_json = parse_json_response(text)
        except Exception as exc:
            # Model emitted malformed JSON. Don't 422 — return empty diff
            # with a parse-error diagnostic so the SPA shows the admin what
            # happened (raw response preview / tail / parser message).
            parse_diag = _build_parse_error_diagnostic(
                raw_yaml=raw_yaml, raw_response=text, parse_error=str(exc)
            )
            logger.warning(
                "enrich.entity PARSE_FAILED entity_id=%s tokens=%s response_chars=%s error=%s",
                entity_id,
                tokens,
                parse_diag.response_chars,
                str(exc)[:200],
            )
            return EnrichEntityResponse(
                entity_id=entity_id,
                provider=provider,
                model=model,
                entity_diff=EntityDiff(),
                field_diffs=[],
                fields_skipped_technical=sorted(
                    f["name"]
                    for f in _iter_fields(raw_yaml)
                    if f.get("name") and is_technical_field(f["name"], f.get("source"))
                ),
                fields_unchanged=[],
                tokens_used=tokens,
                elapsed_ms=elapsed_ms,
                diagnostic=parse_diag,
            )

        scope_names = set(scope_clean.field_names)
        entity_diff, field_diffs, fields_unchanged_in_scope = diff_from_json(
            raw_yaml=raw_yaml,
            enrichment=enrichment_json,
            apply_entity_level=scope_clean.entity_level,
            scope_field_names=scope_names if scope_names else None,
        )

        # PRESERVATION GUARD — cancel any description rewrite that would
        # drop value-mapping tokens (``'C'``, ``ovrll_sts``), source
        # citations (``VBAK.NETWR``), or alternative-field hints from the
        # original. Without this guard the AI silently collapses a
        # status_flag like:
        #
        #   "'C' (fully processed) -> 'CLOSE', else (A,B,NULL) -> 'OPEN'.
        #    For partial detail use ovrll_sts instead."
        #
        # into a generic phrase and the agent downstream can't write
        # correct WHERE clauses anymore.
        entity_diff, field_diffs, preservation_caveats = _apply_preservation_guard(
            entity_diff=entity_diff,
            field_diffs=field_diffs,
        )

        technical = sorted(
            f["name"]
            for f in _iter_fields(raw_yaml)
            if f.get("name") and is_technical_field(f["name"], f.get("source"))
        )

        diagnostic = _build_json_diagnostic(
            raw_yaml=raw_yaml,
            enrichment=enrichment_json,
            raw_response=text,
            field_diffs=field_diffs,
            entity_diff=entity_diff,
        )
        if diagnostic is not None:
            logger.warning(
                "enrich.entity ZERO_CHANGES entity_id=%s tokens=%s "
                "orig_fields=%s enriched_keys=%s matched=%s",
                entity_id,
                tokens,
                diagnostic.original_field_count,
                diagnostic.enriched_field_count,
                diagnostic.matched_field_count,
            )

        if preservation_caveats:
            logger.info(
                "enrich.entity PRESERVATION_GUARD entity_id=%s skipped=%d",
                entity_id,
                len(preservation_caveats),
            )

        return EnrichEntityResponse(
            entity_id=entity_id,
            provider=provider,
            model=model,
            entity_diff=entity_diff,
            field_diffs=field_diffs,
            fields_skipped_technical=technical,
            fields_unchanged=fields_unchanged_in_scope,
            caveats=preservation_caveats,
            tokens_used=tokens,
            elapsed_ms=elapsed_ms,
            diagnostic=diagnostic,
        )

    # ─ field ────────────────────────────────────────────────────────────────

    def preview_field(
        self,
        *,
        entity_id: str,
        raw_yaml: dict[str, Any],
        field_name: str,
    ) -> EnrichFieldResponse:
        fields = _iter_fields(raw_yaml)
        target = next((f for f in fields if f.get("name") == field_name), None)
        if target is None:
            raise ValueError(f"Field '{field_name}' not found in entity '{entity_id}'.")
        if is_technical_field(field_name, target.get("source")):
            raise ValueError(
                f"Field '{field_name}' is excluded from AI enrichment (technical / audit)."
            )

        system_prompt = self._prompt_provider.get_prompt("enrichment")
        entity_layer = str(raw_yaml.get("layer") or "").lower() or None
        standards = self._prompt_provider.get_standards_excerpt(entity_layer)
        org_context = self._resolve_org_context()
        yaml_text = self._serializer.to_yaml(raw_yaml)
        system_msg, user_msg = build_field_prompt(
            system_prompt=system_prompt,
            standards_excerpt=standards,
            organization_context=org_context,
            yaml_text=yaml_text,
            field_name=field_name,
        )

        provider, model = _peek_active_provider()
        started = time.monotonic()
        llm = build_llm({})
        text, tokens = _invoke_llm_chat(llm, system_msg, user_msg)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "enrich.field model=%s tokens=%s elapsed_ms=%s entity=%s field=%s",
            model,
            tokens,
            elapsed_ms,
            entity_id,
            field_name,
        )

        try:
            parsed = parse_json_response(text)
        except Exception as exc:
            raise ValueError(
                f"Could not parse enrichment JSON for field '{field_name}': {exc}"
            ) from exc

        new_desc = str(parsed.get("description") or "").strip()
        new_syn = _norm_synonyms(parsed.get("synonyms"))
        old_desc = str(target.get("description") or "").strip()
        old_syn = _norm_synonyms(target.get("synonyms"))

        desc_diff = (
            ValueDiff(old=old_desc, new=new_desc) if new_desc and new_desc != old_desc else None
        )
        syn_diff = (
            SynonymsDiff(old=old_syn, new=new_syn) if new_syn and new_syn != old_syn else None
        )

        # Same preservation guard the entity-level preview runs (BACKLOG I):
        # scrub added (TABLE.FIELD) citations, drop anti-rephrasing no-ops, and
        # CANCEL a rewrite that would lose critical tokens (value mappings,
        # citations) — explained via `caveats`. Reuses the shared guard by
        # wrapping the single diff; an empty result means the guard turned the
        # whole change into a no-op.
        _, guarded, caveats = _apply_preservation_guard(
            entity_diff=EntityDiff(),
            field_diffs=[
                FieldDiff(field_name=field_name, description=desc_diff, synonyms=syn_diff)
            ],
        )
        final_diff = guarded[0] if guarded else FieldDiff(field_name=field_name)

        return EnrichFieldResponse(
            entity_id=entity_id,
            field_name=field_name,
            provider=provider,
            model=model,
            diff=final_diff,
            tokens_used=tokens,
            elapsed_ms=elapsed_ms,
            caveats=caveats,
        )

    # ─ Relationship suggest (Modo 2 — Complete) ────────────────────────────

    def suggest_relationship_complete(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        source_raw_yaml: dict[str, Any],
        target_raw_yaml: dict[str, Any],
        workspace_id: str | None = None,
    ) -> RelationshipSuggestResponse:
        """Ask the LLM to fill in the join + cardinality + cost for a
        SOURCE→TARGET pair the admin already picked.

        Strategy for keeping the prompt small:
          - source: header + FK-shaped fields only (name+type, no descriptions)
          - target: header + primary_key fields + FK-shaped fields (name+type)
          - workspace_context: same plain-text framing as ``preview_entity``

        Any failure mode (parse error, ambiguous response, hard rule violation)
        is surfaced as a structured outcome — the SPA renders the three UX
        flavours (clean / caveats / no-match) without inspecting the raw text.
        """
        system_prompt = self._prompt_provider.get_prompt("relationship_suggest")
        org_context = self._resolve_org_context()
        workspace_context = self._resolve_workspace_context(workspace_id, source_entity_id)

        # Slim projections of both entities. We extract these once here so
        # the prompt building is straightforward and the tests can assert on
        # the prompt content without monkey-patching deep call-sites.
        source_view = _project_for_relationship(source_raw_yaml, side="source")
        target_view = _project_for_relationship(target_raw_yaml, side="target")

        system_msg, user_msg = _build_relationship_prompt(
            system_prompt=system_prompt,
            organization_context=org_context,
            workspace_context=workspace_context,
            source=source_view,
            target=target_view,
            serializer=self._serializer,
        )

        provider, model = _peek_active_provider()
        started = time.monotonic()
        llm = build_llm({})
        text, tokens = _invoke_llm_chat(llm, system_msg, user_msg)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "enrich.rel_suggest model=%s tokens=%s elapsed_ms=%s source=%s target=%s",
            model,
            tokens,
            elapsed_ms,
            source_entity_id,
            target_entity_id,
        )

        try:
            parsed = parse_json_response(text)
        except Exception as exc:
            parse_diag = _build_parse_error_diagnostic(
                raw_yaml=source_raw_yaml, raw_response=text, parse_error=str(exc)
            )
            logger.warning(
                "enrich.rel_suggest PARSE_FAILED source=%s target=%s tokens=%s error=%s",
                source_entity_id,
                target_entity_id,
                tokens,
                str(exc)[:200],
            )
            return RelationshipSuggestResponse(
                provider=provider,
                model=model,
                relationship=None,
                confidence="low",
                caveats=[],
                no_match_reason=(
                    "The model's response was not valid JSON — likely truncated "
                    "or malformed. See diagnostic for the raw response."
                ),
                tokens_used=tokens,
                elapsed_ms=elapsed_ms,
                diagnostic=parse_diag,
            )

        return _build_relationship_response(
            parsed=parsed,
            provider=provider,
            model=model,
            tokens_used=tokens,
            elapsed_ms=elapsed_ms,
            target_entity_id=target_entity_id,
        )

    # ─ private ──────────────────────────────────────────────────────────────

    def _resolve_org_context(self) -> str | None:
        if self._org_provider is None:
            return None
        try:
            return self._org_provider()
        except Exception:  # noqa: BLE001 — fail soft
            logger.debug("Organization context provider failed — proceeding without it")
            return None

    def _resolve_workspace_context(self, workspace_id: str | None, entity_id: str) -> str | None:
        """Fail-soft workspace context lookup.

        Returns None when no workspace_id was passed or the provider isn't
        wired (e.g. tests). Returns None on provider failure — the LLM
        call still runs with the entity-only context.
        """
        if not workspace_id or self._workspace_provider is None:
            return None
        try:
            return self._workspace_provider(workspace_id, entity_id)
        except Exception:  # noqa: BLE001 — fail soft
            logger.debug(
                "Workspace context provider failed for ws=%s entity=%s",
                workspace_id,
                entity_id,
            )
            return None


def _peek_active_provider() -> tuple[str, str]:
    """Best-effort read of the active provider/model for logging + the response.

    Hits the SecretsProvider — if nothing is stored yet falls back to env vars.
    Failure isn't fatal: we return ``("unknown", "")`` and the LLM call still
    runs (build_llm decides what to use).
    """
    try:
        from ask_llm_gateway.infrastructure.secrets import get_secrets_provider

        resolved = get_secrets_provider().get("llm")
    except Exception:
        resolved = None
    if resolved:
        return (
            str(resolved.get("provider") or "unknown"),
            str(resolved.get("model") or ""),
        )
    import os

    return (
        os.getenv("LLM_PROVIDER", "unknown"),
        os.getenv("LLM_MODEL", ""),
    )


# ── Relationship suggest helpers ────────────────────────────────────────────


# SAP key column prefixes — the canonical PK/FK column names that identify
# master-data entities. A field name typically takes the form
# ``<sap_col>_<origin_table>`` (e.g. ``kunnr_vbak`` = the customer column on
# VBAK). The PREFIX (before the underscore) tells us whether the column is a
# key. The SUFFIX only tells us where it came from.
#
# Anything whose prefix is in this list is treated as a FK candidate and
# shipped to the LLM. Anything else stays out to keep the prompt small —
# measures (``netwr_vbak``), texts (``arktx_vbap``), dates (``bldat_vbkd``),
# rates (``kursf_vbak``) all match by their own prefix, none of which appear
# below.
_SAP_FK_COLUMN_PREFIXES = (
    "kunnr",  # customer
    "matnr",  # material
    "lifnr",  # vendor
    "vbeln",  # sales doc number
    "ebeln",  # purchase order number
    "belnr",  # accounting doc number
    "bukrs",  # company code
    "werks",  # plant
    "lgort",  # storage location
    "ekorg",  # purchasing org
    "vkorg",  # sales org
    "vtweg",  # distribution channel
    "spart",  # division
    "auart",  # sales doc type
    "kostl",  # cost center
    "pernr",  # personnel number
    "anln1",  # asset
    "knrze",  # higher-level customer
    "posnr",  # line item number (composite FK)
    "rposn",  # reservation item
)

# Field name prefixes that are NEVER part of a relationship FK — audit /
# system / client columns that ride along every SAP table but never join.
# Checked BEFORE the FK list to make sure ``mandt_vbak`` etc. are rejected
# even if some future SAP convention recycles a similar prefix.
_NEVER_FK_PREFIXES = (
    "mandt",
    "client",
    "ersys",
    "ernam",
    "erdat",
    "erzet",
    "ernum",
    "aedat",
    "aenam",
    "aezet",
    "laeda",
    "loekz",
    "lvorm",
    "xchpf",
    "xfeld",
)


def _is_likely_fk(field_name: str, source: str | None = None) -> bool:
    """Heuristic: a field is a FK candidate when its SAP key column matches a
    known SAP key AND it is not a system/audit column.

    The SAP origin column is authoritative when the field carries ``source``
    (``VBAP.MATNR``): the published NAME may be alias-based (column naming
    mode ``alias``), where the prefix is a business word that matches nothing
    in the SAP lists. Fields without ``source`` (Gold) fall back to the name
    prefix — two-stage: exclude system fields first (mandt / ernam / etc.),
    then test against the FK list, so ``netwr_vbak`` (net value, measure) and
    ``arktx_vbap`` (item text) are correctly rejected even though their suffix
    indicates they come from VBAK / VBAP.
    """
    token = str(source or "").partition(".")[2].strip().lower()
    if token:
        if any(token.startswith(p) for p in _NEVER_FK_PREFIXES):
            return False
        return token in _SAP_FK_COLUMN_PREFIXES
    name = (field_name or "").strip().lower()
    if not name:
        return False
    if any(name.startswith(p) for p in _NEVER_FK_PREFIXES):
        return False
    if name.endswith("_at") or name.endswith("_by"):
        return False
    base = name.split("_", 1)[0]  # chars before the first underscore
    return base in _SAP_FK_COLUMN_PREFIXES


def _project_for_relationship(raw_yaml: dict[str, Any], *, side: str) -> dict[str, Any]:
    """Slim projection of an entity for the relationship-suggest prompt.

    Keeps: id, layer, module, alias, entity_role, business_process,
    primary_key, composed_of, AND a curated list of fields (name + type only).

    Field selection:
      - ALL primary_key fields, regardless of name pattern (always relevant
        for cardinality detection).
      - Fields whose SAP origin column (``source``) — or name prefix when no
        ``source`` — matches the SAP FK conventions.
      - Drop everything else — descriptions, synonyms, dimensions of measures
        etc. don't affect the join inference.

    Each kept field ships its ``source`` so the LLM sees the SAP key column
    even when the published name is alias-based.
    """
    header = {
        k: raw_yaml.get(k)
        for k in (
            "id",
            "layer",
            "module",
            "alias",
            "entity_role",
            "business_process",
            # ``db_table_name`` is the physical table the SQL executor sees.
            # We surface it so the LLM uses IT as the alias in the proposed
            # join_condition — what ends up in git matches what runs.
            "db_table_name",
        )
        if raw_yaml.get(k) is not None
    }
    pk = raw_yaml.get("primary_key") or []
    if pk:
        header["primary_key"] = list(pk)
    composed = raw_yaml.get("composed_of") or []
    if composed:
        header["composed_of"] = list(composed)

    all_fields = list(_iter_fields(raw_yaml))
    pk_names = {str(n).strip().lower() for n in pk}

    relevant: list[dict[str, Any]] = []
    for f in all_fields:
        name = str(f.get("name") or "").strip()
        if not name:
            continue
        source = str(f.get("source") or "").strip()
        if name.lower() in pk_names or _is_likely_fk(name, source):
            projected = {
                "name": name,
                "type": f.get("type") or "",
            }
            if source:
                projected["source"] = source
            relevant.append(projected)

    header["fields"] = relevant
    header["_side"] = side
    return header


def _build_relationship_prompt(
    *,
    system_prompt: str,
    organization_context: str | None,
    workspace_context: str | None,
    source: dict[str, Any],
    target: dict[str, Any],
    serializer: AskYamlSerializer,
) -> tuple[str, str]:
    """Compose (system, user) messages for the relationship-suggest call.

    The system prompt carries the rules; the user message carries the two
    slim entity projections + (optional) workspace framing. Keep it boring
    so the LLM has minimum context to drift from.
    """
    sys_parts = [system_prompt.strip()]
    if organization_context and organization_context.strip():
        sys_parts.append(
            "=" * 60 + "\nCUSTOMER CONTEXT\n" + "=" * 60 + "\n" + organization_context.strip()
        )

    user_parts: list[str] = []
    user_parts.append("Propose a relationship from SOURCE to TARGET, or return relationship: null.")
    user_parts.append("SOURCE entity (the one being edited):")
    user_parts.append(serializer.to_yaml(source))
    user_parts.append("TARGET entity (the one to join to):")
    user_parts.append(serializer.to_yaml(target))

    if workspace_context and workspace_context.strip():
        user_parts.append(
            "WORKSPACE CONTEXT (how the SOURCE is consumed):\n" + workspace_context.strip()
        )

    user_parts.append(
        "Use the EXACT id from the input as `target_entity` in the output. Use "
        "the EXACT field names from the input — do not invent.\n\n"
        "ALIAS RULE for `join_condition`: use the `db_table_name` of each "
        "entity verbatim as the alias (e.g. `VW_SALES_ORDER.matnr_vbap = "
        "VW_TRADING_GOODS.matnr_mara`). If `db_table_name` is missing on an "
        "entity, fall back to its `id` uppercased.\n\n"
        "If no confident FK match exists, set `relationship: null` and "
        "explain in `no_match_reason`."
    )

    return "\n\n".join(sys_parts), "\n\n".join(user_parts)


_ALLOWED_CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}
_ALLOWED_SAFETY = {"safe", "requires_dedup", "unsafe"}
_ALLOWED_CONFIDENCE = {"high", "medium", "low"}


def _build_relationship_response(
    *,
    parsed: dict[str, Any],
    provider: str,
    model: str,
    tokens_used: int,
    elapsed_ms: int,
    target_entity_id: str,
) -> RelationshipSuggestResponse:
    """Validate + normalise the JSON the LLM returned.

    Three terminal states:
      - relationship: null → propagate, set confidence='low', stash no_match_reason
      - relationship: present → enforce enums / required fields, drop bad values
      - relationship: malformed (wrong types, missing target_entity) → degrade
        to no_match with a synthetic no_match_reason so the SPA still has
        something to show.
    """
    raw_rel = parsed.get("relationship")
    confidence_raw = str(parsed.get("confidence") or "").strip().lower()
    confidence: str = confidence_raw if confidence_raw in _ALLOWED_CONFIDENCE else "low"
    caveats = [str(c).strip() for c in (parsed.get("caveats") or []) if str(c).strip()]
    no_match_reason = parsed.get("no_match_reason")
    if no_match_reason is not None:
        no_match_reason = str(no_match_reason).strip() or None

    if raw_rel is None or not isinstance(raw_rel, dict):
        return RelationshipSuggestResponse(
            provider=provider,
            model=model,
            relationship=None,
            confidence="low",
            caveats=caveats,
            no_match_reason=no_match_reason
            or "The model could not find a confident FK match between the two entities.",
            tokens_used=tokens_used,
            elapsed_ms=elapsed_ms,
        )

    # Enforce enum fields — values outside the whitelist drop to defaults so
    # the SPA never has to render unknown strings.
    rel_type = str(raw_rel.get("relationship_type") or "many_to_one").strip()
    if rel_type not in _ALLOWED_CARDINALITIES:
        rel_type = "many_to_one"
        caveats.append("relationship_type from model was invalid; defaulted to many_to_one.")

    agg_safety = str(raw_rel.get("aggregation_safety") or "").strip()
    if agg_safety not in _ALLOWED_SAFETY:
        agg_safety = "requires_dedup" if rel_type in ("one_to_many", "many_to_many") else "safe"

    try:
        cost = float(raw_rel.get("traversal_cost") or 0)
        if cost <= 0:
            cost = 1.0
    except (TypeError, ValueError):
        cost = 1.0

    # Honour the LLM's target_entity if it matches the input; otherwise force
    # it to the canonical id passed in. Defends against the model echoing a
    # mis-cased or aliased id back.
    target_in_response = str(raw_rel.get("target_entity") or "").strip()
    if target_in_response and target_in_response != target_entity_id:
        caveats.append(
            f"Model echoed target as '{target_in_response}'; using canonical "
            f"'{target_entity_id}' instead."
        )

    suggestion = SuggestedRelationship(
        target_entity=target_entity_id,
        relationship_type=rel_type,
        join_condition=_clean_join_condition(raw_rel.get("join_condition")),
        semantic_label=_clean_str(raw_rel.get("semantic_label")),
        traversal_cost=cost,
        aggregation_safety=agg_safety,
        cross_module=bool(raw_rel.get("cross_module"))
        if raw_rel.get("cross_module") is not None
        else None,
        description=_clean_str(raw_rel.get("description")),
    )

    return RelationshipSuggestResponse(
        provider=provider,
        model=model,
        relationship=suggestion,
        confidence=confidence,  # type: ignore[arg-type]
        caveats=caveats,
        no_match_reason=None,
        tokens_used=tokens_used,
        elapsed_ms=elapsed_ms,
    )


def _clean_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# ── Description-preservation validator ──────────────────────────────────────


# Quoted value tokens: 'C', 'CLOSE', 'BLOCKED'. The original descriptions
# of status_flag fields tend to use these to spell out the value mapping
# explicitly. If the AI rewrite drops them, downstream SQL generators
# can't reason about WHERE clauses anymore.
_QUOTED_TOKEN_RE = re.compile(r"'([A-Za-z0-9_]+)'")

# Bare-LHS mappings like ``X = active``, ``1 -> CLOSE``. The LHS (1-8 chars)
# is the value the description is explaining. We don't capture the RHS as
# critical because the meaning side is usually paraphrased on rewrite — the
# value side must survive verbatim.
_EQ_OR_ARROW_TOKEN_RE = re.compile(r"\b([A-Za-z0-9_]{1,8})\s*(?:=|->)\s*[A-Za-z0-9_']+")

# SAP-style table.field citations: ``VBAK.NETWR``, ``VBUK.GBSTK``. Must
# survive — the LLM downstream uses them as anchor to write JOINs and to
# pick the right column for a given business meaning.
_TABLE_FIELD_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\.([A-Z][A-Z0-9_]+)\b")


def _extract_critical_tokens(text: str) -> set[str]:
    """Pull value-mapping / source-citation / field-reference tokens.

    Returned set is normalised (upper-cased single tokens; TABLE.FIELD
    citations kept verbatim) so preservation comparisons are semantic
    instead of literal. Used by the preview-time validator to decide
    whether an AI rewrite would silently drop information the agent needs.
    """
    if not text:
        return set()
    tokens: set[str] = set()
    for m in _QUOTED_TOKEN_RE.finditer(text):
        tokens.add(m.group(1).upper())
    for m in _EQ_OR_ARROW_TOKEN_RE.finditer(text):
        # LHS of the mapping (the value being explained).
        tokens.add(m.group(1).upper())
    for m in _TABLE_FIELD_RE.finditer(text):
        tokens.add(f"{m.group(1)}.{m.group(2)}")
    return tokens


def _description_preserves_critical_info(old: str, new: str) -> tuple[bool, set[str]]:
    """Check whether ``new`` keeps the critical tokens of ``old``.

    Returns ``(preserved, missing)``. ``preserved`` is True when either:
      - ``old`` had nothing critical to preserve, OR
      - ``new`` covers every critical token from ``old``.

    Otherwise ``preserved=False`` and ``missing`` is the set of tokens the
    rewrite would drop — the caller cancels the change and surfaces the
    missing tokens to the admin.
    """
    old_tokens = _extract_critical_tokens(old or "")
    if not old_tokens:
        return True, set()
    new_tokens = _extract_critical_tokens(new or "")
    missing = old_tokens - new_tokens
    return len(missing) == 0, missing


# Pattern for a trailing " (TABLE.FIELD)" SAP-style citation tacked onto a
# description. The LLM keeps adding these despite the prompt explicitly
# forbidding it — probably because we ship `sap_origin` as anchoring
# context. We strip them server-side when the original didn't already have
# a citation (preservation rule still wins when it did).
_TRAILING_CITATION_RE = re.compile(r"\s*\(\s*[A-Z][A-Z0-9_]{2,}\.[A-Z][A-Z0-9_]+\s*\)\s*\.?\s*$")


def _strip_added_table_field_citation(old: str, new: str) -> tuple[str, bool]:
    """Remove a trailing ``(TABLE.FIELD)`` citation when the original
    description didn't have one.

    Returns ``(cleaned, was_stripped)``. ``was_stripped=True`` means a
    citation was removed from ``new`` because it was not present in
    ``old`` — the LLM violated rule #4 of the system prompt and we cleaned
    it up. ``was_stripped=False`` either no citation existed or the
    original already had it (preservation rule still wins).
    """
    if not new:
        return new, False
    if not _TRAILING_CITATION_RE.search(new):
        return new, False
    # Preservation: if the original already had a citation anywhere in its
    # text, keep ``new`` as-is — rule 6 protects existing citations.
    if old and _TABLE_FIELD_RE.search(old):
        return new, False
    cleaned = _TRAILING_CITATION_RE.sub("", new).strip()
    return cleaned, True


def _apply_preservation_guard(
    *,
    entity_diff: EntityDiff,
    field_diffs: list[FieldDiff],
) -> tuple[EntityDiff, list[FieldDiff], list[str]]:
    """Cancel description rewrites that would drop critical tokens.

    Two passes:
      1. Entity-level ``description`` — if the AI's new wording loses value
         mappings / TABLE.FIELD citations from the current one, the change
         is dropped (alias / business_process changes survive).
      2. Each field's ``description`` — same rule. If the field's diff was
         description-only and we cancel it, the entry is removed from
         field_diffs entirely so the SPA doesn't render a no-op card.

    Returns the (possibly trimmed) diff objects + a list of caveat messages
    explaining each cancellation — these go in ``EnrichEntityResponse.caveats``
    so the admin sees what was preserved and why.
    """
    caveats: list[str] = []

    def _scrub(old: str, new: str) -> tuple[str, bool]:
        """Strip a trailing TABLE.FIELD citation that the LLM added when it
        wasn't in the original. Returns (clean_new, was_stripped)."""
        return _strip_added_table_field_citation(old, new)

    if entity_diff.description is not None:
        # First: strip added (TABLE.FIELD) citations the LLM tacked on.
        cleaned_new, was_stripped = _scrub(entity_diff.description.old, entity_diff.description.new)
        if was_stripped:
            entity_diff = EntityDiff(
                description=ValueDiff(old=entity_diff.description.old, new=cleaned_new),
                alias=entity_diff.alias,
                business_process=entity_diff.business_process,
            )
        # Then: if the cleaned new equals the old, drop the change entirely
        # (anti-rephrasing — would otherwise show as a no-op diff card).
        if (
            entity_diff.description is not None
            and entity_diff.description.old.strip() == entity_diff.description.new.strip()
        ):
            entity_diff = EntityDiff(
                description=None,
                alias=entity_diff.alias,
                business_process=entity_diff.business_process,
            )
        # Finally: preservation guard — would the rewrite drop value mappings
        # or other critical tokens from the original?
        if entity_diff.description is not None:
            ok, missing = _description_preserves_critical_info(
                entity_diff.description.old, entity_diff.description.new
            )
            if not ok:
                caveats.append(
                    "Entity description: kept original — AI rewrite would have "
                    f"dropped {sorted(missing)}."
                )
                entity_diff = EntityDiff(
                    description=None,
                    alias=entity_diff.alias,
                    business_process=entity_diff.business_process,
                )

    filtered: list[FieldDiff] = []
    for fd in field_diffs:
        desc = fd.description
        syn = fd.synonyms
        if desc is not None:
            # Same three-pass cleanup as entity-level: scrub → anti-rephrase →
            # preservation guard.
            cleaned_new, _ = _scrub(desc.old, desc.new)
            if cleaned_new != desc.new:
                desc = ValueDiff(old=desc.old, new=cleaned_new)
            if desc.old.strip() == desc.new.strip():
                desc = None
            elif desc is not None:
                ok, missing = _description_preserves_critical_info(desc.old, desc.new)
                if not ok:
                    caveats.append(
                        f"Field '{fd.field_name}' description: kept original "
                        f"— AI rewrite would have dropped {sorted(missing)}."
                    )
                    desc = None
        if desc is None and syn is None:
            # Whole field-diff turned into a no-op after the guard; skip it
            # so the preview doesn't show empty rows.
            continue
        filtered.append(FieldDiff(field_name=fd.field_name, description=desc, synonyms=syn))

    return entity_diff, filtered, caveats


# Forbidden tokens in join_condition — MANDT enforcement. Hard rule from the
# system prompt; we double-check at parse time so a model that ignored the
# instruction can't slip a `MANDT = MANDT` clause into the workspace.
_MANDT_FORBIDDEN = ("mandt", "client_id", "tenant")


def _clean_join_condition(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    lowered = s.lower()
    # If MANDT/client/tenant snuck into the condition, strip the offending
    # AND-clause(s). We split on AND, drop any clause that references the
    # forbidden tokens, re-join the rest. A side-effect-free defense.
    if any(tok in lowered for tok in _MANDT_FORBIDDEN):
        clauses = [c.strip() for c in __split_and(s) if c.strip()]
        kept = [c for c in clauses if not any(tok in c.lower() for tok in _MANDT_FORBIDDEN)]
        if not kept:
            return None
        return " AND ".join(kept)
    return s


def __split_and(s: str) -> list[str]:
    # Case-insensitive split on " AND " — keeps the parser private to this
    # validator (we don't want join_condition rewrites leaking through).
    return re.split(r"\s+AND\s+", s, flags=re.IGNORECASE)

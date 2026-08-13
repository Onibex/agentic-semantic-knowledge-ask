"""DDL → ASK YAML mapping — deterministic skeleton first, LLM as annotator.

For every ``CREATE TABLE`` with a typed column list the pipeline is:

1. ``ddl_parser.parse_relations`` extracts the MECHANICAL facts in code —
   byte-exact column names, raw types, the declared key, the physical table
   name. Nothing here depends on a model transcribing 76 column names.
2. One schema-forced LLM call per relation (``ask_llm_gateway.application
   .structured``) fills the SEMANTIC annotation only: business name,
   descriptions, field roles, classification. The Pydantic schema makes the
   required keys impossible to omit.
3. ``ddl_skeleton.build_skeleton`` assembles the entity per the layer
   standards. An unavailable/unparsed annotation degrades to mechanical
   defaults (empty descriptions, type-derived roles) — the import still lands,
   In Review.

Views / CTAS / column-less statements fall back to the legacy full-LLM YAML
path (the editable ``ddl_mapping`` prompt), and EVERY silver/gold doc — from
either path — passes the deterministic ``module`` backstop before import: a
missing ``module`` can no longer 422 the batch.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .ddl_parser import CREATE_RELATION_RE as _CREATE_RELATION_RE
from .ddl_parser import ParsedRelation, parse_relations
from .ddl_skeleton import (
    DEFAULT_MODULE,
    EntityAnnotation,
    annotation_user_payload,
    build_skeleton,
    detect_module,
)

logger = logging.getLogger(__name__)

# Largest DDL we'll forward to the LLM. Guards against an accidental paste of a
# whole schema dump (cost + context blow-up). ~50k chars ≈ a few thousand lines.
DDL_MAX_CHARS = 50_000

# A fenced code block anywhere in the text (```yaml … ``` or bare ``` … ```),
# tolerant of prose before/after it.
_FENCE_RE = re.compile(r"```(?:ya?ml)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)

# A line that plausibly starts YAML content: a top-level key, a list item, or a
# document separator. Used to trim leading prose when there is no fence.
_YAML_LINE_RE = re.compile(r"^\s*(?:- |---\s*$|[A-Za-z_][\w-]*\s*:)")

# A JOIN keyword in the DDL body (a VIEW / CTAS / materialized view). Its PRESENCE
# means the relation genuinely composes multiple tables; its ABSENCE means a bare
# CREATE TABLE — which cannot be a multi-source join no matter what the model
# infers from column-name suffixes (`_mara`, `_makt`, …). `\bJOIN\b` deliberately
# does not match column names like `join_key` (underscore is a word char).
_JOIN_RE = re.compile(r"\bJOIN\b", re.IGNORECASE)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    """Remove ``--`` line and ``/* */`` block comments so a JOIN mentioned only in
    a comment doesn't defeat the bare-table detection."""
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", sql or ""))


def _normalize_flat_entity(docs: list[str], ddl: str, layer: str) -> tuple[list[str], list[str]]:
    """Deterministic guardrail for a Silver/Gold entity that the model gets wrong on
    Nova Pro. Applies to both layers (Gold reuses ``SilverField`` and is always a
    single physical table); two fixes:

    (a) COMPOSITION, **SILVER ONLY** (bare CREATE TABLE only — no JOIN anywhere in the
        DDL) — a bare table cannot be a multi-source join, so it must be flat:
        ``composed_of`` = its own physical table, no ``join_graph``. The model still
        splits it into several bronze tables from column-name suffixes (`_mara`,
        `_makt`), which then trips the multi-table ``join_graph`` invariant (no join
        conditions exist to derive). Gold is exempt because neither key exists in its
        contract any more (see ``GoldNode``) — writing them there would only produce
        values Pydantic drops on load.

    (b) FIELD NAME + SOURCE (any DDL shape) — the field ``name`` IS the physical SQL
        column (what the query SELECTs). The model tends to strip the provenance
        suffix onto a "business" name (`mandt_vbak` → ``name: mandt``) and hide the
        real column in ``source`` (``{table}.mandt_vbak``). That makes every generated
        query reference a non-existent column. When ``source`` self-references the
        entity's own table (``{db_table_name}.<col>``), ``<col>`` is authoritative —
        restore it as ``name`` and then DROP the ``source``: a self-reference is
        redundant noise (the table is already in ``db_table_name``) and NOT real bronze
        lineage, which the design says ``source`` must never fabricate. A ``source``
        pointing at a DIFFERENT table means the model identified a genuine origin, so
        that field's name and source are both left alone.

    Rewritten in code so the import never depends on the model obeying the prompt.
    Returns ``(docs, warnings)``; a doc is left untouched when unparseable, not the
    target layer, or has no ``db_table_name`` to anchor on."""
    if layer not in ("silver", "gold"):
        return docs, []
    is_bare_table = not _JOIN_RE.search(_strip_sql_comments(ddl))
    from ask_knowledge_graph.infrastructure.yaml_serializer import dump_yaml, load_yaml_text

    out: list[str] = []
    warnings: list[str] = []
    for doc in docs:
        try:
            parsed = load_yaml_text(doc)
        except Exception:  # noqa: BLE001 — leave unparseable docs for the retry/parser path
            out.append(doc)
            continue
        if not isinstance(parsed, dict) or parsed.get("layer") != layer:
            out.append(doc)
            continue
        flat_name = str(parsed.get("db_table_name") or parsed.get("name") or "").strip()
        if not flat_name:
            out.append(doc)  # nothing safe to anchor on — let validation surface it
            continue
        changed = False
        label = layer.capitalize()

        # (a) collapse a wrongly-split composition to a single flat table (bare table
        #     only — a JOIN body carries real composition we must not discard).
        composed = parsed.get("composed_of")
        composed_list = (
            [c for c in composed if str(c).strip()] if isinstance(composed, list) else []
        )
        join_graph = parsed.get("join_graph")
        has_join_graph = isinstance(join_graph, list) and bool(join_graph)
        if layer == "gold" and (composed_list or has_join_graph):
            # Neither key belongs to a Gold. Drop them outright rather than
            # normalizing them — leaving them in the YAML the user is about to save
            # would write dead keys that the model then silently ignores on load.
            parsed.pop("composed_of", None)
            parsed.pop("join_graph", None)
            changed = True
            warnings.append(
                f"'{parsed.get('id') or flat_name}': dropped `composed_of` / `join_graph` — "
                f"neither is part of the Gold contract. A Gold's physical table is "
                f"`db_table_name`; its lineage is `relationships[]` plus the description."
            )
        elif is_bare_table and (len(composed_list) > 1 or has_join_graph):
            parsed["composed_of"] = [flat_name]
            parsed.pop("join_graph", None)
            changed = True
            warnings.append(
                f"'{parsed.get('id') or flat_name}' was mapped from a single CREATE TABLE "
                f"(no JOIN) — flattened to a single-table {label} (composed_of=[{flat_name}], "
                f"no join_graph). Column suffixes like `_mara`/`_makt` are field lineage, not "
                f"separate source tables; add a join_graph in the editor if truly derived."
            )

        # (b) restore each field's physical column name from a self-referencing
        #     source, then drop that redundant self-reference.
        prefix = f"{flat_name}."
        renamed: list[tuple[str, str]] = []
        dropped_source = 0
        fields = parsed.get("fields")
        if isinstance(fields, list):
            for fld in fields:
                if not isinstance(fld, dict):
                    continue
                src = str(fld.get("source") or "").strip().strip('"').strip("`")
                if not src.startswith(prefix):
                    continue  # origin points elsewhere (or none) — trust the model's field
                col = src[len(prefix) :].strip().strip('"').strip("`")
                if col and fld.get("name") != col:
                    renamed.append((str(fld.get("name")), col))
                    fld["name"] = col
                fld.pop("source", None)  # self-ref = no real lineage → redundant noise
                dropped_source += 1
                changed = True
        if renamed:
            sample = f"{renamed[0][0]!r}→{renamed[0][1]!r}"
            warnings.append(
                f"'{parsed.get('id') or flat_name}': restored {len(renamed)} field name(s) to "
                f"their physical SQL column (e.g. {sample}) — the query engine SELECTs `name`, "
                f"so it must match the physical column, not a suffix-stripped alias."
            )
        if dropped_source:
            warnings.append(
                f"'{parsed.get('id') or flat_name}': dropped {dropped_source} redundant "
                f"self-referencing `source` value(s) — a flat {label} has no bronze lineage, "
                f"and `db_table_name` already declares the physical table."
            )

        out.append(dump_yaml(parsed) if changed else doc)
    return out, warnings


def _ensure_module(
    docs: list[str], *, layer: str, module: str = DEFAULT_MODULE
) -> tuple[list[str], list[str]]:
    """Deterministic backstop: a silver/gold doc without a non-empty ``module``
    gets ``module`` (auto-detected upstream, else ``gen``). The 2026-08-12
    ClickHouse import failed exactly here — the model omitted the key and the
    import 422'd; the guarantee that ``module`` is present must not depend on
    the model obeying the prompt. Unparseable docs pass through untouched (the
    import surfaces those)."""
    if layer not in ("silver", "gold"):
        return docs, []
    from ask_knowledge_graph.infrastructure.yaml_serializer import dump_yaml, load_yaml_text

    out: list[str] = []
    warnings: list[str] = []
    for doc in docs:
        try:
            parsed = load_yaml_text(doc)
        except Exception:  # noqa: BLE001 — the per-doc import reports these
            out.append(doc)
            continue
        if not isinstance(parsed, dict) or parsed.get("layer") != layer:
            out.append(doc)
            continue
        current = parsed.get("module")
        present = (
            any(str(m).strip() for m in current)
            if isinstance(current, list)
            else bool(str(current or "").strip())
        )
        if present:
            out.append(doc)
            continue
        parsed["module"] = module
        warnings.append(
            f"'{parsed.get('id') or parsed.get('name') or '(no id)'}': `module` was missing — "
            f"defaulted to '{module}' (it drives the workspace path); adjust it in the editor "
            f"if the entity belongs to a specific module."
        )
        out.append(dump_yaml(parsed))
    return out, warnings


def validate_ddl_input(ddl: str, *, max_chars: int = DDL_MAX_CHARS) -> None:
    """Fail-fast shape/size guard run BEFORE the LLM call (§7.1).

    Raises ``ValueError`` (the router maps it to HTTP 400) so garbage / non-DDL /
    oversized pastes never reach — and never cost — the model.
    """
    text = (ddl or "").strip()
    if not text:
        raise ValueError("ddl must not be empty.")
    if len(text) > max_chars:
        raise ValueError(
            f"DDL too large ({len(text)} chars > {max_chars} limit) — "
            f"split it into smaller batches."
        )
    if not _CREATE_RELATION_RE.search(text):
        raise ValueError(
            "No CREATE TABLE/VIEW statement found — paste SQL DDL "
            "(CREATE TABLE, CREATE VIEW, or CREATE MATERIALIZED VIEW)."
        )


def count_create_tables(ddl: str) -> int:
    """How many relation definitions the input declares — ``CREATE TABLE`` /
    ``CREATE VIEW`` / ``CREATE MATERIALIZED VIEW`` (multi-relation check)."""
    return len(_CREATE_RELATION_RE.findall(ddl or ""))


def extract_yaml_payload(text: str) -> str:
    """Pull the YAML out of an LLM response, tolerant of surrounding prose (§7.1).

    Strategy (conservative, never raises):
      1. If a fenced block exists anywhere, return the FIRST block's content —
         this handles ``Here is the YAML:\\n```yaml … ``` \\nLet me know…``.
      2. Otherwise trim leading prose down to the first YAML-looking line and
         return the rest. If nothing looks like YAML, return the stripped text
         unchanged so the parser fails with a clear message.
    """
    t = (text or "").strip()
    if not t:
        return ""
    m = _FENCE_RE.search(t)
    if m:
        return m.group(1).strip()
    lines = t.splitlines()
    for i, ln in enumerate(lines):
        if _YAML_LINE_RE.match(ln):
            return "\n".join(lines[i:]).strip()
    return t


def _any_unparseable(docs: list[str]) -> bool:
    """True if any doc fails to parse as a YAML mapping (triggers a retry).

    Smaller models occasionally drift indentation on long field lists, yielding
    YAML that raises on load — a fresh regeneration is usually clean."""
    from ask_knowledge_graph.infrastructure.yaml_serializer import load_yaml_text

    for doc in docs:
        try:
            parsed = load_yaml_text(doc)
        except Exception:  # noqa: BLE001 — malformed → needs a retry
            return True
        if not isinstance(parsed, dict):
            return True
    return False


def _invoke_llm_chat(llm: Any, system: str, user: str) -> tuple[str, int]:
    from langchain_core.messages import HumanMessage, SystemMessage

    result = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = result.content if hasattr(result, "content") else result
    text = _content_to_text(content)
    tokens = 0
    usage = getattr(result, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        tokens = int(usage.get("total_tokens", 0) or 0)
    return text, tokens


def _content_to_text(content: Any) -> str:
    """Flatten a LangChain message content (str or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def split_yaml_docs(text: str) -> list[str]:
    """Split a multi-document YAML string on lines that are exactly ``---``."""
    docs: list[str] = []
    cur: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            chunk = "\n".join(cur).strip()
            if chunk:
                docs.append(chunk)
            cur = []
        else:
            cur.append(line)
    tail = "\n".join(cur).strip()
    if tail:
        docs.append(tail)
    return docs


class DdlImportService:
    def __init__(self, prompts_service: Any | None = None, llm: Any | None = None) -> None:
        self._prompts = prompts_service
        self._llm = llm

    def _system_prompt(self) -> str:
        return self._prompt_body("ddl_mapping")

    def _prompt_body(self, key: str) -> str:
        if self._prompts is not None:
            try:
                return self._prompts.get_prompt(key)
            except Exception:  # noqa: BLE001
                pass
        from .system_prompts_service import _DEFAULT_PROMPTS

        return _DEFAULT_PROMPTS[key]

    def _get_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        from ask_llm_gateway.application.factory import build_llm

        return build_llm({})

    def generate_yaml(
        self,
        ddl: str,
        *,
        layer: str,
        source_system: str,
        context: str = "",
        module: str | None = None,
        max_attempts: int = 3,
    ) -> tuple[list[str], int, list[str]]:
        """Return ``(yaml_docs, tokens_used, warnings)`` — one YAML doc per table.

        Deterministic split: every relation with a typed column list is built by
        ``build_skeleton`` (code owns names/types/keys; one schema-forced LLM
        call annotates semantics, degrading to mechanical defaults when the
        provider can't honor the schema). Views/CTAS/unparseable statements go
        through the legacy full-LLM YAML path with its retry loop. Both paths
        end at the ``module`` backstop — a silver/gold doc can no longer reach
        the importer without one.

        ``module`` is normally ``None``: it is auto-detected PER RELATION from
        the physical table name (``SILVER_SD_*`` → ``sd``) against a whitelist,
        falling back to ``gen``. Pass a value only as an explicit override — it
        then applies to every relation in the batch.
        """
        total_tokens = 0
        warnings: list[str] = []
        docs: list[str] = []

        relations = parse_relations(ddl)
        skeleton_rels = [r for r in relations if r.skeleton_eligible]
        fallback_rels = [r for r in relations if not r.skeleton_eligible]

        if skeleton_rels:
            from ask_knowledge_graph.infrastructure.yaml_serializer import dump_yaml

            for rel in skeleton_rels:
                annotation, tokens, ann_error = self._annotate(rel, layer=layer, context=context)
                total_tokens += tokens
                if ann_error:
                    warnings.append(
                        f"'{rel.name}': semantic annotation degraded ({ann_error}) — "
                        f"the entity imports with mechanical defaults; enrich it In Review."
                    )
                doc, skel_warnings = build_skeleton(
                    rel,
                    layer=layer,
                    source_system=source_system,
                    module=module,
                    annotation=annotation,
                    context=context,
                )
                warnings.extend(skel_warnings)
                docs.append(dump_yaml(doc))

        if fallback_rels or not relations:
            # Statements the parser can't own (views, CTAS, column-less) — or a
            # paste the slicer didn't recognize at all — take the legacy path.
            legacy_ddl = (
                "\n\n".join(r.statement for r in fallback_rels) if relations else (ddl or "")
            )
            # Views/CTAS take the AI path BY DESIGN (their columns live in a query
            # body) — only an unparseable TABLE is worth flagging.
            unparsed_tables = [r for r in fallback_rels if not r.is_view]
            if unparsed_tables:
                names = ", ".join(r.name or "(unnamed)" for r in unparsed_tables)
                warnings.append(
                    f"Mapped via the full-AI path (no typed column list to parse): {names}."
                )
            # The legacy path has no per-relation build step, so detect once off
            # the first fallback relation's name (an explicit override wins).
            legacy_module = detect_module(
                fallback_rels[0].name if fallback_rels else "", declared=module
            )
            legacy_docs, tokens, legacy_warnings = self._generate_legacy(
                legacy_ddl,
                layer=layer,
                source_system=source_system,
                context=context,
                module=legacy_module,
                max_attempts=max_attempts,
            )
            total_tokens += tokens
            warnings.extend(legacy_warnings)
            docs.extend(legacy_docs)

        # Backstop only fires on docs that still carry no module — skeleton docs
        # always do, so in practice this covers the legacy path.
        docs, module_warnings = _ensure_module(
            docs, layer=layer, module=detect_module("", declared=module)
        )
        warnings.extend(module_warnings)
        return docs, total_tokens, warnings

    # ── Structured annotation (skeleton path) ────────────────────────────────

    def _annotate(
        self, rel: ParsedRelation, *, layer: str, context: str
    ) -> tuple[EntityAnnotation | None, int, str | None]:
        """One schema-forced call for the semantic annotation of ``rel``.
        Returns ``(annotation | None, tokens, error | None)`` — never raises;
        a second attempt covers transient parse misses."""
        from ask_knowledge_graph.domain.language import authoring_directive
        from ask_knowledge_graph.infrastructure.language_config import (
            resolve_semantic_language,
        )
        from ask_llm_gateway.application.structured import invoke_structured

        # The language block is appended at CALL time so the deployment flag stays
        # authoritative over an edited `ddl_annotation` override, and so a Spanish
        # deployment annotates an English DDL in Spanish (the layer's language is
        # what retrieval matches against, not the DDL's).
        system = (
            self._prompt_body("ddl_annotation")
            + "\n\n"
            + authoring_directive(resolve_semantic_language())
        )
        user = annotation_user_payload(rel, layer=layer, context=context)
        try:
            llm = self._get_llm()
        except Exception as exc:  # noqa: BLE001 — no provider configured
            return None, 0, f"LLM unavailable: {exc}"

        tokens = 0
        error: str | None = None
        for _ in range(2):
            result = invoke_structured(llm, schema=EntityAnnotation, system=system, user=user)
            tokens += result.tokens
            if result.parsed is not None:
                return result.parsed, tokens, None
            error = result.error
        return None, tokens, error

    # ── Legacy full-LLM path (views / CTAS / unparseable statements) ─────────

    def _generate_legacy(
        self,
        ddl: str,
        *,
        layer: str,
        source_system: str,
        context: str,
        module: str = DEFAULT_MODULE,
        max_attempts: int = 3,
    ) -> tuple[list[str], int, list[str]]:
        """The original prompt-then-parse loop. Regenerates up to
        ``max_attempts`` times when the model produces YAML that fails to parse
        — a smaller model drifts indentation on long field lists and a fresh
        pass is usually clean. Tokens accumulate across attempts. A *persistent*
        failure on a wide table is usually output truncation (the YAML hit the
        token ceiling), which retries cannot fix — the warning says so.
        """
        total_tokens = 0
        last: tuple[list[str], list[str]] = ([], [])
        for _ in range(max(1, max_attempts)):
            docs, tokens, warnings = self._generate_once(ddl, layer, source_system, context, module)
            total_tokens += tokens
            last = (docs, warnings)
            if not _any_unparseable(docs):
                return docs, total_tokens, warnings
        # Still malformed after the retries — return the last attempt with a flag
        # so the route surfaces the bad doc(s) per-item rather than silently.
        docs, warnings = last
        # A large-but-unparseable doc ≈ truncated at the output-token ceiling
        # (~8k tokens ≈ ~12k+ chars); retries don't help — raising the ceiling does.
        likely_truncated = any(len(d) > 12_000 for d in docs)
        hint = (
            "the YAML was likely TRUNCATED at the output-token ceiling — raise "
            "LLM_MAX_TOKENS (e.g. 16384) and re-run"
            if likely_truncated
            else "re-run, or split/simplify the table"
        )
        warnings = [
            *warnings,
            f"The model produced malformed YAML for one or more tables even after "
            f"{max(1, max_attempts)} attempts — {hint}. The raw output is shown under "
            f"'Generated YAML' for review.",
        ]
        return docs, total_tokens, warnings

    def _generate_once(
        self, ddl: str, layer: str, source_system: str, context: str = "", module: str = "gen"
    ) -> tuple[list[str], int, list[str]]:
        system = self._system_prompt()
        # Wire the resolved source-system profile's guidance into the system
        # prompt so the model maps types in that system's vocabulary (e.g. SAP
        # ABAP DDIC codes vs ANSI SQL). The TypeMapper still normalizes on import,
        # but a source-guided first pass yields cleaner aliases/types (Phase C1).
        from ask_knowledge_graph.domain.source_profiles import get_profile

        fragment = get_profile(source_system).prompt_fragment
        if fragment:
            system = f"{system}\n\nSOURCE SYSTEM GUIDANCE:\n{fragment}"
        # Author-supplied business context — authoritative for descriptions/aliases.
        context_block = (
            f"BUSINESS CONTEXT (authoritative — use it for accurate descriptions and "
            f"business aliases, do not contradict it):\n{context.strip()}\n\n"
            if context and context.strip()
            else ""
        )
        user = (
            f"LAYER: {layer}\nSOURCE_SYSTEM: {source_system}\nMODULE: {module}\n\n"
            f"{context_block}DDL:\n{ddl.strip()}"
        )
        text, tokens = _invoke_llm_chat(self._get_llm(), system, user)
        cleaned = extract_yaml_payload(text)
        docs = split_yaml_docs(cleaned)
        if not docs and cleaned:
            docs = [cleaned]

        warnings: list[str] = []
        input_tables = count_create_tables(ddl)
        if input_tables > 1 and len(docs) < input_tables:
            warnings.append(
                f"Input had {input_tables} CREATE TABLE statements but the model emitted "
                f"{len(docs)} YAML document(s) — a table may have been merged or dropped. "
                f"Review the generated YAML."
            )
        # Deterministic guardrail (Silver + Gold): a flat entity's field names are the
        # physical columns, self-referencing `source` is dropped, and a bare-table
        # composition is flattened — regardless of what the model inferred from
        # column-name suffixes.
        docs, norm_warnings = _normalize_flat_entity(docs, ddl, layer)
        warnings.extend(norm_warnings)
        return docs, tokens, warnings

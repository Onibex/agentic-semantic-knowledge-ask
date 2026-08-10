"""DDL → ASK YAML mapping via the LLM (UX_CHANGES audit CH-6, Iter 6).

Maps SQL DDL (one or more ``CREATE TABLE`` statements) into ASK semantic-layer
YAML at a chosen layer, using the editable ``ddl_mapping`` system prompt. Returns
one YAML document per table (the router imports each into the workspace).

Mirrors the enrichment service's LLM-call pattern (build_llm → invoke → parse);
kept separate so the prompt + parsing live in one testable place.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Largest DDL we'll forward to the LLM. Guards against an accidental paste of a
# whole schema dump (cost + context blow-up). ~50k chars ≈ a few thousand lines.
DDL_MAX_CHARS = 50_000

# Matches a CREATE for any queryable relation we can turn into an entity:
#   CREATE [OR REPLACE] [<qualifier>...] TABLE|VIEW
# where <qualifier> is any of the vendor keywords that can sit between CREATE
# and TABLE/VIEW (Snowflake dynamic/transient/iceberg tables, materialized
# views, temp/global/local, external, secure/recursive views, …). A Gold entity
# is a physical queryable relation, so all of these are valid inputs — e.g.
# Databricks `SHOW CREATE TABLE` on a materialized view returns
# `CREATE MATERIALIZED VIEW ... AS <select>`, and Snowflake `GET_DDL` on a
# dynamic table returns `CREATE OR REPLACE DYNAMIC TABLE ... TARGET_LAG=... AS
# <select>`. (+ optional IF NOT EXISTS handled by the \bTABLE\b / \bVIEW\b
# anchor.) Used both for the input shape guard and the multi-relation count.
_CREATE_RELATION_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?:(?:GLOBAL|LOCAL|TEMP(?:ORARY)?|VOLATILE|TRANSIENT|MATERIALIZED|DYNAMIC|"
    r"EXTERNAL|ICEBERG|HYBRID|SECURE|RECURSIVE)\s+)*"
    r"(?:TABLE|VIEW)\b",
    re.IGNORECASE,
)

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
        if self._prompts is not None:
            try:
                return self._prompts.get_prompt("ddl_mapping")
            except Exception:  # noqa: BLE001
                pass
        from .system_prompts_service import _DEFAULT_PROMPTS

        return _DEFAULT_PROMPTS["ddl_mapping"]

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
        max_attempts: int = 3,
    ) -> tuple[list[str], int, list[str]]:
        """Return ``(yaml_docs, tokens_used, warnings)`` — one YAML doc per table.

        ``context`` is optional free-text business purpose injected into the prompt
        so the model writes accurate descriptions instead of guessing from column
        names. ``warnings`` flags non-fatal robustness issues (e.g. the model
        emitted fewer documents than the input had ``CREATE TABLE`` statements).

        Regenerates up to ``max_attempts`` times when the model produces YAML that
        fails to parse — a smaller model drifts indentation on long field lists and
        a fresh pass is usually clean. Tokens accumulate across attempts. A
        *persistent* failure on a wide table is usually output truncation (the YAML
        hit the token ceiling), which retries cannot fix — the warning says so.
        """
        total_tokens = 0
        last: tuple[list[str], list[str]] = ([], [])
        for _ in range(max(1, max_attempts)):
            docs, tokens, warnings = self._generate_once(ddl, layer, source_system, context)
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
        self, ddl: str, layer: str, source_system: str, context: str = ""
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
            f"LAYER: {layer}\nSOURCE_SYSTEM: {source_system}\n\n{context_block}DDL:\n{ddl.strip()}"
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

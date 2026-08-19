# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Deterministic DDL parser — the code side of the DDL → YAML split.

The DDL already carries most of the semantic-layer entity mechanically: the
physical table name, every column name exactly as the database stores it, every
raw type, and the declared key (``PRIMARY KEY`` or ClickHouse ``ORDER BY``).
Asking a model to *transcribe* those is what produced hallucinated/renamed
columns and truncated YAML on wide tables — so this module extracts them in
code, byte-exact, and the model is left to annotate only what the DDL cannot
say (business names, descriptions, field roles). See ``ddl_skeleton.py`` for
the assembly and ``ddl_import_service.py`` for the orchestration.

Scope: ``CREATE TABLE`` statements with a typed column list, across the engines
the DDL + AI feature declares (PostgreSQL, SAP HANA, ClickHouse, Db2, Snowflake,
Databricks, BigQuery, SQL Server, Fabric — docs/ask-admin/02-add-data-products.md
Mode C). Views / CTAS / column-less definitions parse to a relation with
``columns == []`` — the caller falls back to the full-LLM path for those.

Identifier casing: names are kept EXACTLY as written (quotes stripped). Real
DDL dumps (``SHOW CREATE TABLE``, ``GET_DDL``, ``pg_dump``) spell identifiers
the way the catalog stores them — ClickHouse backticks its lowercase names,
Snowflake emits folded uppercase, Postgres emits folded lowercase — so
as-written IS the physical name in every dump scenario, per the Bronze
standard's "mirror the source faithfully" rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Matches a CREATE for any queryable relation we can turn into an entity —
# shared with ddl_import_service (input guard + multi-relation count) and used
# here to slice a multi-statement paste into per-relation statements.
CREATE_RELATION_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?:(?:GLOBAL|LOCAL|TEMP(?:ORARY)?|VOLATILE|TRANSIENT|MATERIALIZED|DYNAMIC|"
    r"EXTERNAL|ICEBERG|HYBRID|SECURE|RECURSIVE)\s+)*"
    r"(?:TABLE|VIEW)\b",
    re.IGNORECASE,
)

_VIEW_RE = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:\w+\s+)*VIEW\b", re.IGNORECASE)

# After the relation name: `AS SELECT` / `AS (SELECT` / `AS WITH` marks a query
# body (CTAS, views, dynamic tables) — those columns are not a typed list.
_AS_QUERY_RE = re.compile(r"\bAS\s*\(?\s*(?:SELECT|WITH)\b", re.IGNORECASE)

# One identifier: quoted (double quotes / backticks / brackets) or bare word.
_IDENT = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$#]*)'
_IDENT_RE = re.compile(_IDENT)

# The relation name after TABLE/VIEW (+ optional IF NOT EXISTS): a dotted chain
# of identifiers (catalog.schema.table).
_NAME_AFTER_CREATE_RE = re.compile(
    rf"\b(?:TABLE|VIEW)\b(?:\s+IF\s+NOT\s+EXISTS)?\s+({_IDENT}(?:\s*\.\s*{_IDENT})*)",
    re.IGNORECASE,
)

# Items inside the column block that declare constraints, not columns.
_CONSTRAINT_HEADS = (
    "CONSTRAINT",
    "PRIMARY",
    "FOREIGN",
    "UNIQUE",
    "KEY",
    "INDEX",
    "CHECK",
    "EXCLUDE",
    "PERIOD",
    "LIKE",
    "PROJECTION",
)

_PK_COLS_RE = re.compile(r"\bPRIMARY\s+KEY\s*\(([^)]*)\)", re.IGNORECASE)
_ORDER_BY_HEAD_RE = re.compile(r"\bORDER\s+BY\s*", re.IGNORECASE)
_COMMENT_LITERAL_RE = re.compile(r"\bCOMMENT\s+(?:=\s*)?'((?:[^']|'')*)'", re.IGNORECASE)
_COLUMN_PK_RE = re.compile(r"\bPRIMARY\s+KEY\b", re.IGNORECASE)

# Multi-word type phrases that must be captured whole (longest first). The
# TypeMapper owns the canonical mapping; the parser only needs to not split them.
_MULTIWORD_TYPES = (
    "NATIONAL CHARACTER VARYING",
    "TIMESTAMP WITHOUT TIME ZONE",
    "TIMESTAMP WITH TIME ZONE",
    "TIME WITHOUT TIME ZONE",
    "TIME WITH TIME ZONE",
    "NATIONAL CHARACTER",
    "CHARACTER VARYING",
    "DOUBLE PRECISION",
    "LONG VARCHAR",
)


@dataclass
class ParsedColumn:
    name: str  # exactly as written in the DDL, quotes stripped
    raw_type: str  # raw type expression (wrappers intact — TypeMapper unwraps)
    comment: str = ""  # COMMENT 'text' literal when the column carries one


@dataclass
class ParsedRelation:
    name: str  # relation name, UNQUALIFIED, as written (quotes stripped)
    qualifier: str = ""  # schema/catalog prefix as written ("" when bare)
    columns: list[ParsedColumn] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    key_source: str = ""  # "primary_key" | "order_by" | ""
    is_view: bool = False  # VIEW / MATERIALIZED VIEW / AS-SELECT body
    statement: str = ""  # the original statement slice (for LLM fallback)

    @property
    def skeleton_eligible(self) -> bool:
        """True when the deterministic skeleton path can own this relation:
        a typed column list exists and there is no query body to interpret."""
        return bool(self.columns) and not self.is_view


def _strip_quotes(ident: str) -> str:
    s = ident.strip()
    if len(s) >= 2 and (
        (s[0] == s[-1] and s[0] in ('"', "`")) or (s[0] == "[" and s[-1] == "]")
    ):
        return s[1:-1]
    return s


def strip_sql_comments(sql: str) -> str:
    """Remove ``--`` line and ``/* */`` block comments, QUOTE-AWARE — a ``--``
    inside a string literal (e.g. ``COMMENT 'a -- b'``) survives."""
    out: list[str] = []
    i, n = 0, len(sql)
    quote: str | None = None
    while i < n:
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                # doubled quote inside a literal ('' or "") stays inside it
                if i + 1 < n and sql[i + 1] == quote:
                    out.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j  # keep the newline
            continue
        if ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split on ``sep`` at paren depth 0, respecting quoted strings."""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    quote: str | None = None
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                if i + 1 < n and text[i + 1] == quote:
                    cur.append(text[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            cur.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    tail = "".join(cur)
    if tail.strip():
        parts.append(tail)
    return parts


def _balanced_group(text: str, start: int) -> tuple[str, int] | None:
    """Return ``(content, end_index)`` of the balanced paren group opening at
    ``start`` (which must be '('), quote-aware. ``end_index`` is past ')'."""
    if start >= len(text) or text[start] != "(":
        return None
    depth = 0
    quote: str | None = None
    i, n = start, len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == quote:
                if i + 1 < n and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return None


def _parse_column_item(item: str) -> tuple[ParsedColumn, bool] | None:
    """One item of the column block → ``(column, has_inline_primary_key)``, or
    None for constraints/noise."""
    s = item.strip()
    if not s:
        return None
    m = _IDENT_RE.match(s)
    if not m:
        return None
    head = _strip_quotes(m.group(0))
    if head.upper() in _CONSTRAINT_HEADS and not (s[: m.end()].startswith(('"', "`", "["))):
        return None  # a QUOTED head is a column named like a keyword — keep it
    rest = s[m.end() :].strip()
    if not rest:
        return None  # bare name, no type (a view column-name list) — not typed

    # Type expression: longest known multi-word phrase, else the first word …
    upper_rest = " ".join(rest.split()).upper()
    type_word = None
    for phrase in _MULTIWORD_TYPES:
        if upper_rest.startswith(phrase):
            # find the phrase's end in the ORIGINAL spacing by consuming words
            words_needed = len(phrase.split())
            wm = re.match(r"\s*" + r"\s+".join([r"[A-Za-z_][\w]*"] * words_needed), rest)
            if wm:
                type_word = wm.group(0).strip()
                rest_after = rest[wm.end() :]
                break
    if type_word is None:
        wm = re.match(r"[A-Za-z_][\w]*", rest)
        if not wm:
            return None
        type_word = wm.group(0)
        rest_after = rest[wm.end() :]

    # … plus its balanced paren group when present: Decimal(76, 7),
    # Nullable(DateTime('UTC')), NUMBER(10,2), Enum8('a' = 1).
    k = 0
    while k < len(rest_after) and rest_after[k].isspace():
        k += 1
    raw_type = type_word
    if k < len(rest_after) and rest_after[k] == "(":
        grp = _balanced_group(rest_after, k)
        if grp:
            raw_type = f"{type_word}({grp[0]})"
            rest_after = rest_after[grp[1] :]

    cm = _COMMENT_LITERAL_RE.search(rest_after)
    comment = cm.group(1).replace("''", "'") if cm else ""
    col = ParsedColumn(name=head, raw_type=" ".join(raw_type.split()), comment=comment)
    return col, bool(_COLUMN_PK_RE.search(rest_after))


def _key_columns(fragment: str, known: set[str]) -> list[str]:
    """Identifier list out of a PRIMARY KEY / ORDER BY fragment, filtered to
    known columns (expressions like ``toYYYYMM(d)`` are skipped, not guessed)."""
    inner = fragment.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    cols: list[str] = []
    for part in _split_top_level(inner):
        p = part.strip()
        if not p:
            continue
        m = _IDENT_RE.fullmatch(p)
        if not m:
            continue  # an expression, not a bare column — never guess
        name = _strip_quotes(p)
        if name in known and name not in cols:
            cols.append(name)
    return cols


def split_statements(ddl: str) -> list[str]:
    """Slice a paste into one string per CREATE relation (comment-stripped)."""
    text = strip_sql_comments(ddl or "")
    starts = [m.start() for m in CREATE_RELATION_RE.finditer(text)]
    if not starts:
        return []
    bounds = starts + [len(text)]
    return [text[bounds[i] : bounds[i + 1]].strip().rstrip(";").strip() for i in range(len(starts))]


def parse_relations(ddl: str) -> list[ParsedRelation]:
    """Parse every CREATE statement in the paste. Never raises: a statement the
    scanner cannot shape lands as a relation with no columns (LLM fallback)."""
    relations: list[ParsedRelation] = []
    for stmt in split_statements(ddl):
        rel = ParsedRelation(name="", statement=stmt)
        rel.is_view = bool(_VIEW_RE.search(stmt))

        nm = _NAME_AFTER_CREATE_RE.search(stmt)
        if not nm:
            relations.append(rel)
            continue
        chain = [_strip_quotes(p) for p in _split_top_level(nm.group(1), sep=".")]
        # BigQuery quotes the WHOLE path in one backtick pair (`proj.ds.table`)
        # — re-split so the unqualified name is really the last component.
        if len(chain) == 1 and "." in chain[0]:
            chain = chain[0].split(".")
        rel.name = chain[-1] if chain else ""
        rel.qualifier = ".".join(chain[:-1])

        after_name = stmt[nm.end() :]
        if _AS_QUERY_RE.search(after_name):
            rel.is_view = True

        # The typed column block is the first balanced group right after the name.
        k = 0
        while k < len(after_name) and after_name[k].isspace():
            k += 1
        block: str | None = None
        tail = after_name
        if k < len(after_name) and after_name[k] == "(":
            grp = _balanced_group(after_name, k)
            if grp:
                block, end = grp
                tail = after_name[end:]

        if block and not rel.is_view:
            inline_pk: list[str] = []
            table_pk: list[str] = []
            for item in _split_top_level(block):
                stripped = item.strip()
                pk_m = _PK_COLS_RE.search(stripped)
                head_word = stripped.split("(")[0].split()[0].upper() if stripped else ""
                if pk_m and head_word in ("PRIMARY", "CONSTRAINT"):
                    table_pk.append(pk_m.group(1))
                    continue
                parsed_item = _parse_column_item(item)
                if parsed_item is None:
                    continue
                col, has_inline_pk = parsed_item
                rel.columns.append(col)
                if has_inline_pk:
                    inline_pk.append(col.name)

            known = {c.name for c in rel.columns}
            if table_pk:
                rel.primary_key = _key_columns(f"({table_pk[0]})", known)
                rel.key_source = "primary_key"
            elif inline_pk:
                rel.primary_key = inline_pk
                rel.key_source = "primary_key"
            else:
                # Tail clauses: an explicit PRIMARY KEY (…) wins over ORDER BY —
                # ClickHouse allows both; ORDER BY is the MergeTree sorting key,
                # the closest key declaration a ClickHouse table ships.
                tpk = _PK_COLS_RE.search(tail)
                if tpk:
                    rel.primary_key = _key_columns(f"({tpk.group(1)})", known)
                    rel.key_source = "primary_key" if rel.primary_key else ""
                else:
                    ob = _ORDER_BY_HEAD_RE.search(tail)
                    if ob:
                        after = tail[ob.end() :]
                        if after.startswith("("):
                            grp = _balanced_group(after, 0)
                            fragment = f"({grp[0]})" if grp else ""
                        else:
                            im = _IDENT_RE.match(after)
                            fragment = im.group(0) if im else ""
                        if fragment:
                            rel.primary_key = _key_columns(fragment, known)
                            rel.key_source = "order_by" if rel.primary_key else ""

        relations.append(rel)
    return relations

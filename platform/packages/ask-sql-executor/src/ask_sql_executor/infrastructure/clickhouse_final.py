# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Place the FINAL modifier after the ClickHouse tables that support it.

Why this exists (2026-10-12, GONAC PoC): the connection's opt-in ``final`` flag
is applied as the ``final=1`` query setting, which ClickHouse 22.1 does not
know (``UNKNOWN_SETTING``). On such a server the adapter used to retry WITHOUT
deduplication, so a ReplacingMergeTree table answered with every version of a
row that background merges had not collapsed yet: 1,641 open order items
against 1,629 real ones, and the gap grew with each incremental load.

The model is told never to write FINAL (ClickHouse prompt rule 13): it cannot
know which tables support it, and a plain MergeTree, a View or a system table
rejects it with ILLEGAL_FINAL. This module is the deterministic stand-in for
the setting. It lists every table the statement reads, the adapter asks the
server which of them use a FINAL-capable engine, and FINAL goes after exactly
those. Everything else in the statement stays byte for byte as it was.

It is a tokenizer, not a parser, on purpose. It never looks inside string
literals, quoted identifiers or comments; it tells a subquery from a function
call by the token in front of the parenthesis, so ``extract(YEAR FROM d)`` is
not read as a table; and it puts FINAL where the grammar wants it, after the
alias (``FROM t AS a FINAL``; ``FROM t FINAL AS a`` is a syntax error). A
reference it cannot read is skipped, and a name the server does not report as
a FINAL-capable table never receives the modifier, so the worst case is the old
behaviour (no deduplication), never a broken query.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Engines whose rows FINAL collapses at read time. Plain MergeTree, Log, View,
# MaterializedView, Dictionary, Distributed and the system engines are left out:
# ClickHouse rejects FINAL on them, or (Distributed) the engine says nothing
# about the table underneath.
_FINAL_ENGINE = re.compile(
    r"^(?:Replicated|Shared)?"
    r"(?:Replacing|Collapsing|VersionedCollapsing|Aggregating|Summing|Graphite)"
    r"MergeTree$"
)

# Words that end a table reference instead of naming its alias.
_NOT_ALIAS = frozenset(
    {
        "ALL", "AND", "ANTI", "ANY", "ARRAY", "AS", "ASOF", "BY", "CROSS", "EXCEPT",
        "FINAL", "FORMAT", "FROM", "FULL", "GLOBAL", "GROUP", "HAVING", "IN", "INNER",
        "INTERSECT", "INTO", "JOIN", "LEFT", "LIMIT", "NOT", "OFFSET", "ON", "OR",
        "ORDER", "OUTER", "PASTE", "PREWHERE", "QUALIFY", "RIGHT", "SAMPLE", "SELECT",
        "SEMI", "SETTINGS", "UNION", "USING", "WHERE", "WINDOW", "WITH",
    }
)  # fmt: skip

# Words that can stand in front of a parenthesis that opens a subquery or an
# expression. Any other word followed by "(" is a function call, whose
# arguments may say FROM without naming a table.
_CLAUSE_WORDS = _NOT_ALIAS | frozenset(
    {"CASE", "DISTINCT", "ELSE", "EXISTS", "IS", "LIKE", "ILIKE", "SOME", "THEN", "VALUES", "WHEN"}
)


@dataclass(frozen=True)
class TableRef:
    """One table the statement reads, and where FINAL would go after it."""

    database: str | None
    name: str
    insert_at: int
    has_final: bool


@dataclass(frozen=True)
class _Token:
    kind: str  # "word" | "quoted" | "string" | "number" | "punct"
    text: str
    start: int
    end: int


def supports_final(engine: str | None) -> bool:
    """True when ClickHouse accepts FINAL on a table with this engine."""
    return bool(engine) and bool(_FINAL_ENGINE.match(engine or ""))


def find_table_refs(sql: str) -> list[TableRef]:
    """Every table named after FROM or JOIN, outside function arguments.

    CTE names are dropped unless qualified with a database, because they name
    a subquery rather than a table on the server.
    """
    toks = _tokenize(sql)
    refs: list[TableRef] = []
    ctes: set[str] = set()
    function_parens: list[bool] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.kind == "punct":
            if tok.text == "(":
                prev = toks[i - 1] if i else None
                function_parens.append(
                    prev is not None
                    and prev.kind == "word"
                    and prev.text.upper() not in _CLAUSE_WORDS
                )
            elif tok.text == ")" and function_parens:
                function_parens.pop()
            i += 1
            continue
        if tok.kind == "word":
            word = tok.text.upper()
            if word == "AS" and i and _next_is(toks, i, "(") and _ident(toks[i - 1]) is not None:
                ctes.add(_ident(toks[i - 1]) or "")
            inside_function = bool(function_parens) and function_parens[-1]
            after_array = (
                i > 0 and toks[i - 1].kind == "word" and toks[i - 1].text.upper() == "ARRAY"
            )
            if (
                word in ("FROM", "JOIN")
                and not inside_function
                and not (word == "JOIN" and after_array)
            ):
                i = _read_items(toks, i + 1, refs, allow_list=word == "FROM")
                continue
        i += 1
    return [r for r in refs if r.database is not None or r.name not in ctes]


def add_final(sql: str, refs: Iterable[TableRef]) -> str:
    """Insert `` FINAL`` after each reference that does not carry it yet."""
    out = sql
    for offset in sorted({r.insert_at for r in refs if not r.has_final}, reverse=True):
        out = f"{out[:offset]} FINAL{out[offset:]}"
    return out


# ── reading table references ─────────────────────────────────────────────────


def _read_items(toks: list[_Token], i: int, refs: list[TableRef], *, allow_list: bool) -> int:
    """Read the table after FROM/JOIN, and the rest of a comma list after FROM."""
    while True:
        i, ref = _read_table(toks, i)
        if ref is None:
            return i
        refs.append(ref)
        if not (allow_list and _is_punct(toks, i, ",")):
            return i
        i += 1


def _read_table(toks: list[_Token], i: int) -> tuple[int, TableRef | None]:
    if i >= len(toks):
        return i, None
    first = toks[i]
    name = _ident(first)
    if name is None or (first.kind == "word" and first.text.upper() in _CLAUSE_WORDS):
        return i, None  # "(" of a subquery, which the main loop walks into
    database: str | None = None
    last = first
    j = i + 1
    if _is_punct(toks, j, ".") and j + 1 < len(toks) and _ident(toks[j + 1]) is not None:
        database, name, last = name, _ident(toks[j + 1]) or "", toks[j + 1]
        j += 2
    if _is_punct(toks, j, "("):
        return j, None  # table function: numbers(10), remote(...)
    end = last.end
    if j < len(toks):
        alias = toks[j]
        if alias.kind == "word" and alias.text.upper() == "AS" and j + 1 < len(toks):
            if _ident(toks[j + 1]) is not None:
                end, j = toks[j + 1].end, j + 2
        elif alias.kind == "quoted" or (
            alias.kind == "word" and alias.text.upper() not in _NOT_ALIAS
        ):
            end, j = alias.end, j + 1
    has_final = j < len(toks) and toks[j].kind == "word" and toks[j].text.upper() == "FINAL"
    return (j + 1 if has_final else j), TableRef(database, name, end, has_final)


def _is_punct(toks: list[_Token], i: int, text: str) -> bool:
    return i < len(toks) and toks[i].kind == "punct" and toks[i].text == text


def _next_is(toks: list[_Token], i: int, text: str) -> bool:
    return _is_punct(toks, i + 1, text)


def _ident(tok: _Token) -> str | None:
    """The identifier a word or quoted token names, unquoted; None otherwise."""
    if tok.kind == "word":
        return tok.text
    if tok.kind == "quoted" and len(tok.text) >= 2:
        quote = tok.text[0]
        body = tok.text[1:-1] if tok.text.endswith(quote) else tok.text[1:]
        return re.sub(r"\\(.)", r"\1", body.replace(quote * 2, quote))
    return None


# ── tokenizer ────────────────────────────────────────────────────────────────


def _tokenize(sql: str) -> list[_Token]:
    toks: list[_Token] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
        elif sql.startswith("--", i) or ch == "#":
            newline = sql.find("\n", i)
            i = n if newline == -1 else newline + 1
        elif sql.startswith("/*", i):
            close = sql.find("*/", i + 2)
            i = n if close == -1 else close + 2
        elif ch in "'\"`":
            end = _close_quote(sql, i)
            toks.append(_Token("string" if ch == "'" else "quoted", sql[i:end], i, end))
            i = end
        elif ch.isalpha() or ch == "_":
            end = i + 1
            while end < n and (sql[end].isalnum() or sql[end] in "_$"):
                end += 1
            toks.append(_Token("word", sql[i:end], i, end))
            i = end
        elif ch.isdigit():
            end = i + 1
            while end < n and (sql[end].isalnum() or sql[end] in "._"):
                end += 1
            toks.append(_Token("number", sql[i:end], i, end))
            i = end
        else:
            toks.append(_Token("punct", ch, i, i + 1))
            i += 1
    return toks


def _close_quote(sql: str, start: int) -> int:
    """Offset just past the quote that closes the one at ``start``."""
    quote, i, n = sql[start], start + 1, len(sql)
    while i < n:
        if sql[i] == "\\":
            i += 2
        elif sql[i] == quote:
            if i + 1 < n and sql[i + 1] == quote:
                i += 2
            else:
                return i + 1
        else:
            i += 1
    return n

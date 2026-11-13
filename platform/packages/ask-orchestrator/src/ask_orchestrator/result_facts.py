# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""What a result held, computed in code from every row: the facts a follow-up
is checked against.

An answer's text is written by a model and, in the history, cut to fit. A
question about it ("why 29 rows and not 10 per channel?") needs what the result
held: how many rows and whether the query's LIMIT cut them; by the column the
rows group on (the channel), each group's rows, the distinct values of the other
text columns and the totals of the measures; and the readings the query took.
``describe`` writes them short enough to travel whole with every turn.

A total adds what the rows mean, not what they repeat:

- A measure repeated on every row of another column's value (a customer's total
  on each of its product rows) is added once per value of that column, and the
  facts say so ("once per cliente"). That column is text, a date, or a number
  named as a code or a calendar unit; never a share, a ratio, an average or a
  rank, which two rows share by chance. And a value that repeats must carry a
  figure: when every repeat carries 0 or nothing, dropping them changes nothing,
  and the facts claim no "once per".
- A distinct count (``COUNT(DISTINCT ...)``, ``uniq(...)``) has no total: a
  customer in two groups would count twice. Neither has a share, a ratio, an
  average, a rank or a calendar number, told by a whole word of the column's
  name.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# The facts computed here fit in this; past it, whole parts are left out, never
# cut. The assumptions, written by the SQL generator, go whole below them.
MAX_FACTS_CHARS = 1000
# A column the rows group on has between 2 and this many values.
MAX_GROUPS = 12
# A value shown in place of a count of one (the code beside a channel's name).
MAX_SHOWN_VALUE_CHARS = 40
EMPTY = "(empty)"

# Whole words of a column's name (split on "_") that say its values are not
# quantities to add up. Where the word stands matters: a share or an average
# anywhere (``pct_perdida_mes_1``); a rank or a code first or last
# (``posicion``, ``cliente_id``); a calendar word only first, since a measure
# names its period after its own name (``facturado_mes_1`` adds up, ``mes``
# does not).
_SHARE_WORDS = frozenset(
    {
        "pct", "percent", "percentage", "porcentaje", "porc", "participacion", "share",
        "ratio", "rate", "tasa", "avg", "average", "mean", "promedio", "prom", "media",
    }
)  # fmt: skip
_RANK_WORDS = frozenset({"rank", "ranking", "rn", "posicion", "position"})
_CODE_WORDS = frozenset({"id", "codigo", "code"})
_CALENDAR_WORDS = frozenset(
    {
        "dia", "dias", "day", "days", "semana", "week", "mes", "month", "anio", "ano",
        "año", "year", "ejercicio", "periodo", "period", "fecha", "date",
    }
)  # fmt: skip

_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?(?:\s+OFFSET\s+\d+)?\s*$", re.I)
_TRAILING_FETCH = re.compile(r"\bFETCH\s+(?:FIRST|NEXT)\s+(\d+)\s+ROWS?\s+ONLY\s*$", re.I)
_LEADING_TOP = re.compile(r"^\s*SELECT\s+(?:DISTINCT\s+)?TOP\s*\(?\s*(\d+)", re.I)
_DISTINCT_COUNT = re.compile(
    r"\b(?:count\s*\(\s*distinct\b|countDistinct\s*\(|uniq\w*\s*\(|approx_count_distinct\s*\()",
    re.I,
)
_ALIAS = re.compile(r'\s*(AS\s+)?(?:"([^"]+)"|`([^`]+)`|\[([^\]]+)\]|([A-Za-z_]\w*))', re.I)
# A bare word after an expression that is a keyword, not an alias.
_NOT_ALIASES = frozenset(
    {
        "from", "where", "group", "order", "having", "limit", "union", "and", "or", "then",
        "else", "end", "when", "on", "join", "left", "right", "inner", "full", "cross",
        "window", "qualify", "settings", "format", "over", "filter", "within", "as",
    }
)  # fmt: skip


def describe(
    rows: Sequence[dict[str, Any]], sql: str | None, assumptions: Sequence[str] = ()
) -> str:
    """The facts of a result: from every row in ``rows`` (one dict per row,
    keyed by column), the statement that produced them and the readings the
    query took. The part computed here stays under ``MAX_FACTS_CHARS``; the
    assumptions follow it whole."""
    facts = _Facts(list(rows), sql or "")
    candidates: list[Callable[[], str]] = [
        lambda: facts.render(group_detail="full"),
        lambda: facts.render(group_detail="counts"),
        lambda: facts.render(group_detail="rows"),
        lambda: facts.render(group_detail=None),
        lambda: facts.render(group_detail=None, columns=False),
    ]
    text = ""
    for build in candidates:
        text = build()
        if len(text) <= MAX_FACTS_CHARS:
            break
    else:
        text = facts.headline(columns=False)
    readings = [a.strip() for a in assumptions if a and a.strip()]
    if readings:
        text += "\nAssumptions the query took:\n" + "\n".join(f"- {a}" for a in readings)
    return text


class _Facts:
    """The figures of one result, computed once and rendered at a level of detail."""

    def __init__(self, rows: list[dict[str, Any]], sql: str) -> None:
        self.rows = rows
        self.sql = sql
        self.columns = list(rows[0].keys()) if rows else []
        values = {c: [row.get(c) for row in rows] for c in self.columns}
        self.measures = [c for c in self.columns if _is_measure(values[c])]
        self.labels = {
            c: [_label(v) for v in values[c]] for c in self.columns if c not in self.measures
        }
        distinct_counts = _distinct_count_aliases(sql)
        kinds = {c: _name_kind(c) for c in self.measures}
        self.totaled = [
            c for c in self.measures if c.lower() not in distinct_counts and kinds[c] is None
        ]
        # The columns a repeated measure can belong to: text and dates, and the
        # numbers named as codes or calendar units. A share, a ratio, an average,
        # a rank or a distinct count repeats a number by chance.
        keys = {c: self.labels[c] for c in self.labels}
        keys.update(
            {
                c: [_label(v) for v in values[c]]
                for c in self.measures
                if kinds[c] in ("code", "calendar") and c.lower() not in distinct_counts
            }
        )
        self.once_per = {m: _repeated_over(values[m], keys, self.columns) for m in self.totaled}
        self.values = values
        self.group = self._group_column()

    # ── rendering ──────────────────────────────────────────────────────────

    def render(self, *, group_detail: str | None, columns: bool = True) -> str:
        lines = [self.headline(columns=columns)]
        if self.group is not None and group_detail is not None:
            lines += self._group_table(group_detail)
        overall = self._overall()
        if overall:
            lines.append(overall)
        return "\n".join(lines)

    def headline(self, *, columns: bool) -> str:
        n = len(self.rows)
        text = f"{n} row{'' if n == 1 else 's'}"
        limit = _limit_of(self.sql)
        if limit is not None:
            if n >= limit:
                text += f", LIMIT {limit} reached: the query may have more rows than these"
            else:
                text += f", LIMIT {limit} not reached"
        text += "."
        if columns and self.columns:
            text += " Columns: " + ", ".join(self.columns) + "."
        return text

    def _group_table(self, detail: str) -> list[str]:
        group = self.group
        assert group is not None
        order: list[str] = []
        members: dict[str, list[int]] = {}
        for i, label in enumerate(self.labels[group]):
            if label not in members:
                order.append(label)
                members[label] = []
            members[label].append(i)

        others = [c for c in self.labels if c != group and len(set(self.labels[c])) > 1]
        shown: list[str] = []  # one value per group: shown instead of a count of one
        counted: list[str] = []
        for c in others:
            per_group = [{self.labels[c][i] for i in members[g]} for g in order]
            if all(len(s) == 1 for s in per_group):
                if all(len(next(iter(s))) <= MAX_SHOWN_VALUE_CHARS for s in per_group):
                    shown.append(c)
            else:
                counted.append(c)

        header = [group, "rows"]
        if detail in ("full", "counts"):
            header += shown + [f"distinct {c}" for c in counted]
        if detail == "full":
            header += [self._total_name(m) for m in self.totaled]
        lines = [f"By {group} ({len(order)} groups):", " | ".join(_cell(h) for h in header)]
        for g in order:
            idx = members[g]
            cells = [g, str(len(idx))]
            if detail in ("full", "counts"):
                cells += [self.labels[c][idx[0]] for c in shown]
                cells += [str(len({self.labels[c][i] for i in idx})) for c in counted]
            if detail == "full":
                cells += [self._total(m, idx) for m in self.totaled]
            lines.append(" | ".join(_cell(v) for v in cells))
        return lines

    def _overall(self) -> str:
        parts = []
        distinct = []
        same = []
        for c, labels in self.labels.items():
            seen = set(labels)
            if len(seen) > 1:
                distinct.append(f"{c} {len(seen)}")
            else:
                value = next(iter(seen), EMPTY)
                if len(value) <= MAX_SHOWN_VALUE_CHARS:
                    same.append(f"{c} {value}")
        if distinct:
            parts.append("distinct " + ", ".join(distinct))
        if same and len(self.rows) > 1:
            parts.append("same in every row: " + ", ".join(same))
        everything = list(range(len(self.rows)))
        totals = [f"{self._total_name(m)} {self._total(m, everything)}" for m in self.totaled]
        if totals:
            parts.append(", ".join(totals))
        return f"All rows: {'; '.join(parts)}." if parts and self.rows else ""

    def _total_name(self, measure: str) -> str:
        key = self.once_per.get(measure)
        return f"total {measure}" + (f" (once per {key})" if key else "")

    def _total(self, measure: str, indexes: list[int]) -> str:
        values = self.values[measure]
        key = self.once_per.get(measure)
        if key is not None:
            labels = self.labels.get(key) or [_label(v) for v in self.values[key]]
            picked: dict[str, Any] = {}
            for i in indexes:
                picked.setdefault(labels[i], values[i])
            chosen = list(picked.values())
        else:
            chosen = [values[i] for i in indexes]
        return _format_sum(chosen)

    def _group_column(self) -> str | None:
        """The text column with the fewest values between 2 and ``MAX_GROUPS``;
        on a tie, the one with the longer values (a name over its code)."""
        best: tuple[int, float, int] | None = None
        chosen = None
        for position, (c, labels) in enumerate(self.labels.items()):
            count = len(set(labels))
            if not 2 <= count <= MAX_GROUPS:
                continue
            key = (count, -sum(len(v) for v in labels) / len(labels), position)
            if best is None or key < best:
                best, chosen = key, c
        return chosen


def _repeated_over(values: list[Any], keys: dict[str, list[str]], order: list[str]) -> str | None:
    """The column whose every value carries one value of this measure, among
    columns where a value that repeats carries a figure; the one with the
    fewest values when several do. ``None`` when the measure is constant or no
    column carries it."""
    if len(set(values)) < 2:
        return None
    best: tuple[int, int] | None = None
    chosen = None
    for c, labels in keys.items():
        counts = Counter(labels)
        count = len(counts)
        # Only repeats that carry a figure change the total when dropped.
        if not any(
            counts[label] > 1 and v is not None and v != 0 for label, v in zip(labels, values)
        ):
            continue
        seen: dict[str, Any] = {}
        if all(seen.setdefault(label, v) == v for label, v in zip(labels, values)):
            key = (count, order.index(c))
            if best is None or key < best:
                best, chosen = key, c
    return chosen


def _is_measure(values: list[Any]) -> bool:
    present = [v for v in values if v is not None]
    return bool(present) and all(
        isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in present
    )


def _label(value: Any) -> str:
    if value is None:
        return EMPTY
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value)
    return text if text.strip() else EMPTY


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r\n", "\\n").replace("\n", "\\n")


def _format_sum(values: list[Any]) -> str:
    present = [v for v in values if v is not None]
    if all(isinstance(v, int) for v in present):
        return str(sum(present))
    total = sum((v if isinstance(v, Decimal) else Decimal(str(v)) for v in present), Decimal(0))
    return format(total, ".2f")


def _name_kind(name: str) -> str | None:
    """What a number's name says it is: "share" (a share, ratio or average),
    "rank", "code" or "calendar"; ``None`` for a quantity that adds up. See
    ``_SHARE_WORDS`` for where each word must stand."""
    words = [w for w in re.split(r"[\W_]+", name.lower()) if w]
    if not words:
        return None
    if _SHARE_WORDS.intersection(words):
        return "share"
    if words[0] in _RANK_WORDS or words[-1] in _RANK_WORDS:
        return "rank"
    if words[0] in _CODE_WORDS or words[-1] in _CODE_WORDS:
        return "code"
    if words[0] in _CALENDAR_WORDS:
        return "calendar"
    return None


def _limit_of(sql: str) -> int | None:
    """The row cap of the statement as a whole: a trailing ``LIMIT n`` (or
    ``LIMIT offset, n``), ``FETCH FIRST n ROWS ONLY``, or a leading ``SELECT TOP
    (n)``. ClickHouse's ``LIMIT n BY`` caps each group, not the result."""
    text = _COMMENTS.sub(" ", sql).strip().rstrip(";").strip()
    match = _TRAILING_LIMIT.search(text)
    if match:
        return int(match.group(2) or match.group(1))
    match = _TRAILING_FETCH.search(text) or _LEADING_TOP.search(text)
    return int(match.group(1)) if match else None


def _distinct_count_aliases(sql: str) -> set[str]:
    """The names, lowercased, the statement gives to distinct counts, CTEs
    included: the alias after the call's closing parenthesis and an optional
    ``OVER (...)``."""
    text = _COMMENTS.sub(" ", sql)
    aliases: set[str] = set()
    for match in _DISTINCT_COUNT.finditer(text):
        end = _closing(text, text.index("(", match.start()))
        if end is None:
            continue
        rest = text[end + 1 :]
        over = re.match(r"\s*OVER\s*\(", rest, re.I)
        if over:
            close = _closing(rest, over.end() - 1)
            if close is None:
                continue
            rest = rest[close + 1 :]
        alias = _ALIAS.match(rest)
        if not alias:
            continue
        name = next(g for g in alias.groups()[1:] if g)
        if alias.group(1) or name.lower() not in _NOT_ALIASES:
            aliases.add(name.lower())
    return aliases


def _closing(text: str, opening: int) -> int | None:
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None

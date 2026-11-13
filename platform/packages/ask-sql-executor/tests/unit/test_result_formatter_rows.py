# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: the answer is written from the whole result, up to a size.

The bug these pin
─────────────────
The formatter wrote the answer from the first 20 rows and told the model that
only those were shown. In GONAC's chat of 2026-11-11, 12 of the 19 answers with
data had more than 20 rows, and all 12 told the customer that data was missing
("¿por qué me lo limitas a 29 registros?"), or drew conclusions from the first
20 rows only (Q05 named the wrong customer as the largest loss), while the table
under the answer had every row. The rows below have the width of that chat's
results.

Then the size limit itself was spent on column names. Each row repeated them
(``col: value | ...``), so in the QA run of 2026-11-12, Q06 and Q10 returned 83
rows of 9 columns, only 74 and 72 fit, and both answers left out the last
channel of the result. The names now go once, in a header line.
"""

from __future__ import annotations

from decimal import Decimal

from ask_sql_executor.application.result_formatter import (
    MAX_RESULT_CHARS,
    LLMResultFormatter,
    _render_rows,
)

_COLUMNS = ["canal_cod", "rank_cliente", "cliente", "producto", "f_ago", "f_sep", "f_oct", "venta_perdida"]


def _row(i: int) -> tuple:
    """One row of "products the main customers stopped buying", as ClickHouse
    returns it (the measures are Decimal(76, 7))."""
    return (
        f"{i // 10 + 1:02d}",
        i % 10 + 1,
        f"CLIENTE NUMERO {i:03d} S DE RL",
        f"CHIDAS PAPAS PRODUCTO {i:03d} TUBI 93G 6/5 PZ",
        Decimal("142959.4400000"),
        Decimal("148090.4000000"),
        Decimal("-3167.0500000"),
        Decimal("291049.8400000"),
    )


class _CapturingLLM:
    def __init__(self):
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)

        class _R:
            content = "respuesta"

        return _R()


def _prompt_for(rows: list[tuple], question: str = "productos que dejaron de comprar por canal") -> str:
    llm = _CapturingLLM()
    LLMResultFormatter(llm=llm).format_rows(_COLUMNS, rows, question)
    return llm.prompts[0]


def test_a_29_row_result_reaches_the_model_whole():
    """Q12 of that chat: 29 rows, and the answer said rows were missing."""
    rows = [_row(i) for i in range(29)]

    prompt = _prompt_for(rows)

    assert all(f"CLIENTE NUMERO {i:03d} S DE RL" in prompt for i in range(29))
    assert "RESULTS (all 29 rows):" in prompt
    assert "only the first" not in prompt
    assert "Never say that rows or data are missing" in prompt


def test_the_longest_reference_result_of_the_qa_fits_whole():
    """77 rows: the canonical "stopped buying, top 10 customers per channel"."""
    rows = [_row(i) for i in range(77)]

    prompt = _prompt_for(rows)

    assert f"CLIENTE NUMERO {76:03d} S DE RL" in prompt
    assert "RESULTS (all 77 rows):" in prompt


def test_the_model_knows_the_user_sees_the_table():
    prompt = _prompt_for([_row(i) for i in range(3)])

    assert "The user sees the result rows in a table under your answer" in prompt
    assert "say something about every group" in prompt


def test_a_result_larger_than_the_limit_is_cut_by_size_and_the_model_is_told():
    rows = [_row(i) for i in range(500)]
    text, shown = _render_rows(_COLUMNS, rows)

    prompt = _prompt_for(rows)

    assert 50 < shown < 500  # by size: about 190 rows of this width
    assert len(text) <= MAX_RESULT_CHARS
    assert f"CLIENTE NUMERO {shown - 1:03d} S DE RL" in prompt
    assert f"CLIENTE NUMERO {shown:03d} S DE RL" not in prompt
    assert f"RESULTS (500 rows; only the first {shown} fit below" in prompt
    assert f"covers the first {shown} of the 500 rows" in prompt
    assert "do not say that data is missing" in prompt


def test_a_single_row_wider_than_the_limit_is_cut_not_dropped():
    rows = [("x" * (MAX_RESULT_CHARS * 2),), ("second",)]
    text, shown = _render_rows(["notas"], rows)

    assert shown == 1
    assert text.startswith("notas\nxxx")
    assert len(text) == MAX_RESULT_CHARS


def test_without_the_model_the_rows_it_would_have_seen_are_returned():
    class _BoomLLM:
        def invoke(self, prompt):
            raise RuntimeError("LLM down")

    answer = LLMResultFormatter(llm=_BoomLLM()).format_rows(_COLUMNS, [_row(i) for i in range(29)], "x")

    assert answer.startswith("Found 29 result(s).")
    assert " | ".join(_COLUMNS) in answer
    assert f"CLIENTE NUMERO {28:03d} S DE RL" in answer


# ── The column names go once, in a header ────────────────────────────────────

# Invented, with the shape of Q06 in the QA run of 2026-11-12: 9 columns with
# names and values as long as that result's, 83 rows ordered by channel in groups
# of 55, 14, 13 and 1. With the names repeated on every row they need about 270
# characters a row, and the last rows, the last channel among them, did not fit.
_Q06_COLUMNS = [
    "canal_codigo",
    "canal_nombre",
    "producto",
    "mes",
    "clientes_que_dejaron_de_comprar",
    "venta_mes_ant",
    "perdida_venta_productos_mes",
    "facturado_mes_previo",
    "pct_perdida_del_mes",
]


def _q06_rows() -> list[tuple]:
    rows = []
    for channel, count in (("01", 55), ("02", 14), ("03", 13), ("04", 1)):
        for i in range(count):
            rows.append(
                (
                    channel,
                    f"Canal {channel}",
                    f"PRODUCTO DE PRUEBA NUMERO {len(rows):03d} BOLSA 90G",
                    202608 + i % 3,
                    i % 9 + 1,
                    12345.67 + i,
                    123456.78 + i,
                    23456.78 + i,
                    1.23,
                )
            )
    return rows


def test_q06_all_83_rows_of_9_columns_fit_and_every_channel_reaches_the_model():
    rows = _q06_rows()
    repeated_names = sum(
        len(" | ".join(f"{col}: {val}" for col, val in zip(_Q06_COLUMNS, row))) + 1 for row in rows
    )
    assert repeated_names > MAX_RESULT_CHARS  # the layout that dropped the last channel

    llm = _CapturingLLM()
    LLMResultFormatter(llm=llm).format_rows(_Q06_COLUMNS, rows, "productos que dejaron de comprar")
    text, shown = _render_rows(_Q06_COLUMNS, rows)

    assert shown == 83
    assert len(text) < MAX_RESULT_CHARS / 2
    assert "RESULTS (all 83 rows):" in llm.prompts[0]
    assert "04 | Canal 04 | PRODUCTO DE PRUEBA NUMERO 082 BOLSA 90G" in llm.prompts[0]


def test_the_column_names_go_once_in_a_header_and_each_row_carries_only_values():
    prompt = _prompt_for([_row(i) for i in range(3)])

    assert prompt.count("venta_perdida") == 1
    lines = prompt.splitlines()
    header = lines.index(" | ".join(_COLUMNS))
    assert lines[header + 1] == " | ".join(str(val) for val in _row(0))
    assert lines[header + 1].startswith("01 | 1 | CLIENTE NUMERO 000 S DE RL | ")
    assert "The first line names the columns; each line after it is one row" in prompt


def test_a_separator_inside_a_value_or_a_name_is_escaped():
    """A "|" would add a value to its row, and a line break a row to the result."""
    columns = ["nombre | alias", "nota"]
    rows = [("ACME | NORTE", "linea uno\nlinea dos"), ("BETA", "una\r\nmas")]

    text, shown = _render_rows(columns, rows)

    lines = text.split("\n")
    assert shown == 2 and len(lines) == 3
    assert all(len(line.split(" | ")) == 2 for line in lines)
    assert lines[0] == "nombre \\| alias | nota"
    assert lines[1] == "ACME \\| NORTE | linea uno\\nlinea dos"
    assert lines[2] == "BETA | una\\nmas"

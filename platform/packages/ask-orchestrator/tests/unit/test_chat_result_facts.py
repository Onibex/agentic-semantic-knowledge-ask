# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: the facts of a result, computed in code from every row.

The bug these pin
─────────────────
In the QA run of 2026-11-13 (Q13), the user asked why the previous answer was
"limited to 29 records in total and not 10 per channel". The history carried
that answer's text cut at 3,000 characters, just before its last channel, and
no figure of its result. The model took the 29 for granted and made up the
rest; the result had 79 rows and 24 customers in 4 channels of 52, 11, 15 and 1
rows. The history now carries, under each answer, facts computed from all its
rows.

The rows below are invented, with the shape of that result: one row per
customer and product, the customer's total repeated on each of its product rows.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ask_orchestrator.result_facts import MAX_FACTS_CHARS, describe

_Q12_SQL = (
    "WITH c AS (SELECT canal, cliente, sum(facturado) AS total_cliente FROM ventas "
    "GROUP BY canal, cliente) SELECT p.canal_codigo, p.canal_nombre, p.cliente, "
    "c.total_cliente, p.producto, p.venta_ago_sep, p.venta_oct FROM p JOIN c USING (cliente) "
    "ORDER BY p.canal_codigo, c.total_cliente DESC LIMIT 500"
)
# (code, name, rows, customers), in the order of the result.
_CHANNELS = [
    ("01", "Mayoreo", 52, 10),
    ("02", "Autoservicio", 11, 3),
    ("03", "Conveniencia", 15, 10),
    ("04", "Exterior", 1, 1),
]


def _q12_rows() -> list[dict]:
    rows = []
    for c, (code, name, count, customers) in enumerate(_CHANNELS):
        for i in range(count):
            customer = i % customers
            rows.append(
                {
                    "canal_codigo": code,
                    "canal_nombre": name,
                    "cliente": f"CLIENTE {code}-{customer:02d}",
                    # The customer's total, the same on each of its product rows.
                    "total_cliente": Decimal(f"{100000 * (c + 1) + 1000 * customer}.5000000"),
                    "producto": f"PRODUCTO {len(rows) % 56:03d}",
                    "venta_ago_sep": Decimal(f"{100 + len(rows)}.2500000"),
                    "venta_oct": Decimal("-1.5000000") if i % 2 else Decimal("0E-7"),
                }
            )
    return rows


def _computed(facts: str) -> str:
    return facts.split("\nAssumptions the query took:")[0]


def _line(facts: str, start: str) -> str:
    return next(line for line in facts.splitlines() if line.startswith(start))


# ── What the result held ─────────────────────────────────────────────────────


def test_q12_the_rows_the_limit_and_each_channels_customers():
    facts = describe(_q12_rows(), _Q12_SQL)

    assert facts.startswith("79 rows, LIMIT 500 not reached. Columns: canal_codigo, canal_nombre,")
    assert "By canal_nombre (4 groups):" in facts
    header = _line(facts, "canal_nombre | rows | ")
    assert header.startswith(
        "canal_nombre | rows | canal_codigo | distinct cliente | distinct producto"
    )
    assert _line(facts, "Mayoreo | ").startswith("Mayoreo | 52 | 01 | 10 | ")
    assert _line(facts, "Autoservicio | ").startswith("Autoservicio | 11 | 02 | 3 | ")
    assert _line(facts, "Conveniencia | ").startswith("Conveniencia | 15 | 03 | 10 | ")
    assert _line(facts, "Exterior | ").startswith("Exterior | 1 | 04 | 1 | ")
    assert "cliente 24, producto 56" in _line(facts, "All rows:")
    assert len(facts) <= MAX_FACTS_CHARS


def test_a_customer_total_repeated_on_each_product_counts_once_per_customer():
    """Added by rows, it would count each customer once per product it lost."""
    rows = _q12_rows()

    facts = describe(rows, _Q12_SQL)

    once = {}
    for row in rows:
        once.setdefault(row["cliente"], row["total_cliente"])
    whole = sum(once.values())
    by_rows = sum(row["total_cliente"] for row in rows)
    assert whole != by_rows
    assert "total total_cliente (once per cliente)" in _line(facts, "canal_nombre | rows | ")
    assert f"total total_cliente (once per cliente) {whole:.2f}" in _line(facts, "All rows:")
    mayoreo = {r["cliente"]: r["total_cliente"] for r in rows if r["canal_nombre"] == "Mayoreo"}
    assert f" | {sum(mayoreo.values()):.2f} | " in _line(facts, "Mayoreo | ")
    # The measures that vary by product add up by rows.
    assert f"total venta_ago_sep {sum(r['venta_ago_sep'] for r in rows):.2f}" in facts
    assert "venta_ago_sep (once per" not in facts


def test_a_channel_total_repeated_on_each_customer_counts_once_per_channel():
    """Both columns carry one value of it; the one with fewer values wins."""
    rows = [
        {"canal": canal, "cliente": f"{canal}-{i}", "total_canal": total, "venta": i + 1}
        for canal, total in (("A", 50), ("B", 70))
        for i in range(3)
    ]

    facts = describe(rows, "SELECT canal, cliente, total_canal, venta FROM t")

    assert "total total_canal (once per canal) 120" in facts
    assert "total venta 12" in facts


def test_a_constant_measure_adds_up_by_rows():
    rows = [{"canal": c, "cliente": f"{c}{i}", "cajas": 5} for c in "AB" for i in range(2)]

    facts = describe(rows, "SELECT * FROM t")

    assert "total cajas 20" in facts
    assert "once per" not in facts


def test_a_share_or_a_rank_never_carries_a_repeated_total():
    """Two channels at 100 % with one customer each share both figures by chance;
    counted once per percentage, the total would lose a customer."""
    rows = [
        {"canal": "A", "cobertura_pct": 100.0, "posicion": 1, "clientes_con_producto": 1},
        {"canal": "B", "cobertura_pct": 100.0, "posicion": 1, "clientes_con_producto": 1},
        {"canal": "C", "cobertura_pct": 50.0, "posicion": 2, "clientes_con_producto": 3},
    ]

    facts = describe(rows, "SELECT * FROM t")

    assert "total clientes_con_producto 5" in facts
    assert "once per" not in facts


def test_a_number_named_as_a_code_can_carry_a_repeated_total():
    rows = [
        {"canal_id": 1, "cliente": "X", "total_canal": 50, "venta": 10},
        {"canal_id": 1, "cliente": "Y", "total_canal": 50, "venta": 20},
        {"canal_id": 2, "cliente": "Z", "total_canal": 70, "venta": 30},
    ]

    facts = describe(rows, "SELECT * FROM t")

    assert "total total_canal (once per canal_id) 120" in facts
    assert "total venta 60" in facts


def test_repeats_that_carry_only_zero_or_nothing_claim_no_once_per():
    """Dropping them would not change the total, so there is nothing to say."""
    rows = [
        {"canal": "A", "cliente": "X", "venta_oct": Decimal("0E-7")},
        {"canal": "A", "cliente": "X", "venta_oct": Decimal("0E-7")},
        {"canal": "B", "cliente": "Y", "venta_oct": None},
        {"canal": "B", "cliente": "Y", "venta_oct": None},
        {"canal": "C", "cliente": "Z", "venta_oct": Decimal("-5.2500000")},
    ]

    facts = describe(rows, "SELECT * FROM t")

    assert "total venta_oct -5.25" in facts
    assert "once per" not in facts


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT canal, COUNT(DISTINCT cliente) AS clientes, sum(x) AS venta FROM t GROUP BY canal",
        "WITH k AS (SELECT canal, uniqExact(cliente) AS clientes, sum(x) AS venta FROM t "
        "GROUP BY canal) SELECT canal, clientes, venta FROM k",
        "SELECT canal, count(DISTINCT cliente) OVER (PARTITION BY canal) AS clientes, "
        "x AS venta FROM t",
        'SELECT canal, uniq(cliente) "clientes", sum(x) venta FROM t GROUP BY canal',
    ],
)
def test_a_distinct_count_has_no_total(sql):
    """A customer that buys in both channels would count twice."""
    rows = [{"canal": "A", "clientes": 3, "venta": 10}, {"canal": "B", "clientes": 2, "venta": 5}]

    facts = describe(rows, sql)

    assert "total clientes" not in facts
    assert "total venta 15" in facts


def test_a_plain_count_keeps_its_total():
    rows = [{"canal": "A", "filas": 3}, {"canal": "B", "filas": 2}]

    facts = describe(rows, "SELECT canal, count(*) AS filas FROM t GROUP BY canal")

    assert "total filas 5" in facts


def test_names_that_say_share_rank_code_or_calendar_have_no_total_by_whole_words():
    columns = {
        # no total
        "pct_perdida_mes_1": 1.5,
        "venta_promedio": 2.5,
        "posicion": 1,
        "rank_cliente": 2,
        "cliente_id": 7,
        "mes": 202608,
        "dias_habiles_transcurridos": 9,
        # a total: the word is not whole, or it names the measure's period
        "unidades": 4,
        "pedido_interno": 3,
        "facturado_mes_1": 10.25,
        "facturado_anio_total": 20.5,
    }
    rows = [{"canal": c, **columns} for c in "AB"]

    facts = describe(rows, "SELECT * FROM t")

    overall = _line(facts, "All rows:")
    for name in list(columns)[:7]:
        assert f"total {name} " not in overall
    assert "total unidades 8" in overall
    assert "total pedido_interno 6" in overall
    assert "total facturado_mes_1 20.50" in overall
    assert "total facturado_anio_total 41.00" in overall


# ── The LIMIT ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sql", "rows", "expected"),
    [
        ("SELECT a FROM t LIMIT 3", 3, "3 rows, LIMIT 3 reached: the query may have more rows"),
        ("SELECT a FROM t LIMIT 500;", 3, "3 rows, LIMIT 500 not reached."),
        ("SELECT a FROM t LIMIT 20, 3 -- page two", 3, "3 rows, LIMIT 3 reached"),
        ("SELECT a FROM t LIMIT 3 OFFSET 6", 3, "3 rows, LIMIT 3 reached"),
        ("SELECT TOP (3) a FROM t", 3, "3 rows, LIMIT 3 reached"),
        ("SELECT a FROM t FETCH FIRST 5 ROWS ONLY", 3, "3 rows, LIMIT 5 not reached."),
    ],
)
def test_the_limit_of_the_statement_and_whether_the_rows_reached_it(sql, rows, expected):
    facts = describe([{"a": f"v{i}"} for i in range(rows)], sql)

    assert facts.startswith(expected)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT canal, cliente FROM t ORDER BY venta DESC LIMIT 10 BY canal",
        "SELECT canal, cliente FROM (SELECT * FROM t LIMIT 2) s",
        "",
    ],
)
def test_a_cap_per_group_or_inside_a_subquery_is_not_the_results_limit(sql):
    facts = describe([{"canal": "A", "cliente": "x"}, {"canal": "A", "cliente": "y"}], sql)

    assert facts.startswith("2 rows.")


# ── The column the rows group on ─────────────────────────────────────────────


def test_between_a_code_and_its_name_the_rows_group_on_the_name():
    rows = [{"cod": c, "nombre": n, "v": 1} for c, n in (("01", "Norte"), ("02", "Sur"))]

    facts = describe(rows, "SELECT * FROM t")

    assert "By nombre (2 groups):" in facts
    assert _line(facts, "Norte | ") == "Norte | 1 | 01 | 1"


def test_an_empty_value_is_a_group_of_its_own():
    rows = [{"zona": z, "v": 1} for z in ("Norte", "", None, "Sur")]

    facts = describe(rows, "SELECT * FROM t")

    assert "By zona (3 groups):" in facts
    assert _line(facts, "(empty) | ") == "(empty) | 2 | 2"


def test_without_a_column_of_few_values_there_is_no_table_by_group():
    rows = [{"cliente": f"C{i}", "v": i} for i in range(20)]

    facts = describe(rows, "SELECT * FROM t")

    assert "By " not in facts
    assert facts == "20 rows. Columns: cliente, v.\nAll rows: distinct cliente 20; total v 190."


def test_a_value_that_is_not_text_nor_number_is_read_as_text():
    rows = [{"canal": "A", "tags": ["x", "y"]}, {"canal": "B", "tags": ["x"]}]

    assert "distinct canal 2, tags 2" in describe(rows, "SELECT * FROM t")


def test_no_rows():
    assert describe([], "SELECT a FROM t LIMIT 500") == "0 rows, LIMIT 500 not reached."


# ── Short, and never cut ─────────────────────────────────────────────────────


def test_a_wide_result_fits_by_leaving_parts_out_never_by_cutting():
    columns = [f"dimension_de_texto_{k}" for k in range(5)] + [
        f"medida_numero_{k}" for k in range(10)
    ]
    rows = []
    for g in range(12):
        for i in range(8):
            row = {"grupo_con_nombre_largo": f"GRUPO NUMERO {g:02d} DE PRUEBA"}
            row.update({c: f"VALOR {g}-{i}-{k}" for k, c in enumerate(columns[:5])})
            row.update({c: Decimal(f"{1000 * g + i}.123") for c in columns[5:]})
            rows.append(row)

    facts = describe(rows, "SELECT * FROM t LIMIT 500")

    assert len(facts) <= MAX_FACTS_CHARS
    assert facts.startswith("96 rows, LIMIT 500 not reached.")
    assert "[...]" not in facts
    assert facts.endswith(".")


def test_the_assumptions_go_whole_below_the_facts():
    readings = ["Lectura " + "a" * 700, "Otra lectura " + "b" * 700]

    facts = describe(_q12_rows(), _Q12_SQL, readings)

    assert len(_computed(facts)) <= MAX_FACTS_CHARS
    assert facts.endswith(f"Assumptions the query took:\n- {readings[0]}\n- {readings[1]}")

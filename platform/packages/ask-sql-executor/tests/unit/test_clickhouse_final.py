# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Where FINAL goes, and where it must not.

The placements marked "verified" were run against ClickHouse 22.1.3.7 (the
GONAC server) on 2026-10-12: FINAL after the alias works in FROM, in both sides
of a JOIN, in a subquery, a CTE and an IN subquery; FINAL before the alias is a
syntax error; a View or a system table rejects it with ILLEGAL_FINAL.
"""

from __future__ import annotations

import pytest

from ask_sql_executor.infrastructure.clickhouse_final import (
    add_final,
    find_table_refs,
    supports_final,
)


def _final_everywhere(sql: str) -> str:
    return add_final(sql, find_table_refs(sql))


def _names(sql: str) -> list[tuple[str | None, str]]:
    return [(r.database, r.name) for r in find_table_refs(sql)]


# ── placements ──────────────────────────────────────────────────────────────


def test_the_chat_query_from_the_gonac_poc():
    sql = (
        'SELECT count(*) AS open_order_items, sum("order_qty") AS total_order_qty '
        'FROM "gonac_gold_sd_open_order_tracker" WHERE "order_status" = \'OPEN\''
    )
    assert _final_everywhere(sql) == (
        'SELECT count(*) AS open_order_items, sum("order_qty") AS total_order_qty '
        'FROM "gonac_gold_sd_open_order_tracker" FINAL WHERE "order_status" = \'OPEN\''
    )


def test_final_goes_after_the_alias_not_before_it():  # verified
    assert (
        _final_everywhere('SELECT 1 FROM "t" AS o WHERE o."x" = 1')
        == 'SELECT 1 FROM "t" AS o FINAL WHERE o."x" = 1'
    )


def test_alias_without_as():
    assert (
        _final_everywhere("SELECT 1 FROM t o WHERE o.x = 1")
        == "SELECT 1 FROM t o FINAL WHERE o.x = 1"
    )


def test_qualified_table_keeps_its_database():  # verified
    sql = 'SELECT count() FROM "dbt_qas_bi"."gonac_gold_sd_open_order_tracker" AS o'
    assert _names(sql) == [("dbt_qas_bi", "gonac_gold_sd_open_order_tracker")]
    assert _final_everywhere(sql) == sql + " FINAL"


def test_both_sides_of_a_join():  # verified
    sql = 'SELECT 1 FROM "a" AS x LEFT JOIN "b" AS y ON x."k" = y."k" WHERE x."s" = \'OPEN\''
    assert _final_everywhere(sql) == (
        'SELECT 1 FROM "a" AS x FINAL LEFT JOIN "b" AS y FINAL ON x."k" = y."k" WHERE x."s" = \'OPEN\''
    )


def test_table_inside_a_subquery_but_not_the_subquery_alias():  # verified
    sql = "SELECT count() FROM (SELECT * FROM t WHERE s = 'OPEN') AS sub"
    assert _names(sql) == [(None, "t")]
    assert (
        _final_everywhere(sql)
        == "SELECT count() FROM (SELECT * FROM t FINAL WHERE s = 'OPEN') AS sub"
    )


def test_cte_name_is_not_a_table():  # verified
    sql = "WITH x AS (SELECT * FROM t) SELECT count() FROM x"
    assert _names(sql) == [(None, "t")]
    assert _final_everywhere(sql) == "WITH x AS (SELECT * FROM t FINAL) SELECT count() FROM x"


def test_in_subquery():  # verified
    sql = "SELECT count() FROM p WHERE m IN (SELECT m FROM o)"
    assert (
        _final_everywhere(sql) == "SELECT count() FROM p FINAL WHERE m IN (SELECT m FROM o FINAL)"
    )


def test_sample_comes_after_final():
    assert _final_everywhere("SELECT 1 FROM t SAMPLE 0.1") == "SELECT 1 FROM t FINAL SAMPLE 0.1"


def test_comma_separated_from_list():
    assert (
        _final_everywhere("SELECT 1 FROM a, b AS y WHERE 1")
        == "SELECT 1 FROM a FINAL, b AS y FINAL WHERE 1"
    )


def test_lowercase_keywords():
    assert _final_everywhere("select * from t join u on t.k = u.k") == (
        "select * from t FINAL join u FINAL on t.k = u.k"
    )


def test_projection_query_from_the_gonac_poc():
    sql = (
        'SELECT "material_id" AS material_id, "future_stock" AS existencia_proyectada '
        'FROM "gonac_gold_inventory_situation" WHERE "plant_id" = \'1001\' '
        'AND "future_date" <= toDate(\'2026-04-30\') ORDER BY "future_date" DESC LIMIT 1'
    )
    assert '"gonac_gold_inventory_situation" FINAL WHERE' in _final_everywhere(sql)


# ── what must be left alone ─────────────────────────────────────────────────


def test_existing_final_is_detected_and_not_doubled():
    sql = "SELECT 1 FROM t AS a FINAL WHERE 1"
    (ref,) = find_table_refs(sql)
    assert ref.has_final
    assert _final_everywhere(sql) == sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT extract(YEAR FROM d) FROM t",
        "SELECT trim(BOTH ' ' FROM name) FROM t",
        "SELECT substring(s FROM 2) FROM t",
    ],
)
def test_from_inside_a_function_is_not_a_table(sql):
    assert _names(sql) == [(None, "t")]


def test_strings_comments_and_quoted_identifiers_are_opaque():
    sql = (
        "SELECT 'FROM fake' AS \"FROM other\" -- FROM commented\n"
        "/* JOIN hidden */ FROM t WHERE c = 'it''s JOIN x'"
    )
    assert _names(sql) == [(None, "t")]


def test_array_join_is_not_a_table():
    assert _names("SELECT a FROM t ARRAY JOIN arr AS a") == [(None, "t")]
    assert _names("SELECT a FROM t LEFT ARRAY JOIN arr AS a") == [(None, "t")]


def test_table_function_is_not_a_table():
    assert _names("SELECT number FROM numbers(10)") == []


def test_unreadable_reference_is_skipped():
    assert _names("SELECT 1 FROM") == []


def test_add_final_only_where_asked():
    sql = 'SELECT 1 FROM "rpt_view" AS v JOIN "gold" AS g ON v.k = g.k'
    refs = find_table_refs(sql)
    gold_only = [r for r in refs if r.name == "gold"]
    assert (
        add_final(sql, gold_only)
        == 'SELECT 1 FROM "rpt_view" AS v JOIN "gold" AS g FINAL ON v.k = g.k'
    )


# ── engines ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        ("ReplacingMergeTree", True),
        ("ReplicatedReplacingMergeTree", True),
        ("CollapsingMergeTree", True),
        ("VersionedCollapsingMergeTree", True),
        ("AggregatingMergeTree", True),
        ("SummingMergeTree", True),
        ("MergeTree", False),
        ("View", False),
        ("MaterializedView", False),
        ("Distributed", False),
        ("", False),
        (None, False),
    ],
)
def test_supports_final(engine, expected):
    assert supports_final(engine) is expected

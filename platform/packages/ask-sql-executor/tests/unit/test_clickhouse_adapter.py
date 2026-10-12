# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The ClickHouse adapter's ``final`` flag, against a fake clickhouse-connect.

The case that motivated it: ClickHouse 22.1 answers ``final=1`` with
"Unknown setting final", and the adapter used to retry with no deduplication.
"""

from __future__ import annotations

import sys
import types

import pytest

from ask_sql_executor.domain.models import ExecutionRequest
from ask_sql_executor.infrastructure import clickhouse_adapter

UNKNOWN_SETTING = (
    "Received ClickHouse exception, code: 115, server response: Code: 115. "
    "DB::Exception: Unknown setting final. (UNKNOWN_SETTING) (version 22.1.3.7 (official build))"
)


class _Result:
    def __init__(self, rows, columns=("n",)):
        self.result_rows = rows
        self.column_names = list(columns)


class _FakeServer:
    """Records every statement and answers like a 22.1 server by default."""

    def __init__(self, *, takes_setting=False, engines=None, refuse_final=False, fail_lookup=False):
        self.takes_setting = takes_setting
        self.engines = engines or {}
        self.refuse_final = refuse_final
        self.fail_lookup = fail_lookup
        self.calls: list[tuple[str, dict | None]] = []

    def get_client(self, **kwargs):
        server = self

        class _Client:
            def query(self, sql, settings=None):
                server.calls.append((sql, settings))
                if settings and "final" in settings and not server.takes_setting:
                    raise RuntimeError(UNKNOWN_SETTING)
                if sql.startswith("SELECT database, name, engine FROM system.tables"):
                    if server.fail_lookup:
                        raise RuntimeError("Not enough privileges")
                    rows = [
                        (db, name, eng)
                        for (db, name), eng in server.engines.items()
                        if f"'{name}'" in sql
                    ]
                    return _Result(rows, ("database", "name", "engine"))
                if server.refuse_final and " FINAL" in sql:
                    raise RuntimeError("Syntax error: failed at position 62")
                return _Result([(1,)])

            def close(self):
                pass

        return _Client()

    def statements(self):
        return [sql for sql, _ in self.calls]


@pytest.fixture(autouse=True)
def _fresh_caches():
    clickhouse_adapter._rejects_setting.clear()
    clickhouse_adapter._engine_cache.clear()
    yield
    clickhouse_adapter._rejects_setting.clear()
    clickhouse_adapter._engine_cache.clear()


@pytest.fixture
def server(monkeypatch):
    def install(**kwargs):
        fake = _FakeServer(**kwargs)
        monkeypatch.setitem(
            sys.modules, "clickhouse_connect", types.SimpleNamespace(get_client=fake.get_client)
        )
        return fake

    return install


def _run(sql, *, final=True, database="dbt_qas_bi"):
    cfg = {
        "host": "ch",
        "port": 8123,
        "username": "read_gonac",
        "database": database,
        "final": final,
    }
    return clickhouse_adapter.execute_clickhouse(
        ExecutionRequest(sql=sql, db_type="clickhouse", db_config=cfg)
    )


GOLD = ("dbt_qas_bi", "gonac_gold_sd_open_order_tracker")
VIEW = ("dbt_qas_bi", "gonac_rpt_sd_open_order_tracker")
CHAT_SQL = 'SELECT count() FROM "gonac_gold_sd_open_order_tracker" WHERE "order_status" = \'OPEN\''


def test_without_the_flag_nothing_changes(server):
    fake = server()
    result = _run(CHAT_SQL, final=False)
    assert result.success and result.executed_sql is None
    assert fake.calls == [(CHAT_SQL, None)]


def test_a_server_that_takes_the_setting_gets_the_setting(server):
    fake = server(takes_setting=True)
    result = _run(CHAT_SQL)
    assert result.success and result.executed_sql is None
    assert fake.calls == [(CHAT_SQL, {"final": 1})]


def test_a_22_1_server_gets_final_on_the_replacing_table(server):
    fake = server(engines={GOLD: "ReplacingMergeTree"})
    result = _run(CHAT_SQL)
    expected = 'SELECT count() FROM "gonac_gold_sd_open_order_tracker" FINAL WHERE "order_status" = \'OPEN\''
    assert result.success
    assert result.executed_sql == expected
    assert fake.statements()[-1] == expected


def test_a_view_never_gets_final(server):
    server(engines={GOLD: "ReplacingMergeTree", VIEW: "View"})
    sql = 'SELECT 1 FROM "gonac_rpt_sd_open_order_tracker" AS v JOIN "gonac_gold_sd_open_order_tracker" AS g ON v.k = g.k'
    result = _run(sql)
    assert result.executed_sql == (
        'SELECT 1 FROM "gonac_rpt_sd_open_order_tracker" AS v JOIN "gonac_gold_sd_open_order_tracker" AS g FINAL ON v.k = g.k'
    )


def test_only_views_means_the_sql_runs_as_given(server):
    fake = server(engines={VIEW: "View"})
    result = _run('SELECT 1 FROM "gonac_rpt_sd_open_order_tracker"')
    assert result.success and result.executed_sql is None
    assert fake.statements()[-1] == 'SELECT 1 FROM "gonac_rpt_sd_open_order_tracker"'


def test_the_rejection_is_remembered_and_engines_are_cached(server):
    fake = server(engines={GOLD: "ReplacingMergeTree"})
    _run(CHAT_SQL)
    first = len(fake.calls)  # setting probe + engine lookup + rewritten query
    assert first == 3
    _run(CHAT_SQL)
    assert len(fake.calls) == first + 1  # straight to the rewritten query
    assert fake.calls[-1][1] is None and " FINAL " in fake.calls[-1][0]


def test_a_refused_rewrite_falls_back_to_the_generated_sql(server):
    fake = server(engines={GOLD: "ReplacingMergeTree"}, refuse_final=True)
    result = _run(CHAT_SQL)
    assert result.success and result.executed_sql is None
    assert fake.statements()[-1] == CHAT_SQL


def test_a_failed_engine_lookup_runs_without_final(server):
    fake = server(fail_lookup=True)
    result = _run(CHAT_SQL)
    assert result.success and result.executed_sql is None
    assert fake.statements()[-1] == CHAT_SQL


def test_a_qualified_table_is_looked_up_in_its_own_database(server):
    server(engines={("qas_sap_bronce", "GONAC_QAS_ORDER_HEADER"): "ReplacingMergeTree"})
    result = _run('SELECT 1 FROM "qas_sap_bronce"."GONAC_QAS_ORDER_HEADER" AS h')
    assert (
        result.executed_sql == 'SELECT 1 FROM "qas_sap_bronce"."GONAC_QAS_ORDER_HEADER" AS h FINAL'
    )


def test_an_unrelated_query_error_is_still_an_error(server, monkeypatch):
    server(takes_setting=True)

    def boom(**kwargs):
        class _Client:
            def query(self, sql, settings=None):
                raise RuntimeError("Missing columns: 'qty' while processing query")

            def close(self):
                pass

        return _Client()

    monkeypatch.setitem(sys.modules, "clickhouse_connect", types.SimpleNamespace(get_client=boom))
    result = _run(CHAT_SQL)
    assert not result.success
    assert "Missing columns" in (result.error or "")

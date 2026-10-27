# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: a chat SQL statement the database rejects gets one repair.

The bug these pin
─────────────────
Artifacts repaired a rejected statement once (PR #90); the chat did not, so on
ClickHouse 22.1 (GONAC) every dialect slip reached the user as "Pipeline
error". The real errors below came from the GONAC server's log: a Spanish alias
with an unquoted ñ, a String date compared with a Date, a conversion applied to
a column that already is a Date. None of them names its own fix, so each gets a
hint; an unreachable database is not sent to the model at all.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ask_orchestrator import sql_repair
from ask_orchestrator.models.requests import QueryRequest
from ask_orchestrator.routers import query as query_router

_GENERATED = 'SELECT SUM("ventas_aa") AS ventas_año_anterior FROM "gold_mv_resumen"'
_FIXED = 'SELECT SUM("ventas_aa") AS ventas_anio_anterior FROM "gold_mv_resumen"'

# Verbatim from the GONAC orchestrator log (2026-10-27), each one a chat failure.
_NON_ASCII = (
    "Received ClickHouse exception, code: 62, server response: Code: 62. DB::Exception: "
    "Syntax error: failed at position 342 ('\\xc3') (line 1, col 342): ño_anterior, "
    "round(toFloat64(SUM(\"facturado\")) / nullIf(toFloat64(SUM(\"objetivo\")), 0) * 100, 2). "
    "Unrecognized token: '\\xc3'. (SYNTAX_ERROR) (version 22.1.3.7 (official build))"
)
_STRING_VS_DATE = (
    "Code: 386. DB::Exception: There is no supertype for types String, Date because some of "
    "them are String/FixedString and some of them are not: while executing 'FUNCTION "
    "greaterOrEquals(order_date : 15, addMonths(toStartOfYear(today()), 6) : 22)'. (NO_COMMON_TYPE)"
)
_CONVERTED_DATE = (
    "Code: 43. DB::Exception: Illegal type Date of first argument of function toDateOrNull. "
    "Conversion functions with postfix 'OrZero' or 'OrNull'  should take String argument: While "
    "processing toDateOrNull(toDateOrNull(order_date) AS order_date). (ILLEGAL_TYPE_OF_ARGUMENT)"
)
_UNREACHABLE = (
    "HTTPDriver for http://3.22.43.208:8123 returned response code 0: "
    "Failed to establish a new connection: [Errno 111] Connection refused"
)


class _Database:
    """Executor stub with the shape of ``FormattedResult``: fails the statements
    listed in ``failures`` with their error, answers the rest with one row."""

    def __init__(self, failures: dict[str, str]):
        self.failures = failures
        self.executed: list[str] = []

    def execute_and_format(self, request, question=""):
        self.executed.append(request.sql)
        error = self.failures.get(request.sql)
        if error:
            return SimpleNamespace(
                sql=request.sql, rows_dict=[], answer=f"Pipeline error: {error}", error=error, row_count=0
            )
        return SimpleNamespace(sql=request.sql, rows_dict=[{"n": 1}], answer="Una fila.", error=None, row_count=1)


class _Repairs:
    """``repair_sql`` stub: answers from ``fixes``, records every call."""

    def __init__(self, fixes: dict[str, str]):
        self.fixes = fixes
        self.calls: list[tuple[str, str, str, str]] = []

    def __call__(self, failed_sql, error, db_type, *, phase):
        self.calls.append((failed_sql, error, db_type, phase))
        return self.fixes.get(failed_sql)


@pytest.fixture
def chat(monkeypatch):
    """Runs the SQL chain with a stub generator (always ``_GENERATED``), the
    given database failures and repairs."""
    from ask_llm_gateway.infrastructure import secrets as secrets_pkg

    def _run(failures: dict[str, str], fixes: dict[str, str]):
        db, repairs = _Database(failures), _Repairs(fixes)
        generator = SimpleNamespace(generate=lambda _req: SimpleNamespace(sql=_GENERATED, error=None, tokens_used=10))
        monkeypatch.setattr(
            secrets_pkg, "resolve_db_config", lambda env=None, **_kw: ("clickhouse", {"host": "db"})
        )
        monkeypatch.setattr(query_router, "_get_sql_generator", lambda _env: generator)
        monkeypatch.setattr(query_router, "_get_sql_executor", lambda: db)
        monkeypatch.setattr(query_router, "repair_sql", repairs)
        resolution = SimpleNamespace(
            yamls=[{"raw_yaml": "id: gold_mv_resumen"}], plan={}, edges=[], trace=SimpleNamespace(tokens_used=5)
        )
        req = QueryRequest(question="resumen de ventas", workspace_id="ws-1", mode="precise", env="dev")
        response = query_router._chain_sql_generation_and_executor(resolution, req, "SQL_EXECUTION", "t-1")
        return response, db, repairs

    return _run


def test_a_rejected_statement_gets_one_repair_and_answers_from_it(chat):
    response, db, repairs = chat({_GENERATED: _NON_ASCII}, {_GENERATED: _FIXED})

    assert db.executed == [_GENERATED, _FIXED]
    assert repairs.calls == [(_GENERATED, _NON_ASCII, "clickhouse", "sql_repair")]
    assert response.rows == [{"n": 1}]
    assert response.sql == _FIXED  # the chat shows the statement that produced the rows
    assert response.answer == "Una fila."


def test_a_statement_that_runs_is_not_repaired(chat):
    response, db, repairs = chat({}, {_GENERATED: _FIXED})

    assert db.executed == [_GENERATED]
    assert repairs.calls == []
    assert response.rows == [{"n": 1}]


def test_a_repair_that_fails_again_keeps_its_own_error_and_is_not_repaired_twice(chat):
    second = "Code: 47. DB::Exception: Missing columns: 'ventas_aa'. (UNKNOWN_IDENTIFIER)"
    response, db, repairs = chat({_GENERATED: _NON_ASCII, _FIXED: second}, {_GENERATED: _FIXED, _FIXED: "SELECT 3"})

    assert db.executed == [_GENERATED, _FIXED]
    assert len(repairs.calls) == 1
    assert response.rows is None
    assert response.sql == _FIXED
    assert "Missing columns" in response.answer


def test_without_a_usable_repair_the_original_error_stands(chat):
    response, db, repairs = chat({_GENERATED: _NON_ASCII}, {})

    assert db.executed == [_GENERATED]
    assert len(repairs.calls) == 1
    assert response.rows is None
    assert "Unrecognized token" in response.answer


def test_an_unreachable_database_is_not_sent_to_the_model(chat):
    response, db, repairs = chat({_GENERATED: _UNREACHABLE}, {_GENERATED: _FIXED})

    assert repairs.calls == []
    assert db.executed == [_GENERATED]
    assert "Connection refused" in response.answer


# ── sql_repair: what the model is told ───────────────────────────────────────


class _CapturingLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.messages: list = []

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.reply)


@pytest.fixture
def llm(monkeypatch):
    from ask_llm_gateway.application import factory

    def _llm(reply: str) -> _CapturingLLM:
        stub = _CapturingLLM(reply)
        monkeypatch.setattr(factory, "build_llm", lambda _cfg: stub)
        monkeypatch.setattr(sql_repair, "SettingsCache", SimpleNamespace(get=lambda: {}))
        return stub

    return _llm


@pytest.mark.parametrize(
    "error, expected_hint",
    [
        (_NON_ASCII, "letters outside ASCII"),
        (_STRING_VS_DATE, "Wrap the String side in toDateOrNull"),
        (_CONVERTED_DATE, "already a Date"),
    ],
    ids=["unquoted-non-ascii-alias", "string-date-vs-date", "conversion-on-a-date"],
)
def test_the_chat_failures_on_22_1_come_with_their_fix(llm, error, expected_hint):
    """The first error quotes a UTF-8 byte and says nothing about which name or
    why; the other two name the types but not the conversion that reconciles
    them."""
    stub = llm("SELECT fixed")

    assert sql_repair.repair_sql(_GENERATED, error, "clickhouse", phase="sql_repair") == "SELECT fixed"

    prompt = stub.messages[-1].content
    assert _GENERATED in prompt
    assert "What the error means" in prompt and expected_hint in prompt


@pytest.mark.parametrize(
    "error, repairable",
    [
        (_NON_ASCII, True),
        (_STRING_VS_DATE, True),
        ("Code: 60. DB::Exception: Table dbt_prd_bi.x doesn't exist. (UNKNOWN_TABLE)", True),
        (_UNREACHABLE, False),
        ("Read timed out. (read timeout=30)", False),
        ("Code: 516. DB::Exception: default: Authentication failed: password is incorrect", False),
        ("", False),
        (None, False),
    ],
)
def test_only_errors_a_rewrite_could_fix_are_repairable(error, repairable):
    assert sql_repair.is_repairable(error) is repairable

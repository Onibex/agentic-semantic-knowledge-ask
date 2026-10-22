# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: a failed artifact sub-query gets one repair attempt, and a
document with no data never invents figures.

The bugs these pin
──────────────────
The analytical sub-queries are written by an LLM that sees neither the semantic
layer nor the server version. On ClickHouse 22.1 (GONAC) two of three failed:
``SUM(facturado) AS facturado`` made a later ``SUM(facturado)`` a sum of a sum,
and a ratio of two window functions in one SELECT is an unknown identifier.
The datasets came back empty with the error and nothing retried them.

And when NO dataset had rows, the document prompt asked for "realistic
benchmarks" and "indicative estimates": the document then carried invented
figures indistinguishable from real ones.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ask_orchestrator.auth.validator import TokenClaims
from ask_orchestrator.models.requests import ArtifactRequest
from ask_orchestrator.routers import artifact as artifact_router
from ask_orchestrator.routers import query as query_router

_CLAIMS = TokenClaims(sub="u-1", email="tester@onibex.com", roles=[], issuer="keycloak")
_MAIN_SQL = "SELECT 1 AS n"
_ALIAS_ERROR = (
    "Code: 184. DB::Exception: Aggregate function sum(facturado) is found inside "
    "another aggregate function in query. (ILLEGAL_AGGREGATION)"
)


class _Database:
    """Executor stub: fails the statements listed in ``failures`` with their error."""

    def __init__(self, failures: dict[str, str]):
        self.failures = failures
        self.executed: list[str] = []

    def execute_and_format(self, request, question=""):
        self.executed.append(request.sql)
        error = self.failures.get(request.sql)
        if error:
            return SimpleNamespace(error=error, rows_dict=None)
        return SimpleNamespace(error=None, rows_dict=[{"n": 1}])

    def run_query_pipeline(self, _data_req, _user):
        return SimpleNamespace(sql=_MAIN_SQL, rows=[{"n": 1}])


class _Repairs:
    """``_repair_sub_sql`` stub: answers from ``fixes``, records every call."""

    def __init__(self, fixes: dict[str, str | None]):
        self.fixes = fixes
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, failed_sql, error, db_type):
        self.calls.append((failed_sql, error, db_type))
        return self.fixes.get(failed_sql)


@pytest.fixture
def wire(monkeypatch):
    """Wire a database and a repairer behind ``create_artifact``."""
    from ask_llm_gateway.infrastructure import secrets as secrets_pkg

    def _wire(sub_sqls, failures, fixes):
        db = _Database(failures)
        repairs = _Repairs(fixes)
        monkeypatch.setattr(
            secrets_pkg, "resolve_db_config", lambda env=None, **_kw: ("clickhouse", {"host": "h"})
        )
        monkeypatch.setattr(query_router, "_get_sql_executor", lambda: db)
        monkeypatch.setattr(query_router, "run_query_pipeline", db.run_query_pipeline)
        monkeypatch.setattr(artifact_router, "_generate_sub_sqls", lambda **_kw: list(sub_sqls))
        monkeypatch.setattr(artifact_router, "_repair_sub_sql", repairs)
        monkeypatch.setattr(artifact_router, "_generate_document", lambda *_a, **_kw: "# Stub")
        return db, repairs

    return _wire


def _request(override: bool = False) -> ArtifactRequest:
    return ArtifactRequest(
        name="Ventas 2026",
        artifact_type="custom",
        purpose="Dirección comercial",
        data_focus="facturado por mes",
        workspace_id="ws-1",
        env="prod",
        sql_override=_MAIN_SQL if override else None,
    )


def _sub_dataset(response, name):
    return next(ds for ds in response.datasets if ds.name == name)


def test_a_failed_sub_query_is_repaired_once_and_run_again(wire):
    db, repairs = wire(
        sub_sqls=[{"name": "Ranking", "sql": "SELECT bad"}],
        failures={"SELECT bad": _ALIAS_ERROR},
        fixes={"SELECT bad": "SELECT good"},
    )

    response = artifact_router.create_artifact(_request(), _CLAIMS)

    ranking = _sub_dataset(response, "Ranking")
    assert repairs.calls == [("SELECT bad", _ALIAS_ERROR, "clickhouse")]
    assert db.executed == ["SELECT bad", "SELECT good"]
    # The dataset shows the SQL that actually produced its rows.
    assert (ranking.sql, ranking.rows, ranking.error) == ("SELECT good", [{"n": 1}], None)


def test_a_repair_that_fails_again_keeps_its_error_and_is_not_retried(wire):
    db, repairs = wire(
        sub_sqls=[{"name": "Ranking", "sql": "SELECT bad"}],
        failures={"SELECT bad": _ALIAS_ERROR, "SELECT still_bad": "Code: 47. Unknown identifier"},
        fixes={"SELECT bad": "SELECT still_bad", "SELECT still_bad": "SELECT never"},
    )

    response = artifact_router.create_artifact(_request(), _CLAIMS)

    ranking = _sub_dataset(response, "Ranking")
    assert len(repairs.calls) == 1
    assert db.executed == ["SELECT bad", "SELECT still_bad"]
    assert (ranking.sql, ranking.error) == ("SELECT still_bad", "Code: 47. Unknown identifier")


def test_no_usable_repair_keeps_the_original_statement_and_error(wire):
    db, repairs = wire(
        sub_sqls=[{"name": "Ranking", "sql": "SELECT bad"}],
        failures={"SELECT bad": _ALIAS_ERROR},
        fixes={},  # the repairer returns None
    )

    response = artifact_router.create_artifact(_request(), _CLAIMS)

    ranking = _sub_dataset(response, "Ranking")
    assert len(repairs.calls) == 1
    assert db.executed == ["SELECT bad"]
    assert (ranking.sql, ranking.error) == ("SELECT bad", _ALIAS_ERROR)


def test_successful_sub_queries_are_never_sent_for_repair(wire):
    _db, repairs = wire(
        sub_sqls=[{"name": "A", "sql": "SELECT 2"}, {"name": "B", "sql": "SELECT 3"}],
        failures={},
        fixes={},
    )

    response = artifact_router.create_artifact(_request(), _CLAIMS)

    assert repairs.calls == []
    assert all(ds.error is None for ds in response.datasets)


def test_a_failed_sql_override_is_the_user_s_sql_and_is_never_repaired(wire):
    """The override is what the user edited; rewriting it behind their back would
    show figures for a query they did not write."""
    _db, repairs = wire(sub_sqls=[], failures={_MAIN_SQL: _ALIAS_ERROR}, fixes={})

    response = artifact_router.create_artifact(_request(override=True), _CLAIMS)

    assert repairs.calls == []
    assert response.data_error == _ALIAS_ERROR


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
        monkeypatch.setattr(artifact_router, "SettingsCache", SimpleNamespace(get=lambda: {}))
        return stub

    return _llm


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("```sql\nSELECT 2 AS total;\n```", "SELECT 2 AS total"),
        ("SELECT 2 AS total", "SELECT 2 AS total"),
        ("```sql\nSELECT bad\n```", None),  # the same statement back is no repair
        ("", None),
    ],
    ids=["fenced", "bare", "unchanged", "empty"],
)
def test_repair_sub_sql_returns_only_a_usable_different_statement(llm, reply, expected):
    stub = llm(reply)

    assert artifact_router._repair_sub_sql("SELECT bad", _ALIAS_ERROR, "clickhouse") == expected
    # The model is given the failed SQL and the database's own error text.
    prompt = stub.messages[-1].content
    assert "SELECT bad" in prompt and "ILLEGAL_AGGREGATION" in prompt


_WINDOW_ERROR = (
    "Code: 47. DB::Exception: Unknown identifier: sum(sum(facturado)) OVER (ORDER BY periodo "
    "ASC); there are columns: periodo, sum(facturado), sum(objetivo). (UNKNOWN_IDENTIFIER)"
)


@pytest.mark.parametrize(
    "error, expected_hint",
    [
        (_WINDOW_ERROR, "window function's result"),
        (_ALIAS_ERROR, "shadows that column"),
        ("Code: 60. DB::Exception: Table dbt_prd_bi.x doesn't exist.", None),
    ],
    ids=["window-in-expression", "alias-shadows-column", "unrelated"],
)
def test_repair_explains_errors_whose_text_does_not_name_the_fix(llm, error, expected_hint):
    """Measured on 22.1: told only "Unknown identifier ... OVER", the model kept the
    ratio between windows in the same SELECT and failed again; with the hint it
    moved the windows into a subquery (3 of 3)."""
    stub = llm("SELECT fixed")

    artifact_router._repair_sub_sql("SELECT bad", error, "clickhouse")

    prompt = stub.messages[-1].content
    if expected_hint:
        assert "What the error means" in prompt and expected_hint in prompt
    else:
        assert "What the error means" not in prompt


def test_a_document_without_data_is_told_never_to_invent_figures(llm):
    stub = llm("# Sin datos")

    artifact_router._generate_document(
        _request(), datasets=[], sql=None, trace_id="t-1", data_error="connection refused"
    )

    prompt = " ".join(m.content for m in stub.messages)
    assert "never invent" in prompt.lower()
    assert "connection refused" in prompt
    for invitation in (
        "realistic benchmarks",
        "realistic business estimates",
        "indicative estimates",
    ):
        assert invitation not in prompt

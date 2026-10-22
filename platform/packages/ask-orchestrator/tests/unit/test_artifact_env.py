# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
Regression tests: every SQL statement behind ``/v1/artifact`` must run against
the DB connection of the environment the request asked for.

The bug these pin
─────────────────
``_execute_sql_direct`` resolved the connection with ``resolve_db_config(None)``,
which means ``dev``. It backs the ``sql_override`` path and the analytical
sub-queries, so an artifact requested in ``prod`` mixed production rows (main
dataset) with dev rows (sub-queries), and a regenerated artifact, which always
sends the main SQL as ``sql_override``, came entirely from dev. Nothing errored:
the document simply carried the wrong figures. Only the main dataset without an
override honoured ``req.env``.
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
_SUB_SQLS = [
    {"name": "By plant", "sql": "SELECT 2 AS n"},
    {"name": "Top 10", "sql": "SELECT 3 AS n"},
]
_CONNECTIONS = {
    "dev": ("clickhouse", {"host": "dev-db", "database": "dbt_qas_bi"}),
    "prod": ("clickhouse", {"host": "prod-db", "database": "dbt_prd_bi"}),
}


class _Recorder:
    """Records every env resolved and every connection the executor received."""

    def __init__(self, connections: dict[str, tuple[str, dict]]):
        self.connections = connections
        self.resolved_envs: list[str | None] = []
        self.executed: list[tuple[str, str]] = []  # (sql, host)
        self.pipeline_envs: list[str] = []

    def resolve_db_config(self, env=None, **_kw):
        self.resolved_envs.append(env)
        return self.connections.get("prod" if env == "prod" else "dev", ("clickhouse", {}))

    def execute_and_format(self, request, question=""):
        self.executed.append((request.sql, request.db_config.get("host")))
        return SimpleNamespace(error=None, rows_dict=[{"n": 1}])

    def run_query_pipeline(self, data_req, _user):
        self.pipeline_envs.append(data_req.env)
        return SimpleNamespace(sql=_MAIN_SQL, rows=[{"n": 1}])


@pytest.fixture
def recorder(monkeypatch):
    from ask_llm_gateway.infrastructure import secrets as secrets_pkg

    rec = _Recorder(dict(_CONNECTIONS))
    # Both call sites import resolve_db_config lazily from the package, so
    # patching the package attribute reaches them.
    monkeypatch.setattr(secrets_pkg, "resolve_db_config", rec.resolve_db_config)
    monkeypatch.setattr(query_router, "_get_sql_executor", lambda: rec)
    monkeypatch.setattr(query_router, "run_query_pipeline", rec.run_query_pipeline)
    monkeypatch.setattr(artifact_router, "_generate_sub_sqls", lambda **_kw: list(_SUB_SQLS))
    monkeypatch.setattr(artifact_router, "_generate_document", lambda *_a, **_kw: "# Stub document")
    return rec


def _request(env: str, override: bool) -> ArtifactRequest:
    return ArtifactRequest(
        name="Open orders",
        artifact_type="custom",
        purpose="Weekly review",
        data_focus="open orders by plant",
        workspace_id="ws-1",
        env=env,
        sql_override=_MAIN_SQL if override else None,
    )


@pytest.mark.parametrize("override", [True, False], ids=["sql_override", "pipeline"])
@pytest.mark.parametrize("env", ["prod", "dev"])
def test_every_statement_runs_against_the_requested_env(recorder, env, override):
    """The core regression: main dataset and sub-queries all hit ``env``."""
    response = artifact_router.create_artifact(_request(env, override), _CLAIMS)

    expected_host = _CONNECTIONS[env][1]["host"]
    assert response.data_error is None
    assert recorder.resolved_envs, "the artifact resolved no connection at all"
    assert set(recorder.resolved_envs) == {env}, recorder.resolved_envs
    # Sub-queries always run here; the main SQL runs here only with an override
    # (otherwise it ran inside run_query_pipeline, which got the env below).
    expected_sqls = {item["sql"] for item in _SUB_SQLS} | ({_MAIN_SQL} if override else set())
    assert {sql for sql, _ in recorder.executed} == expected_sqls
    assert {host for _, host in recorder.executed} == {expected_host}
    assert recorder.pipeline_envs == ([] if override else [env])
    assert len(response.datasets) == 1 + len(_SUB_SQLS)


def test_prod_without_a_connection_errors_instead_of_falling_back_to_dev(recorder):
    """``prod`` does not inherit the dev connection, same rule as /v1/query.
    The document reports the missing connection; no statement reaches dev."""
    recorder.connections = {"dev": _CONNECTIONS["dev"]}

    response = artifact_router.create_artifact(_request("prod", override=True), _CLAIMS)

    assert recorder.executed == []
    assert response.data_error == "No database is configured for the 'prod' environment."
    assert response.datasets[0].error == response.data_error

# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""``POST /v1/admin/mcp/restart`` — the contract ASK Setup's button relies on.

The button reads ``ok`` and shows ``message`` in a toast, so the route must
answer 200 with ``ok: false`` when a restart is impossible. A 500 would reach
the SPA as "Restart failed: Request failed with status code 500", which says
nothing a reader can act on and hides the reason the helper worked out.

``outcome`` rides along so a future SPA can hide the button where restarting is
not a thing this deployment can do, instead of offering it and then explaining.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ask_admin_api.application.container_control import RestartOutcome, RestartReport
from ask_admin_api.routers import mcp


@pytest.fixture
def mcp_client() -> TestClient:
    app = FastAPI()

    class _Claims:
        email = "tester@onibex.com"

    app.dependency_overrides[mcp.validate_token] = lambda: _Claims()
    app.include_router(mcp.router)
    return TestClient(app)


def test_a_restart_reports_success(
    mcp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mcp,
        "restart_container",
        lambda name: RestartReport(RestartOutcome.RESTARTED, "Container 'ask-mcp' restarted."),
    )

    resp = mcp_client.post("/v1/admin/mcp/restart")

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "message": "Container 'ask-mcp' restarted.",
        "outcome": "restarted",
    }


def test_no_socket_is_a_200_the_button_can_explain(
    mcp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Kubernetes case must not arrive as a 500."""
    monkeypatch.setattr(
        mcp,
        "restart_container",
        lambda name: RestartReport(RestartOutcome.NO_SOCKET, "no Docker socket is mounted"),
    )

    resp = mcp_client.post("/v1/admin/mcp/restart")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["outcome"] == "no_socket"
    assert body["message"] == "no Docker socket is mounted"


def test_the_restart_targets_the_compose_container_by_name(
    mcp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No lookup, no substring filter: the route asks for one exact name."""
    asked: list[str] = []

    def _record(name: str) -> RestartReport:
        asked.append(name)
        return RestartReport(RestartOutcome.RESTARTED, "ok")

    monkeypatch.setattr(mcp, "restart_container", _record)

    mcp_client.post("/v1/admin/mcp/restart")

    assert asked == ["ask-mcp"]

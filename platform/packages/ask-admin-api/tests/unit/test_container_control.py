# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""The container restart helper, and the four answers it is allowed to give.

Written after the "Restart MCP" button reported "docker CLI not found on this
host" in every deployment it ever shipped in. The old code shelled out to a
binary the Python image does not carry, so the failure was total and silent to
CI: nothing here imported it, so nothing here could notice.

The two cases worth the most are the ones a boolean would have hidden. A
deployment WITHOUT a Docker socket, which is every Kubernetes deployment, is not
a failure and must not read like one. And an unsafe container name must never
reach the request path, because the name is interpolated into it.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ask_admin_api.application import container_control as cc


def _client_returning(status_code: int, *, calls: list[str]) -> Any:
    """Replace httpx's UNIX-socket transport with one that records and answers."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(status_code)

    return httpx.MockTransport(handler)


@pytest.fixture
def with_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend a Docker socket is mounted, without needing one."""
    monkeypatch.setattr(cc, "socket_available", lambda: True)


def test_a_deployment_without_a_socket_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Kubernetes case. It gets its own outcome and says what to do."""
    monkeypatch.setattr(cc, "socket_available", lambda: False)

    report = cc.restart_container("ask-mcp")

    assert report.ok is False
    assert report.outcome is cc.RestartOutcome.NO_SOCKET
    # The message has to name the cause. "docker CLI not found" was the old one
    # and it sent readers looking for a broken installation.
    assert "no Docker socket" in report.message
    assert "Kubernetes" in report.message


def test_204_is_the_success_the_engine_api_documents(
    with_socket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        httpx, "HTTPTransport", lambda **kw: _client_returning(204, calls=calls)
    )

    report = cc.restart_container("ask-mcp")

    assert report.ok is True
    assert report.outcome is cc.RestartOutcome.RESTARTED
    # By EXACT name. The old code ran `docker ps --filter name=mcp`, which
    # matches on substring, and restarted whatever came back first.
    assert calls == ["/containers/ask-mcp/restart"]


def test_404_names_the_profile_that_starts_it(
    with_socket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MCP is opt-in, so "not found" is a likely and recoverable answer."""
    calls: list[str] = []
    monkeypatch.setattr(
        httpx, "HTTPTransport", lambda **kw: _client_returning(404, calls=calls)
    )

    report = cc.restart_container("ask-mcp")

    assert report.outcome is cc.RestartOutcome.NOT_FOUND
    assert "--profile extras" in report.message


def test_any_other_status_is_a_failure_carrying_the_code(
    with_socket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        httpx, "HTTPTransport", lambda **kw: _client_returning(500, calls=[])
    )

    report = cc.restart_container("ask-mcp")

    assert report.outcome is cc.RestartOutcome.FAILED
    assert "500" in report.message


def test_an_unreachable_socket_does_not_raise(
    with_socket: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both call sites are a button or a save handler; neither may 500."""

    def boom(**kw: Any) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr(httpx, "HTTPTransport", boom)

    report = cc.restart_container("ask-mcp")

    assert report.outcome is cc.RestartOutcome.FAILED
    assert "connection refused" in report.message


@pytest.mark.parametrize(
    "name",
    [
        "../../secrets",
        "ask-mcp/restart?x=1",
        "",
        "-leading-dash",
    ],
)
def test_an_unsafe_name_never_reaches_the_request_path(
    with_socket: None, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The guard that keeps the Docker socket one verb wide.

    No caller passes a name from a request today. This is what keeps that from
    becoming exploitable the day one does.
    """
    calls: list[str] = []
    monkeypatch.setattr(
        httpx, "HTTPTransport", lambda **kw: _client_returning(204, calls=calls)
    )

    report = cc.restart_container(name)

    assert report.ok is False
    assert report.outcome is cc.RestartOutcome.FAILED
    assert calls == [], "an unsafe name must be refused before any HTTP call"


def test_the_mcp_container_name_is_the_one_compose_declares() -> None:
    """A rename in docker-compose.yml has to be mirrored here, so pin it."""
    assert cc.MCP_CONTAINER == "ask-mcp"

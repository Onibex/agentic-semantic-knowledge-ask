# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Restarting a sibling container, through the Docker Engine API socket.

Two call sites need it, both about the MCP server picking up something new:
the "Restart MCP" button on ASK Setup's Contracts page, and the SAP connection
save (the credentials reach the OData proxy through ``SAP_S4_SALESORDER_*`` in
the environment, which ``patch.js`` reads at boot, so a save only takes effect
on a restart).

WHY NOT THE ``docker`` CLI. The Contracts button used to shell out to
``subprocess.run(["docker", "restart", ...])``. The admin API image is Python
and has never carried the docker binary, so that call raised
``FileNotFoundError`` in every deployment it ever shipped in, and the button
reported "docker CLI not found on this host". The socket was mounted and
answering the whole time; only the binary was missing. Measured 2026-09-10
inside ``ask-admin-api``: ``/_ping`` returned 200 with API version 1.43, and
``which docker`` returned nothing. Talking to the Engine API over the socket
needs no binary, and it is what ``routers/sap_connection`` already did.

THE NAME IS NOT TAKEN FROM A LOOKUP. The old code ran
``docker ps --filter name=mcp`` and restarted ``containers[0]``. Docker's
``name`` filter matches on SUBSTRING, so on a host running more than one stack,
which is what the shared dev box does, the first match is not necessarily this
stack's container. This module restarts a container by EXACT name instead.

WHERE THIS CANNOT WORK, BY DESIGN. There is no Docker socket in a Kubernetes
pod, and on a containerd cluster there is no Docker at all. ``platform/deploy/``
mounts none and should not. So a missing socket is reported as its own outcome,
with a message that says the deployment does not support it, rather than one
that reads like a broken installation. The durable fix is for the MCP to expose
its own reload endpoint, the way the orchestrator already does with
``/v1/internal/reload``; tracked in group W of the backlog.

THE PRIVILEGE, STATED PLAINLY. A mounted Docker socket is the largest privilege
in the stack: a process that can write to it can do anything the daemon can,
including starting a container that mounts the host filesystem. That is why
this module is deliberately one verb wide. It restarts a container by a name the
CALLER holds as a constant, and it exposes nothing else. Never widen it to take
a container name from a request body, and never add a generic passthrough.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# The compose file mounts this into ask-admin-api. Absent in Kubernetes.
DOCKER_SOCKET = "/var/run/docker.sock"

# The MCP container's name is fixed in docker-compose.yml (``container_name:``),
# so it is a constant here rather than something discovered at run time.
MCP_CONTAINER = "ask-mcp"

# Docker's own rule for a container name. Enforced because the name is
# interpolated into the request path: a name carrying a slash would address a
# different Engine API endpoint entirely.
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class RestartOutcome(str, Enum):
    """Why the caller got the answer it got.

    Four cases, kept distinct because they need four different messages. A
    single boolean would collapse "this deployment has no Docker" into "it
    broke", which is the confusion this module was written to end.
    """

    RESTARTED = "restarted"
    NO_SOCKET = "no_socket"
    NOT_FOUND = "not_found"
    FAILED = "failed"


@dataclass(frozen=True)
class RestartReport:
    outcome: RestartOutcome
    message: str

    @property
    def ok(self) -> bool:
        return self.outcome is RestartOutcome.RESTARTED


def socket_available() -> bool:
    """Whether a Docker socket is mounted at all.

    Callers use it to decide whether to OFFER a restart, not only to explain a
    failure after the fact.
    """
    return Path(DOCKER_SOCKET).exists()


def restart_container(
    name: str = MCP_CONTAINER,
    *,
    timeout: float = 30.0,
) -> RestartReport:
    """Restart one container by exact name. Never raises.

    Every call site is a button or a save handler, so a failure here has to come
    back as a message a reader can act on, not as a 500 on an unrelated save.
    """
    if not _SAFE_NAME.match(name):
        # Not reachable from a request today, and the guard stays anyway: it is
        # what keeps that true if a future caller gets careless.
        return RestartReport(
            RestartOutcome.FAILED,
            f"Refusing to restart a container with an unsafe name: {name!r}",
        )

    if not socket_available():
        return RestartReport(
            RestartOutcome.NO_SOCKET,
            "This deployment cannot restart containers: no Docker socket is "
            f"mounted at {DOCKER_SOCKET}. Expected on Kubernetes. Restart "
            f"'{name}' with your orchestrator instead.",
        )

    import httpx

    try:
        transport = httpx.HTTPTransport(uds=DOCKER_SOCKET)
        with httpx.Client(
            transport=transport,
            base_url="http://docker",
            timeout=timeout,
        ) as client:
            resp = client.post(f"/containers/{name}/restart")
    except Exception as exc:  # noqa: BLE001 — a button must not 500
        return RestartReport(
            RestartOutcome.FAILED,
            f"Could not reach the Docker socket at {DOCKER_SOCKET}: {exc}",
        )

    # 204 is the documented success for POST /containers/{id}/restart. It
    # carries no body, so there is nothing to read on the happy path.
    if resp.status_code == 204:
        return RestartReport(
            RestartOutcome.RESTARTED,
            f"Container '{name}' restarted.",
        )
    if resp.status_code == 404:
        return RestartReport(
            RestartOutcome.NOT_FOUND,
            f"No container named '{name}' on this host. It is an opt-in "
            "service: start it with `docker compose --profile extras up -d`.",
        )
    return RestartReport(
        RestartOutcome.FAILED,
        f"Docker returned HTTP {resp.status_code} restarting '{name}'.",
    )


def restart_container_in_background(
    name: str = MCP_CONTAINER,
    *,
    trace_id: str = "",
) -> None:
    """Fire a restart and return at once, logging the outcome.

    For the save handlers, where the restart is a side effect: the user asked to
    store credentials, and a slow or missing MCP must not make that save look
    like it failed. The button path calls ``restart_container`` directly instead,
    because there the restart IS the request and the user is waiting for it.
    """

    def _run() -> None:
        report = restart_container(name)
        if report.ok:
            logger.info(
                "[%s] %s", trace_id, report.message, extra={"trace_id": trace_id}
            )
        else:
            logger.warning(
                "[%s] %s (restart it manually: docker restart %s)",
                trace_id,
                report.message,
                name,
                extra={"trace_id": trace_id},
            )

    threading.Thread(target=_run, daemon=True).start()

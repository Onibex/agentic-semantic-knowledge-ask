# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""Every OpenSearch client resolves its host from the environment, and only there.

Cross-package on purpose, which is why it lives here rather than under one
package's ``tests/``: it walks all nine client-construction sites, and no single
package may import the others (see ``.importlinter``).

**Why this exists.** The 1155 package tests never construct an OpenSearch
client, so they cannot catch the failure this guards: a construction path that
stops resolving, or one that quietly keeps reading ``config/settings.json``.
That is not hypothetical. While removing the file fallback,
``rag_vectorstore_client`` lost a parameter from its signature and kept a
reference to it in the body, which no unit test would have noticed because
nothing calls the function without a live cluster in sight.

opensearch-py does not connect when constructed, so this needs no cluster.

The rule being pinned, from ITERATION_K8S_MULTICLOUD_PLAN section 3.3: you
cannot read the address of OpenSearch out of OpenSearch, so the connection is
one of the three things that stays in the environment for good. A settings file
in the working directory must never win, and must never be consulted at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ENV_HOST = "env-host.invalid"
FILE_HOST = "file-host.invalid"


def _construction_sites() -> list[tuple[str, Any]]:
    """The nine sites, imported lazily so a collection error names the culprit."""
    from ask_admin_api.application.system_prompts_repository import (
        _build_client as prompts_client,
    )
    from ask_admin_api.application.workspace_repository import (
        _build_client as workspace_client,
    )
    from ask_docs_service.application.factory import _opensearch_kwargs as docs_kwargs
    from ask_knowledge_graph.infrastructure.opensearch_repository import (
        _opensearch_kwargs as kg_kwargs,
    )
    from ask_knowledge_graph.infrastructure.rag_vectorstore_client import _get_os_client
    from ask_llm_gateway.infrastructure.secrets.repository import (
        _build_client as secrets_client,
    )
    from ask_orchestrator.organization_context import _build_client as org_client
    from ask_orchestrator.workspace_scope import _build_client as scope_client

    return [
        ("admin-api/system_prompts_repository", prompts_client),
        ("admin-api/workspace_repository", workspace_client),
        ("docs-service/factory", docs_kwargs),
        ("knowledge-graph/opensearch_repository", kg_kwargs),
        ("knowledge-graph/rag_vectorstore_client", _get_os_client),
        ("llm-gateway/secrets.repository", secrets_client),
        ("orchestrator/organization_context", org_client),
        ("orchestrator/workspace_scope", scope_client),
    ]


def _resolved_host(built: Any) -> str:
    """The host a built client, or a kwargs dict, ended up pointing at."""
    if isinstance(built, dict):
        return str(built["hosts"][0]["host"])
    hosts = getattr(getattr(built, "transport", None), "hosts", None)
    if hosts:
        first = hosts[0]
        return str(first["host"] if isinstance(first, dict) else first)
    pool = getattr(getattr(built, "transport", None), "connection_pool", None)
    connections = getattr(pool, "connections", None)
    if connections:
        return str(getattr(connections[0], "host", ""))
    raise AssertionError(f"cannot read the resolved host off a {type(built).__name__}")


@pytest.fixture
def cwd_with_a_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory carrying a settings.json that must be ignored.

    Deliberately hostile: it names a different host, port and TLS setting from
    anything the environment says, so a path that still reads it fails loudly
    instead of coincidentally agreeing.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(
        json.dumps(
            {
                "opensearch": {
                    "host": FILE_HOST,
                    "port": 9999,
                    "use_ssl": True,
                    "username": "from-the-file",
                    "password": "from-the-file",
                    "pool_maxsize": 3,
                    "embedding_dim": 42,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("label,build", _construction_sites(), ids=lambda v: v)
def test_environment_wins_and_the_file_is_not_read(
    label: str,
    build: Any,
    cwd_with_a_settings_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSEARCH_HOST", ENV_HOST)
    monkeypatch.delenv("OPENSEARCH_PORT", raising=False)

    host = _resolved_host(build())

    assert host != FILE_HOST, f"{label} still reads config/settings.json"
    assert host == ENV_HOST, f"{label} resolved {host!r}, expected the env var"


@pytest.mark.parametrize("label,build", _construction_sites(), ids=lambda v: v)
def test_unset_falls_to_localhost_never_to_the_file(
    label: str,
    build: Any,
    cwd_with_a_settings_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing set, the historical default stands.

    Removing the file as a source deliberately did NOT change what happens when
    the environment is empty, so a native local run still works untouched.
    """
    monkeypatch.delenv("OPENSEARCH_HOST", raising=False)

    host = _resolved_host(build())

    assert host != FILE_HOST, f"{label} still reads config/settings.json"
    assert host == "localhost", f"{label} resolved {host!r}, expected localhost"

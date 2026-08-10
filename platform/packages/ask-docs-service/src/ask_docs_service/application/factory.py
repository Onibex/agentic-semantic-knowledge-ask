"""
Default-construction helper for the docs service (Iter 8.8).

Wires `DocsRagService` with its dedicated retriever, embedder, and LLM.
The orchestrator's `query.py` calls `build_default_docs_service()` on
first use; previously this wiring lived in `legacy_adapter.py`.

Per ADR (Iter 5 Q6): ask-docs-service is a peer of ask-knowledge-graph.
It uses the SAME OpenSearch backend but its OWN retriever class — the
two packages must NOT share Reader/Writer code paths so they can evolve
independently. import-linter forbids `ask_docs_service` from importing
`ask_knowledge_graph`. The OpenSearch CLIENT, however, is shared via
the `OpenSearchAskRepository` constructor (same cluster, same indices).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .rag_flow import DocsRagService


def build_default_docs_service(env: str | None = None) -> DocsRagService:
    """Construct a `DocsRagService` ready to answer DOCS_QUERY intents.

    ``env`` (dev/prod/None) selects the env-suffixed docs index so a
    DOCS_QUERY reads the same environment the chat user picked.

    The OpenSearch client is built locally (not borrowed from
    `ask_knowledge_graph`) so the peer-isolation contract holds — the two
    packages must NOT share Python imports even though they hit the same
    cluster. This is identical client construction to what
    `ask_knowledge_graph.infrastructure.opensearch_repository` does.
    """
    from opensearchpy import OpenSearch

    from ask_llm_gateway.application.factory import build_embedder, build_llm

    from ..infrastructure.opensearch_docs_retriever import OpenSearchDocsRetriever

    cfg = _load_config()
    llm = build_llm(cfg)
    embedder = build_embedder(cfg)
    client = OpenSearch(**_opensearch_kwargs(cfg.get("opensearch") or {}))
    retriever = OpenSearchDocsRetriever(client=client, env=env)
    return DocsRagService(retriever=retriever, embedder=embedder, llm=llm)


def _load_config() -> dict[str, Any]:
    cfg_path = Path("config/settings.json")
    if not cfg_path.exists():
        raise RuntimeError("config/settings.json not found — service must run from project root")
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _opensearch_kwargs(os_cfg: dict[str, Any]) -> dict[str, Any]:
    """Env-first OpenSearch client kwargs (OPENSEARCH_*), settings.json fallback.

    Mirrors ask_llm_gateway.infrastructure.secrets.repository — env vars win so
    this survives the cleanup that strips ``opensearch`` from settings.json.
    """
    host = os.getenv("OPENSEARCH_HOST")
    port_env = os.getenv("OPENSEARCH_PORT")
    use_ssl_env = os.getenv("OPENSEARCH_USE_SSL")
    username = os.getenv("OPENSEARCH_USER") or None
    password = os.getenv("OPENSEARCH_PASSWORD") or None

    if not host:
        host = os_cfg.get("host", "localhost")
        port = int(port_env or os_cfg.get("port", 9200))
        use_ssl = (
            bool(os_cfg.get("use_ssl", False)) if use_ssl_env is None else _truthy(use_ssl_env)
        )
        username = username or os_cfg.get("username") or None
        password = password or os_cfg.get("password") or None
        verify_certs = bool(os_cfg.get("verify_certs", False))
    else:
        port = int(port_env or 9200)
        use_ssl = _truthy(use_ssl_env or "")
        verify_certs = _truthy(os.getenv("OPENSEARCH_VERIFY_CERTS", ""))

    kwargs: dict[str, Any] = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
    }
    if username and password:
        kwargs["http_auth"] = (username, password)
    return kwargs

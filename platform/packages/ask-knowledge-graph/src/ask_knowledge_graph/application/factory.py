"""
Default-construction helpers for the Knowledge Graph package.

The admin API and the CLI both need to wire the typed adapters
(reader / writer / dictionary writer / ingestion service). This module
centralises the bootstrap so every caller goes through one place.

The package is **runtime-self-contained** for cluster-3 concerns: the
OpenSearch repo, the SAP JSON parser, the YAML serializer, the file-storage
repo, the ingestion + dictionary classes, and the domain node models all
live here. The embedder is delegated to `ask-llm-gateway` (the architectural
home for managed model access).

Callers receive typed Protocol instances (`KnowledgeGraphReader`,
`KnowledgeGraphWriter`, `IngestionService`, `DictionaryWriter`) and
never have to know about the underlying classes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..domain.ports import (
    DictionaryWriter,
    IngestionService,
    KnowledgeGraphReader,
    KnowledgeGraphWriter,
)

if TYPE_CHECKING:
    from .rag_indexing_service import RagIndexingService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_default_config(
    config_path: str | Path = "config/settings.json",
) -> dict[str, Any]:
    """Read `config/settings.json` from the current working directory.

    The CLI uses this directly. Service callers that already hold a config
    dict should pass it through to the build_* functions instead of calling
    this.
    """
    path = Path(config_path)
    if not path.exists():
        raise SystemExit(f"{path} not found — run from project root or pass an explicit path")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_repo(env: str | None = None) -> Any:
    """Construct an OpenSearchAskRepository instance (KG package class).

    ``env`` (Iter 2) suffixes every registry index (``-dev``/``-prod``);
    ``None`` keeps the legacy un-suffixed names.
    """
    from ..infrastructure.opensearch_repository import OpenSearchAskRepository

    return OpenSearchAskRepository(env=env)


def _build_embedder(config: dict[str, Any]) -> Any | None:
    """Construct a SAPAICoreEmbedder, returning None on any failure.

    The dictionary admin page is permissive about a missing embedder
    (entries get saved without embeddings + a warning) — preserve that.
    Ingestion-side callers that REQUIRE an embedder should check the
    return value themselves.
    """
    try:
        from ask_llm_gateway.application.factory import build_embedder

        return build_embedder(config)
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.warning("Embedder construction failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public factories
# ─────────────────────────────────────────────────────────────────────────────
def build_default_reader(env: str | None = None) -> KnowledgeGraphReader:
    """Return a `KnowledgeGraphReader` over the OpenSearch repo.

    ``env`` targets the env-suffixed registry indices (``-dev``/``-prod``, Iter 2)
    — use it for deployment queries like "what is published to dev". ``None``
    keeps the legacy un-suffixed names. Curation browse should NOT use this:
    the SPA reads the WORKING YAMLs (git workspace) so unpublished/just-created
    entities are visible — env indices only hold what's been deployed.
    """
    from ..infrastructure.opensearch_reader import OpenSearchKnowledgeGraphReader

    return OpenSearchKnowledgeGraphReader(legacy_repo=_build_repo(env))


def build_default_writer(env: str | None = None) -> KnowledgeGraphWriter:
    """Return a `KnowledgeGraphWriter` over the OpenSearch repo.

    ``env`` targets the env-suffixed registry indices (Iter 2); ``None`` = legacy.
    """
    from ..infrastructure.opensearch_writer import OpenSearchKnowledgeGraphWriter

    return OpenSearchKnowledgeGraphWriter(legacy_repo=_build_repo(env))


def build_default_dictionary_writer(
    config: dict[str, Any],
) -> DictionaryWriter:
    """Return a `DictionaryWriter` (read + write) over the semantic dictionary.

    `config` is the runtime config dict (typically from
    `utils.config_manager.ConfigManager().load_config()` or
    `load_default_config()`). The embedder is best-effort — see
    `_build_embedder`.
    """
    from ..infrastructure.opensearch_dictionary_writer import (
        OpenSearchDictionaryWriter,
    )
    from ._legacy_dictionary import SemanticDictionaryService

    repo = _build_repo()
    embedder = _build_embedder(config)
    legacy_service = SemanticDictionaryService(
        repo.client, embedder=embedder, embedding_dim=repo.embedding_dim
    )
    return OpenSearchDictionaryWriter(legacy_service=legacy_service)


def build_default_ingestion_service(
    config: dict[str, Any],
    *,
    with_file_storage: bool = False,
    env: str | None = None,
) -> IngestionService:
    """Return an `IngestionService` ready to ingest YAMLs or SAP JSON.

    Wraps the production-tested `MetadataIngestionService` +
    `OpenSearchKnowledgeGraphWriter` in the Iter 6 typed Protocol.
    `config` provides the AI Core + embedding deployment id needed by
    SAPAICoreEmbedder.

    `with_file_storage=True` injects a `LocalFileStorageRepository` so
    `ingest_sap_json` also writes the parsed Bronze + Silver YAMLs to
    disk under `config["workspace_dir"]` (default `./workspace`). The
    CLI does not need this; the admin API Ingestor endpoints do.
    """
    from ..infrastructure.naming_config import resolve_column_naming_mode
    from ..infrastructure.opensearch_writer import OpenSearchKnowledgeGraphWriter
    from ..infrastructure.sap_json_parser import SapJsonParser
    from ._legacy_ingestion import MetadataIngestionService
    from .ingestion_service import MetadataIngestionServiceWrapper

    repo = _build_repo(env)
    embedder = _build_embedder(config)
    # Explicit because this caller holds the parsed config; every other
    # construction site self-resolves (env / settings.json).
    parser = SapJsonParser(naming_mode=resolve_column_naming_mode(config))

    file_repo = None
    if with_file_storage:
        from ..infrastructure.file_storage_repo import LocalFileStorageRepository

        workspace_dir = config.get("workspace_dir", "./workspace")
        file_repo = LocalFileStorageRepository(base_dir=workspace_dir)

    legacy = MetadataIngestionService(
        parser=parser,
        os_repository=repo,
        file_repository=file_repo,
        embedder=embedder,
    )
    writer = OpenSearchKnowledgeGraphWriter(legacy_repo=repo)
    return MetadataIngestionServiceWrapper(legacy_service=legacy, writer=writer)


def build_default_rag_indexing_service(
    config: dict[str, Any],
    env: str | None = None,
) -> RagIndexingService:
    """Return a ready-to-use :class:`RagIndexingService`.

    Wires the configured embedder + the OpenSearch config from
    ``config/settings.json``. Raises ``RuntimeError`` if the embedder
    cannot be built — RAG indexing is useless without one, so we fail
    loud here (unlike the dictionary path where missing embedder is OK).
    """
    from .rag_indexing_service import RagIndexingService

    embedder = _build_embedder(config)
    if embedder is None:
        raise RuntimeError(
            "RAG indexing requires an embedder — check embedder provider config "
            "(config['embedder']['provider'] or EMBEDDER_PROVIDER env var)."
        )
    os_config = config.get("opensearch", {}) or {}
    return RagIndexingService(embedder=embedder, os_config=os_config, env=env)

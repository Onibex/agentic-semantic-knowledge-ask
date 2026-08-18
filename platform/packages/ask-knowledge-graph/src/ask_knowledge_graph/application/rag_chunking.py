# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ask_knowledge_graph.application.rag_chunking
─────────────────────────────────────────────────────────────────────────────
Split rendered embedding-text (from :mod:`rag_text_renderer`) into chunks
suitable for OpenSearch indexing.

The separators line up with the section markers emitted by the renderer
(``\\n\\nFIELDS\\n``, ``\\n\\nRELATIONSHIPS\\n``) so chunks break on
semantic boundaries instead of mid-field. The defaults mirror what the
former 3_Embeddings.py page used (chunk_size=2000, overlap=200) to keep
retrieval behaviour in the `rag_schema` collection unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ChunkDoc", "build_chunks", "clean_text"]


@dataclass
class ChunkDoc:
    """A chunked document ready to be embedded + indexed.

    Mirrors the langchain ``Document`` shape (``page_content`` + ``metadata``)
    so adapters can convert to it trivially, but we keep a typed dataclass
    here to avoid leaking langchain into the application layer.
    """

    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# Default chunking parameters — match the legacy 3_Embeddings.py "YAML Data
# Products" mode so retrieval quality is preserved when callers don't override.
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_SEPARATORS = ["\n\nRELATIONSHIPS", "\n\nFIELDS", "\n\n", "\n"]


def build_chunks(
    text: str,
    base_metadata: dict[str, Any] | None = None,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: list[str] | None = None,
) -> list[ChunkDoc]:
    """Split *text* into :class:`ChunkDoc` instances.

    The default separators match the section markers produced by the renderer
    so a YAML document chunks at FIELDS / RELATIONSHIPS boundaries naturally.
    Each chunk inherits *base_metadata* verbatim — callers that want unique
    ids per chunk should add them after this returns.
    """
    if not text or not text.strip():
        return []

    seps = separators or DEFAULT_SEPARATORS
    base_metadata = dict(base_metadata or {})

    # Import lazily so the package doesn't hard-depend on langchain at module
    # load time — only callers that actually chunk pay the import cost.
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=seps,
    )

    pieces = splitter.split_text(text)
    return [
        ChunkDoc(page_content=clean_text(piece), metadata=dict(base_metadata))
        for piece in pieces
        if piece and piece.strip()
    ]


def clean_text(text: str) -> str:
    """Strip control characters + collapse triple-newlines.

    Mirrors the cleaner from the legacy 3_Embeddings page so chunks land
    in OpenSearch with the same shape regardless of source.
    """
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = "".join(c for c in text if c in "\n\r\t" or ord(c) >= 32)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()

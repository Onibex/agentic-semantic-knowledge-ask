"""Request / response models for ``/v1/admin/embeddings/*``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """One chunk produced by the UI's local file parser + splitter.

    The UI owns parsing (PDF / DOCX / Excel / TXT) and chunking (langchain
    text splitter); the admin API only embeds + indexes.
    """

    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IndexDocumentsRequest(BaseModel):
    collection_name: str = Field(
        ...,
        description="OpenSearch index/collection name (e.g. 'rag_schema', 'rag_data_product_docs').",
    )
    documents: list[DocumentChunk] = Field(
        default_factory=list,
        description="Pre-chunked documents to embed and index.",
    )
    batch_size: int = Field(
        default=64,
        ge=1,
        le=512,
        description="Server-side batch size for the embedding model. Tune to AI Core rate limits.",
    )


class IndexDocumentsResponse(BaseModel):
    indexed: int = 0
    batches_sent: int = 0
    error: str | None = None


class EmbeddingEntry(BaseModel):
    source_file: str
    table_name: str | None = None
    # entity_id is the canonical join key against the catalog (set by the
    # renderer on Silver/Gold chunks). Prefer this over table_name when
    # matching to ``yaml_catalog()`` results — table_name can diverge from
    # entity.id when ``db_table_name`` is set explicitly in the YAML.
    entity_id: str | None = None
    doc_count: int = 0


class ListDocumentsResponse(BaseModel):
    collection: str
    total_docs: int = 0
    entries: list[EmbeddingEntry] = Field(default_factory=list)
    error: str | None = None


class DeleteDocumentsRequest(BaseModel):
    source_files: list[str] | None = Field(
        default=None,
        description="Source files to delete (metadata.source_file.keyword).",
    )
    entity_ids: list[str] | None = Field(
        default=None,
        description=(
            "Entity ids to delete (metadata.entity_id.keyword). Takes "
            "precedence over source_files when both are set. None on both "
            "fields = delete entire collection."
        ),
    )


class DeleteDocumentsResponse(BaseModel):
    deleted: int = 0
    error: str | None = None

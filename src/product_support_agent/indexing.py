from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from product_support_agent.catalog import ProductReference
from product_support_agent.document_store import CanonicalDocumentRepository
from product_support_agent.documents import (
    CanonicalChunk,
    CanonicalDocument,
    chunk_document,
    normalize_html,
)
from product_support_agent.search import SearchProvider


class EmbeddingProvider(Protocol):
    @property
    def model_version(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class DocumentIndexingError(RuntimeError):
    pass


def _same_indexed_content(previous: CanonicalDocument, current: CanonicalDocument) -> bool:
    return (
        previous.content_hash == current.content_hash
        and previous.title == current.title
        and previous.product_name == current.product_name
        and previous.schema_version == current.schema_version
        and previous.parser_version == current.parser_version
    )


class DocumentIndexingService:
    def __init__(
        self,
        *,
        repository: CanonicalDocumentRepository,
        search: SearchProvider,
        embedder: EmbeddingProvider,
        chunk_size_chars: int = 1_200,
        chunk_overlap_chars: int = 150,
        max_document_bytes: int = 4_194_304,
    ) -> None:
        if not embedder.model_version.strip() or embedder.dimensions <= 0:
            raise ValueError("embedding model version and positive dimensions are required")
        self.repository = repository
        self.search = search
        self.embedder = embedder
        self.chunk_size_chars = chunk_size_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.max_document_bytes = max_document_bytes

    async def index_html(
        self,
        source: ProductReference,
        body: bytes,
        content_type: str,
        *,
        fetched_at: datetime | None = None,
    ) -> CanonicalDocument:
        document = normalize_html(
            source,
            body,
            content_type,
            max_bytes=self.max_document_bytes,
            fetched_at=fetched_at,
        )
        chunks = chunk_document(
            document,
            max_chars=self.chunk_size_chars,
            overlap_chars=self.chunk_overlap_chars,
        )
        existing = await asyncio.to_thread(self.repository.get_document, document.document_id)
        if existing is None or not _same_indexed_content(existing[0], document):
            await self._replace_search_index(document.document_id, chunks)
        # The repository write is the commit marker: it happens only after the search index
        # accepted the chunks, so an interrupted run re-embeds instead of skipping.
        await asyncio.to_thread(self.repository.replace_document, document, chunks)
        return document

    async def reprocess_document(self, document_id: str) -> CanonicalDocument | None:
        record = await asyncio.to_thread(self.repository.get_document, document_id)
        if record is None:
            await self.search.delete_document(document_id)
            return None

        document, chunks = record
        await self._replace_search_index(document.document_id, chunks)
        return document

    async def reconcile_all(self) -> int:
        document_ids = await asyncio.to_thread(self.repository.list_document_ids)
        for document_id in document_ids:
            await self.reprocess_document(document_id)
        return len(document_ids)

    async def delete_document(self, document_id: str) -> None:
        await self.search.delete_document(document_id)
        await asyncio.to_thread(self.repository.delete_document, document_id)

    async def _replace_search_index(
        self,
        document_id: str,
        chunks: Sequence[CanonicalChunk],
    ) -> None:
        embeddings = await self.embedder.embed_documents([chunk.content for chunk in chunks])
        if len(embeddings) != len(chunks):
            raise DocumentIndexingError("embedding provider returned an unexpected result count")

        vectors: list[list[float]] = []
        for embedding in embeddings:
            vector = [float(value) for value in embedding]
            if len(vector) != self.embedder.dimensions:
                raise DocumentIndexingError(
                    "embedding dimensions do not match the configured model"
                )
            if not all(math.isfinite(value) for value in vector):
                raise DocumentIndexingError("embedding provider returned a non-finite value")
            vectors.append(vector)
        await self.search.replace_document(document_id, chunks, vectors)


class RepositoryOnlyIndexer:
    """Persist canonical documents and chunks without embeddings or a search index.

    Use until an embedding provider is approved; `DocumentIndexingService.reconcile_all`
    later embeds and indexes everything stored here.
    """

    def __init__(
        self,
        *,
        repository: CanonicalDocumentRepository,
        chunk_size_chars: int = 1_200,
        chunk_overlap_chars: int = 150,
        max_document_bytes: int = 4_194_304,
    ) -> None:
        self.repository = repository
        self.chunk_size_chars = chunk_size_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.max_document_bytes = max_document_bytes

    async def index_html(
        self,
        source: ProductReference,
        body: bytes,
        content_type: str,
        *,
        fetched_at: datetime | None = None,
    ) -> CanonicalDocument:
        document = normalize_html(
            source,
            body,
            content_type,
            max_bytes=self.max_document_bytes,
            fetched_at=fetched_at,
        )
        chunks = chunk_document(
            document,
            max_chars=self.chunk_size_chars,
            overlap_chars=self.chunk_overlap_chars,
        )
        await asyncio.to_thread(self.repository.replace_document, document, chunks)
        return document

    async def delete_document(self, document_id: str) -> None:
        await asyncio.to_thread(self.repository.delete_document, document_id)

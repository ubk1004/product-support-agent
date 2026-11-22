import asyncio

import pytest

from product_support_agent.catalog import ProductReference
from product_support_agent.document_store import (
    InMemoryCanonicalDocumentRepository,
    MongoCanonicalDocumentRepository,
)
from product_support_agent.documents import (
    CanonicalChunk,
    CanonicalDocument,
    chunk_document,
    normalize_html,
)
from product_support_agent.indexing import DocumentIndexingError, DocumentIndexingService
from product_support_agent.search import InMemorySearchProvider

SOURCE_URL = "https://my.opentext.com/support/products/product-a"
HTML_CONTENT = b"<html><body>Searchable support material for indexing.</body></html>"


def source(
    product_id: str = "product-a",
    source_url: str = SOURCE_URL,
) -> ProductReference:
    return ProductReference(
        product_id=product_id,
        name=f"Product {product_id}",
        slug=product_id,
        source_url=source_url,
    )


def canonical_document(
    body: bytes = HTML_CONTENT,
    *,
    product_id: str = "product-a",
    source_url: str = SOURCE_URL,
) -> CanonicalDocument:
    return normalize_html(
        source(product_id, source_url),
        body,
        "text/html",
    )


def canonical_chunks(
    body: bytes = HTML_CONTENT,
    *,
    product_id: str = "product-a",
    source_url: str = SOURCE_URL,
    max_chars: int = 16,
) -> tuple[CanonicalDocument, list[CanonicalChunk]]:
    document = canonical_document(body, product_id=product_id, source_url=source_url)
    return document, chunk_document(document, max_chars=max_chars, overlap_chars=0)


def embeddings_for(chunks: list[CanonicalChunk], vector: list[float]) -> list[list[float]]:
    return [vector.copy() for _ in chunks]


def test_in_memory_repository_replace_get_and_delete_document() -> None:
    repository = InMemoryCanonicalDocumentRepository()
    initial_document, initial_chunks = canonical_chunks(
        b"<p>initial content with multiple separate chunks</p>",
        max_chars=10,
    )
    updated_document, updated_chunks = canonical_chunks(
        b"<p>replacement</p>",
        max_chars=20,
    )
    assert initial_document.document_id == updated_document.document_id
    assert len(initial_chunks) > len(updated_chunks)

    repository.replace_document(initial_document, initial_chunks)
    repository.replace_document(updated_document, updated_chunks)
    stored = repository.get_document(updated_document.document_id)

    assert stored is not None
    stored_document, stored_chunks = stored
    assert stored_document.content == "replacement"
    assert stored_document.content_hash == updated_document.content_hash
    assert [chunk.chunk_id for chunk in stored_chunks] == [
        chunk.chunk_id for chunk in updated_chunks
    ]
    assert [chunk.chunk_index for chunk in stored_chunks] == [0]
    assert repository.list_document_ids() == [updated_document.document_id]

    repository.delete_document(updated_document.document_id)

    assert repository.get_document(updated_document.document_id) is None
    assert repository.list_document_ids() == []


class FakeCursor(list):
    def sort(self, key: str, direction: int = 1):
        return FakeCursor(sorted(self, key=lambda record: record[key], reverse=direction < 0))


class FakeMongoCollection:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.indexes: list[tuple[str, bool]] = []
        self.replace_calls = []
        self.bulk_operations = []
        self.delete_many_calls = []
        self.delete_one_calls = []

    def create_index(self, field: str, *, unique: bool = False):
        self.indexes.append((field, unique))

    def replace_one(self, query, replacement, *, upsert: bool):
        self.replace_calls.append((query, replacement, upsert))
        key = query.get("document_id", query.get("chunk_id"))
        self.records[key] = replacement

    def bulk_write(self, operations, *, ordered: bool):
        self.bulk_operations.extend(operations)
        for operation in operations:
            replacement = operation._doc
            query = operation._filter
            key = query.get("chunk_id")
            self.records[key] = replacement

    def delete_many(self, query):
        self.delete_many_calls.append(query)
        document_id = query["document_id"]
        chunk_filter = query.get("chunk_id")
        allowed_ids = set(chunk_filter.get("$nin", [])) if isinstance(chunk_filter, dict) else None
        stale = [
            key
            for key, record in self.records.items()
            if record.get("document_id") == document_id
            and (allowed_ids is None or key not in allowed_ids)
        ]
        for key in stale:
            del self.records[key]

    def delete_one(self, query):
        self.delete_one_calls.append(query)
        self.records.pop(query["document_id"], None)

    def find_one(self, query):
        record = self.records.get(query["document_id"])
        return record.copy() if record is not None else None

    def find(self, query=None, projection=None):
        query = query or {}
        records = [
            record.copy()
            for record in self.records.values()
            if not query or record.get("document_id") == query.get("document_id")
        ]
        if projection:
            fields = {name for name, enabled in projection.items() if enabled}
            records = [
                {name: record[name] for name in fields if name in record} for record in records
            ]
        return FakeCursor(records)


class FakeMongoDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeMongoCollection] = {}

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return self.collections.setdefault(name, FakeMongoCollection())


class FakeMongoClient:
    def __init__(self) -> None:
        self.database = FakeMongoDatabase()
        self.closed = False

    def __getitem__(self, name: str) -> FakeMongoDatabase:
        del name
        return self.database

    def close(self) -> None:
        self.closed = True


def test_mongo_repository_uses_injected_client_for_replace_get_delete_offline() -> None:
    client = FakeMongoClient()
    repository = MongoCanonicalDocumentRepository("mongodb://unused", client=client)
    initial_document, initial_chunks = canonical_chunks(
        b"<p>persist this document across several chunks</p>",
        max_chars=10,
    )
    updated_document, updated_chunks = canonical_chunks(
        b"<p>updated</p>",
        max_chars=10,
    )
    repository.ensure_indexes()
    repository.replace_document(initial_document, initial_chunks)
    repository.replace_document(updated_document, updated_chunks)

    stored = repository.get_document(updated_document.document_id)
    assert stored is not None
    stored_document, stored_chunks = stored
    assert stored_document.content == "updated"
    assert [chunk.chunk_id for chunk in stored_chunks] == [
        chunk.chunk_id for chunk in updated_chunks
    ]
    assert repository.list_document_ids() == [updated_document.document_id]
    assert ("document_id", True) in repository.documents.indexes
    assert ("chunk_id", True) in repository.chunks.indexes
    assert len(repository.chunks.bulk_operations) == len(initial_chunks) + len(updated_chunks)
    assert repository.chunks.delete_many_calls[-1]["chunk_id"]["$nin"] == [
        chunk.chunk_id for chunk in updated_chunks
    ]

    repository.delete_document(updated_document.document_id)

    assert repository.get_document(updated_document.document_id) is None
    assert repository.list_document_ids() == []
    assert client.closed is False
    repository.close()
    assert client.closed is True


class DeterministicEmbedder:
    model_version = "test-embedding-v1"
    dimensions = 2

    def __init__(self, response=None) -> None:
        self.response = response
        self.calls: list[list[str]] = []

    async def embed_documents(self, texts):
        self.calls.append(list(texts))
        if self.response is not None:
            return self.response
        return [[1.0, 0.0] for _ in texts]


def make_indexing_service(
    repository: InMemoryCanonicalDocumentRepository | None = None,
    search: InMemorySearchProvider | None = None,
    embedder: DeterministicEmbedder | None = None,
) -> tuple[
    DocumentIndexingService,
    InMemoryCanonicalDocumentRepository,
    InMemorySearchProvider,
    DeterministicEmbedder,
]:
    repo = repository or InMemoryCanonicalDocumentRepository()
    provider = search or InMemorySearchProvider(embedding_dimensions=2)
    embedding = embedder or DeterministicEmbedder()
    service = DocumentIndexingService(
        repository=repo,
        search=provider,
        embedder=embedding,
        chunk_size_chars=16,
        chunk_overlap_chars=0,
    )
    return service, repo, provider, embedding


def test_indexing_service_persists_canonical_document_and_indexes_chunks() -> None:
    service, repository, search, embedder = make_indexing_service()

    indexed_document = asyncio.run(service.index_html(source(), HTML_CONTENT, "text/html"))
    stored = repository.get_document(indexed_document.document_id)

    assert stored is not None
    stored_document, stored_chunks = stored
    assert stored_document == indexed_document
    assert stored_chunks
    assert all(chunk.document_id == indexed_document.document_id for chunk in stored_chunks)
    assert embedder.calls == [[chunk.content for chunk in stored_chunks]]
    results = asyncio.run(
        search.search(
            "support material",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=10,
        )
    )
    assert {result.chunk_id for result in results} == {chunk.chunk_id for chunk in stored_chunks}
    assert all(str(result.source_url) == SOURCE_URL for result in results)


def test_indexing_service_reindexes_changed_content_and_reprocesses_persisted_chunks() -> None:
    service, repository, search, embedder = make_indexing_service()
    original = asyncio.run(
        service.index_html(
            source(),
            b"<p>older content that makes several chunks for deletion checks</p>",
            "text/html",
        )
    )
    old_chunks = repository.get_document(original.document_id)[1]
    changed = asyncio.run(service.index_html(source(), b"<p>fresh content</p>", "text/html"))
    current_chunks = repository.get_document(changed.document_id)[1]
    assert len(old_chunks) > len(current_chunks)

    reprocessed = asyncio.run(service.reprocess_document(changed.document_id))

    assert reprocessed == changed
    stored = repository.get_document(changed.document_id)
    assert stored is not None
    assert [chunk.chunk_id for chunk in stored[1]] == [chunk.chunk_id for chunk in current_chunks]
    results = asyncio.run(
        search.search(
            "fresh content",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=20,
        )
    )
    assert {result.chunk_id for result in results} == {chunk.chunk_id for chunk in current_chunks}
    assert embedder.calls == [
        [chunk.content for chunk in old_chunks],
        [chunk.content for chunk in current_chunks],
        [chunk.content for chunk in current_chunks],
    ]


def test_indexing_service_delete_removes_search_and_repository_records() -> None:
    service, repository, search, _ = make_indexing_service()
    indexed = asyncio.run(service.index_html(source(), HTML_CONTENT, "text/html"))

    asyncio.run(service.delete_document(indexed.document_id))

    assert repository.get_document(indexed.document_id) is None
    assert (
        asyncio.run(
            search.search(
                "support material",
                [1.0, 0.0],
                product_ids=["product-a"],
                top=10,
            )
        )
        == []
    )


def test_reprocessing_missing_document_removes_stale_search_record() -> None:
    service, _, search, _ = make_indexing_service()
    stale_document, stale_chunks = canonical_chunks(b"<p>stale indexed content</p>")
    asyncio.run(
        search.replace_document(
            stale_document.document_id,
            stale_chunks,
            embeddings_for(stale_chunks, [1.0, 0.0]),
        )
    )

    result = asyncio.run(service.reprocess_document(stale_document.document_id))

    assert result is None
    assert (
        asyncio.run(
            search.search(
                "stale indexed content",
                [1.0, 0.0],
                product_ids=["product-a"],
            )
        )
        == []
    )


@pytest.mark.parametrize(
    "embedding_response",
    [
        [],
        [[1.0]],
        [[float("nan"), 0.0]],
    ],
    ids=["missing-vector", "wrong-dimensions", "non-finite-vector"],
)
def test_indexing_service_rejects_invalid_embedding_results(
    embedding_response: list[list[float]],
) -> None:
    service, _, _, _ = make_indexing_service(embedder=DeterministicEmbedder(embedding_response))

    with pytest.raises(DocumentIndexingError):
        asyncio.run(service.index_html(source(), b"<p>one chunk</p>", "text/html"))


def test_indexing_service_skips_embedding_when_content_is_unchanged() -> None:
    service, repository, _, embedder = make_indexing_service()
    first = asyncio.run(service.index_html(source(), HTML_CONTENT, "text/html"))
    second = asyncio.run(service.index_html(source(), HTML_CONTENT, "text/html"))

    assert first.content_hash == second.content_hash
    assert len(embedder.calls) == 1
    assert repository.get_document(first.document_id) is not None


def test_failed_search_write_does_not_commit_repository_record() -> None:
    service, repository, _, _ = make_indexing_service(embedder=DeterministicEmbedder([[1.0]]))
    with pytest.raises(DocumentIndexingError):
        asyncio.run(service.index_html(source(), b"<p>one chunk</p>", "text/html"))
    assert repository.list_document_ids() == []

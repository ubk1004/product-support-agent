import asyncio
import hashlib
import inspect
from types import SimpleNamespace

import pytest
from azure.search.documents.indexes.models import SearchFieldDataType

from product_support_agent.catalog import ProductReference
from product_support_agent.documents import (
    CanonicalDocument,
    DocumentNormalizationError,
    chunk_document,
    normalize_html,
)
from product_support_agent.search import (
    VECTOR_FIELD_NAME,
    AzureAISearchProvider,
    InMemorySearchProvider,
    SearchResult,
    build_search_index,
    build_versioned_index_name,
)

SOURCE_URL = "https://my.opentext.com/support/products/product-a"
VECTOR_DIMENSIONS = 2


def source(product_id: str = "product-a", source_url: str = SOURCE_URL) -> ProductReference:
    return ProductReference(
        product_id=product_id,
        name=f"Product {product_id}",
        slug=product_id,
        source_url=source_url,
    )


def document(
    body: bytes = b"<p>Canonical product support content.</p>",
    *,
    product_id: str = "product-a",
    source_url: str = SOURCE_URL,
    max_bytes: int = 4096,
) -> CanonicalDocument:
    return normalize_html(
        source(product_id, source_url),
        body,
        "text/html; charset=utf-8",
        max_bytes=max_bytes,
    )


def chunks_for(
    body: bytes,
    *,
    product_id: str = "product-a",
    source_url: str = SOURCE_URL,
    max_chars: int = 128,
    overlap_chars: int = 0,
):
    normalized = document(body, product_id=product_id, source_url=source_url)
    return chunk_document(
        normalized,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )


def embeddings_for(chunks, vector: list[float]) -> list[list[float]]:
    return [vector.copy() for _ in chunks]


def index_with_fake(
    provider: InMemorySearchProvider,
    chunks,
    vector: list[float],
) -> None:
    asyncio.run(
        provider.replace_document(
            chunks[0].document_id,
            chunks,
            embeddings_for(chunks, vector),
        )
    )


def test_document_identity_uses_product_and_canonical_url() -> None:
    first = document()
    same_source = document(body=b"<p>Different content.</p>")
    other_product = document(product_id="product-b")
    other_url = document(source_url=f"{SOURCE_URL}/manual")

    assert first.document_id == same_source.document_id
    assert first.document_id != other_product.document_id
    assert first.document_id != other_url.document_id


def test_content_hash_tracks_normalized_content_not_html_whitespace() -> None:
    first = document(b"<p>Support   reference</p>")
    same_text = document(b"<div> Support\n reference </div>")
    changed_text = document(b"<p>Support replacement</p>")

    expected_hash = hashlib.sha256(first.content.encode("utf-8")).hexdigest()
    assert first.content == same_text.content == "Support reference"
    assert first.content_hash == expected_hash
    assert same_text.content_hash == first.content_hash
    assert changed_text.content_hash != first.content_hash


def test_canonical_document_records_versions_and_source_provenance() -> None:
    normalized = document()

    assert normalized.product_id == "product-a"
    assert normalized.source_id == normalized.product_id
    assert str(normalized.source_url) == SOURCE_URL
    assert normalized.document_id
    assert normalized.parser_version
    assert normalized.schema_version


def test_normalize_html_removes_noncontent_and_collapses_whitespace() -> None:
    html = (
        b"<html><head><style>.secret { display:none }</style>"
        b"<script>doNotIndex()</script></head>"
        b"<body> Product <strong>support</strong>\n reference </body></html>"
    )

    normalized = document(html)

    assert normalized.content == "Product support reference"
    assert "doNotIndex" not in normalized.content
    assert "display:none" not in normalized.content


def test_normalize_html_accepts_exact_byte_limit() -> None:
    body = b"<p>Exact boundary</p>"

    normalized = document(body, max_bytes=len(body))

    assert normalized.content == "Exact boundary"


def test_normalize_html_rejects_one_byte_over_limit() -> None:
    body = b"<p>Exact boundary</p> "

    with pytest.raises(DocumentNormalizationError):
        document(body, max_bytes=len(body) - 1)


def test_normalize_html_rejects_unsupported_content_type() -> None:
    with pytest.raises(DocumentNormalizationError):
        normalize_html(source(), b'{"content":"not HTML"}', "application/json")


def test_normalize_html_rejects_empty_html() -> None:
    body = b"<html><head><script>hidden</script></head><body></body></html>"

    with pytest.raises(DocumentNormalizationError):
        document(body)


def test_normalize_html_rejects_unsafe_source_url() -> None:
    unsafe_source = source(source_url="https://docs.example.invalid/product-a")

    with pytest.raises(DocumentNormalizationError):
        normalize_html(unsafe_source, b"<p>Do not ingest</p>", "text/html")


def test_empty_document_produces_no_chunks() -> None:
    normalized = document()
    empty = normalized.model_copy(update={"content": ""})

    assert chunk_document(empty, max_chars=32, overlap_chars=0) == []


def test_singleton_document_produces_one_provenance_preserving_chunk() -> None:
    normalized = document(b"<p>One short chunk.</p>")

    result = chunk_document(normalized, max_chars=32, overlap_chars=0)

    assert len(result) == 1
    chunk = result[0]
    assert chunk.content == normalized.content == "One short chunk."
    assert chunk.document_id == normalized.document_id
    assert chunk.source_id == normalized.source_id
    assert chunk.product_id == normalized.product_id
    assert str(chunk.source_url) == str(normalized.source_url)
    assert chunk.parser_version == normalized.parser_version
    assert chunk.schema_version == normalized.schema_version
    assert chunk.chunk_index == 0


def test_exact_max_chars_produces_one_chunk() -> None:
    normalized = document(b"<p>abcdefgh</p>")

    result = chunk_document(normalized, max_chars=8, overlap_chars=0)

    assert [chunk.content for chunk in result] == ["abcdefgh"]


def test_oversize_document_splits_into_bounded_ordered_chunks() -> None:
    normalized = document(b"<p>abcdefghijkl</p>")

    result = chunk_document(normalized, max_chars=5, overlap_chars=0)

    assert [chunk.content for chunk in result] == ["abcde", "fghij", "kl"]
    assert all(len(chunk.content) <= 5 for chunk in result)
    assert [chunk.chunk_index for chunk in result] == [0, 1, 2]
    assert "".join(chunk.content for chunk in result) == normalized.content


def test_multichunking_is_deterministic_and_preserves_provenance() -> None:
    normalized = document(b"<p>abcdefghijkl</p>")

    first = chunk_document(normalized, max_chars=5, overlap_chars=1)
    second = chunk_document(normalized, max_chars=5, overlap_chars=1)

    assert [chunk.model_dump() for chunk in first] == [chunk.model_dump() for chunk in second]
    assert all(len(chunk.content) <= 5 for chunk in first)
    assert all(
        right.content.startswith(left.content[-1:])
        for left, right in zip(first[:-1], first[1:], strict=True)
    )
    rebuilt_content = first[0].content + "".join(chunk.content[1:] for chunk in first[1:])
    assert rebuilt_content == normalized.content
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(chunk.document_id == normalized.document_id for chunk in first)
    assert all(chunk.source_id == normalized.source_id for chunk in first)
    assert all(chunk.product_id == normalized.product_id for chunk in first)
    assert all(str(chunk.source_url) == SOURCE_URL for chunk in first)
    assert all(chunk.parser_version == normalized.parser_version for chunk in first)
    assert all(chunk.schema_version == normalized.schema_version for chunk in first)


def test_chunk_boundary_at_whitespace_does_not_repeat_or_lose_words() -> None:
    normalized = document(b"<p>abcde fghij</p>")

    result = chunk_document(normalized, max_chars=5, overlap_chars=2)

    assert [chunk.content for chunk in result] == ["abcde", "fghij"]


def test_overlap_after_word_boundary_does_not_repeat_prior_chunk() -> None:
    normalized = document(b"<p>ab cdefghij</p>")

    result = chunk_document(normalized, max_chars=5, overlap_chars=1)

    assert [chunk.content for chunk in result] == ["ab", "cdefg", "ghij"]
    assert all(len(chunk.content) <= 5 for chunk in result)


def test_overlap_inside_long_word_retains_requested_overlap_and_progresses() -> None:
    normalized = document(b"<p>abcdefghij</p>")

    result = chunk_document(normalized, max_chars=5, overlap_chars=2)

    assert [chunk.content for chunk in result] == ["abcde", "defgh", "ghij"]
    assert (
        "".join(
            chunk.content if index == 0 else chunk.content[2:] for index, chunk in enumerate(result)
        )
        == normalized.content
    )


def _search_result_values(chunk) -> dict[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "source_id": chunk.source_id,
        "product_id": chunk.product_id,
        "source_url": chunk.source_url,
        "title": chunk.title,
        "excerpt": chunk.excerpt,
        "content_hash": chunk.content_hash,
        "chunk_index": chunk.chunk_index,
        "score": 1.0,
    }


def test_search_result_rejects_source_id_that_does_not_match_product_id() -> None:
    chunk = chunks_for(b"<p>citation provenance</p>")[0]
    values = _search_result_values(chunk)
    values["source_id"] = "different-product"

    with pytest.raises(ValueError, match="source ID must preserve its product ID"):
        SearchResult(**values)


def test_search_result_rejects_document_id_that_does_not_match_canonical_source() -> None:
    chunk = chunks_for(b"<p>citation provenance</p>")[0]
    values = _search_result_values(chunk)
    values["document_id"] = "not-the-stable-document-id"

    with pytest.raises(ValueError, match="document ID does not match its canonical source"):
        SearchResult(**values)


def test_search_result_rejects_chunk_id_that_does_not_match_its_index() -> None:
    chunk = chunks_for(b"<p>citation provenance</p>")[0]
    values = _search_result_values(chunk)
    values["chunk_index"] = chunk.chunk_index + 1

    with pytest.raises(ValueError, match="chunk ID does not match its document and index"):
        SearchResult(**values)


def test_search_result_preserves_valid_document_and_source_provenance() -> None:
    chunk = chunks_for(b"<p>citation provenance</p>")[0]

    result = SearchResult(**_search_result_values(chunk))

    assert result.document_id == chunk.document_id
    assert result.source_id == result.product_id == chunk.product_id
    assert str(result.source_url) == SOURCE_URL
    assert result.chunk_id == chunk.chunk_id


@pytest.mark.parametrize(
    ("max_chars", "overlap_chars"),
    [(0, 0), (-1, 0), (4, -1), (4, 4)],
    ids=["zero-size", "negative-size", "negative-overlap", "overlap-equals-size"],
)
def test_chunk_document_rejects_invalid_size_and_overlap(
    max_chars: int, overlap_chars: int
) -> None:
    with pytest.raises(ValueError):
        chunk_document(
            document(),
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )


def test_index_schema_is_versioned_and_contains_filterable_provenance_and_vector_fields() -> None:
    index_name = build_versioned_index_name(
        "Product Support",
        embedding_model_version="embedding-v1",
        embedding_dimensions=3,
        parser_version="html-v1",
    )
    index = build_search_index(index_name, embedding_dimensions=3)
    fields = {field.name: field for field in index.fields}

    assert index.name == index_name
    assert "s1" in index_name
    assert fields["id"].key is True
    assert fields["product_id"].filterable is True
    assert fields["document_id"].filterable is True
    assert fields["source_id"].filterable is True
    assert fields["source_url"].type == SearchFieldDataType.STRING
    assert fields["content"].searchable is True
    assert fields["excerpt"].type == SearchFieldDataType.STRING
    assert fields["content_hash"].filterable is True
    assert fields["parser_version"].filterable is True
    assert fields["schema_version"].filterable is True
    assert fields[VECTOR_FIELD_NAME].vector_search_dimensions == 3


def test_index_schema_rejects_invalid_vector_dimensions() -> None:
    with pytest.raises(ValueError):
        build_search_index("product-support-test", embedding_dimensions=0)


def test_versioned_index_name_changes_when_embedding_version_changes() -> None:
    first = build_versioned_index_name(
        "product-support",
        embedding_model_version="embedding-v1",
        embedding_dimensions=3,
        parser_version="html-v1",
    )
    changed_embedding = build_versioned_index_name(
        "product-support",
        embedding_model_version="embedding-v2",
        embedding_dimensions=3,
        parser_version="html-v1",
    )
    changed_parser = build_versioned_index_name(
        "product-support",
        embedding_model_version="embedding-v1",
        embedding_dimensions=3,
        parser_version="html-v2",
    )
    changed_schema = build_versioned_index_name(
        "product-support",
        embedding_model_version="embedding-v1",
        embedding_dimensions=3,
        parser_version="html-v1",
        schema_version="2",
    )

    assert first == build_versioned_index_name(
        "product-support",
        embedding_model_version="embedding-v1",
        embedding_dimensions=3,
        parser_version="html-v1",
    )
    assert first != changed_embedding
    assert first != changed_parser
    assert first != changed_schema


def test_in_memory_provider_replace_is_idempotent() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    current_chunks = chunks_for(b"<p>idempotent indexing reference</p>")
    vectors = embeddings_for(current_chunks, [1.0, 0.0])

    async def replace_twice() -> None:
        await provider.replace_document(current_chunks[0].document_id, current_chunks, vectors)
        await provider.replace_document(current_chunks[0].document_id, current_chunks, vectors)

    asyncio.run(replace_twice())
    results = asyncio.run(
        provider.search(
            "idempotent indexing",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=10,
        )
    )

    assert [result.chunk_id for result in results] == [current_chunks[0].chunk_id]


def test_in_memory_provider_methods_are_async() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)

    assert inspect.iscoroutinefunction(provider.replace_document)
    assert inspect.iscoroutinefunction(provider.delete_document)
    assert inspect.iscoroutinefunction(provider.search)


def test_replace_updates_changed_content_without_changing_document_identity() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    old_chunks = chunks_for(b"<p>old searchable material</p>")
    new_chunks = chunks_for(b"<p>new searchable material</p>")
    assert old_chunks[0].document_id == new_chunks[0].document_id
    assert old_chunks[0].chunk_id == new_chunks[0].chunk_id
    assert old_chunks[0].content_hash != new_chunks[0].content_hash

    async def reprocess() -> None:
        await provider.replace_document(
            old_chunks[0].document_id,
            old_chunks,
            embeddings_for(old_chunks, [1.0, 0.0]),
        )
        await provider.replace_document(
            new_chunks[0].document_id,
            new_chunks,
            embeddings_for(new_chunks, [1.0, 0.0]),
        )

    asyncio.run(reprocess())
    results = asyncio.run(
        provider.search(
            "new searchable material",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=10,
        )
    )

    assert len(results) == 1
    assert results[0].chunk_id == new_chunks[0].chunk_id
    assert results[0].document_id == new_chunks[0].document_id
    assert results[0].source_id == new_chunks[0].source_id
    assert results[0].content_hash == new_chunks[0].content_hash
    assert str(results[0].source_url) == SOURCE_URL
    assert results[0].excerpt == new_chunks[0].excerpt


def test_replace_removes_stale_chunks_and_preserves_current_ids_and_urls() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    old_chunks = chunks_for(
        b"<p>stale-token stale-token stale-token stale-token</p>",
        max_chars=12,
    )
    new_chunks = chunks_for(b"<p>fresh reference</p>", max_chars=12)
    assert len(old_chunks) > len(new_chunks)

    async def replace_document() -> None:
        await provider.replace_document(
            old_chunks[0].document_id,
            old_chunks,
            embeddings_for(old_chunks, [1.0, 0.0]),
        )
        await provider.replace_document(
            new_chunks[0].document_id,
            new_chunks,
            embeddings_for(new_chunks, [1.0, 0.0]),
        )

    asyncio.run(replace_document())
    results = asyncio.run(
        provider.search(
            "fresh",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=20,
        )
    )

    assert {result.chunk_id for result in results} == {chunk.chunk_id for chunk in new_chunks}
    assert all(result.document_id == new_chunks[0].document_id for result in results)
    assert all(result.source_id == new_chunks[0].source_id for result in results)
    assert all(str(result.source_url) == SOURCE_URL for result in results)


def test_delete_document_removes_all_chunks_for_that_document() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    indexed = chunks_for(
        b"<p>delete this source material from multiple chunks</p>",
        max_chars=8,
    )
    assert len(indexed) > 1
    index_with_fake(provider, indexed, [1.0, 0.0])

    asyncio.run(provider.delete_document(indexed[0].document_id))
    results = asyncio.run(
        provider.search(
            "delete source",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=10,
        )
    )

    assert results == []


def test_hybrid_search_returns_keyword_and_vector_matches() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    keyword_chunks = chunks_for(
        b"<p>retention policy guidance</p>",
        source_url=f"{SOURCE_URL}/keyword",
    )
    vector_chunks = chunks_for(
        b"<p>unrelated administration guide</p>",
        source_url=f"{SOURCE_URL}/vector",
    )

    async def index_both() -> None:
        await provider.replace_document(
            keyword_chunks[0].document_id,
            keyword_chunks,
            embeddings_for(keyword_chunks, [1.0, 0.0]),
        )
        await provider.replace_document(
            vector_chunks[0].document_id,
            vector_chunks,
            embeddings_for(vector_chunks, [0.0, 1.0]),
        )

    asyncio.run(index_both())
    keyword_result = asyncio.run(
        provider.search(
            "retention policy",
            [0.0, 1.0],
            product_ids=["product-a"],
            top=1,
        )
    )
    vector_result = asyncio.run(
        provider.search(
            "unmatched query terms",
            [0.0, 1.0],
            product_ids=["product-a"],
            top=1,
        )
    )

    assert [result.chunk_id for result in keyword_result] == [keyword_chunks[0].chunk_id]
    assert [result.chunk_id for result in vector_result] == [vector_chunks[0].chunk_id]


def test_product_metadata_filters_partition_search_results() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    first = chunks_for(b"<p>shared keyword first product</p>", product_id="product-a")
    second = chunks_for(
        b"<p>shared keyword second product</p>",
        product_id="product-b",
        source_url="https://my.opentext.com/support/products/product-b",
    )

    async def index_both() -> None:
        await provider.replace_document(
            first[0].document_id,
            first,
            embeddings_for(first, [1.0, 0.0]),
        )
        await provider.replace_document(
            second[0].document_id,
            second,
            embeddings_for(second, [1.0, 0.0]),
        )

    asyncio.run(index_both())
    results = asyncio.run(
        provider.search(
            "shared keyword",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=10,
        )
    )

    assert [result.product_id for result in results] == ["product-a"]
    assert [result.chunk_id for result in results] == [first[0].chunk_id]


def test_search_results_preserve_ids_canonical_url_and_excerpt() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    indexed = chunks_for(b"<p>citation provenance excerpt</p>")
    index_with_fake(provider, indexed, [1.0, 0.0])

    results = asyncio.run(
        provider.search(
            "citation provenance",
            [1.0, 0.0],
            product_ids=["product-a"],
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.chunk_id == indexed[0].chunk_id
    assert result.document_id == indexed[0].document_id
    assert result.source_id == indexed[0].source_id
    assert result.product_id == indexed[0].product_id
    assert str(result.source_url) == SOURCE_URL
    assert result.chunk_index == indexed[0].chunk_index
    assert result.excerpt == indexed[0].excerpt


def test_search_respects_top_k() -> None:
    provider = InMemorySearchProvider(embedding_dimensions=VECTOR_DIMENSIONS)
    first = chunks_for(b"<p>common query alpha</p>", product_id="product-a")
    second = chunks_for(
        b"<p>common query beta</p>",
        product_id="product-b",
        source_url="https://my.opentext.com/support/products/product-b",
    )

    async def index_both() -> None:
        await provider.replace_document(
            first[0].document_id, first, embeddings_for(first, [1.0, 0.0])
        )
        await provider.replace_document(
            second[0].document_id, second, embeddings_for(second, [1.0, 0.0])
        )

    asyncio.run(index_both())
    results = asyncio.run(provider.search("common query", [1.0, 0.0], top=1))

    assert len(results) == 1


class AsyncRows:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        async def generate():
            for row in self.rows:
                yield row

        return generate()


class AsyncPagedRows:
    def __init__(self, pages):
        self.pages = pages
        self.pages_consumed = 0

    def by_page(self):
        async def generate_pages():
            for rows in self.pages:
                self.pages_consumed += 1
                yield AsyncRows(rows)

        return generate_pages()

    def __aiter__(self):
        async def generate_rows():
            async for page in self.by_page():
                async for row in page:
                    yield row

        return generate_rows()


class AzureSearchSdkDouble:
    def __init__(self) -> None:
        self.documents = {}
        self.uploaded_documents = []
        self.deleted_ids = []
        self.search_arguments = []
        self.query_results = []

    async def merge_or_upload_documents(self, *, documents):
        self.uploaded_documents.extend(documents)
        self.documents.update({document["id"]: document for document in documents})
        return [SimpleNamespace(succeeded=True, status_code=200) for _ in documents]

    async def delete_documents(self, *, documents):
        self.deleted_ids.extend(document["id"] for document in documents)
        for document in documents:
            self.documents.pop(document["id"], None)
        return [SimpleNamespace(succeeded=True, status_code=200) for _ in documents]

    async def search(self, *, search_text, filter=None, select=None, top=None, vector_queries=None):
        self.search_arguments.append(
            {
                "search_text": search_text,
                "filter": filter,
                "select": select,
                "top": top,
                "vector_queries": vector_queries,
            }
        )
        if select == ["id"]:
            document_id = filter.split("eq ", maxsplit=1)[1].strip("'")
            return AsyncRows(
                [
                    {"id": indexed["id"]}
                    for indexed in self.documents.values()
                    if indexed["document_id"] == document_id
                ]
            )
        if search_text == "*":
            return AsyncRows([])
        return AsyncRows(self.query_results)


class PagedAzureSearchSdkDouble(AzureSearchSdkDouble):
    def __init__(self, chunk_id_pages) -> None:
        super().__init__()
        self.chunk_id_pages = chunk_id_pages
        self.paged_results = None
        self.delete_batches = []

    async def search(self, *, search_text, filter=None, select=None, top=None, vector_queries=None):
        self.search_arguments.append(
            {
                "search_text": search_text,
                "filter": filter,
                "select": select,
                "top": top,
                "vector_queries": vector_queries,
            }
        )
        if select == ["id"]:
            self.paged_results = AsyncPagedRows(
                [[{"id": chunk_id} for chunk_id in page] for page in self.chunk_id_pages]
            )
            return self.paged_results
        return AsyncRows([])

    async def delete_documents(self, *, documents):
        self.delete_batches.append([document["id"] for document in documents])
        return await super().delete_documents(documents=documents)


def test_azure_provider_delegates_to_injected_sdk_double_without_live_service() -> None:
    sdk = AzureSearchSdkDouble()
    provider = AzureAISearchProvider(
        sdk,
        embedding_dimensions=VECTOR_DIMENSIONS,
        embedding_model_version="embedding-v1",
    )
    old_chunks = chunks_for(
        b"<p>sdk stale content sdk stale content sdk stale content</p>",
        max_chars=12,
    )
    new_chunks = chunks_for(b"<p>sdk current content</p>", max_chars=12)
    assert len(old_chunks) > len(new_chunks)
    sdk.query_results = [
        {
            "id": new_chunks[0].chunk_id,
            "document_id": new_chunks[0].document_id,
            "source_id": new_chunks[0].source_id,
            "product_id": new_chunks[0].product_id,
            "source_url": SOURCE_URL,
            "title": new_chunks[0].title,
            "excerpt": new_chunks[0].excerpt,
            "content_hash": new_chunks[0].content_hash,
            "chunk_index": new_chunks[0].chunk_index,
            "@search.score": 1.0,
        }
    ]

    async def exercise_adapter() -> list[SearchResult]:
        await provider.replace_document(
            old_chunks[0].document_id,
            old_chunks,
            embeddings_for(old_chunks, [1.0, 0.0]),
        )
        await provider.replace_document(
            new_chunks[0].document_id,
            new_chunks,
            embeddings_for(new_chunks, [1.0, 0.0]),
        )
        await provider.delete_document(new_chunks[0].document_id)
        return await provider.search(
            "sdk query",
            [1.0, 0.0],
            product_ids=["product-a"],
            top=3,
        )

    results = asyncio.run(exercise_adapter())

    stale_ids = {chunk.chunk_id for chunk in old_chunks} - {chunk.chunk_id for chunk in new_chunks}
    assert stale_ids <= set(sdk.deleted_ids)
    assert {chunk.chunk_id for chunk in new_chunks} <= set(sdk.deleted_ids)
    assert sdk.uploaded_documents
    assert sdk.uploaded_documents[0]["id"] == old_chunks[0].chunk_id
    assert sdk.uploaded_documents[0]["document_id"] == old_chunks[0].document_id
    assert sdk.uploaded_documents[0]["source_id"] == old_chunks[0].source_id
    assert sdk.uploaded_documents[0]["product_id"] == old_chunks[0].product_id
    assert sdk.uploaded_documents[0]["source_url"] == SOURCE_URL
    assert sdk.uploaded_documents[0][VECTOR_FIELD_NAME] == [1.0, 0.0]
    assert sdk.documents == {}
    assert len(sdk.search_arguments) == 4
    assert sdk.search_arguments[-1]["search_text"] == "sdk query"
    assert sdk.search_arguments[-1]["top"] == 3
    assert sdk.search_arguments[-1]["filter"] == "product_id eq 'product-a'"
    assert sdk.search_arguments[-1]["vector_queries"]
    assert len(results) == 1
    assert results[0].chunk_id == new_chunks[0].chunk_id
    assert results[0].document_id == new_chunks[0].document_id
    assert results[0].source_id == results[0].product_id == "product-a"
    assert str(results[0].source_url) == SOURCE_URL
    assert results[0].excerpt == new_chunks[0].excerpt
    assert results[0].chunk_index == new_chunks[0].chunk_index


def test_azure_replace_discovers_stale_ids_across_all_result_pages() -> None:
    stale_ids = [f"stale-{index:04d}" for index in range(1001)]
    pages = [stale_ids[:400], stale_ids[400:800], stale_ids[800:]]
    sdk = PagedAzureSearchSdkDouble(pages)
    provider = AzureAISearchProvider(
        sdk,
        embedding_dimensions=VECTOR_DIMENSIONS,
        embedding_model_version="embedding-v1",
    )
    current_chunks = chunks_for(b"<p>current content</p>")

    asyncio.run(
        provider.replace_document(
            current_chunks[0].document_id,
            current_chunks,
            embeddings_for(current_chunks, [1.0, 0.0]),
        )
    )

    expected_ids = sorted(stale_ids)
    assert sdk.paged_results.pages_consumed == 3
    assert sdk.search_arguments[0]["filter"] == (
        f"document_id eq '{current_chunks[0].document_id}'"
    )
    assert sdk.delete_batches == [
        expected_ids[:500],
        expected_ids[500:1000],
        expected_ids[1000:],
    ]
    assert sdk.deleted_ids == expected_ids
    assert sdk.uploaded_documents[0]["id"] == current_chunks[0].chunk_id


def test_azure_delete_document_discovers_and_batches_more_than_500_ids() -> None:
    chunk_ids = [f"chunk-{index:04d}" for index in range(1001)]
    pages = [chunk_ids[:400], chunk_ids[400:800], chunk_ids[800:]]
    sdk = PagedAzureSearchSdkDouble(pages)
    provider = AzureAISearchProvider(
        sdk,
        embedding_dimensions=VECTOR_DIMENSIONS,
        embedding_model_version="embedding-v1",
    )

    asyncio.run(provider.delete_document("document-with-many-chunks"))

    expected_ids = sorted(chunk_ids)
    assert sdk.paged_results.pages_consumed == 3
    assert sdk.search_arguments[0]["filter"] == "document_id eq 'document-with-many-chunks'"
    assert [len(batch) for batch in sdk.delete_batches] == [500, 500, 1]
    assert sdk.delete_batches == [
        expected_ids[:500],
        expected_ids[500:1000],
        expected_ids[1000:],
    ]
    assert sdk.deleted_ids == expected_ids

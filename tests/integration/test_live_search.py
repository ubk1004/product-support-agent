import asyncio
import time
from uuid import uuid4

import pytest
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient

from product_support_agent.catalog import ProductReference
from product_support_agent.config import ModelAndSearchSettings
from product_support_agent.documents import chunk_document, normalize_html
from product_support_agent.embeddings import OpenAICompatibleEmbedder
from product_support_agent.search import (
    AzureAISearchProvider,
    apply_search_index,
    build_search_index,
    build_versioned_index_name,
)


@pytest.mark.live
def test_live_search_upsert_filter_replacement_and_delete() -> None:
    asyncio.run(_exercise_live_search())


async def _exercise_live_search() -> None:
    settings = ModelAndSearchSettings()  # type: ignore[call-arg]
    index_name = build_versioned_index_name(
        f"product-support-test-{uuid4().hex[:12]}",
        embedding_model_version=settings.embedding_model_version,
        embedding_dimensions=settings.embedding_dimensions,
        parser_version="phase-four-live",
    )
    credential = AzureKeyCredential(settings.search_key.get_secret_value())
    index_client = SearchIndexClient(settings.search_endpoint, credential)
    search_client: SearchClient | None = None
    index_created = False

    try:
        await apply_search_index(
            index_client,
            build_search_index(index_name, embedding_dimensions=settings.embedding_dimensions),
        )
        index_created = True
        search_client = SearchClient(settings.search_endpoint, index_name, credential)
        provider = AzureAISearchProvider(
            search_client,
            embedding_dimensions=settings.embedding_dimensions,
            embedding_model_version=settings.embedding_model_version,
        )
        embedder = OpenAICompatibleEmbedder(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key.get_secret_value(),
            deployment=settings.embedding_deployment,
            model_version=settings.embedding_model_version,
            dimensions=settings.embedding_dimensions,
        )
        first_source = ProductReference(
            product_id="live-a",
            name="Synthetic product A",
            slug="live-a",
            source_url="https://docs.microfocus.com/doc/phase-four/live-a",
        )
        second_source = ProductReference(
            product_id="live-b",
            name="Synthetic product B",
            slug="live-b",
            source_url="https://docs.microfocus.com/doc/phase-four/live-b",
        )
        first_document = normalize_html(
            first_source,
            b"<p>Phase four synthetic alpha retrieval evidence. "
            b"Additional content makes this document long enough to replace.</p>",
            "text/html",
        )
        second_document = normalize_html(
            second_source,
            b"<p>Phase four synthetic beta retrieval evidence.</p>",
            "text/html",
        )
        original_chunks = chunk_document(first_document, max_chars=64, overlap_chars=0)
        second_chunks = chunk_document(second_document, max_chars=64, overlap_chars=0)
        original_ids = {chunk.chunk_id for chunk in original_chunks}

        for document, chunks in (
            (first_document, original_chunks),
            (second_document, second_chunks),
        ):
            vectors = await embedder.embed_documents([chunk.content for chunk in chunks])
            await provider.replace_document(document.document_id, chunks, vectors)

        results = await provider.search(
            "phase four synthetic alpha retrieval evidence",
            await embedder.embed_query("phase four synthetic alpha retrieval evidence"),
            product_ids=["live-a"],
        )
        assert results
        assert all(result.product_id == "live-a" for result in results)
        assert all(str(result.source_url) == str(first_source.source_url) for result in results)
        assert {result.chunk_id for result in results} <= original_ids

        replacement = normalize_html(
            first_source,
            b"<p>Replacement evidence for phase four search.</p>",
            "text/html",
        )
        replacement_chunks = chunk_document(replacement, max_chars=64, overlap_chars=0)
        vectors = await embedder.embed_documents([chunk.content for chunk in replacement_chunks])
        await provider.replace_document(replacement.document_id, replacement_chunks, vectors)

        stored = await _wait_for_document_chunk_ids(
            search_client,
            replacement.document_id,
            {chunk.chunk_id for chunk in replacement_chunks},
        )
        assert stored == {chunk.chunk_id for chunk in replacement_chunks}
        assert stored.isdisjoint(original_ids - {chunk.chunk_id for chunk in replacement_chunks})

        await provider.delete_document(replacement.document_id)
        assert (
            await _wait_for_document_chunk_ids(search_client, replacement.document_id, set())
            == set()
        )
        assert await _document_chunk_ids(search_client, second_document.document_id) == {
            chunk.chunk_id for chunk in second_chunks
        }
    finally:
        if search_client is not None:
            await search_client.close()
        if index_created:
            await index_client.delete_index(index_name)
        await index_client.close()


async def _document_chunk_ids(client: SearchClient, document_id: str) -> set[str]:
    results = await client.search(
        search_text="*",
        filter=f"document_id eq '{document_id}'",
        select=["id"],
    )
    return {str(result["id"]) async for result in results}


async def _wait_for_document_chunk_ids(
    client: SearchClient,
    document_id: str,
    expected: set[str],
) -> set[str]:
    deadline = time.monotonic() + 30
    while True:
        actual = await _document_chunk_ids(client, document_id)
        if actual == expected:
            return actual
        if time.monotonic() >= deadline:
            return actual
        await asyncio.sleep(0.5)

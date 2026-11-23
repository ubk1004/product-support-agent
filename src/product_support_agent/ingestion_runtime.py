"""Shared construction of the ingestion worker for the scheduled script and the queue worker."""

from __future__ import annotations

from datetime import timedelta

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient

from product_support_agent.config import ModelAndSearchSettings, Settings
from product_support_agent.document_store import CanonicalDocumentRepository
from product_support_agent.documents import HTML_PARSER_VERSION
from product_support_agent.embeddings import OpenAICompatibleEmbedder
from product_support_agent.fetch_state import FreshnessPolicy, MongoFetchStateStore
from product_support_agent.http_fetch import BoundedFetcher
from product_support_agent.indexing import DocumentIndexingService
from product_support_agent.search import (
    AzureAISearchProvider,
    apply_search_index,
    build_search_index,
    build_versioned_index_name,
)
from product_support_agent.source_ingestion import (
    SourceDocumentIndexer,
    SourceIngestionLimits,
    SourceIngestionWorker,
)
from product_support_agent.sources import SourceMap


async def build_search_indexer(
    repository: CanonicalDocumentRepository,
) -> tuple[SourceDocumentIndexer, AzureAISearchProvider]:
    """Create the versioned index if needed and return an indexer that keeps Search in sync."""
    settings = ModelAndSearchSettings()  # type: ignore[call-arg]
    index_name = build_versioned_index_name(
        settings.demo_index_base,
        embedding_model_version=settings.embedding_model_version,
        embedding_dimensions=settings.embedding_dimensions,
        parser_version=HTML_PARSER_VERSION,
    )
    credential = AzureKeyCredential(settings.search_key.get_secret_value())
    index_client = SearchIndexClient(settings.search_endpoint, credential)
    try:
        await apply_search_index(
            index_client,
            build_search_index(index_name, embedding_dimensions=settings.embedding_dimensions),
        )
    finally:
        await index_client.close()
    provider = AzureAISearchProvider(
        SearchClient(settings.search_endpoint, index_name, credential),
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
    indexer = DocumentIndexingService(repository=repository, search=provider, embedder=embedder)
    return indexer, provider


def build_source_worker(
    settings: Settings,
    *,
    source_map: SourceMap,
    state: MongoFetchStateStore,
    repository: CanonicalDocumentRepository,
    indexer: SourceDocumentIndexer,
) -> SourceIngestionWorker:
    return SourceIngestionWorker(
        source_map=source_map,
        state=state,
        fetcher=BoundedFetcher(
            user_agent=settings.source_user_agent,
            max_retry_after_seconds=settings.source_max_retry_after_seconds,
        ),
        indexer=indexer,
        repository=repository,
        policy=FreshnessPolicy(
            success_freshness=timedelta(hours=settings.source_success_freshness_hours),
            transient_failure_backoff=timedelta(
                hours=settings.source_transient_failure_backoff_hours
            ),
            permanent_failure_backoff=timedelta(
                days=settings.source_permanent_failure_backoff_days
            ),
        ),
        limits=SourceIngestionLimits(
            request_budget=settings.source_request_budget,
            min_request_interval_seconds=settings.source_min_request_interval_seconds,
            fail_fast_consecutive_failures=settings.source_fail_fast_consecutive_failures,
        ),
    )

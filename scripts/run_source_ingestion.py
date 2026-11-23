"""Run one bounded, resumable documentation ingestion pass from the approved source map.

Intended to be scheduled (for example weekly). Durable fetch state in MongoDB lets a rerun or a
restart after a crash skip URLs fetched successfully within the freshness window.

By default each stored or removed page is also embedded and written to, or deleted from, the
versioned Azure AI Search index, so search stays consistent with MongoDB. Pass `--repository-only`
to store pages without calling the embedding or Search services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient

from product_support_agent.config import ModelAndSearchSettings, Settings
from product_support_agent.document_store import (
    CanonicalDocumentRepository,
    MongoCanonicalDocumentRepository,
)
from product_support_agent.documents import HTML_PARSER_VERSION
from product_support_agent.embeddings import OpenAICompatibleEmbedder
from product_support_agent.fetch_state import FreshnessPolicy, MongoFetchStateStore
from product_support_agent.http_fetch import BoundedFetcher
from product_support_agent.indexing import DocumentIndexingService, RepositoryOnlyIndexer
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
from product_support_agent.sources import load_source_map

LEASE_NAME = "source-ingestion"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", action="append", default=None, help="limit to a product ID")
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="fetch robots.txt and seeds and report the selection without fetching pages",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore freshness and failure backoff for this run",
    )
    parser.add_argument(
        "--repository-only",
        action="store_true",
        help="store pages in MongoDB only; skip embeddings and Azure AI Search",
    )
    parser.add_argument("--report", type=Path, default=None, help="write the JSON run report")
    return parser.parse_args(argv)


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


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    mongo_uri = settings.mongodb_uri.get_secret_value().strip() if settings.mongodb_uri else ""
    if not mongo_uri:
        print("PRODUCT_SUPPORT_MONGODB_URI must be set", file=sys.stderr)
        return 2
    source_map = load_source_map(Path(settings.source_map_path))
    state = MongoFetchStateStore(mongo_uri)
    repository = MongoCanonicalDocumentRepository(mongo_uri)
    holder = f"{socket.gethostname()}:{uuid4()}"
    now = datetime.now(UTC)
    lease_ttl = timedelta(hours=6)
    provider: AzureAISearchProvider | None = None
    try:
        if args.repository_only or args.discover_only:
            indexer: SourceDocumentIndexer = RepositoryOnlyIndexer(repository=repository)
        else:
            indexer, provider = await build_search_indexer(repository)
        state.ensure_indexes()
        repository.ensure_indexes()
        if not state.acquire_lease(LEASE_NAME, holder, now=now, ttl=lease_ttl):
            print("another source ingestion run holds the lease; exiting", file=sys.stderr)
            return 3
        worker = SourceIngestionWorker(
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
        report = await worker.run(
            args.product,
            force=args.force,
            discover_only=args.discover_only,
        )
    finally:
        state.release_lease(LEASE_NAME, holder)
        state.close()
        repository.close()
        if provider is not None:
            await provider.close()

    payload = report.model_dump(mode="json")
    if args.report is not None:
        args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for product in report.products:
        print(
            f"{product.product_id:>6} {product.outcome:<16} {product.reason_category:<28} "
            f"selected={product.pages_selected} indexed={product.pages_indexed} "
            f"unchanged={product.pages_unchanged} fresh={product.pages_skipped_fresh} "
            f"failed={product.pages_failed} removed={product.pages_removed} "
            f"requests={product.requests}"
        )
    print(f"requests={report.requests}/{report.request_budget} stopped={report.stopped_reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(_run(args, Settings()))


if __name__ == "__main__":
    raise SystemExit(main())

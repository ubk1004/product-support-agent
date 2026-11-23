"""Run one bounded, resumable documentation ingestion pass from the approved source map.

For queue-driven ingestion with one product per message, use `run_queue_ingestion.py`; both
share the same worker, fetch state, and lease. Intended to be scheduled (for example weekly).
Durable fetch state in MongoDB lets a rerun or a restart after a crash skip URLs fetched
successfully within the freshness window.

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

from product_support_agent.config import Settings
from product_support_agent.document_store import MongoCanonicalDocumentRepository
from product_support_agent.fetch_state import MongoFetchStateStore
from product_support_agent.indexing import RepositoryOnlyIndexer
from product_support_agent.ingestion_runtime import build_search_indexer, build_source_worker
from product_support_agent.search import AzureAISearchProvider
from product_support_agent.source_ingestion import SourceDocumentIndexer
from product_support_agent.sources import load_source_map
from product_support_agent.telemetry import (
    TelemetrySettings,
    configure_telemetry,
    record_ingestion_pages,
    tracer,
)

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
        worker = build_source_worker(
            settings,
            source_map=source_map,
            state=state,
            repository=repository,
            indexer=indexer,
        )
        with tracer().start_as_current_span("psa.ingestion.run") as span:
            span.set_attribute("psa.ingestion.search_indexing", provider is not None)
            report = await worker.run(
                args.product,
                force=args.force,
                discover_only=args.discover_only,
            )
            span.set_attribute("psa.ingestion.requests", report.requests)
            span.set_attribute("psa.ingestion.products", len(report.products))
            span.set_attribute("psa.ingestion.stopped_reason", str(report.stopped_reason))
        record_ingestion_pages(
            {
                "indexed": sum(product.pages_indexed for product in report.products),
                "unchanged": sum(product.pages_unchanged for product in report.products),
                "skipped_fresh": sum(product.pages_skipped_fresh for product in report.products),
                "failed": sum(product.pages_failed for product in report.products),
                "removed": sum(product.pages_removed for product in report.products),
            }
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
    telemetry = configure_telemetry(TelemetrySettings(), service_name="product-support-ingestion")
    try:
        return asyncio.run(_run(args, Settings()))
    finally:
        # A short-lived job must flush its batches before the process exits.
        telemetry.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())

"""Run one bounded, resumable documentation ingestion pass from the approved source map.

Intended to be scheduled (for example weekly). Durable fetch state in MongoDB lets a rerun or a
restart after a crash skip URLs fetched successfully within the freshness window.
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
from product_support_agent.fetch_state import FreshnessPolicy, MongoFetchStateStore
from product_support_agent.http_fetch import BoundedFetcher
from product_support_agent.indexing import RepositoryOnlyIndexer
from product_support_agent.source_ingestion import SourceIngestionLimits, SourceIngestionWorker
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
    try:
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
            indexer=RepositoryOnlyIndexer(repository=repository),
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

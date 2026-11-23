"""Queue-driven documentation ingestion: one product per queue message.

    enqueue   Start a run: one message per manifest product that has an approved source.
              Products without one are recorded as skipped (no_public_source) straight away.
    work      Take messages one at a time, ingest that product, record the outcome in MongoDB,
              then delete the message. Stops when the queue is empty or the budget is spent.
    run       enqueue, then work (the local and scheduled default).
    status    Print the latest run (or --run-id) and its per-product outcomes.

The queue is Azure Storage Queue: Azurite locally (`UseDevelopmentStorage=true`), and a private
storage account with managed identity in Azure (`PRODUCT_SUPPORT_QUEUE_ACCOUNT_URL`). Each
message carries only a run ID and a product reference, never content.
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

from azure.storage.queue import QueueClient

from product_support_agent.config import Settings
from product_support_agent.coverage import load_manifest
from product_support_agent.document_store import MongoCanonicalDocumentRepository
from product_support_agent.fetch_state import MongoFetchStateStore
from product_support_agent.indexing import RepositoryOnlyIndexer
from product_support_agent.ingestion_runtime import build_search_indexer, build_source_worker
from product_support_agent.queue import AzureQueueConsumer, AzureQueueProducer
from product_support_agent.queue_ingestion import QueueIngestionWorker, enqueue_manifest_products
from product_support_agent.search import AzureAISearchProvider
from product_support_agent.source_ingestion import SourceDocumentIndexer
from product_support_agent.sources import load_source_map
from product_support_agent.store import MongoIngestionStore
from product_support_agent.telemetry import TelemetrySettings, configure_telemetry, tracer

LEASE_NAME = "source-ingestion"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["enqueue", "work", "run", "status"])
    parser.add_argument("--product", action="append", default=None, help="limit to a product ID")
    parser.add_argument("--run-id", default=None, help="run ID for enqueue or status")
    parser.add_argument("--max-messages", type=int, default=None, help="stop after N messages")
    parser.add_argument("--force", action="store_true", help="ignore freshness and failure backoff")
    parser.add_argument(
        "--repository-only",
        action="store_true",
        help="store pages in MongoDB only; skip embeddings and Azure AI Search",
    )
    return parser.parse_args(argv)


def _queue_clients(settings: Settings) -> tuple[QueueClient, QueueClient]:
    """Queue and poison-queue clients from a connection string, or a URL plus managed identity."""
    name = settings.ingestion_queue_name
    version = settings.queue_api_version
    connection = settings.queue_connection()
    if connection:
        return (
            QueueClient.from_connection_string(connection, queue_name=name, api_version=version),
            QueueClient.from_connection_string(
                connection, queue_name=f"{name}-poison", api_version=version
            ),
        )
    if settings.queue_account_url:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        return (
            QueueClient(
                settings.queue_account_url, name, credential=credential, api_version=version
            ),
            QueueClient(
                settings.queue_account_url,
                f"{name}-poison",
                credential=credential,
                api_version=version,
            ),
        )
    raise SystemExit(
        "set PRODUCT_SUPPORT_QUEUE_CONNECTION_STRING (Azurite) or "
        "PRODUCT_SUPPORT_QUEUE_ACCOUNT_URL (Azure, managed identity)"
    )


def _mongo_uri(settings: Settings) -> str:
    uri = settings.mongodb_uri.get_secret_value().strip() if settings.mongodb_uri else ""
    if not uri:
        raise SystemExit("PRODUCT_SUPPORT_MONGODB_URI must be set")
    return uri


def _enqueue(args: argparse.Namespace, settings: Settings, store: MongoIngestionStore) -> str:
    queue_client, _ = _queue_clients(settings)
    result = enqueue_manifest_products(
        manifest=load_manifest(Path(settings.manifest_path)),
        source_map=load_source_map(Path(settings.source_map_path)),
        producer=AzureQueueProducer(None, settings.ingestion_queue_name, client=queue_client),
        store=store,
        run_id=args.run_id,
        product_ids=args.product,
    )
    print(
        f"run {result.run_id}: queued {result.enqueued} products; "
        f"recorded {result.no_public_source} without an approved source as skipped"
    )
    return result.run_id


async def _work(args: argparse.Namespace, settings: Settings, store: MongoIngestionStore) -> int:
    mongo_uri = _mongo_uri(settings)
    queue_client, poison_client = _queue_clients(settings)
    source_map = load_source_map(Path(settings.source_map_path))
    state = MongoFetchStateStore(mongo_uri)
    repository = MongoCanonicalDocumentRepository(mongo_uri)
    holder = f"{socket.gethostname()}:{uuid4()}"
    provider: AzureAISearchProvider | None = None
    # One worker at a time shares the request budget and host spacing; a second process waits.
    if not state.acquire_lease(LEASE_NAME, holder, now=datetime.now(UTC), ttl=timedelta(hours=6)):
        print("another ingestion run holds the lease; exiting", file=sys.stderr)
        return 3
    try:
        state.ensure_indexes()
        repository.ensure_indexes()
        if args.repository_only:
            indexer: SourceDocumentIndexer = RepositoryOnlyIndexer(repository=repository)
        else:
            indexer, provider = await build_search_indexer(repository)
        worker = QueueIngestionWorker(
            queue=AzureQueueConsumer(
                None,
                settings.ingestion_queue_name,
                client=queue_client,
                poison_client=poison_client,
            ),
            worker=build_source_worker(
                settings,
                source_map=source_map,
                state=state,
                repository=repository,
                indexer=indexer,
            ),
            source_map=source_map,
            store=store,
            poison_dequeue_count=settings.poison_dequeue_count,
            force=args.force,
        )
        with tracer().start_as_current_span("psa.ingestion.queue_drain") as span:
            stats = await worker.run_until_empty(max_messages=args.max_messages)
            span.set_attribute("psa.ingestion.processed", stats.processed)
            span.set_attribute("psa.ingestion.deferred", stats.deferred)
            span.set_attribute("psa.ingestion.dead_lettered", stats.dead_lettered)
    finally:
        state.release_lease(LEASE_NAME, holder)
        state.close()
        repository.close()
        if provider is not None:
            await provider.close()
    print(
        f"processed={stats.processed} deferred={stats.deferred} "
        f"dead_lettered={stats.dead_lettered} stopped={stats.stopped_reason}"
    )
    return 0


def _status(args: argparse.Namespace, store: MongoIngestionStore) -> int:
    run = store.get_run(args.run_id) if args.run_id else store.latest_run()
    if run is None:
        print("no ingestion run recorded")
        return 1
    print(json.dumps(run.model_dump(mode="json"), indent=2))
    for product in store.list_products(run.run_id):
        print(
            f"{product.product_id:>6} {product.outcome:<11} {product.reason_category:<28} "
            f"indexed={product.pages_indexed} unchanged={product.pages_unchanged} "
            f"failed={product.pages_failed} attempts={product.attempt_count}"
        )
    return 0


async def _main(args: argparse.Namespace, settings: Settings) -> int:
    store = MongoIngestionStore(_mongo_uri(settings))
    try:
        store.ensure_indexes()
        if args.command == "status":
            return _status(args, store)
        if args.command in ("enqueue", "run"):
            args.run_id = _enqueue(args, settings, store)
        if args.command in ("work", "run"):
            code = await _work(args, settings, store)
            if code:
                return code
            if args.command == "run":
                return _status(args, store)
        return 0
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    telemetry = configure_telemetry(TelemetrySettings(), service_name="product-support-ingestion")
    try:
        return asyncio.run(_main(args, Settings()))
    finally:
        telemetry.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())

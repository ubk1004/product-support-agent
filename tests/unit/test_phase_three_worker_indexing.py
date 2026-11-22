import asyncio

import httpx

from product_support_agent.catalog import ProductReference
from product_support_agent.documents import DocumentNormalizationError, normalize_html
from product_support_agent.indexing import DocumentIndexingError
from product_support_agent.queue import InMemoryQueue
from product_support_agent.store import IngestionRun, InMemoryIngestionStore
from product_support_agent.worker import IngestionWorker

SOURCE_URL = "https://my.opentext.com/support/products/product-a"
PRODUCT_NAME = "Analytics Database"
HTML_BODY = b"<html><body>Indexed support content.</body></html>"


class RecordingIndexer:
    def __init__(self) -> None:
        self.calls: list[tuple[ProductReference, bytes, str]] = []

    async def index_html(
        self,
        source: ProductReference,
        body: bytes,
        content_type: str,
    ):
        self.calls.append((source, body, content_type))
        return normalize_html(source, body, content_type)


class FailingIndexer:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def index_html(
        self,
        source: ProductReference,
        body: bytes,
        content_type: str,
    ):
        del source, body, content_type
        raise self.error


def worker_with_indexer(indexer) -> tuple[IngestionWorker, InMemoryQueue, InMemoryIngestionStore]:
    queue = InMemoryQueue()
    queue.send_product_reference(
        "run-phase-3",
        "product-a",
        SOURCE_URL,
        product_name=PRODUCT_NAME,
    )
    store = InMemoryIngestionStore()
    store.start_run(
        IngestionRun(
            run_id="run-phase-3",
            manifest_version="manifest-v1",
            started_at="start",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == SOURCE_URL
        return httpx.Response(
            200,
            content=HTML_BODY,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    worker = IngestionWorker(
        queue=queue,
        store=store,
        http_client=httpx.MockTransport(handler),
        document_indexer=indexer,
    )
    return worker, queue, store


def test_worker_indexes_download_and_preserves_queued_product_name() -> None:
    indexer = RecordingIndexer()
    worker, queue, store = worker_with_indexer(indexer)

    assert queue.messages[0].payload["product_name"] == PRODUCT_NAME
    assert asyncio.run(worker.process()) == 1

    source, body, content_type = indexer.calls[0]
    outcome = store.products[("run-phase-3", "product-a")]
    assert len(indexer.calls) == 1
    assert source.product_id == "product-a"
    assert source.name == PRODUCT_NAME
    assert source.slug == "product-a"
    assert str(source.source_url) == SOURCE_URL
    assert body == HTML_BODY
    assert content_type == "text/html; charset=utf-8"
    assert (outcome.outcome, outcome.reason_category, outcome.http_status) == (
        "success",
        "indexed",
        200,
    )
    assert queue.receive() == []
    assert store.runs["run-phase-3"].successful == 1


def test_worker_records_document_normalization_failure() -> None:
    worker, queue, store = worker_with_indexer(
        FailingIndexer(DocumentNormalizationError("unsupported fixture"))
    )

    assert asyncio.run(worker.process()) == 1

    outcome = store.products[("run-phase-3", "product-a")]
    assert (outcome.outcome, outcome.reason_category, outcome.http_status) == (
        "failed",
        "normalization_failed",
        200,
    )
    assert queue.receive() == []


def test_worker_records_document_indexing_failure() -> None:
    worker, queue, store = worker_with_indexer(
        FailingIndexer(DocumentIndexingError("embedding fixture failed"))
    )

    assert asyncio.run(worker.process()) == 1

    outcome = store.products[("run-phase-3", "product-a")]
    assert (outcome.outcome, outcome.reason_category, outcome.http_status) == (
        "failed",
        "indexing_failed",
        200,
    )
    assert queue.receive() == []

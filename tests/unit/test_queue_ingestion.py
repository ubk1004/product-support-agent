import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from azure.core.exceptions import ResourceExistsError

from product_support_agent.catalog import Manifest, ProductReference
from product_support_agent.document_store import InMemoryCanonicalDocumentRepository
from product_support_agent.fetch_state import InMemoryFetchStateStore
from product_support_agent.http_fetch import BoundedFetcher
from product_support_agent.indexing import RepositoryOnlyIndexer
from product_support_agent.queue import AzureQueueConsumer, AzureQueueProducer, InMemoryQueue
from product_support_agent.queue_ingestion import (
    QueueIngestionWorker,
    enqueue_manifest_products,
)
from product_support_agent.source_ingestion import SourceIngestionLimits, SourceIngestionWorker
from product_support_agent.sources import ProductSource, SourceMap
from product_support_agent.store import InMemoryIngestionStore

DOCS = "https://docs.microfocus.com"
START = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def reference(number: int) -> ProductReference:
    return ProductReference(
        product_id=str(number),
        name=f"Product {number}",
        slug=f"slug{number}",
        source_url=f"https://my.opentext.com/support/products/slug{number}",
    )


def manifest(count: int) -> Manifest:
    return Manifest(
        manifest_version="m1",
        selection_method="test",
        selected_products=[reference(number) for number in range(1, count + 1)],
        selection_timestamp="2026-11-23",
        seed="seed",
    )


def source(number: int) -> ProductSource:
    return ProductSource(
        product_id=str(number),
        product_name=f"Product {number}",
        kind="docs_portal_toc",
        seed_url=f"{DOCS}/{number}/tocflat.json",
        max_pages=5,
    )


def source_map(*numbers: int) -> SourceMap:
    return SourceMap(
        schema_version="1",
        source_map_version="s1",
        manifest_version="m1",
        sources=tuple(source(number) for number in numbers),
    )


class Site:
    """A docs portal for products whose TOC is served at /<id>/tocflat.json."""

    def __init__(self, failing: set[str] | None = None, protected: set[str] | None = None) -> None:
        self.requests: list[str] = []
        self.failing = failing or set()
        self.protected = protected or set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        product = path.split("/")[1]
        if path.endswith("/tocflat.json"):
            entries = [
                {"href": f"{product}/1/topic{i}", "revisionId": f"{i}", "level": 2, "text": f"T{i}"}
                for i in range(2)
            ]
            return httpx.Response(200, json={"Toc": {"tocFlat": entries}})
        if product in self.protected:
            return httpx.Response(401)
        if product in self.failing:
            return httpx.Response(500)
        payload = {"parse": {"displaytitle": path, "text": {"*": f"<p>{'Docs ' * 20}{path}</p>"}}}
        return httpx.Response(200, content=json.dumps(payload).encode())


class Harness:
    def __init__(self, *, products: int = 3, with_source: tuple[int, ...] = (1, 2), site=None):
        self.site = site or Site()
        self.store = InMemoryIngestionStore()
        self.queue = InMemoryQueue()
        self.repository = InMemoryCanonicalDocumentRepository()
        self.state = InMemoryFetchStateStore()
        self.manifest = manifest(products)
        self.source_map = source_map(*with_source)

    def enqueue(self, **options):
        return enqueue_manifest_products(
            manifest=self.manifest,
            source_map=self.source_map,
            producer=self.queue,
            store=self.store,
            run_id="run-1",
            now=START,
            **options,
        )

    def worker(self, *, budget: int = 400, **options) -> QueueIngestionWorker:
        async def no_sleep(_: float) -> None:
            return None

        source_worker = SourceIngestionWorker(
            source_map=self.source_map,
            state=self.state,
            fetcher=BoundedFetcher(
                transport=httpx.MockTransport(self.site.handler), max_retry_after_seconds=60
            ),
            indexer=RepositoryOnlyIndexer(repository=self.repository),
            repository=self.repository,
            limits=SourceIngestionLimits(request_budget=budget, min_request_interval_seconds=1.0),
            clock=lambda: START,
            sleep=no_sleep,
            monotonic=lambda: 0.0,
        )
        return QueueIngestionWorker(
            queue=self.queue,
            worker=source_worker,
            source_map=self.source_map,
            store=self.store,
            **options,
        )

    def drain(self, **options):
        return asyncio.run(self.worker(**options).run_until_empty())


def test_enqueue_puts_one_message_per_product_with_a_source_and_records_the_rest() -> None:
    harness = Harness(products=3, with_source=(1, 2))

    result = harness.enqueue()

    assert (result.enqueued, result.no_public_source) == (2, 1)
    assert sorted(message.payload["product_id"] for message in harness.queue.messages) == ["1", "2"]
    skipped = harness.store.products[("run-1", "3")]
    assert (skipped.outcome, skipped.reason_category) == ("skipped", "no_public_source")
    assert harness.store.runs["run-1"].total == 3


def test_every_message_carries_only_a_product_reference() -> None:
    harness = Harness()
    harness.enqueue()

    assert all(
        set(message.payload) == {"run_id", "product_id", "product_name", "source_url"}
        for message in harness.queue.messages
    )


def test_worker_takes_one_product_per_message_and_records_each_outcome() -> None:
    harness = Harness()
    harness.enqueue()

    stats = harness.drain()

    assert stats.processed == 2
    assert harness.queue.messages == []
    first = harness.store.products[("run-1", "1")]
    assert (first.outcome, first.pages_indexed) == ("success", 2)
    assert {doc for doc in harness.repository.list_document_ids()}


def test_run_completes_when_every_product_has_an_outcome() -> None:
    harness = Harness()
    harness.enqueue()

    harness.drain()

    run = harness.store.runs["run-1"]
    assert (run.status, run.processed, run.total) == ("completed", 3, 3)
    assert (run.successful, run.skipped) == (2, 1)
    assert run.finished_at is not None


def test_a_failing_product_is_recorded_and_does_not_stop_the_others() -> None:
    harness = Harness(site=Site(failing={"1"}))
    harness.enqueue()

    harness.drain()

    assert harness.store.products[("run-1", "1")].outcome == "failed"
    assert harness.store.products[("run-1", "2")].outcome == "success"
    assert harness.store.runs["run-1"].status == "completed_with_errors"


def test_a_product_whose_pages_are_protected_is_skipped_with_a_reason() -> None:
    harness = Harness(site=Site(protected={"2"}))
    harness.enqueue()

    harness.drain()

    status = harness.store.products[("run-1", "2")]
    assert (status.outcome, status.reason_category) == ("skipped", "protected_content")
    assert harness.repository.list_document_ids() != []


def test_message_is_deleted_only_after_the_outcome_is_recorded() -> None:
    harness = Harness()
    harness.enqueue()
    order: list[str] = []
    record = harness.store.record_product
    delete = harness.queue.delete
    harness.store.record_product = lambda status: (order.append("record"), record(status))[1]
    harness.queue.delete = lambda message: (order.append("delete"), delete(message))[1]

    harness.drain()

    first_delete = order.index("delete")
    assert order[:first_delete].count("record") >= 1
    assert all(order[index - 1] == "record" for index, item in enumerate(order) if item == "delete")


def test_a_crash_leaves_the_message_so_a_retry_does_not_lose_or_duplicate_work() -> None:
    harness = Harness(with_source=(1,), products=1)
    harness.enqueue()
    first = harness.worker()
    message = harness.queue.receive_one()
    assert message is not None
    # Simulate a worker that took the message and died before recording anything.
    harness.queue.release(message)

    stats = asyncio.run(first.run_until_empty())

    assert stats.processed == 1
    assert harness.store.runs["run-1"].successful == 1
    # A second delivery of the same product (at-least-once) is harmless.
    harness.queue.send_product_reference("run-1", "1", message.payload["source_url"], "Product 1")
    again = asyncio.run(harness.worker().run_until_empty())
    assert again.processed == 1
    assert harness.store.runs["run-1"].processed == 1
    assert harness.store.runs["run-1"].successful == 1


def test_a_message_delivered_too_many_times_is_dead_lettered() -> None:
    harness = Harness(with_source=(1,), products=1)
    harness.enqueue()
    for _ in range(4):
        message = harness.queue.receive_one()
        assert message is not None
        harness.queue.release(message)

    stats = harness.drain(poison_dequeue_count=5)

    status = harness.store.products[("run-1", "1")]
    assert (status.outcome, status.reason_category) == ("dead_letter", "poison")
    assert stats.dead_lettered == 1
    assert len(harness.queue.poison_messages) == 1
    assert harness.queue.messages == []
    assert harness.site.requests == []


def test_a_product_missing_from_the_source_map_is_skipped_not_retried_forever() -> None:
    harness = Harness(with_source=(1,), products=1)
    harness.queue.send_product_reference("run-1", "99", "https://my.opentext.com/p", "Ghost")
    harness.store.start_run(
        __import__("product_support_agent.store", fromlist=["IngestionRun"]).IngestionRun(
            run_id="run-1", manifest_version="m1", started_at="s", total=1
        )
    )

    stats = harness.drain()

    status = harness.store.products[("run-1", "99")]
    assert (status.outcome, status.reason_category) == ("skipped", "no_public_source")
    assert stats.unknown_product == 1
    assert harness.queue.messages == []


def test_an_exhausted_request_budget_defers_remaining_products_without_losing_them() -> None:
    harness = Harness(products=2, with_source=(1, 2))
    harness.enqueue()

    stats = harness.drain(budget=4)

    # Product 1 fits the budget (robots.txt, TOC, two pages); product 2 does not.
    assert harness.store.products[("run-1", "1")].outcome == "success"
    assert stats.stopped_reason == "request_budget_exhausted"
    assert stats.deferred == 1
    assert ("run-1", "2") not in harness.store.products
    assert [message.payload["product_id"] for message in harness.queue.messages] == ["2"]
    assert harness.store.runs["run-1"].finished_at is None

    harness.queue.make_delayed_visible()
    again = harness.drain(budget=400)

    assert again.stopped_reason is None
    assert harness.store.runs["run-1"].status == "completed"


def test_an_unexpected_error_leaves_the_message_for_a_retry() -> None:
    harness = Harness(with_source=(1,), products=1)
    harness.enqueue()
    worker = harness.worker()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    worker.worker.process_source = boom  # type: ignore[method-assign]
    message = harness.queue.receive_one()
    assert message is not None
    harness.queue.release(message)

    stats = asyncio.run(worker.run_until_empty(max_messages=1))

    assert stats.processed == 0
    assert [m.payload["product_id"] for m in harness.queue.messages] == ["1"]
    assert ("run-1", "1") not in harness.store.products


def test_requests_for_one_host_share_the_worker_budget_across_products() -> None:
    harness = Harness(products=2, with_source=(1, 2))
    harness.enqueue()

    asyncio.run(harness.worker().run_until_empty())

    robots = [url for url in harness.site.requests if url.endswith("/robots.txt")]
    assert len(robots) == 1


def test_restricting_the_run_to_named_products() -> None:
    harness = Harness(products=3, with_source=(1, 2, 3))

    result = harness.enqueue(product_ids=["2"])

    assert result.enqueued == 1
    assert harness.store.runs["run-1"].total == 1
    with pytest.raises(ValueError):
        Harness().enqueue(product_ids=["does-not-exist"])


class FakeQueueClient:
    def __init__(self) -> None:
        self.items: list[SimpleNamespace] = []
        self.deleted: list[tuple[str, str]] = []
        self.sent_with: list[dict[str, object]] = []
        self.created = 0

    def create_queue(self) -> None:
        self.created += 1
        if self.created > 1:
            raise ResourceExistsError("queue exists")

    def send_message(self, content, **options):
        self.sent_with.append(options)
        item = SimpleNamespace(
            id=f"id-{len(self.items) + 1}",
            content=content,
            dequeue_count=1,
            pop_receipt=f"receipt-{len(self.items) + 1}",
        )
        self.items.append(item)
        return item

    def receive_messages(self, *, messages_per_page, max_messages=None, visibility_timeout):
        self.sent_with.append({"visibility_timeout": visibility_timeout, "max": max_messages})
        return iter(self.items[: max_messages or len(self.items)])

    def delete_message(self, message_id, pop_receipt):
        self.deleted.append((message_id, pop_receipt))
        self.items = [item for item in self.items if item.id != message_id]

    def get_queue_properties(self):
        return SimpleNamespace(approximate_message_count=len(self.items))


def test_azure_consumer_takes_one_message_with_a_long_visibility_timeout() -> None:
    client = FakeQueueClient()
    consumer = AzureQueueConsumer(None, "products", client=client, poison_client=FakeQueueClient())
    producer = AzureQueueProducer(None, "products", client=client)
    producer.send_product_reference("run-1", "1", "https://my.opentext.com/p1", "One")
    producer.send_product_reference("run-1", "2", "https://my.opentext.com/p2", "Two")

    message = consumer.receive_one()

    assert message is not None and message.payload["product_id"] == "1"
    assert client.sent_with[-1] == {"visibility_timeout": 900, "max": 1}
    assert consumer.approximate_count() == 2


def test_azure_consumer_deletes_with_the_pop_receipt_and_moves_poison_aside() -> None:
    client, poison = FakeQueueClient(), FakeQueueClient()
    consumer = AzureQueueConsumer(None, "products", client=client, poison_client=poison)
    AzureQueueProducer(None, "products", client=client).send_product_reference(
        "run-1", "1", "https://my.opentext.com/p1", "One"
    )
    message = consumer.receive_one()
    assert message is not None

    consumer.transfer_to_poison(message)

    assert client.deleted == [("id-1", "receipt-1")]
    assert json.loads(poison.items[0].content)["product_id"] == "1"


def test_azure_defer_requeues_with_a_delay_and_a_fresh_delivery_count() -> None:
    client = FakeQueueClient()
    consumer = AzureQueueConsumer(None, "products", client=client, poison_client=FakeQueueClient())
    AzureQueueProducer(None, "products", client=client).send_product_reference(
        "run-1", "1", "https://my.opentext.com/p1", "One"
    )
    message = consumer.receive_one()
    assert message is not None

    consumer.defer(message, 3600)

    assert client.sent_with[-1] == {"visibility_timeout": 3600}
    assert [item.id for item in client.items] == ["id-2"]
    assert client.items[0].dequeue_count == 1


def test_creating_an_existing_queue_is_not_an_error() -> None:
    client = FakeQueueClient()
    AzureQueueProducer(None, "products", client=client)

    AzureQueueProducer(None, "products", client=client)

    assert client.created == 2


def test_enqueue_with_nothing_to_queue_completes_the_run_immediately() -> None:
    harness = Harness(products=2, with_source=())

    result = harness.enqueue()

    assert result.enqueued == 0
    run = harness.store.runs["run-1"]
    assert (run.status, run.processed) == ("completed", 2)
    assert run.finished_at is not None


def test_run_start_time_comes_from_the_injected_clock() -> None:
    harness = Harness()
    harness.enqueue()

    assert harness.store.runs["run-1"].started_at == START.isoformat()
    assert datetime.fromisoformat(harness.store.runs["run-1"].started_at) + timedelta(0) == START


def test_run_status_api_reads_the_durable_store(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx as _httpx

    from product_support_agent.api import app as api

    harness = Harness()
    harness.enqueue()
    harness.drain()
    run = harness.store.runs["run-1"]

    def reader(run_id: str | None):
        if run_id not in (None, "run-1"):
            return {"run": None, "products": []}
        return {
            "run": run.model_dump(mode="json"),
            "products": [
                status.model_dump(mode="json") for status in harness.store.list_products("run-1")
            ],
        }

    monkeypatch.setattr(api, "ingestion_run_reader", reader)

    async def call(path: str) -> _httpx.Response:
        transport = _httpx.ASGITransport(app=api.app)
        async with _httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    latest = asyncio.run(call("/ingestion/runs/latest")).json()
    assert latest["run"]["status"] == "completed"
    assert {product["product_id"] for product in latest["products"]} == {"1", "2", "3"}
    assert asyncio.run(call("/ingestion/runs/unknown")).json() == {"run": None, "products": []}


def test_run_status_api_reports_unavailable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx as _httpx

    from product_support_agent.api import app as api

    monkeypatch.setattr(api, "ingestion_run_reader", lambda run_id: None)

    async def call() -> _httpx.Response:
        transport = _httpx.ASGITransport(app=api.app)
        async with _httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/ingestion/runs/latest")

    response = asyncio.run(call())
    assert response.status_code == 503


def test_a_refused_queue_create_is_tolerated_when_queues_are_preprovisioned() -> None:
    from azure.core.exceptions import HttpResponseError

    class ForbiddenCreate(FakeQueueClient):
        def create_queue(self) -> None:
            error = HttpResponseError("AuthorizationPermissionMismatch")
            error.status_code = 403
            raise error

    AzureQueueConsumer(None, "products", client=ForbiddenCreate(), poison_client=ForbiddenCreate())


def test_other_queue_create_failures_are_raised() -> None:
    from azure.core.exceptions import HttpResponseError

    class BrokenCreate(FakeQueueClient):
        def create_queue(self) -> None:
            error = HttpResponseError("ServerBusy")
            error.status_code = 503
            raise error

    with pytest.raises(HttpResponseError):
        AzureQueueProducer(None, "products", client=BrokenCreate())

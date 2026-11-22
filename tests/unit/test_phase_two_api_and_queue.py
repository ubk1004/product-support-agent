import asyncio
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from product_support_agent.catalog import (
    CatalogClient,
    CatalogOutcome,
    ProductReference,
    create_manifest,
)
from product_support_agent.orchestration import PhaseTwoService
from product_support_agent.queue import AzureQueueConsumer, AzureQueueProducer, InMemoryQueue
from product_support_agent.store import InMemoryIngestionStore
from product_support_agent.worker import IngestionWorker

api = importlib.import_module("product_support_agent.api.app")


def products(count: int) -> list[ProductReference]:
    return [
        ProductReference(
            product_id=f"p{i:03}",
            name=f"Product {i}",
            slug=f"p{i:03}",
            source_url=f"https://my.opentext.com/support/products/p{i:03}",
        )
        for i in range(count)
    ]


class FakeCatalog:
    def __init__(self, items):
        self.items = items

    async def discover(self):
        return CatalogOutcome(source="feed", products=self.items, page_count=1)


def make_service(items, limit=100):
    return PhaseTwoService(
        catalog=FakeCatalog(items),
        queue=InMemoryQueue(),
        store=InMemoryIngestionStore(),
        manifest_seed="seed",
        max_demo_products=limit,
    )


def get(path):
    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_queue_messages_include_run_product_and_source_url() -> None:
    service = make_service(products(125))
    manifest, outcome = asyncio.run(service.discover_and_prepare())
    run = service.enqueue_manifest("run-1")

    assert outcome.source == "feed"
    assert manifest is not None
    assert run.manifest_version == manifest.manifest_version
    assert run.status == "running"
    payloads = [message.payload for message in service.queue.receive()]
    assert len(payloads) == 100
    assert all(
        set(payload) == {"run_id", "product_id", "product_name", "source_url"}
        for payload in payloads
    )
    assert {payload["run_id"] for payload in payloads} == {"run-1"}
    assert {payload["product_id"] for payload in payloads} == {
        product.product_id for product in manifest.selected_products
    }
    assert {(payload["product_id"], payload["source_url"]) for payload in payloads} == {
        (product.product_id, str(product.source_url)) for product in manifest.selected_products
    }
    assert {(payload["product_id"], payload["product_name"]) for payload in payloads} == {
        (product.product_id, product.name) for product in manifest.selected_products
    }


def test_azure_queue_round_trip_preserves_product_source_url(monkeypatch) -> None:
    class FakeQueueClient:
        def __init__(self):
            self.messages = []

        def create_queue(self):
            pass

        def send_message(self, content):
            message = SimpleNamespace(
                id="message-1", content=content, dequeue_count=1, pop_receipt="receipt-1"
            )
            self.messages.append(message)
            return message

        def receive_messages(self, *, messages_per_page, visibility_timeout):
            return self.messages

    clients = {"products": FakeQueueClient(), "products-poison": FakeQueueClient()}
    monkeypatch.setattr(
        "product_support_agent.queue.QueueClient.from_connection_string",
        lambda connection_string, queue_name: clients[queue_name],
    )
    producer = AzureQueueProducer("unused", "products")
    consumer = AzureQueueConsumer("unused", "products")
    source_url = "https://my.opentext.com/support/products/analytics-database"

    assert (
        producer.send_product_reference("run-1", "1", source_url, "Analytics Database")
        == "message-1"
    )
    sent = clients["products"].messages
    assert len(sent) == 1
    assert json.loads(sent[0].content) == {
        "run_id": "run-1",
        "product_id": "1",
        "product_name": "Analytics Database",
        "source_url": source_url,
    }
    messages = consumer.receive()
    assert len(messages) == 1
    assert messages[0].payload == {
        "run_id": "run-1",
        "product_id": "1",
        "product_name": "Analytics Database",
        "source_url": source_url,
    }


def test_enqueue_preserves_manifest_source_for_product_with_distinct_slug() -> None:
    source_url = "https://my.opentext.com/support/products/analytics-database"
    service = make_service(
        [
            ProductReference(
                product_id="1",
                name="Analytics Database",
                slug="analytics-database",
                source_url=source_url,
            )
        ]
    )
    manifest, _ = asyncio.run(service.discover_and_prepare())
    assert manifest is not None
    selected = manifest.selected_products[0]
    assert (selected.product_id, selected.slug, str(selected.source_url)) == (
        "1",
        "analytics-database",
        source_url,
    )

    service.enqueue_manifest("run-1")
    messages = service.queue.receive()
    assert len(messages) == 1
    payload = messages[0].payload
    assert payload["run_id"] == "run-1"
    assert payload["product_id"] == "1"
    assert payload["product_name"] == "Analytics Database"
    assert payload["source_url"] == source_url


def test_feed_manifest_enqueue_and_worker_use_source_url_and_original_id() -> None:
    source_url = "https://my.opentext.com/support/products/analytics-database"
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path == "/support/products/":
            return httpx.Response(200, text="<html>Empty</html>")
        if request.url.path == "/api/web/support/search-results":
            return httpx.Response(200, json={"results": []})
        if request.url.path == "/api/web/feed/product":
            return httpx.Response(
                200, json=[{"id": "1", "name": "Analytics Database", "slug": "analytics-database"}]
            )
        return httpx.Response(200, text="Public documentation")

    transport = httpx.MockTransport(handler)
    queue = InMemoryQueue()
    store = InMemoryIngestionStore()
    service = PhaseTwoService(
        catalog=CatalogClient(client=transport),
        queue=queue,
        store=store,
        manifest_seed="seed",
        max_demo_products=100,
    )
    manifest, outcome = asyncio.run(service.discover_and_prepare())
    assert outcome.source == "feed"
    assert manifest is not None
    selected = manifest.selected_products[0]
    assert (selected.product_id, selected.slug, str(selected.source_url)) == (
        "1",
        "analytics-database",
        source_url,
    )
    service.enqueue_manifest("run-1")
    requests.clear()

    worker = IngestionWorker(queue=queue, store=store, http_client=transport)
    assert asyncio.run(worker.process()) == 1
    assert requests == [source_url]
    result = store.products[("run-1", "1")]
    assert (result.run_id, result.product_id, result.source_url) == ("run-1", "1", source_url)
    assert (result.outcome, result.reason_category, result.http_status) == (
        "success",
        "downloaded",
        200,
    )


def test_empty_catalog_cannot_be_enqueued() -> None:
    service = make_service([])
    manifest, outcome = asyncio.run(service.discover_and_prepare())
    assert manifest is None
    assert outcome.products == []
    with pytest.raises(RuntimeError, match="manifest"):
        service.enqueue_manifest("run-1")
    assert service.queue.receive() == []
    assert service.store.runs == {}


def test_normal_enqueue_reruns_reuse_prepared_manifest() -> None:
    service = make_service(products(125))
    manifest, _ = asyncio.run(service.discover_and_prepare())
    assert manifest is not None
    service.enqueue_manifest("run-1")
    service.enqueue_manifest("run-2")
    payloads = [message.payload for message in service.queue.receive()]
    first = {p["product_id"] for p in payloads if p["run_id"] == "run-1"}
    second = {p["product_id"] for p in payloads if p["run_id"] == "run-2"}
    assert first == second == {p.product_id for p in manifest.selected_products}
    assert len(first) == 100
    assert (
        service.store.runs["run-1"].manifest_version == service.store.runs["run-2"].manifest_version
    )


def test_manifest_api_reports_absent_catalog_without_network(monkeypatch) -> None:
    monkeypatch.setattr(
        api, "phase_two_service", SimpleNamespace(manifest=None, catalog_outcome=None)
    )
    response = get("/catalog/manifest")
    assert response.status_code == 200
    assert response.json() == {"manifest": None, "catalog": None}


def test_manifest_api_returns_selected_products_and_catalog(monkeypatch) -> None:
    manifest = create_manifest(
        products(2), manifest_version="v1", seed="seed", selection_timestamp="2026-01-01"
    )
    outcome = CatalogOutcome(source="feed", products=products(2), page_count=1)
    monkeypatch.setattr(
        api, "phase_two_service", SimpleNamespace(manifest=manifest, catalog_outcome=outcome)
    )
    response = get("/catalog/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["manifest"] == manifest.model_dump(mode="json")
    assert body["catalog"] == outcome.model_dump(mode="json")
    assert [p["product_id"] for p in body["manifest"]["selected_products"]] == ["p000", "p001"]

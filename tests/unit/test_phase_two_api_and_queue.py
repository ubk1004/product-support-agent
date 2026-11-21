import asyncio
import importlib
from types import SimpleNamespace

import httpx
import pytest

from product_support_agent.catalog import CatalogOutcome, ProductReference, create_manifest
from product_support_agent.orchestration import PhaseTwoService
from product_support_agent.queue import InMemoryQueue
from product_support_agent.store import InMemoryIngestionStore

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


def test_queue_messages_contain_only_run_and_product_references() -> None:
    service = make_service(products(125))
    manifest, outcome = asyncio.run(service.discover_and_prepare())
    run = service.enqueue_manifest("run-1")

    assert outcome.source == "feed"
    assert manifest is not None
    assert run.manifest_version == manifest.manifest_version
    assert run.status == "running"
    payloads = [message.payload for message in service.queue.receive()]
    assert len(payloads) == 100
    assert all(set(payload) == {"run_id", "product_id"} for payload in payloads)
    assert {payload["run_id"] for payload in payloads} == {"run-1"}
    assert {payload["product_id"] for payload in payloads} == {
        product.product_id for product in manifest.selected_products
    }


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

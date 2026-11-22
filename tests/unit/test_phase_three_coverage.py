import asyncio
import importlib
from datetime import UTC, datetime

import httpx
import pytest

from product_support_agent.catalog import Manifest, ProductReference
from product_support_agent.coverage import build_coverage_report
from product_support_agent.fetch_state import FetchStateRecord
from product_support_agent.sources import ProductSource, SourceMap

api = importlib.import_module("product_support_agent.api.app")
NOW = datetime(2026, 11, 22, tzinfo=UTC)
DOCS = "https://docs.microfocus.com"


def manifest(*ids: str, version: str = "manifest-v1") -> Manifest:
    return Manifest(
        manifest_version=version,
        selection_method="deterministic-random-v1",
        selection_timestamp="2026-11-21",
        seed="seed",
        selected_products=[
            ProductReference(
                product_id=product_id,
                name=f"Product {product_id}",
                slug=product_id,
                source_url=f"https://my.opentext.com/support/products/{product_id}",
            )
            for product_id in ids
        ],
    )


def source(product_id: str, *, enabled: bool = True) -> ProductSource:
    return ProductSource(
        product_id=product_id,
        product_name=f"Product {product_id}",
        kind="docs_portal_toc",
        seed_url=f"{DOCS}/{product_id}/1.0/tocflat.json",
        enabled=enabled,
    )


def source_map(*sources: ProductSource, manifest_version: str = "manifest-v1") -> SourceMap:
    return SourceMap(
        schema_version="1",
        source_map_version="map-v1",
        manifest_version=manifest_version,
        sources=sources,
    )


def record(product_id: str, kind: str, outcome: str, *, document: bool = False, n: int = 0):
    return FetchStateRecord(
        key=f"{product_id}-{kind}-{n}",
        product_id=product_id,
        kind=kind,
        fetch_url=f"{DOCS}/{product_id}/p{n}/default-1.json",
        citation_url=f"{DOCS}/doc/{product_id}/p{n}",
        last_outcome=outcome,
        reason_category="protected_403" if outcome == "failed" else outcome,
        last_attempt_at=NOW,
        last_success_at=NOW if outcome != "failed" else None,
        document_id=f"doc_{product_id}_{n}" if document else None,
    )


def test_coverage_classifies_every_manifest_product_and_orders_indexed_first() -> None:
    report = build_coverage_report(
        manifest("a", "b", "c", "d", "e"),
        source_map(source("a"), source("b"), source("c"), source("e", enabled=False)),
        [
            record("a", "page", "indexed", document=True, n=1),
            record("a", "page", "indexed", document=True, n=2),
            record("a", "page", "removed", document=False, n=3),
            record("b", "seed", "failed"),
        ],
    )

    statuses = [(item.product_id, item.status) for item in report.products]
    assert statuses == [
        ("a", "indexed"),
        ("c", "pending"),
        ("b", "unavailable"),
        ("e", "excluded"),
        ("d", "no_public_source"),
    ]
    indexed = report.products[0]
    assert (indexed.pages_indexed, indexed.last_indexed_at, indexed.source_host) == (
        2,
        NOW,
        "docs.microfocus.com",
    )
    assert report.products[2].reason_category == "protected_403"
    assert report.summary.model_dump() == {
        "manifest_products": 5,
        "products_with_sources": 3,
        "products_indexed": 1,
        "pages_indexed": 2,
    }
    assert report.state_available and report.source_map_matches_manifest
    assert report.retrieval_enabled is False


def test_unreadable_state_reports_sources_as_pending_not_indexed() -> None:
    report = build_coverage_report(manifest("a"), source_map(source("a")), None)
    assert report.state_available is False
    assert report.products[0].status == "pending"
    assert report.summary.products_indexed == 0


def test_coverage_flags_manifest_mismatch() -> None:
    report = build_coverage_report(
        manifest("a"), source_map(source("a"), manifest_version="other"), []
    )
    assert report.source_map_matches_manifest is False


def test_coverage_report_contains_no_page_urls_or_content() -> None:
    report = build_coverage_report(
        manifest("a"),
        source_map(source("a")),
        [record("a", "page", "indexed", document=True, n=1)],
    )
    payload = report.model_dump_json()
    assert "/doc/a/p1" not in payload
    assert "default-1.json" not in payload


def get(path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_coverage_endpoint_uses_repository_manifest_and_source_map(monkeypatch) -> None:
    monkeypatch.setattr(api, "fetch_state_reader", lambda: [])
    response = get("/catalog/coverage")

    assert response.status_code == 200
    body = response.json()
    assert body["manifest_version"] == "opentext-2026-11-21-v1"
    assert body["source_map_matches_manifest"] is True
    assert body["summary"]["manifest_products"] == 100
    assert body["summary"]["products_with_sources"] == 10
    assert body["summary"]["products_indexed"] == 0
    assert {item["status"] for item in body["products"]} == {"pending", "no_public_source"}


def test_coverage_endpoint_without_mongo_reports_state_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(api.settings, "mongodb_uri", None)
    monkeypatch.setattr(api, "fetch_state_reader", api._read_fetch_state)
    body = get("/catalog/coverage").json()
    assert body["state_available"] is False


@pytest.mark.parametrize("field", ["manifest_path", "source_map_path"])
def test_coverage_endpoint_returns_503_when_inputs_are_missing(monkeypatch, field) -> None:
    monkeypatch.setattr(api, "fetch_state_reader", lambda: [])
    monkeypatch.setattr(api.settings, field, "does/not/exist.json")
    response = get("/catalog/coverage")
    assert response.status_code == 503
    assert response.json() == {"detail": "coverage data unavailable"}

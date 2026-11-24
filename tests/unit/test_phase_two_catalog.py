import asyncio

import httpx
import pytest
from pydantic import ValidationError

from product_support_agent.catalog import (
    CatalogClient,
    ProductReference,
    create_manifest,
    validate_source_url,
)
from product_support_agent.config import Settings


def product(number: int) -> ProductReference:
    return ProductReference(
        product_id=f"p{number:03}",
        name=f"Product {number}",
        slug=f"p{number:03}",
        source_url=f"https://my.opentext.com/support/products/p{number:03}",
    )


def item(number: int) -> dict[str, str]:
    return {"id": f"p{number:03}", "name": f"Product {number}", "slug": f"p{number:03}"}


CATALOG_URLS = {
    "listing_url": "https://my.opentext.com/support/products/",
    "search_url": "https://my.opentext.com/api/web/support/search-results",
    "feed_url": "https://my.opentext.com/api/web/feed/product",
}


def discover(handler, **kwargs):
    client = CatalogClient(client=httpx.MockTransport(handler), **{**CATALOG_URLS, **kwargs})
    return asyncio.run(client.discover())


def test_listing_is_preferred_and_duplicates_are_removed() -> None:
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            text='<a href="/support/products/alpha">A</a>'
            '<a href="/support/products/alpha">A again</a>'
            '<a href="https://elsewhere.example/support/products/beta">B</a>',
        )

    outcome = discover(handler)
    assert calls == ["/support/products/"]
    assert outcome.source == "listing"
    assert [p.product_id for p in outcome.products] == ["alpha"]


def test_search_is_used_before_feed_after_empty_listing() -> None:
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="<html>No products</html>")
        return httpx.Response(200, json={"results": [item(2), item(1), item(2)]})

    outcome = discover(handler)
    assert calls == ["/support/products/", "/api/web/support/search-results"]
    assert outcome.source == "search"
    assert [p.product_id for p in outcome.products] == ["p001", "p002"]


def test_feed_is_used_after_empty_listing_and_search() -> None:
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="<html>Empty</html>")
        if request.url.path.endswith("search-results"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"products": [item(3), item(3)]})

    outcome = discover(handler)
    assert calls == [
        "/support/products/",
        "/api/web/support/search-results",
        "/api/web/feed/product",
    ]
    assert outcome.source == "feed"
    assert [p.product_id for p in outcome.products] == ["p003"]


def test_malformed_search_falls_back_to_feed() -> None:
    def handler(request):
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="")
        if request.url.path.endswith("search-results"):
            return httpx.Response(200, text="not json")
        return httpx.Response(200, json=[item(4)])

    outcome = discover(handler)
    assert outcome.source == "feed"
    assert [p.product_id for p in outcome.products] == ["p004"]


@pytest.mark.parametrize("status", [401, 403])
def test_protected_search_is_skipped_and_the_feed_is_used(status: int) -> None:
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="")
        if request.url.path.endswith("search-results"):
            return httpx.Response(status)
        return httpx.Response(200, json=[item(3), item(1)])

    outcome = discover(handler)
    assert calls == [
        "/support/products/",
        "/api/web/support/search-results",
        "/api/web/feed/product",
    ]
    assert outcome.source == "feed"
    assert [p.product_id for p in outcome.products] == ["p001", "p003"]
    assert outcome.notes == ["listing: empty", "search: protected"]


def test_protected_search_and_protected_feed_yield_no_catalog() -> None:
    def handler(request):
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="")
        return httpx.Response(401)

    outcome = discover(handler)
    assert outcome.products == []
    assert outcome.source == "feed"
    assert outcome.reason == "protected"
    assert outcome.notes == ["listing: empty", "search: protected"]


def test_credentials_are_never_sent_to_protected_endpoints() -> None:
    seen = []

    def handler(request):
        seen.append((request.headers.get("authorization"), request.headers.get("cookie")))
        return httpx.Response(401)

    discover(handler)
    assert seen and all(pair == (None, None) for pair in seen)


def test_empty_catalog_has_no_products_and_an_explicit_reason() -> None:
    def handler(request):
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="")
        return httpx.Response(200, json=[])

    outcome = discover(handler)
    assert outcome.source == "feed"
    assert outcome.products == []
    assert outcome.reason in {"empty", "catalog empty"}


def test_search_continues_after_full_page_and_deduplicates_between_pages() -> None:
    starts = []

    def handler(request):
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="")
        starts.append(request.url.params["start"])
        if starts[-1] == "1":
            return httpx.Response(200, json={"results": [item(i) for i in range(100)]})
        return httpx.Response(200, json={"results": [item(99), item(100)]})

    outcome = discover(handler, max_pages=3)
    assert starts == ["1", "101"]
    assert [p.product_id for p in outcome.products] == [f"p{i:03}" for i in range(101)]
    assert outcome.page_count == 2


def test_search_stops_at_page_limit() -> None:
    starts = []

    def handler(request):
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="")
        starts.append(request.url.params["start"])
        return httpx.Response(200, json={"results": [item(i) for i in range(100)]})

    outcome = discover(handler, max_pages=1)
    assert starts == ["1"]
    assert len(outcome.products) == 100
    assert outcome.page_count == 1


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://my.opentext.com/support/products/a", True),
        ("https://support.opentext.com/csm?id=knowledge", True),
        ("https://docs.microfocus.com/doc/product", True),
        ("https://www.microfocus.com/documentation/product", True),
        ("https://admhelp.microfocus.com/product/help", True),
        ("https://liaisontechnologies.service-now.com/sp", True),
        ("https://answers.webroot.com/Webroot/ukp.aspx", True),
        ("http://my.opentext.com/support/products/a", False),
        ("https://my.opentext.com.evil.example/a", False),
        ("https://support.opentext.com.evil.example/a", False),
        ("https://evil.support.opentext.com/a", False),
        ("https://evil.example/my.opentext.com/a", False),
        ("https://my.opentext.com:444/a", False),
        ("https://my.opentext.com:notaport/a", False),
        ("https://user:password@my.opentext.com/a", False),
    ],
    ids=[
        "catalog",
        "opentext-support",
        "microfocus-docs",
        "microfocus-website",
        "microfocus-admhelp",
        "liaison-knowledge",
        "webroot-knowledge",
        "http",
        "catalog-suffix-host",
        "support-suffix-host",
        "support-subdomain",
        "wrong-host",
        "port",
        "bad-port",
        "userinfo",
    ],
)
def test_source_url_allowlist(url: str, allowed: bool) -> None:
    assert validate_source_url(url) is allowed


def test_catalog_urls_are_required_and_have_no_second_default() -> None:
    with pytest.raises(TypeError):
        CatalogClient(client=httpx.MockTransport(lambda request: httpx.Response(404)))  # type: ignore[call-arg]


def test_catalog_client_uses_the_urls_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PRODUCT_SUPPORT_CATALOG_LISTING_URL", "https://my.opentext.com/support/other/"
    )
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.catalog_search_url == "https://my.opentext.com/api/web/support/search-results"
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>No products</html>")

    client = CatalogClient(
        client=httpx.MockTransport(handler),
        listing_url=settings.catalog_listing_url,
        search_url=settings.catalog_search_url,
        feed_url=settings.catalog_feed_url,
    )
    asyncio.run(client.discover())
    assert calls[0] == "https://my.opentext.com/support/other/"


def test_catalog_requests_remain_limited_to_catalog_host() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text="unexpected")

    client = CatalogClient(client=httpx.MockTransport(handler), **CATALOG_URLS)
    result = asyncio.run(client._bounded_get("https://support.opentext.com/csm"))

    assert result is None
    assert calls == []


def test_manifest_selection_is_reproducible_across_input_order() -> None:
    products = [product(i) for i in range(125)]
    kwargs = dict(manifest_version="v1", seed="seed", selection_timestamp="2026-01-01")
    first = create_manifest(products, **kwargs)
    second = create_manifest(reversed(products), **kwargs)
    assert first.model_dump() == second.model_dump()
    assert len(first.selected_products) == 100
    assert len({p.product_id for p in first.selected_products}) == 100
    assert first.selection_method == "deterministic-random-v1"


def test_manifest_seed_changes_the_sample() -> None:
    products = [product(i) for i in range(125)]
    kwargs = dict(manifest_version="v1", selection_timestamp="2026-01-01")
    first = create_manifest(products, seed="seed-a", **kwargs)
    second = create_manifest(products, seed="seed-b", **kwargs)
    assert {p.product_id for p in first.selected_products} != {
        p.product_id for p in second.selected_products
    }


@pytest.mark.parametrize("limit", [0, -1, 101, 102])
def test_manifest_rejects_limits_outside_one_to_one_hundred(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        create_manifest(
            [product(1)],
            manifest_version="v1",
            seed="seed",
            selection_timestamp="2026-01-01",
            max_products=limit,
        )


def test_manifest_rejects_empty_catalog() -> None:
    with pytest.raises(ValueError, match="empty catalog"):
        create_manifest([], manifest_version="v1", seed="s", selection_timestamp="2026-01-01")


def test_manifest_deduplicates_and_respects_smaller_limit() -> None:
    manifest = create_manifest(
        [product(1), product(1), product(2), product(3)],
        manifest_version="v1",
        seed="s",
        selection_timestamp="2026-01-01",
        max_products=2,
    )
    ids = [p.product_id for p in manifest.selected_products]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert set(ids) <= {"p001", "p002", "p003"}


def test_manifest_accepts_exact_upper_and_lower_limits() -> None:
    kwargs = dict(manifest_version="v1", seed="seed", selection_timestamp="2026-01-01")
    full = create_manifest([product(i) for i in range(101)], max_products=100, **kwargs)
    single = create_manifest([product(1), product(2)], max_products=1, **kwargs)
    assert len(full.selected_products) == 100
    assert len(single.selected_products) == 1


def test_malformed_feed_has_explicit_failure_reason() -> None:
    def handler(request):
        if request.url.path.endswith("/products/"):
            return httpx.Response(200, text="")
        if request.url.path.endswith("search-results"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, text="{")

    outcome = discover(handler)
    assert outcome.products == []
    assert outcome.source == "feed"
    assert outcome.reason == "malformed"


def test_login_search_response_is_skipped_and_the_feed_is_tried() -> None:
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if len(paths) == 1:
            return httpx.Response(200, text="")
        return httpx.Response(200, text="<form>Please sign in</form>")

    outcome = discover(handler)
    assert paths == [
        "/support/products/",
        "/api/web/support/search-results",
        "/api/web/feed/product",
    ]
    assert outcome.products == []
    assert outcome.reason == "protected"
    assert outcome.notes == ["listing: empty", "search: protected"]


def test_catalog_does_not_request_non_allowlisted_listing_url() -> None:
    paths = []

    def handler(request):
        paths.append(str(request.url))
        return httpx.Response(403)

    outcome = discover(handler, listing_url="https://evil.example/products")
    assert paths == [
        "https://my.opentext.com/api/web/support/search-results?start=1&maxResults=100&text=%2A",
        "https://my.opentext.com/api/web/feed/product",
    ]
    assert outcome.products == []
    assert outcome.reason == "protected"


@pytest.mark.parametrize("limit", [0, 101])
def test_settings_rejects_invalid_max_demo_products(limit: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_demo_products=limit)

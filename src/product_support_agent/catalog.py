from __future__ import annotations

import hashlib
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, HttpUrl

ALLOWED_SOURCE_HOST = "my.opentext.com"
MAX_DEMO_PRODUCTS = 100
LISTING_URL = "https://my.opentext.com/support/products/"
SEARCH_URL = "https://my.opentext.com/api/web/support/search-results"
FEED_URL = "https://my.opentext.com/api/web/feed/product"


class ProductReference(BaseModel):
    product_id: str
    name: str
    slug: str
    source_url: HttpUrl


class Manifest(BaseModel):
    manifest_version: str
    selection_method: str
    selected_products: list[ProductReference]
    selection_timestamp: str
    seed: str


class CatalogOutcome(BaseModel):
    source: str
    products: list[ProductReference]
    page_count: int
    reason: str | None = None


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def validate_source_url(
    url: str,
    *,
    allowed_host: str = ALLOWED_SOURCE_HOST,
) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == allowed_host
        and parsed.username is None
        and parsed.password is None
        and port is None
        and bool(parsed.path)
    )


def is_login_redirect(response: httpx.Response) -> bool:
    if response.status_code not in (301, 302, 303, 307, 308):
        return False
    location = response.headers.get("location")
    if not location:
        return True
    try:
        destination = urlparse(urljoin(str(response.url), location))
    except ValueError:
        return True
    return destination.hostname != ALLOWED_SOURCE_HOST or "login" in destination.path.lower()


def is_login_content(content: str) -> bool:
    lowered = content.lower()
    indicators = ("sign in", "log in", "login", "saml", "authentication required")
    return any(indicator in lowered for indicator in indicators)


def deduplicate_products(products: Iterable[ProductReference]) -> list[ProductReference]:
    deduplicated: dict[str, ProductReference] = {}
    for product in products:
        key = product.product_id.strip().lower()
        if key and key not in deduplicated:
            deduplicated[key] = product
    return [deduplicated[key] for key in sorted(deduplicated)]


def parse_feed(payload: Any) -> list[ProductReference]:
    if not isinstance(payload, list):
        if isinstance(payload, dict):
            payload = payload.get("products") or payload.get("items") or payload.get("data")
    if not isinstance(payload, list):
        return []

    products: list[ProductReference] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "").strip()
        slug = str(item.get("slug") or item.get("productCode") or "").strip()
        product_id = str(item.get("id") or item.get("productId") or slug).strip()
        if not name or not slug:
            continue
        source_url = f"https://{ALLOWED_SOURCE_HOST}/support/products/{slug}"
        if validate_source_url(source_url):
            products.append(
                ProductReference(
                    product_id=product_id,
                    name=name,
                    slug=slug,
                    source_url=HttpUrl(source_url),
                )
            )
    return deduplicate_products(products)


class CatalogClient:
    def __init__(
        self,
        *,
        client: httpx.AsyncBaseTransport | httpx.Client | None = None,
        listing_url: str = LISTING_URL,
        search_url: str = SEARCH_URL,
        feed_url: str = FEED_URL,
        max_pages: int = 20,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 4_194_304,
    ) -> None:
        self.client = client
        self.listing_url = listing_url
        self.search_url = search_url
        self.feed_url = feed_url
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    async def discover(self) -> CatalogOutcome:
        listing = await self._get_listing()
        if listing.products:
            return listing

        search = await self._get_search()
        if search.products:
            return search
        if search.reason and search.reason.startswith("protected"):
            return CatalogOutcome(
                source="feed",
                products=[],
                page_count=0,
                reason="search protected; fallback feed not used",
            )

        feed = await self._get_feed()
        if feed.products:
            return feed
        return CatalogOutcome(
            source="feed",
            products=[],
            page_count=feed.page_count,
            reason=feed.reason or "catalog empty",
        )

    async def _get_listing(self) -> CatalogOutcome:
        response = await self._bounded_get(self.listing_url)
        if response is None:
            return CatalogOutcome(
                source="listing", products=[], page_count=0, reason="request_failed"
            )
        if response.status_code in (401, 403) or is_login_redirect(response):
            return CatalogOutcome(source="listing", products=[], page_count=0, reason="protected")
        if response.status_code != 200:
            return CatalogOutcome(
                source="listing",
                products=[],
                page_count=0,
                reason=f"http_{response.status_code}",
            )
        text = response.text
        if is_login_content(text):
            return CatalogOutcome(source="listing", products=[], page_count=0, reason="protected")

        parser = AnchorParser()
        parser.feed(text)
        products: list[ProductReference] = []
        for href in parser.hrefs:
            absolute = urljoin(str(response.url), href)
            parsed = urlparse(absolute)
            if parsed.hostname != ALLOWED_SOURCE_HOST:
                continue
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 3 and parts[:2] == ["support", "products"]:
                slug = parts[2]
                if slug and not slug.startswith("index"):
                    source_url = f"https://{ALLOWED_SOURCE_HOST}/support/products/{slug}"
                    if validate_source_url(source_url):
                        products.append(
                            ProductReference(
                                product_id=slug,
                                name=slug,
                                slug=slug,
                                source_url=HttpUrl(source_url),
                            )
                        )
        return CatalogOutcome(
            source="listing",
            products=deduplicate_products(products),
            page_count=1,
            reason=None if products else "empty",
        )

    async def _get_search(self) -> CatalogOutcome:
        products: list[ProductReference] = []
        start = 1
        for page in range(1, self.max_pages + 1):
            response = await self._bounded_get(
                self.search_url,
                params={
                    "start": str(start),
                    "maxResults": "100",
                    "text": "*",
                },
            )
            if response is None:
                return CatalogOutcome(
                    source="search",
                    products=[],
                    page_count=page - 1,
                    reason="request_failed",
                )
            if response.status_code in (401, 403) or is_login_redirect(response):
                return CatalogOutcome(
                    source="search",
                    products=[],
                    page_count=page - 1,
                    reason="protected",
                )
            if response.status_code != 200:
                return CatalogOutcome(
                    source="search",
                    products=[],
                    page_count=page - 1,
                    reason=f"http_{response.status_code}",
                )
            if is_login_content(response.text):
                return CatalogOutcome(
                    source="search",
                    products=[],
                    page_count=page - 1,
                    reason="protected",
                )
            try:
                payload = response.json()
            except ValueError:
                return CatalogOutcome(
                    source="search",
                    products=[],
                    page_count=page - 1,
                    reason="malformed",
                )
            page_products = self._parse_search_payload(payload)
            if not page_products:
                break
            products.extend(page_products)
            if len(page_products) < 100:
                break
            next_start = start + len(page_products)
            if next_start <= start:
                break
            start = next_start
        result = deduplicate_products(products)
        return CatalogOutcome(
            source="search",
            products=result,
            page_count=min(page, self.max_pages),
            reason=None if result else "empty",
        )

    @staticmethod
    def _parse_search_payload(payload: Any) -> list[ProductReference]:
        if not isinstance(payload, dict):
            return []
        items = payload.get("results") or payload.get("items") or payload.get("data")
        if not isinstance(items, list):
            return []
        return parse_feed(items)

    async def _get_feed(self) -> CatalogOutcome:
        response = await self._bounded_get(self.feed_url)
        if response is None:
            return CatalogOutcome(source="feed", products=[], page_count=0, reason="request_failed")
        if response.status_code in (401, 403) or is_login_redirect(response):
            return CatalogOutcome(source="feed", products=[], page_count=0, reason="protected")
        if response.status_code != 200:
            return CatalogOutcome(
                source="feed",
                products=[],
                page_count=0,
                reason=f"http_{response.status_code}",
            )
        if is_login_content(response.text):
            return CatalogOutcome(source="feed", products=[], page_count=0, reason="protected")
        try:
            payload = response.json()
        except ValueError:
            return CatalogOutcome(source="feed", products=[], page_count=0, reason="malformed")
        products = parse_feed(payload)
        return CatalogOutcome(
            source="feed",
            products=products,
            page_count=1,
            reason=None if products else "empty",
        )

    async def _bounded_get(
        self,
        url: str,
        *,
        params: dict[str, str | int | float | bool | None] | None = None,
    ) -> httpx.Response | None:
        if not validate_source_url(url):
            return None
        if isinstance(self.client, httpx.Client):
            raise TypeError("CatalogClient requires an async httpx transport")
        transport = self.client
        async with httpx.AsyncClient(
            transport=transport,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.get(url, params=params)
                if len(response.content) > self.max_response_bytes:
                    return None
                return response
            except httpx.HTTPError:
                return None


def create_manifest(
    products: Iterable[ProductReference],
    *,
    manifest_version: str,
    seed: str,
    selection_timestamp: str,
    max_products: int = MAX_DEMO_PRODUCTS,
) -> Manifest:
    if max_products < 1 or max_products > MAX_DEMO_PRODUCTS:
        raise ValueError("max_products must be between 1 and 100")
    unique = deduplicate_products(products)
    if not unique:
        raise ValueError("cannot create a manifest from an empty catalog")
    selected = sorted(unique, key=lambda item: item.product_id)
    selected.sort(
        key=lambda item: hashlib.sha256(
            f"{manifest_version}:{seed}:{item.product_id}".encode()
        ).hexdigest()
    )
    selected = selected[: min(max_products, MAX_DEMO_PRODUCTS)]
    selected.sort(key=lambda item: item.product_id)
    return Manifest(
        manifest_version=manifest_version,
        selection_method="deterministic-random-v1",
        selected_products=selected,
        selection_timestamp=selection_timestamp,
        seed=seed,
    )

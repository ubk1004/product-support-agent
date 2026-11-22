import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from product_support_agent.document_store import InMemoryCanonicalDocumentRepository
from product_support_agent.documents import stable_document_id
from product_support_agent.fetch_state import (
    FetchStateRecord,
    FreshnessPolicy,
    InMemoryFetchStateStore,
    classify_failure,
    fetch_state_key,
)
from product_support_agent.http_fetch import BoundedFetcher
from product_support_agent.indexing import DocumentIndexingError, RepositoryOnlyIndexer
from product_support_agent.source_ingestion import SourceIngestionLimits, SourceIngestionWorker
from product_support_agent.sources import ProductSource, SourceMap

DOCS = "https://docs.microfocus.com"
ADM = "https://admhelp.microfocus.com"
START = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeSite:
    """Serves robots.txt, a docs-portal TOC, page JSON, and a sitemap; records every request."""

    def __init__(self, pages: int = 3) -> None:
        self.requests: list[str] = []
        self.headers: list[httpx.Headers] = []
        self.robots = "User-agent: *\nDisallow: */beta/*\n"
        self.robots_status = 200
        self.page_status: dict[str, int] = {}
        self.page_text: dict[str, str] = {}
        self.etags: dict[str, str] = {}
        self.toc_entries = [
            {"href": f"27/26.4/topic{i}", "revisionId": f"{i}00", "level": 2, "text": f"T{i}"}
            for i in range(pages)
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        self.headers.append(request.headers)
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(self.robots_status, text=self.robots)
        if path.endswith("/tocflat.json"):
            return httpx.Response(200, json={"Toc": {"tocFlat": self.toc_entries}})
        if path.endswith(".xml"):
            body = "".join(f"<url><loc>{ADM}/lr/en/26/help/p{i}.htm</loc></url>" for i in range(3))
            return httpx.Response(
                200,
                text=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
            )
        status = self.page_status.get(path, 200)
        if status == 429:
            return httpx.Response(429, headers={"retry-after": "3600"})
        if status != 200:
            return httpx.Response(status)
        etag = self.etags.get(path)
        if etag and request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        text = self.page_text.get(path, f"Documentation for {path}. " * 3)
        headers = {"etag": etag} if etag else {}
        if path.endswith(".json"):
            payload = {"parse": {"displaytitle": path, "text": {"*": f"<p>{text}</p>"}}}
            return httpx.Response(200, content=json.dumps(payload).encode(), headers=headers)
        return httpx.Response(
            200,
            text=f"<html><title>{path}</title><body><p>{text}</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8", **headers},
        )

    def page_requests(self) -> list[str]:
        return [url for url in self.requests if "/default-" in url or url.endswith(".htm")]


def toc_source(**overrides) -> ProductSource:
    values = {
        "product_id": "1167",
        "product_name": "iPrint",
        "kind": "docs_portal_toc",
        "seed_url": f"{DOCS}/27/26.4/tocflat.json",
        "max_pages": 30,
    }
    values.update(overrides)
    return ProductSource(**values)


def sitemap_source() -> ProductSource:
    return ProductSource(
        product_id="1185",
        product_name="LoadRunner Professional",
        kind="sitemap",
        seed_url=f"{ADM}/lr/sitemaps/LR_sitemap.xml",
    )


class Harness:
    def __init__(self, *sources: ProductSource, site: FakeSite | None = None, **limits) -> None:
        self.site = site or FakeSite()
        self.clock = Clock()
        self.state = InMemoryFetchStateStore()
        self.repository = InMemoryCanonicalDocumentRepository()
        self.sleeps: list[float] = []
        self.sources = sources or (toc_source(),)
        self.limits = SourceIngestionLimits(**{"min_request_interval_seconds": 1.0, **limits})

    def worker(self, *, indexer=None, sources=None) -> SourceIngestionWorker:
        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        return SourceIngestionWorker(
            source_map=SourceMap(
                schema_version="1",
                source_map_version="test-v1",
                manifest_version="manifest-v1",
                sources=tuple(sources or self.sources),
            ),
            state=self.state,
            fetcher=BoundedFetcher(
                transport=httpx.MockTransport(self.site.handler),
                max_retry_after_seconds=60,
            ),
            indexer=indexer or RepositoryOnlyIndexer(repository=self.repository),
            repository=self.repository,
            limits=self.limits,
            clock=self.clock,
            sleep=sleep,
            monotonic=lambda: 0.0,
        )

    def run(self, **options):
        indexer = options.pop("indexer", None)
        sources = options.pop("sources", None)
        return asyncio.run(self.worker(indexer=indexer, sources=sources).run(**options))


def test_first_run_indexes_pages_with_citation_urls_and_records_state() -> None:
    harness = Harness()
    report = harness.run()

    product = report.products[0]
    assert (product.outcome, product.pages_selected, product.pages_indexed) == ("completed", 3, 3)
    assert harness.site.requests[:2] == [f"{DOCS}/robots.txt", f"{DOCS}/27/26.4/tocflat.json"]
    assert harness.site.page_requests() == [
        f"{DOCS}/27/26.4/topic{i}/default-{i}00.json" for i in range(3)
    ]
    document_ids = set(harness.repository.list_document_ids())
    assert document_ids == {
        stable_document_id("1167", f"{DOCS}/doc/27/26.4/topic{i}") for i in range(3)
    }
    stored, _ = harness.repository.get_document(sorted(document_ids)[0])
    assert str(stored.source_url).startswith(f"{DOCS}/doc/27/26.4/")
    assert stored.fetched_at == START
    assert report.requests == 5
    assert harness.sleeps == [1.0] * 4


def test_rerun_within_a_day_makes_no_requests_after_restart() -> None:
    harness = Harness()
    harness.run()
    harness.site.requests.clear()
    harness.clock.advance(hours=23)

    report = harness.run()

    assert harness.site.requests == []
    assert report.products[0].outcome == "skipped_fresh"
    assert report.products[0].pages_skipped_fresh == 3


def test_interrupted_run_resumes_with_remaining_pages_only() -> None:
    harness = Harness(request_budget=4)
    first = harness.run()
    assert first.stopped_reason == "request_budget_exhausted"
    assert len(harness.site.page_requests()) == 2

    harness.site.requests.clear()
    harness.limits.request_budget = 400
    harness.clock.advance(minutes=5)
    second = harness.run()

    assert harness.site.page_requests() == [f"{DOCS}/27/26.4/topic2/default-200.json"]
    assert second.products[0].pages_skipped_fresh == 2
    assert second.products[0].pages_indexed == 1


def test_lost_state_write_is_recovered_from_document_fetched_at() -> None:
    harness = Harness()
    harness.run()
    harness.state.records.clear()
    harness.site.requests.clear()
    harness.clock.advance(hours=2)

    report = harness.run()

    assert harness.site.page_requests() == []
    assert report.products[0].pages_skipped_fresh == 3
    record = harness.state.get(fetch_state_key("1167", f"{DOCS}/doc/27/26.4/topic0"))
    assert record is not None and record.reason_category == "recovered_from_document_store"


def test_weekly_run_skips_unchanged_revisions_and_refetches_changed_ones() -> None:
    harness = Harness()
    harness.run()
    harness.site.requests.clear()
    harness.site.toc_entries[1]["revisionId"] = "101"
    harness.clock.advance(days=7)

    report = harness.run()

    assert harness.site.page_requests() == [f"{DOCS}/27/26.4/topic1/default-101.json"]
    assert (report.products[0].pages_unchanged, report.products[0].pages_indexed) == (2, 1)


def test_conditional_get_uses_etag_and_counts_not_modified() -> None:
    site = FakeSite()
    harness = Harness(sitemap_source(), site=site)
    site.etags = {f"/lr/en/26/help/p{i}.htm": f'"e{i}"' for i in range(3)}
    harness.run()
    harness.clock.advance(days=7)
    site.headers.clear()

    report = harness.run()

    page_headers = [h for h in site.headers if h.get("if-none-match")]
    assert [h["if-none-match"] for h in page_headers] == ['"e0"', '"e1"', '"e2"']
    assert report.products[0].pages_unchanged == 3


def test_unchanged_body_does_not_reindex() -> None:
    harness = Harness(sitemap_source())
    harness.run()
    harness.clock.advance(days=7)

    class CountingIndexer(RepositoryOnlyIndexer):
        calls = 0

        async def index_html(self, *args, **kwargs):
            CountingIndexer.calls += 1
            return await super().index_html(*args, **kwargs)

    report = harness.run(indexer=CountingIndexer(repository=harness.repository))
    assert CountingIndexer.calls == 0
    assert report.products[0].pages_unchanged == 3


def test_product_fails_fast_after_consecutive_page_failures_and_backs_off() -> None:
    site = FakeSite(pages=6)
    site.page_status = {f"/27/26.4/topic{i}/default-{i}00.json": 404 for i in range(6)}
    harness = Harness(site=site, fail_fast_consecutive_failures=3)

    report = harness.run()

    product = report.products[0]
    assert (product.outcome, product.reason_category) == (
        "failed_fast",
        "consecutive_permanent_page_failures",
    )
    assert len(site.page_requests()) == 3

    site.requests.clear()
    harness.clock.advance(days=7)
    again = harness.run()
    assert site.requests == []
    assert again.products[0].outcome == "failed_fast"
    assert again.products[0].reason_category == "consecutive_permanent_page_failures"


def test_transient_fail_fast_retries_after_a_day() -> None:
    site = FakeSite(pages=4)
    site.page_status = {f"/27/26.4/topic{i}/default-{i}00.json": 503 for i in range(4)}
    harness = Harness(site=site, fail_fast_consecutive_failures=2, page_max_attempts=1)

    report = harness.run()
    assert report.products[0].reason_category == "consecutive_page_failures"
    assert len(site.page_requests()) == 2

    site.page_status = {}
    site.requests.clear()
    harness.clock.advance(hours=25)
    again = harness.run()
    assert again.products[0].pages_indexed == 4


def test_protected_pages_are_skipped_without_storing_content() -> None:
    site = FakeSite(pages=1)
    site.page_text = {"/27/26.4/topic0/default-000.json": "<form>Please sign in</form>"}
    harness = Harness(site=site)

    report = harness.run()

    assert report.products[0].pages[0].reason_category == "protected_login_content"
    assert report.products[0].pages[0].outcome == "skipped"
    assert harness.repository.list_document_ids() == []


def test_rate_limit_aborts_the_host_for_the_run_and_other_hosts_continue() -> None:
    site = FakeSite()
    site.page_status = {"/27/26.4/topic0/default-000.json": 429}
    harness = Harness(
        toc_source(),
        toc_source(product_id="1220", product_name="APLS"),
        sitemap_source(),
        site=site,
    )

    report = harness.run()

    outcomes = {product.product_id: product.outcome for product in report.products}
    assert outcomes == {"1167": "failed_fast", "1220": "failed_fast", "1185": "completed"}
    assert report.products[1].reason_category == "host_aborted_rate_limited"
    assert all(not url.startswith(f"{DOCS}/27/26.4/topic1") for url in site.requests)


def test_unavailable_robots_fails_closed_for_the_host() -> None:
    site = FakeSite()
    site.robots_status = 503
    harness = Harness(site=site)

    report = harness.run()

    assert report.products[0].reason_category == "host_aborted_robots_unavailable"
    assert site.requests == [f"{DOCS}/robots.txt"]
    assert harness.repository.list_document_ids() == []


def test_robots_disallowed_pages_are_never_requested() -> None:
    site = FakeSite()
    site.robots = "User-agent: *\nDisallow: /doc/27/26.4/topic1\nDisallow: /27/26.4/topic2/\n"
    harness = Harness(site=site)

    report = harness.run()

    assert site.page_requests() == [f"{DOCS}/27/26.4/topic0/default-000.json"]
    assert report.products[0].pages_robots_excluded == 2


def test_seed_failure_is_backed_off_and_reported() -> None:
    harness = Harness(toc_source(seed_url=f"{DOCS}/2263/26.4/tocflat.json"))
    harness.site.handler_original = harness.site.handler

    def handler(request):
        if request.url.path == "/2263/26.4/tocflat.json":
            harness.site.requests.append(str(request.url))
            return httpx.Response(403)
        return harness.site.handler_original(request)

    harness.site.handler = handler
    report = harness.run()
    assert (report.products[0].outcome, report.products[0].reason_category) == (
        "failed_fast",
        "protected_403",
    )
    harness.site.requests.clear()
    harness.clock.advance(days=7)
    harness.run()
    assert harness.site.requests == []


def test_pages_removed_from_selection_are_deleted() -> None:
    harness = Harness()
    harness.run()
    harness.clock.advance(days=2)
    narrowed = toc_source(max_pages=1)

    report = harness.run(sources=[narrowed])

    assert report.products[0].pages_removed == 2
    assert harness.repository.list_document_ids() == [
        stable_document_id("1167", f"{DOCS}/doc/27/26.4/topic0")
    ]


def test_indexing_failure_is_transient_and_retried_next_run() -> None:
    harness = Harness()

    class FailingIndexer(RepositoryOnlyIndexer):
        async def index_html(self, *args, **kwargs):
            raise DocumentIndexingError("embedding offline")

    first = harness.run(indexer=FailingIndexer(repository=harness.repository))
    assert first.products[0].pages_failed == 3
    assert first.products[0].reason_category == "consecutive_page_failures"

    harness.clock.advance(days=2)
    harness.site.requests.clear()
    second = harness.run()
    assert second.products[0].pages_indexed == 3


def test_force_ignores_freshness_and_discover_only_fetches_no_pages() -> None:
    harness = Harness()
    harness.run()
    harness.site.requests.clear()

    harness.run(force=True)
    assert len(harness.site.page_requests()) == 3

    harness.site.requests.clear()
    report = harness.run(force=True, discover_only=True)
    assert harness.site.page_requests() == []
    assert report.products[0].reason_category == "discovered_only"
    assert report.products[0].pages_selected == 3


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("protected_403", "permanent"),
        ("robots_disallowed", "permanent"),
        ("http_404", "permanent"),
        ("http_307", "permanent"),
        ("server_error", "transient"),
        ("network_error", "transient"),
        ("rate_limited", "transient"),
        ("indexing_failed", "transient"),
    ],
)
def test_failure_classification(reason, kind) -> None:
    assert classify_failure(reason) == kind


def test_transient_backoff_grows_and_is_capped() -> None:
    policy = FreshnessPolicy()
    base = {
        "key": "k",
        "product_id": "p",
        "kind": "page",
        "fetch_url": f"{DOCS}/a",
        "citation_url": f"{DOCS}/a",
        "reason_category": "server_error",
    }
    record: FetchStateRecord | None = None
    delays = []
    for _ in range(5):
        record = policy.after_failure(record, base=base, now=START)
        delays.append(record.next_eligible_at - START)
    assert delays == [
        timedelta(days=1),
        timedelta(days=2),
        timedelta(days=4),
        timedelta(days=7),
        timedelta(days=7),
    ]


def test_run_lease_blocks_concurrent_runs_until_expiry() -> None:
    store = InMemoryFetchStateStore()
    ttl = timedelta(hours=6)
    assert store.acquire_lease("ingest", "a", now=START, ttl=ttl)
    assert not store.acquire_lease("ingest", "b", now=START + timedelta(hours=1), ttl=ttl)
    assert store.acquire_lease("ingest", "b", now=START + timedelta(hours=7), ttl=ttl)
    store.release_lease("ingest", "a")
    assert not store.acquire_lease("ingest", "a", now=START + timedelta(hours=8), ttl=ttl)
    store.release_lease("ingest", "b")
    assert store.acquire_lease("ingest", "a", now=START + timedelta(hours=8), ttl=ttl)

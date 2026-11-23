from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, HttpUrl

from product_support_agent.catalog import (
    ProductReference,
    is_login_content,
    validate_source_url,
)
from product_support_agent.document_store import CanonicalDocumentRepository
from product_support_agent.documents import (
    CanonicalDocument,
    DocumentNormalizationError,
    stable_document_id,
)
from product_support_agent.fetch_state import (
    DiscoveredPage,
    FetchStateRecord,
    FetchStateStore,
    FreshnessPolicy,
    classify_failure,
    fetch_state_key,
)
from product_support_agent.http_fetch import BoundedFetcher, FetchResponse
from product_support_agent.indexing import DocumentIndexingError
from product_support_agent.robots import RobotsPolicy, policy_for_status
from product_support_agent.sources import (
    DiscoveryError,
    PageCandidate,
    ProductSource,
    SourceMap,
    discover_pages,
    extract_page,
    robots_url_for,
    select_pages,
)

PageOutcome = Literal["indexed", "unchanged", "not_modified", "skipped", "failed"]
ProductOutcome = Literal[
    "completed", "partial", "failed", "failed_fast", "skipped_fresh", "budget_exhausted"
]


class SourceDocumentIndexer(Protocol):
    async def index_html(
        self,
        source: ProductReference,
        body: bytes,
        content_type: str,
        *,
        fetched_at: datetime | None = None,
    ) -> CanonicalDocument: ...

    async def delete_document(self, document_id: str) -> None: ...


class PageResult(BaseModel):
    citation_url: str
    outcome: PageOutcome
    reason_category: str
    http_status: int | None = None


class ProductRunResult(BaseModel):
    product_id: str
    product_name: str
    outcome: ProductOutcome
    reason_category: str
    pages_selected: int = 0
    pages_indexed: int = 0
    pages_unchanged: int = 0
    pages_skipped_fresh: int = 0
    pages_failed: int = 0
    pages_removed: int = 0
    pages_robots_excluded: int = 0
    requests: int = 0
    pages: list[PageResult] = []


class SourceRunReport(BaseModel):
    source_map_version: str
    manifest_version: str
    started_at: datetime
    finished_at: datetime | None = None
    requests: int = 0
    request_budget: int
    stopped_reason: str | None = None
    products: list[ProductRunResult] = []


@dataclass
class SourceIngestionLimits:
    request_budget: int = 400
    min_request_interval_seconds: float = 1.0
    fail_fast_consecutive_failures: int = 3
    page_max_attempts: int = 2


class _HostAbort(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _BudgetExhausted(Exception):
    pass


@dataclass
class RunContext:
    report: SourceRunReport
    robots: dict[str, RobotsPolicy] = field(default_factory=dict)
    last_request_at: dict[str, float] = field(default_factory=dict)
    aborted_hosts: dict[str, str] = field(default_factory=dict)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def source_config_hash(source: ProductSource) -> str:
    return _sha256(source.model_dump_json().encode())


class SourceIngestionWorker:
    """Periodic, resumable ingestion of approved documentation sources.

    Durable per-URL fetch state (not the run log) decides what to fetch, and it is written
    after every request, so a restart skips URLs that succeeded within the freshness window.
    If a state write was lost, the canonical document's `fetched_at` is a second guard.
    Products fail fast after consecutive page failures and are then backed off as a unit; a
    host is abandoned for the run on rate limiting or an unavailable robots.txt.
    """

    def __init__(
        self,
        *,
        source_map: SourceMap,
        state: FetchStateStore,
        fetcher: BoundedFetcher,
        indexer: SourceDocumentIndexer,
        repository: CanonicalDocumentRepository | None = None,
        policy: FreshnessPolicy | None = None,
        limits: SourceIngestionLimits | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.source_map = source_map
        self.state = state
        self.fetcher = fetcher
        self.indexer = indexer
        self.repository = repository
        self.policy = policy or FreshnessPolicy()
        self.limits = limits or SourceIngestionLimits()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleep = sleep or asyncio.sleep
        self.monotonic = monotonic or time.monotonic
        self._force = False
        self._discover_only = False

    async def run(
        self,
        product_ids: Sequence[str] | None = None,
        *,
        force: bool = False,
        discover_only: bool = False,
    ) -> SourceRunReport:
        """Process enabled sources.

        `force` ignores freshness and backoff (use after a reset). `discover_only` fetches
        robots.txt and seeds and reports the page selection without fetching pages.
        """
        wanted = set(product_ids) if product_ids else None
        context = self.begin()
        for source in self.source_map.enabled_sources():
            if wanted is not None and source.product_id not in wanted:
                continue
            result = await self.process_source(
                source, context, force=force, discover_only=discover_only
            )
            if result.outcome == "budget_exhausted":
                context.report.stopped_reason = "request_budget_exhausted"
                break
        context.report.finished_at = self.clock()
        return context.report

    def begin(self) -> RunContext:
        """Start a run. One context shares the request budget, robots.txt cache, and per-host
        request spacing across every product processed with it, including products handed over
        one at a time from a queue."""
        return RunContext(
            report=SourceRunReport(
                source_map_version=self.source_map.source_map_version,
                manifest_version=self.source_map.manifest_version,
                started_at=self.clock(),
                request_budget=self.limits.request_budget,
            )
        )

    async def process_source(
        self,
        source: ProductSource,
        context: RunContext,
        *,
        force: bool = False,
        discover_only: bool = False,
    ) -> ProductRunResult:
        """Ingest exactly one product and append its result to the context's report."""
        self._force = force
        self._discover_only = discover_only
        result = await self._run_product(source, context)
        context.report.products.append(result)
        return result

    async def _run_product(self, source: ProductSource, context: RunContext) -> ProductRunResult:
        result = ProductRunResult(
            product_id=source.product_id,
            product_name=source.product_name,
            outcome="completed",
            reason_category="ok",
        )
        host = urlparse(source.seed_url).hostname or ""
        if host in context.aborted_hosts:
            result.outcome = "failed_fast"
            result.reason_category = f"host_aborted_{context.aborted_hosts[host]}"
            return result

        product_key = self._product_key(source)
        product_record = self.state.get(product_key)
        if (
            not self._force
            and self.policy.skip_reason(product_record, now=self.clock()) == "failure_backoff"
        ):
            result.outcome = "failed_fast"
            result.reason_category = (
                product_record.reason_category if product_record else "failure_backoff"
            )
            return result

        requests_before = context.report.requests
        try:
            candidates = await self._discover(source, context)
            if candidates is None:
                result.outcome = "failed_fast"
                seed_record = self.state.get(fetch_state_key(source.product_id, source.seed_url))
                result.reason_category = (
                    seed_record.reason_category if seed_record else "discovery_failed"
                )
                return result
            allowed: list[PageCandidate] = []
            for candidate in candidates:
                if self._discover_only and not await self._robots_allows(candidate, context):
                    result.pages_robots_excluded += 1
                else:
                    allowed.append(candidate)
            selected = select_pages(allowed, source)
            result.pages_selected = len(selected)
            if self._discover_only:
                result.reason_category = "discovered_only"
                result.pages = [
                    PageResult(
                        citation_url=page.citation_url,
                        outcome="skipped",
                        reason_category="discover_only",
                    )
                    for page in selected
                ]
                return result
            await self._ingest_pages(source, selected, context, result)
            if result.outcome == "completed" and selected:
                await self._remove_unselected(source, selected, result)
        except _BudgetExhausted:
            result.outcome = "budget_exhausted"
            result.reason_category = "request_budget_exhausted"
        except _HostAbort as abort:
            context.aborted_hosts[host] = abort.reason
            result.outcome = "failed_fast"
            result.reason_category = f"host_aborted_{abort.reason}"
        finally:
            result.requests = context.report.requests - requests_before

        if result.reason_category.startswith("consecutive_"):
            self._record_failure(
                product_record,
                {
                    "key": product_key,
                    "product_id": source.product_id,
                    "kind": "product",
                    "fetch_url": source.seed_url,
                    "citation_url": source.seed_url,
                    "source_map_version": self.source_map.source_map_version,
                },
                result.reason_category,
                self.clock(),
            )
        if result.pages_robots_excluded and not self._discover_only:
            result.pages_selected -= result.pages_robots_excluded
        if result.outcome == "completed":
            if not result.pages_selected:
                result.outcome, result.reason_category = "failed_fast", "robots_excluded_all"
            elif result.pages_failed and (result.pages_indexed or result.pages_unchanged):
                result.outcome, result.reason_category = "partial", "some_pages_failed"
            elif result.pages_failed and not result.pages_skipped_fresh:
                result.outcome, result.reason_category = "failed", "all_pages_failed"
            elif result.pages_selected and result.pages_skipped_fresh == result.pages_selected:
                result.outcome, result.reason_category = "skipped_fresh", "recently_fetched"
        return result

    async def _discover(
        self,
        source: ProductSource,
        context: RunContext,
    ) -> list[PageCandidate] | None:
        key = fetch_state_key(source.product_id, source.seed_url)
        previous = self.state.get(key)
        now = self.clock()
        config_hash = source_config_hash(source)
        skip = None if self._force else self.policy.skip_reason(previous, now=now)
        if (
            skip == "recently_fetched"
            and previous is not None
            and previous.discovered_pages is not None
            and previous.source_config_hash == config_hash
        ):
            return [
                PageCandidate(page.fetch_url, page.citation_url, page.title, page.revision)
                for page in previous.discovered_pages
            ]
        if skip == "failure_backoff":
            return None

        headers = self._conditional_headers(previous)
        response = await self._request(source.seed_url, context, headers=headers, json_like=True)
        base = {**self._seed_base(source), "http_status": response.http_status}
        if response.outcome == "not_modified" and previous and previous.discovered_pages:
            if previous.source_config_hash == config_hash:
                self.state.put(
                    self.policy.after_success(
                        previous,
                        base={**base, "reason_category": "not_modified"},
                        now=now,
                        outcome="not_modified",
                    )
                )
                return [
                    PageCandidate(page.fetch_url, page.citation_url, page.title, page.revision)
                    for page in previous.discovered_pages
                ]
            response = await self._request(source.seed_url, context, json_like=True)
        if response.outcome != "success":
            self._record_failure(previous, base, response.reason_category, now)
            self._raise_if_host_failure(response)
            return None
        try:
            candidates = discover_pages(response.body, source)
        except DiscoveryError:
            self._record_failure(previous, base, "discovery_malformed", now)
            return None
        if not candidates:
            self._record_failure(previous, base, "discovery_empty", now)
            return None
        self.state.put(
            self.policy.after_success(
                previous,
                base={
                    **base,
                    "reason_category": "discovered",
                    "etag": response.etag,
                    "last_modified": response.last_modified,
                    "body_hash": _sha256(response.body),
                    "discovered_pages": [
                        DiscoveredPage(
                            fetch_url=item.fetch_url,
                            citation_url=item.citation_url,
                            title=item.title,
                            revision=item.revision,
                        )
                        for item in candidates
                    ],
                },
                now=now,
                outcome="discovered",
            )
        )
        return candidates

    @staticmethod
    def _product_key(source: ProductSource) -> str:
        return fetch_state_key(source.product_id, f"product:{source.seed_url}")

    def _seed_base(self, source: ProductSource) -> dict[str, Any]:
        return {
            "key": fetch_state_key(source.product_id, source.seed_url),
            "product_id": source.product_id,
            "kind": "seed",
            "fetch_url": source.seed_url,
            "citation_url": source.seed_url,
            "source_map_version": self.source_map.source_map_version,
            "source_config_hash": source_config_hash(source),
        }

    async def _robots_allows(self, candidate: PageCandidate, context: RunContext) -> bool:
        for url in dict.fromkeys((candidate.fetch_url, candidate.citation_url)):
            if not (await self._robots(url, context)).is_allowed(url):
                return False
        return True

    async def _remove_unselected(
        self,
        source: ProductSource,
        selected: Sequence[PageCandidate],
        result: ProductRunResult,
    ) -> None:
        """Delete documents for pages that left the approved selection (moved, capped, removed)."""
        keep = {page.citation_url for page in selected}
        now = self.clock()
        for record in self.state.list_for_product(source.product_id):
            if record.kind != "page" or record.citation_url in keep or not record.document_id:
                continue
            await self.indexer.delete_document(record.document_id)
            self.state.put(
                record.model_copy(
                    update={
                        "last_outcome": "removed",
                        "reason_category": "not_in_selection",
                        "last_attempt_at": now,
                        "last_success_at": None,
                        "next_eligible_at": None,
                        "document_id": None,
                        "body_hash": None,
                        "etag": None,
                        "last_modified": None,
                    }
                )
            )
            result.pages_removed += 1

    async def _ingest_pages(
        self,
        source: ProductSource,
        pages: Sequence[PageCandidate],
        context: RunContext,
        result: ProductRunResult,
    ) -> None:
        consecutive_failures = 0
        streak_permanent = True
        for page in pages:
            page_result = await self._ingest_page(source, page, context)
            result.pages.append(page_result)
            if page_result.outcome == "indexed":
                result.pages_indexed += 1
            elif page_result.outcome in ("unchanged", "not_modified"):
                result.pages_unchanged += 1
            elif page_result.reason_category in ("recently_fetched", "failure_backoff"):
                result.pages_skipped_fresh += 1
            elif page_result.reason_category == "robots_disallowed":
                result.pages_robots_excluded += 1
                continue
            else:
                result.pages_failed += 1

            if page_result.outcome == "failed" or (
                page_result.outcome == "skipped"
                and page_result.reason_category not in ("recently_fetched", "failure_backoff")
            ):
                consecutive_failures += 1
                streak_permanent = streak_permanent and (
                    classify_failure(page_result.reason_category) == "permanent"
                )
            elif page_result.reason_category != "failure_backoff":
                consecutive_failures = 0
                streak_permanent = True
            if consecutive_failures >= self.limits.fail_fast_consecutive_failures:
                result.outcome = "failed_fast"
                result.reason_category = (
                    "consecutive_permanent_page_failures"
                    if streak_permanent
                    else "consecutive_page_failures"
                )
                return

    async def _ingest_page(
        self,
        source: ProductSource,
        page: PageCandidate,
        context: RunContext,
    ) -> PageResult:
        key = fetch_state_key(source.product_id, page.citation_url)
        previous = self.state.get(key)
        now = self.clock()
        skip = (
            None
            if self._force
            else self.policy.skip_reason(previous, now=now, revision=page.revision)
        )
        if skip is None and not self._force and (previous is None or not previous.last_success_at):
            skip = await self._recently_indexed(source, page, now)
        if skip in ("recently_fetched", "failure_backoff"):
            return PageResult(
                citation_url=page.citation_url,
                outcome="skipped",
                reason_category=skip,
            )
        base: dict[str, Any] = {
            "key": key,
            "product_id": source.product_id,
            "kind": "page",
            "fetch_url": page.fetch_url,
            "citation_url": page.citation_url,
            "revision": page.revision,
            "source_map_version": self.source_map.source_map_version,
        }
        if skip == "unchanged_revision":
            self.state.put(
                self.policy.after_success(
                    previous,
                    base={**base, "reason_category": "unchanged_revision"},
                    now=now,
                    outcome="unchanged",
                )
            )
            return PageResult(
                citation_url=page.citation_url,
                outcome="unchanged",
                reason_category="unchanged_revision",
            )

        if not await self._robots_allows(page, context):
            self._record_failure(previous, base, "robots_disallowed", now)
            return PageResult(
                citation_url=page.citation_url,
                outcome="skipped",
                reason_category="robots_disallowed",
            )
        response = await self._request(
            page.fetch_url,
            context,
            headers=self._conditional_headers(previous),
            json_like=source.kind == "docs_portal_toc",
        )
        base["http_status"] = response.http_status
        if response.outcome == "not_modified":
            self.state.put(
                self.policy.after_success(
                    previous,
                    base={**base, "reason_category": "not_modified"},
                    now=now,
                    outcome="not_modified",
                )
            )
            return PageResult(
                citation_url=page.citation_url,
                outcome="not_modified",
                reason_category="not_modified",
                http_status=304,
            )
        if response.outcome != "success":
            self._record_failure(previous, base, response.reason_category, now)
            self._raise_if_host_failure(response)
            outcome: PageOutcome = (
                "skipped" if classify_failure(response.reason_category) == "permanent" else "failed"
            )
            return PageResult(
                citation_url=page.citation_url,
                outcome=outcome,
                reason_category=response.reason_category,
                http_status=response.http_status,
            )

        body_hash = _sha256(response.body)
        base.update(
            etag=response.etag,
            last_modified=response.last_modified,
            body_hash=body_hash,
        )
        if previous is not None and previous.body_hash == body_hash and previous.document_id:
            self.state.put(
                self.policy.after_success(
                    previous,
                    base={**base, "reason_category": "unchanged_body"},
                    now=now,
                    outcome="unchanged",
                )
            )
            return PageResult(
                citation_url=page.citation_url,
                outcome="unchanged",
                reason_category="unchanged_body",
                http_status=response.http_status,
            )

        reason, document_id = await self._index(source, page, response, now)
        if document_id is None:
            self._record_failure(previous, base, reason, now)
            return PageResult(
                citation_url=page.citation_url,
                outcome="skipped" if classify_failure(reason) == "permanent" else "failed",
                reason_category=reason,
                http_status=response.http_status,
            )
        self.state.put(
            self.policy.after_success(
                previous,
                base={**base, "reason_category": reason, "document_id": document_id},
                now=now,
                outcome="indexed",
            )
        )
        return PageResult(
            citation_url=page.citation_url,
            outcome="indexed",
            reason_category=reason,
            http_status=response.http_status,
        )

    async def _recently_indexed(
        self,
        source: ProductSource,
        page: PageCandidate,
        now: datetime,
    ) -> str | None:
        """Fallback guard when the state write for a successful fetch was lost."""
        if self.repository is None:
            return None
        document_id = stable_document_id(source.product_id, page.citation_url)
        record = await asyncio.to_thread(self.repository.get_document, document_id)
        if record is None or record[0].fetched_at is None:
            return None
        fetched_at = record[0].fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        if now - fetched_at >= self.policy.success_freshness:
            return None
        self.state.put(
            FetchStateRecord(
                key=fetch_state_key(source.product_id, page.citation_url),
                product_id=source.product_id,
                kind="page",
                fetch_url=page.fetch_url,
                citation_url=page.citation_url,
                last_outcome="indexed",
                reason_category="recovered_from_document_store",
                last_attempt_at=fetched_at,
                last_success_at=fetched_at,
                revision=page.revision,
                document_id=document_id,
                source_map_version=self.source_map.source_map_version,
            )
        )
        return "recently_fetched"

    async def _index(
        self,
        source: ProductSource,
        page: PageCandidate,
        response: FetchResponse,
        now: datetime,
    ) -> tuple[str, str | None]:
        try:
            extracted = extract_page(source, page, response.body, response.content_type)
        except DiscoveryError:
            return "normalization_failed", None
        if source.kind == "docs_portal_toc" and is_login_content(
            extracted.body.decode("utf-8", errors="replace")
        ):
            return "protected_login_content", None
        reference = ProductReference(
            product_id=source.product_id,
            name=source.product_name,
            slug=urlparse(page.citation_url).path.rstrip("/").rsplit("/", 1)[-1] or "page",
            source_url=HttpUrl(page.citation_url),
        )
        try:
            document = await self.indexer.index_html(
                reference,
                extracted.body,
                extracted.content_type,
                fetched_at=now,
            )
        except DocumentNormalizationError:
            return "normalization_failed", None
        except DocumentIndexingError:
            return "indexing_failed", None
        return "indexed", document.document_id

    async def _request(
        self,
        url: str,
        context: RunContext,
        *,
        headers: dict[str, str] | None = None,
        json_like: bool = False,
    ) -> FetchResponse:
        host = urlparse(url).hostname or ""
        if host in context.aborted_hosts:
            raise _HostAbort(context.aborted_hosts[host])
        if not validate_source_url(url):
            return FetchResponse("skipped", "invalid_url", None, 0)
        robots = await self._robots(url, context)
        if not robots.is_allowed(url):
            return FetchResponse("skipped", "robots_disallowed", None, 0)
        await self._reserve_request(host, context)
        response = await self.fetcher.get(
            url,
            headers=headers,
            check_login_content=not json_like,
            max_attempts=self.limits.page_max_attempts,
        )
        context.report.requests += max(response.attempt_count - 1, 0)
        return response

    async def _robots(self, url: str, context: RunContext) -> RobotsPolicy:
        host = urlparse(url).hostname or ""
        cached = context.robots.get(host)
        if cached is not None:
            return cached
        robots_url = robots_url_for(url)
        await self._reserve_request(host, context)
        response = await self.fetcher.get(robots_url, check_login_content=False, max_attempts=1)
        if response.outcome == "success":
            text = response.body.decode("utf-8", errors="replace")
            policy = policy_for_status(response.http_status or 200, text)
        elif response.http_status is not None and response.http_status < 500:
            policy = policy_for_status(response.http_status, "")
        else:
            context.aborted_hosts[host] = "robots_unavailable"
            raise _HostAbort("robots_unavailable")
        context.robots[host] = policy
        return policy

    async def _reserve_request(self, host: str, context: RunContext) -> None:
        if context.report.requests >= self.limits.request_budget:
            raise _BudgetExhausted
        last = context.last_request_at.get(host)
        if last is not None:
            wait = self.limits.min_request_interval_seconds - (self.monotonic() - last)
            if wait > 0:
                await self.sleep(wait)
        context.last_request_at[host] = self.monotonic()
        context.report.requests += 1

    def _record_failure(
        self,
        previous: FetchStateRecord | None,
        base: dict[str, Any],
        reason: str,
        now: datetime,
    ) -> None:
        self.state.put(
            self.policy.after_failure(previous, base={**base, "reason_category": reason}, now=now)
        )

    @staticmethod
    def _raise_if_host_failure(response: FetchResponse) -> None:
        if response.reason_category in ("rate_limited", "retry_limit") and (
            response.http_status == 429
        ):
            raise _HostAbort("rate_limited")

    @staticmethod
    def _conditional_headers(previous: FetchStateRecord | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if previous is None or previous.last_success_at is None:
            return headers
        if previous.etag:
            headers["if-none-match"] = previous.etag
        if previous.last_modified:
            headers["if-modified-since"] = previous.last_modified
        return headers

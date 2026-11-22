import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from product_support_agent.queue import InMemoryQueue, QueueMessage
from product_support_agent.store import IngestionRun, InMemoryIngestionStore, ProductIngestionStatus
from product_support_agent.worker import IngestionWorker


def setup_worker(handler, *, dequeue_count=1, **options):
    queue = InMemoryQueue()
    queue.send_product_reference(
        "run-1", "product-a", "https://my.opentext.com/support/products/product-a"
    )
    original = queue.messages[0]
    queue.messages[0] = QueueMessage(
        message_id=original.message_id,
        dequeue_count=dequeue_count,
        pop_receipt=original.pop_receipt,
        payload=original.payload,
    )
    store = InMemoryIngestionStore()
    store.start_run(IngestionRun(run_id="run-1", manifest_version="v1", started_at="start"))
    worker = IngestionWorker(
        queue=queue, store=store, http_client=httpx.MockTransport(handler), **options
    )
    return worker, queue, store


def test_worker_uses_message_source_url_and_records_original_product_id() -> None:
    source_url = "https://my.opentext.com/support/products/analytics-database"
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text="Public documentation")

    queue = InMemoryQueue()
    queue.messages.append(
        QueueMessage(
            message_id="run-1:1",
            dequeue_count=1,
            pop_receipt=None,
            payload={"run_id": "run-1", "product_id": "1", "source_url": source_url},
        )
    )
    store = InMemoryIngestionStore()
    store.start_run(IngestionRun(run_id="run-1", manifest_version="v1", started_at="start"))
    worker = IngestionWorker(queue=queue, store=store, http_client=httpx.MockTransport(handler))

    assert asyncio.run(worker.process()) == 1
    assert requests == [source_url]
    result = store.products[("run-1", "1")]
    assert (result.run_id, result.product_id, result.source_url) == ("run-1", "1", source_url)
    assert (result.outcome, result.reason_category, result.http_status) == (
        "success",
        "downloaded",
        200,
    )
    assert queue.receive() == []


@pytest.mark.parametrize(
    ("response", "outcome", "reason", "status"),
    [
        (httpx.Response(200, text="Public documentation"), "success", "downloaded", 200),
        (httpx.Response(401), "skipped", "protected_401", 401),
        (httpx.Response(403), "skipped", "protected_403", 403),
        (httpx.Response(302, headers={"Location": "/login"}), "skipped", "protected_redirect", 302),
        (
            httpx.Response(302, headers={"Location": "/signin"}),
            "skipped",
            "protected_redirect",
            302,
        ),
        (
            httpx.Response(302, headers={"Location": "https://evil.example/login"}),
            "skipped",
            "protected_redirect",
            302,
        ),
        (
            httpx.Response(200, text="<form>Please sign in</form>"),
            "skipped",
            "protected_login_content",
            200,
        ),
        (httpx.Response(404), "failed", "http_404", 404),
    ],
)
def test_worker_records_status_and_does_not_follow_redirects(
    response, outcome, reason, status
) -> None:
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return response

    worker, queue, store = setup_worker(handler)
    assert asyncio.run(worker.process()) == 1
    assert requests == ["https://my.opentext.com/support/products/product-a"]
    result = store.products[("run-1", "product-a")]
    assert (result.outcome, result.reason_category, result.http_status, result.attempt_count) == (
        outcome,
        reason,
        status,
        1,
    )
    assert queue.receive() == []
    assert store.runs["run-1"].processed == 1


def test_worker_does_not_store_protected_response_content() -> None:
    secret_content = "Please sign in: confidential form content"
    worker, _, store = setup_worker(lambda request: httpx.Response(200, text=secret_content))
    asyncio.run(worker.process())
    status = store.products[("run-1", "product-a")]
    assert status.outcome == "skipped"
    assert status.reason_category == "protected_login_content"
    assert secret_content not in status.model_dump_json()


def test_worker_does_not_follow_nonlogin_redirect_on_approved_documentation_host() -> None:
    source_url = "https://admhelp.microfocus.com/product/old"
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "/product/new"})

    queue = InMemoryQueue()
    queue.send_product_reference("run-1", "product-a", source_url)
    store = InMemoryIngestionStore()
    store.start_run(IngestionRun(run_id="run-1", manifest_version="v1", started_at="start"))
    worker = IngestionWorker(queue=queue, store=store, http_client=httpx.MockTransport(handler))

    assert asyncio.run(worker.process()) == 1
    status = store.products[("run-1", "product-a")]
    assert calls == [source_url]
    assert (status.outcome, status.reason_category) == ("failed", "http_307")


def test_worker_retries_429_using_retry_after_then_succeeds(monkeypatch) -> None:
    calls = []
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("product_support_agent.http_fetch.asyncio.sleep", sleep)

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, text="public content")

    worker, _, store = setup_worker(handler, max_attempts=3)
    assert asyncio.run(worker.process()) == 1
    status = store.products[("run-1", "product-a")]
    assert (status.outcome, status.reason_category, status.http_status, status.attempt_count) == (
        "success",
        "downloaded",
        200,
        2,
    )
    assert len(calls) == 2
    assert sleeps == [7.0]


def test_retry_after_is_not_shortened_below_server_delay(monkeypatch) -> None:
    sleeps = []
    calls = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("product_support_agent.http_fetch.asyncio.sleep", sleep)

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, text="public")

    worker, _, store = setup_worker(handler, max_attempts=2)
    asyncio.run(worker.process())
    status = store.products[("run-1", "product-a")]
    if len(calls) > 1:
        assert sleeps == [120.0]
        assert status.outcome == "success"
    else:
        assert status.outcome == "failed"


@pytest.mark.parametrize(("http_status", "reason"), [(429, "retry_limit"), (503, "server_error")])
def test_worker_stops_at_max_attempts(monkeypatch, http_status, reason) -> None:
    calls = []
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("product_support_agent.http_fetch.asyncio.sleep", sleep)
    monkeypatch.setattr("product_support_agent.http_fetch.secrets.randbelow", lambda _upper: 0)

    def handler(request):
        calls.append(request)
        return httpx.Response(http_status)

    worker, _, store = setup_worker(handler, max_attempts=3)
    asyncio.run(worker.process())
    status = store.products[("run-1", "product-a")]
    assert (status.outcome, status.reason_category, status.http_status, status.attempt_count) == (
        "failed",
        reason,
        http_status,
        3,
    )
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_network_errors_are_bounded_and_reported(monkeypatch) -> None:
    calls = []
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("product_support_agent.http_fetch.asyncio.sleep", sleep)
    monkeypatch.setattr("product_support_agent.http_fetch.secrets.randbelow", lambda _upper: 0)

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("offline", request=request)

    worker, _, store = setup_worker(handler, max_attempts=2)
    asyncio.run(worker.process())
    status = store.products[("run-1", "product-a")]
    assert (status.outcome, status.reason_category, status.http_status, status.attempt_count) == (
        "failed",
        "network_error",
        None,
        2,
    )
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_oversized_download_is_skipped() -> None:
    worker, _, store = setup_worker(
        lambda request: httpx.Response(200, text="12345"), max_download_bytes=4
    )
    asyncio.run(worker.process())
    status = store.products[("run-1", "product-a")]
    assert (status.outcome, status.reason_category, status.http_status) == (
        "skipped",
        "oversized",
        200,
    )


def test_oversized_stream_stops_before_reading_subsequent_chunks() -> None:
    class RecordingStream(httpx.AsyncByteStream):
        def __init__(self):
            self.consumed = []
            self.closed = False

        async def __aiter__(self):
            for chunk in (b"abcd", b"e", b"must not be read"):
                self.consumed.append(chunk)
                yield chunk

        async def aclose(self):
            self.closed = True

    stream = RecordingStream()
    worker, queue, store = setup_worker(
        lambda request: httpx.Response(200, stream=stream), max_download_bytes=4
    )

    assert asyncio.run(worker.process()) == 1
    status = store.products[("run-1", "product-a")]
    assert (status.outcome, status.reason_category, status.http_status, status.attempt_count) == (
        "skipped",
        "oversized",
        200,
        1,
    )
    assert stream.consumed == [b"abcd", b"e"]
    assert stream.closed
    assert queue.receive() == []


def test_poison_threshold_records_dead_letter_without_http() -> None:
    calls = []
    worker, queue, store = setup_worker(
        lambda request: calls.append(request), dequeue_count=5, poison_dequeue_count=5
    )
    assert asyncio.run(worker.process()) == 1
    status = store.products[("run-1", "product-a")]
    assert (status.outcome, status.reason_category, status.attempt_count) == (
        "dead_letter",
        "poison",
        5,
    )
    assert calls == []
    assert queue.receive() == []
    assert store.runs["run-1"].dead_lettered == 1


def test_message_below_poison_threshold_is_processed_normally() -> None:
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="public")

    worker, queue, store = setup_worker(handler, dequeue_count=4, poison_dequeue_count=5)
    assert asyncio.run(worker.process()) == 1
    assert calls == ["https://my.opentext.com/support/products/product-a"]
    assert store.products[("run-1", "product-a")].outcome == "success"
    assert store.runs["run-1"].dead_lettered == 0
    assert queue.receive() == []


def test_retry_after_parses_date_and_invalid_header(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, tzinfo=UTC)

    monkeypatch.setattr("product_support_agent.http_fetch.datetime", FixedDateTime)
    future = httpx.Response(429, headers={"Retry-After": "Thu, 01 Jan 2026 00:00:10 GMT"})
    past = httpx.Response(429, headers={"Retry-After": "Wed, 31 Dec 2025 23:59:50 GMT"})
    invalid = httpx.Response(429, headers={"Retry-After": "later"})
    assert IngestionWorker._retry_after_seconds(future) == 10.0
    assert IngestionWorker._retry_after_seconds(past) == 0
    assert IngestionWorker._retry_after_seconds(invalid) is None


@pytest.mark.parametrize(
    ("outcomes", "expected_status", "counts"),
    [
        (["success", "success"], "completed", (2, 2, 0, 0, 0)),
        (["success", "skipped", "failed", "dead_letter"], "completed_with_errors", (4, 1, 1, 1, 1)),
    ],
)
def test_run_completion_reports_outcomes(outcomes, expected_status, counts) -> None:
    store = InMemoryIngestionStore()
    store.start_run(IngestionRun(run_id="run", manifest_version="v1", started_at="start"))
    for index, outcome in enumerate(outcomes):
        store.record_product(
            ProductIngestionStatus(
                run_id="run",
                product_id=f"p{index}",
                outcome=outcome,
                reason_category="example",
                source_url="https://my.opentext.com/p",
            )
        )
    run = store.complete_run("run", completed_at="end")
    assert run.status == expected_status
    assert run.finished_at == "end"
    assert (run.processed, run.successful, run.skipped, run.failed, run.dead_lettered) == counts


def test_retrying_status_is_not_a_completed_product() -> None:
    store = InMemoryIngestionStore()
    store.start_run(IngestionRun(run_id="run", manifest_version="v1", started_at="start"))
    store.record_product(
        ProductIngestionStatus(
            run_id="run",
            product_id="p1",
            outcome="retrying",
            reason_category="rate_limited",
            source_url="https://my.opentext.com/p",
        )
    )
    assert store.runs["run"].processed == 0
    assert store.runs["run"].status == "running"


def test_repeated_delivery_does_not_double_count_product() -> None:
    store = InMemoryIngestionStore()
    store.start_run(IngestionRun(run_id="run", manifest_version="v1", started_at="start"))
    status = ProductIngestionStatus(
        run_id="run",
        product_id="p1",
        outcome="success",
        reason_category="downloaded",
        source_url="https://my.opentext.com/p",
    )
    store.record_product(status)
    store.record_product(status)
    assert store.runs["run"].processed == 1
    assert store.runs["run"].successful == 1
    assert len(store.products) == 1

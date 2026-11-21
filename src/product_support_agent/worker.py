from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Literal, Protocol, TypedDict

import httpx

from product_support_agent.catalog import (
    ALLOWED_SOURCE_HOST,
    is_login_content,
    is_login_redirect,
    validate_source_url,
)
from product_support_agent.queue import QueueMessage
from product_support_agent.store import InMemoryIngestionStore, ProductIngestionStatus


class QueueConsumer(Protocol):
    def receive(self) -> list[QueueMessage]: ...
    def delete(self, message: QueueMessage) -> None: ...


class FetchResult(TypedDict):
    outcome: Literal["success", "skipped", "retrying", "failed", "dead_letter"]
    reason_category: str
    http_status: int | None
    attempt_count: int


class IngestionWorker:
    def __init__(
        self,
        *,
        queue: QueueConsumer,
        store: InMemoryIngestionStore,
        http_client: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 4,
        timeout_seconds: float = 10.0,
        max_download_bytes: int = 4_194_304,
        poison_dequeue_count: int = 5,
    ) -> None:
        self.queue = queue
        self.store = store
        self.http_client = http_client
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.poison_dequeue_count = poison_dequeue_count

    async def process(self) -> int:
        processed = 0
        run_ids: set[str] = set()
        for message in self.queue.receive():
            run_id = message.payload["run_id"]
            product_id = message.payload["product_id"]
            run_ids.add(run_id)
            if message.dequeue_count >= self.poison_dequeue_count:
                self.store.record_product(
                    ProductIngestionStatus(
                        run_id=run_id,
                        product_id=product_id,
                        outcome="dead_letter",
                        reason_category="poison",
                        source_url=f"https://{ALLOWED_SOURCE_HOST}/support/products/{product_id}",
                        attempt_count=message.dequeue_count,
                    )
                )
                transfer_to_poison = getattr(self.queue, "transfer_to_poison", None)
                if callable(transfer_to_poison):
                    transfer_to_poison(message)
                else:
                    self.queue.delete(message)
                processed += 1
                continue

            source_url = f"https://{ALLOWED_SOURCE_HOST}/support/products/{product_id}"
            result = await self._fetch(source_url)
            self.store.record_product(
                ProductIngestionStatus(
                    run_id=run_id,
                    product_id=product_id,
                    outcome=result["outcome"],
                    reason_category=result["reason_category"],
                    http_status=result["http_status"],
                    source_url=source_url,
                    attempt_count=result["attempt_count"],
                )
            )
            self.queue.delete(message)
            processed += 1
        completed_at = datetime.now(UTC).isoformat()
        for run_id in run_ids:
            self.store.complete_run(run_id, completed_at=completed_at)
        return processed

    async def _fetch(
        self,
        source_url: str,
    ) -> FetchResult:
        if not validate_source_url(source_url):
            return self._result("skipped", "invalid_url", None, 1)

        async with httpx.AsyncClient(
            transport=self.http_client,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.get(source_url)
                except httpx.HTTPError:
                    if attempt >= self.max_attempts:
                        return self._result("failed", "network_error", None, attempt)
                    await asyncio.sleep(self._retry_delay(attempt, None))
                    continue

                if is_login_redirect(response):
                    return self._result(
                        "skipped", "protected_redirect", response.status_code, attempt
                    )
                if response.status_code in (401, 403):
                    return self._result(
                        "skipped",
                        f"protected_{response.status_code}",
                        response.status_code,
                        attempt,
                    )
                if response.status_code == 429:
                    if attempt >= self.max_attempts:
                        return self._result("failed", "retry_limit", 429, attempt)
                    retry_after = self._retry_after_seconds(response)
                    await asyncio.sleep(self._retry_delay(attempt, retry_after))
                    continue
                if 500 <= response.status_code < 600:
                    if attempt >= self.max_attempts:
                        return self._result(
                            "failed",
                            "server_error",
                            response.status_code,
                            attempt,
                        )
                    await asyncio.sleep(self._retry_delay(attempt, None))
                    continue
                if response.status_code not in range(200, 300):
                    return self._result(
                        "failed",
                        f"http_{response.status_code}",
                        response.status_code,
                        attempt,
                    )
                if len(response.content) > self.max_download_bytes:
                    return self._result("skipped", "oversized", 200, attempt)
                if is_login_content(response.text):
                    return self._result("skipped", "protected_login_content", 200, attempt)
                return self._result("success", "downloaded", 200, attempt)

        return self._result("failed", "retry_limit", None, self.max_attempts)

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                date = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT")
                now = datetime.now(UTC)
                delay = (date.replace(tzinfo=UTC) - now).total_seconds()
                return max(0.0, delay)
            except ValueError:
                return None

    @staticmethod
    def _retry_delay(attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        base = min(2.0**attempt, 8.0)
        jitter = secrets.randbelow(251) / 1000.0
        return base + jitter

    @staticmethod
    def _result(
        outcome: Literal["success", "skipped", "retrying", "failed", "dead_letter"],
        reason_category: str,
        http_status: int | None,
        attempt_count: int,
    ) -> FetchResult:
        if outcome not in ("success", "skipped", "retrying", "failed", "dead_letter"):
            raise ValueError("invalid ingestion outcome")
        return {
            "outcome": outcome,
            "reason_category": reason_category,
            "http_status": http_status,
            "attempt_count": attempt_count,
        }

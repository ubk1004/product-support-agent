from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol, TypedDict
from urllib.parse import urlparse

import httpx
from pydantic import HttpUrl

from product_support_agent.catalog import ProductReference
from product_support_agent.documents import CanonicalDocument, DocumentNormalizationError
from product_support_agent.http_fetch import BoundedFetcher, retry_after_seconds
from product_support_agent.indexing import DocumentIndexingError
from product_support_agent.queue import QueueMessage
from product_support_agent.store import InMemoryIngestionStore, ProductIngestionStatus


class QueueConsumer(Protocol):
    def receive(self) -> list[QueueMessage]: ...
    def delete(self, message: QueueMessage) -> None: ...


class DocumentIndexer(Protocol):
    async def index_html(
        self,
        source: ProductReference,
        body: bytes,
        content_type: str,
    ) -> CanonicalDocument: ...


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
        document_indexer: DocumentIndexer | None = None,
    ) -> None:
        self.queue = queue
        self.store = store
        self.http_client = http_client
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.poison_dequeue_count = poison_dequeue_count
        self.document_indexer = document_indexer
        self.fetcher = BoundedFetcher(
            transport=http_client,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            max_download_bytes=max_download_bytes,
        )

    async def process(self) -> int:
        processed = 0
        run_ids: set[str] = set()
        for message in self.queue.receive():
            run_id = message.payload["run_id"]
            product_id = message.payload["product_id"]
            source_url = message.payload.get("source_url", "")
            run_ids.add(run_id)
            if message.dequeue_count >= self.poison_dequeue_count:
                self.store.record_product(
                    ProductIngestionStatus(
                        run_id=run_id,
                        product_id=product_id,
                        outcome="dead_letter",
                        reason_category="poison",
                        source_url=source_url,
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

            result = await self._fetch(
                source_url,
                product_id=product_id,
                product_name=message.payload.get("product_name", product_id),
            )
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
        *,
        product_id: str,
        product_name: str,
    ) -> FetchResult:
        response = await self.fetcher.get(source_url)
        attempt = max(response.attempt_count, 1)
        if response.outcome != "success":
            outcome: Literal["skipped", "failed"] = (
                "skipped" if response.outcome == "skipped" else "failed"
            )
            return self._result(outcome, response.reason_category, response.http_status, attempt)

        if self.document_indexer is not None:
            source = ProductReference(
                product_id=product_id,
                name=product_name,
                slug=urlparse(source_url).path.rstrip("/").rsplit("/", 1)[-1],
                source_url=HttpUrl(source_url),
            )
            try:
                await self.document_indexer.index_html(
                    source,
                    response.body,
                    response.content_type,
                )
            except DocumentNormalizationError:
                return self._result("failed", "normalization_failed", 200, attempt)
            except DocumentIndexingError:
                return self._result("failed", "indexing_failed", 200, attempt)
            return self._result("success", "indexed", 200, attempt)
        return self._result("success", "downloaded", 200, attempt)

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        return retry_after_seconds(response)

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

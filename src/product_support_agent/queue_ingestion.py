"""Queue-driven ingestion: one product per message, one message per worker step.

The enqueuer reads the approved manifest and the source map, and puts one message per product
on the queue. The worker takes one message, runs the same `SourceIngestionWorker` used by the
scheduled script for that single product, records the outcome durably, and only then deletes the
message. A crash before the delete makes the message reappear, so delivery is at-least-once and
the work is idempotent: durable per-URL fetch state and content hashes skip anything that was
already fetched or indexed.

Why a queue rather than one loop: each product is independent, a failing product cannot stall
the others, several workers can share a run later, and every product's outcome is recorded
whether it succeeded, was skipped, or failed. Request budget and per-host spacing are shared
across all products a single worker process handles.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from product_support_agent.catalog import Manifest
from product_support_agent.queue import ProductQueueConsumer, QueueMessage, QueueProducer
from product_support_agent.source_ingestion import (
    ProductRunResult,
    RunContext,
    SourceIngestionWorker,
)
from product_support_agent.sources import ProductSource, SourceMap
from product_support_agent.store import IngestionRun, ProductIngestionStatus
from product_support_agent.telemetry import record_ingestion_pages, tracer

logger = logging.getLogger(__name__)

# Seconds before a product that could not run now (request budget used up) is tried again.
BUDGET_RETRY_DELAY_SECONDS = 3_600


class IngestionRunStore(Protocol):
    def start_run(self, run: IngestionRun) -> None: ...

    def record_product(self, status: ProductIngestionStatus) -> None: ...

    def complete_run(self, run_id: str, *, completed_at: str) -> IngestionRun: ...

    def get_run(self, run_id: str) -> IngestionRun | None: ...


@dataclass(frozen=True)
class EnqueueResult:
    run_id: str
    enqueued: int
    no_public_source: int


def enqueue_manifest_products(
    *,
    manifest: Manifest,
    source_map: SourceMap,
    producer: QueueProducer,
    store: IngestionRunStore,
    run_id: str | None = None,
    product_ids: Sequence[str] | None = None,
    now: datetime | None = None,
) -> EnqueueResult:
    """Queue one message per manifest product; every product gets its own recorded outcome.

    Products without an enabled source are still recorded, as skipped, so the run shows all of
    the demo products and why most of them have no documentation.
    """
    wanted = set(product_ids) if product_ids else None
    enabled = {source.product_id for source in source_map.enabled_sources()}
    selected = [
        product
        for product in manifest.selected_products
        if wanted is None or product.product_id in wanted
    ]
    if not selected:
        raise ValueError("no manifest products match the request")
    active_run_id = run_id or str(uuid4())
    started = (now or datetime.now(UTC)).isoformat()
    store.start_run(
        IngestionRun(
            run_id=active_run_id,
            manifest_version=manifest.manifest_version,
            started_at=started,
            total=len(selected),
        )
    )
    enqueued = 0
    no_source = 0
    for product in selected:
        if product.product_id in enabled:
            producer.send_product_reference(
                active_run_id, product.product_id, str(product.source_url), product.name
            )
            enqueued += 1
        else:
            no_source += 1
            store.record_product(
                ProductIngestionStatus(
                    run_id=active_run_id,
                    product_id=product.product_id,
                    product_name=product.name,
                    outcome="skipped",
                    reason_category="no_public_source",
                    source_url=str(product.source_url),
                )
            )
    if enqueued == 0:
        store.complete_run(active_run_id, completed_at=(now or datetime.now(UTC)).isoformat())
    return EnqueueResult(run_id=active_run_id, enqueued=enqueued, no_public_source=no_source)


_OUTCOME_MAP = {
    "completed": "success",
    "skipped_fresh": "success",
    "partial": "partial",
    "failed": "failed",
    "failed_fast": "failed",
}


def status_from_result(
    run_id: str,
    message: QueueMessage,
    result: ProductRunResult,
) -> ProductIngestionStatus:
    """Translate a source-worker result into the durable per-product status record."""
    protected = [page for page in result.pages if page.reason_category.startswith("protected")]
    outcome = _OUTCOME_MAP.get(result.outcome, "failed")
    reason = result.reason_category
    if outcome == "failed" and protected and len(protected) == len(result.pages):
        outcome, reason = "skipped", "protected_content"
    return ProductIngestionStatus(
        run_id=run_id,
        product_id=result.product_id,
        product_name=result.product_name,
        outcome=outcome,  # type: ignore[arg-type]
        reason_category=reason,
        source_url=message.payload.get("source_url", ""),
        attempt_count=message.dequeue_count,
        pages_selected=result.pages_selected,
        pages_indexed=result.pages_indexed,
        pages_unchanged=result.pages_unchanged,
        pages_failed=result.pages_failed,
        pages_removed=result.pages_removed,
    )


@dataclass
class WorkerStats:
    processed: int = 0
    deferred: int = 0
    dead_lettered: int = 0
    unknown_product: int = 0
    stopped_reason: str | None = None


class QueueIngestionWorker:
    """Takes products from the queue one at a time and ingests each with the source worker."""

    def __init__(
        self,
        *,
        queue: ProductQueueConsumer,
        worker: SourceIngestionWorker,
        source_map: SourceMap,
        store: IngestionRunStore,
        poison_dequeue_count: int = 5,
        budget_retry_delay_seconds: int = BUDGET_RETRY_DELAY_SECONDS,
        force: bool = False,
    ) -> None:
        self.queue = queue
        self.worker = worker
        self.store = store
        self.poison_dequeue_count = poison_dequeue_count
        self.budget_retry_delay_seconds = budget_retry_delay_seconds
        self.force = force
        self._sources: dict[str, ProductSource] = {
            source.product_id: source for source in source_map.enabled_sources()
        }
        self._context: RunContext = worker.begin()

    async def run_until_empty(self, *, max_messages: int | None = None) -> WorkerStats:
        stats = WorkerStats()
        while max_messages is None or stats.processed + stats.deferred < max_messages:
            message = self.queue.receive_one()
            if message is None:
                break
            await self._handle(message, stats)
            if stats.stopped_reason is not None:
                # The request budget is shared by every product this process handles, so once it
                # is spent the remaining messages stay on the queue for the next run.
                break
        return stats

    async def _handle(self, message: QueueMessage, stats: WorkerStats) -> None:
        run_id = message.payload["run_id"]
        product_id = message.payload["product_id"]
        with tracer().start_as_current_span("psa.ingestion.product") as span:
            span.set_attribute("psa.ingestion.product_id", product_id)
            span.set_attribute("psa.queue.dequeue_count", message.dequeue_count)
            if message.dequeue_count >= self.poison_dequeue_count:
                self._dead_letter(message, stats)
                span.set_attribute("psa.ingestion.outcome", "dead_letter")
                return
            source = self._sources.get(product_id)
            if source is None:
                self._record(
                    message,
                    ProductIngestionStatus(
                        run_id=run_id,
                        product_id=product_id,
                        product_name=message.payload.get("product_name"),
                        outcome="skipped",
                        reason_category="no_public_source",
                        source_url=message.payload.get("source_url", ""),
                        attempt_count=message.dequeue_count,
                    ),
                    stats,
                )
                stats.unknown_product += 1
                span.set_attribute("psa.ingestion.outcome", "skipped")
                return

            try:
                result = await self.worker.process_source(source, self._context, force=self.force)
            except Exception:
                # Leave the message on the queue: it reappears after the visibility timeout and
                # is dead-lettered after repeated failures, so one bad product cannot stall the
                # rest or loop forever.
                logger.exception("product ingestion raised; message left for retry")
                span.set_attribute("psa.ingestion.outcome", "error")
                return

            span.set_attribute("psa.ingestion.outcome", result.outcome)
            span.set_attribute("psa.ingestion.pages_indexed", result.pages_indexed)
            if result.outcome == "budget_exhausted":
                self.queue.defer(message, self.budget_retry_delay_seconds)
                stats.deferred += 1
                stats.stopped_reason = "request_budget_exhausted"
                return
            self._record(message, status_from_result(run_id, message, result), stats)
            record_ingestion_pages(
                {
                    "indexed": result.pages_indexed,
                    "unchanged": result.pages_unchanged,
                    "skipped_fresh": result.pages_skipped_fresh,
                    "failed": result.pages_failed,
                    "removed": result.pages_removed,
                }
            )

    def _dead_letter(self, message: QueueMessage, stats: WorkerStats) -> None:
        self._record(
            message,
            ProductIngestionStatus(
                run_id=message.payload["run_id"],
                product_id=message.payload["product_id"],
                product_name=message.payload.get("product_name"),
                outcome="dead_letter",
                reason_category="poison",
                source_url=message.payload.get("source_url", ""),
                attempt_count=message.dequeue_count,
            ),
            stats,
            poison=True,
        )
        stats.dead_lettered += 1

    def _record(
        self,
        message: QueueMessage,
        status: ProductIngestionStatus,
        stats: WorkerStats,
        *,
        poison: bool = False,
    ) -> None:
        # Record first, delete second: a crash between the two replays the product, which is
        # idempotent, rather than losing its outcome.
        self.store.record_product(status)
        if poison:
            self.queue.transfer_to_poison(message)
        else:
            self.queue.delete(message)
        stats.processed += 1
        self._complete_run_if_finished(status.run_id)

    def _complete_run_if_finished(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run is None or run.finished_at is not None:
            return
        if run.total and run.processed >= run.total:
            self.store.complete_run(run_id, completed_at=datetime.now(UTC).isoformat())

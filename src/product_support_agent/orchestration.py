from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from product_support_agent.catalog import CatalogClient, CatalogOutcome, Manifest, create_manifest
from product_support_agent.queue import InMemoryQueue
from product_support_agent.store import IngestionRun, InMemoryIngestionStore


class PhaseTwoService:
    def __init__(
        self,
        *,
        catalog: CatalogClient,
        store: InMemoryIngestionStore,
        queue: InMemoryQueue,
        manifest_seed: str,
        max_demo_products: int,
    ) -> None:
        self.catalog = catalog
        self.store = store
        self.queue = queue
        self.manifest_seed = manifest_seed
        self.max_demo_products = max_demo_products
        self.manifest: Manifest | None = None
        self.catalog_outcome: CatalogOutcome | None = None

    async def discover_and_prepare(self) -> tuple[Manifest | None, CatalogOutcome]:
        outcome = await self.catalog.discover()
        self.catalog_outcome = outcome
        if not outcome.products:
            return None, outcome

        manifest = create_manifest(
            outcome.products,
            manifest_version=f"demo-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
            seed=self.manifest_seed,
            selection_timestamp=datetime.now(UTC).isoformat(),
            max_products=self.max_demo_products,
        )
        self.manifest = manifest
        return manifest, outcome

    def enqueue_manifest(self, run_id: str | None = None) -> IngestionRun:
        if self.manifest is None:
            raise RuntimeError("a manifest must be prepared before enqueueing")
        active_run_id = run_id or str(uuid4())
        now = datetime.now(UTC).isoformat()
        run = IngestionRun(
            run_id=active_run_id,
            manifest_version=self.manifest.manifest_version,
            started_at=now,
        )
        self.store.start_run(run)
        for product in self.manifest.selected_products:
            self.queue.send_product_reference(active_run_id, product.product_id)
        return run

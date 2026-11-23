from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from pymongo import MongoClient

IngestionOutcome = Literal["success", "partial", "skipped", "retrying", "failed", "dead_letter"]


class IngestionRun(BaseModel):
    run_id: str
    manifest_version: str
    status: Literal["running", "completed", "completed_with_errors"] = "running"
    started_at: str
    finished_at: str | None = None
    # Products queued for this run; 0 when the run was not created by the queue enqueuer.
    total: int = 0
    processed: int = 0
    successful: int = 0
    partial: int = 0
    skipped: int = 0
    failed: int = 0
    dead_lettered: int = 0


class ProductIngestionStatus(BaseModel):
    run_id: str
    product_id: str
    outcome: IngestionOutcome
    reason_category: str
    http_status: int | None = None
    source_url: str
    attempt_count: int = 1
    product_name: str | None = None
    # Page counts from the source worker; zero for products that were never fetched.
    pages_selected: int = 0
    pages_indexed: int = 0
    pages_unchanged: int = 0
    pages_failed: int = 0
    pages_removed: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class InMemoryIngestionStore:
    def __init__(self) -> None:
        self.runs: dict[str, IngestionRun] = {}
        self.products: dict[tuple[str, str], ProductIngestionStatus] = {}

    def start_run(self, run: IngestionRun) -> None:
        self.runs[run.run_id] = run

    def get_run(self, run_id: str) -> IngestionRun | None:
        return self.runs.get(run_id)

    def latest_run(self) -> IngestionRun | None:
        return max(self.runs.values(), key=lambda run: run.started_at, default=None)

    def list_products(self, run_id: str) -> list[ProductIngestionStatus]:
        return [
            status
            for (status_run_id, _), status in self.products.items()
            if status_run_id == run_id
        ]

    def record_product(self, status: ProductIngestionStatus) -> None:
        key = (status.run_id, status.product_id)
        if key in self.products:
            existing = self.products[key]
            if existing.outcome == "retrying" and status.outcome != "retrying":
                self.products[key] = status
            else:
                return
        else:
            if status.outcome == "retrying":
                self.products[key] = status
                return
            self.products[key] = status
        run = self.runs[status.run_id]
        if status.outcome == "success":
            run.successful += 1
        elif status.outcome == "partial":
            run.partial += 1
        elif status.outcome == "skipped":
            run.skipped += 1
        elif status.outcome == "dead_letter":
            run.dead_lettered += 1
        elif status.outcome == "failed":
            run.failed += 1
        run.processed += 1

    def complete_run(
        self,
        run_id: str,
        *,
        completed_at: str,
    ) -> IngestionRun:
        run = self.runs[run_id]
        run.finished_at = completed_at
        # Skipped products (no public source, or protected content) are expected by design.
        run.status = (
            "completed_with_errors"
            if run.partial or run.failed or run.dead_lettered
            else "completed"
        )
        return run


class MongoIngestionStore:
    def __init__(self, mongo_uri: str, database_name: str = "product_support") -> None:
        self.client: MongoClient[Any] = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5_000,
        )
        self.database = self.client[database_name]
        self.runs = self.database["ingestion_runs"]
        self.products = self.database["product_ingestion_status"]

    def ensure_indexes(self) -> None:
        self.runs.create_index("run_id", unique=True)
        self.runs.create_index("started_at")
        self.products.create_index([("run_id", 1), ("product_id", 1)], unique=True)

    def close(self) -> None:
        self.client.close()

    def start_run(self, run: IngestionRun) -> None:
        self.runs.replace_one(
            {"run_id": run.run_id},
            run.model_dump(mode="json"),
            upsert=True,
        )

    def get_run(self, run_id: str) -> IngestionRun | None:
        document = self.runs.find_one({"run_id": run_id})
        return IngestionRun.model_validate(document) if document is not None else None

    def latest_run(self) -> IngestionRun | None:
        document = self.runs.find_one(sort=[("started_at", -1)])
        return IngestionRun.model_validate(document) if document is not None else None

    def list_products(self, run_id: str) -> list[ProductIngestionStatus]:
        return [
            ProductIngestionStatus.model_validate(document)
            for document in self.products.find({"run_id": run_id}).sort("product_id", 1)
        ]

    def record_product(self, status: ProductIngestionStatus) -> None:
        key = {"run_id": status.run_id, "product_id": status.product_id}
        existing = self.products.find_one(key)
        if existing is not None:
            if existing.get("outcome") == "retrying" and status.outcome != "retrying":
                self.products.replace_one(key, status.model_dump(mode="json"), upsert=True)
            else:
                return
        else:
            if status.outcome == "retrying":
                self.products.replace_one(key, status.model_dump(mode="json"), upsert=True)
                return
            self.products.replace_one(key, status.model_dump(mode="json"), upsert=True)

        run = self.runs.find_one({"run_id": status.run_id})
        if run is None:
            return
        increments: dict[str, int] = {"processed": 1}
        if status.outcome == "success":
            increments["successful"] = 1
        elif status.outcome == "partial":
            increments["partial"] = 1
        elif status.outcome == "skipped":
            increments["skipped"] = 1
        elif status.outcome == "dead_letter":
            increments["dead_lettered"] = 1
        elif status.outcome == "failed":
            increments["failed"] = 1
        self.runs.update_one({"run_id": status.run_id}, {"$inc": increments})

    def complete_run(
        self,
        run_id: str,
        *,
        completed_at: str,
    ) -> IngestionRun:
        run_document = self.runs.find_one({"run_id": run_id})
        if run_document is None:
            raise KeyError(run_id)
        run = IngestionRun.model_validate(run_document)
        run.finished_at = completed_at
        # Skipped products (no public source, or protected content) are expected by design.
        run.status = (
            "completed_with_errors"
            if run.partial or run.failed or run.dead_lettered
            else "completed"
        )
        self.runs.replace_one({"run_id": run_id}, run.model_dump(mode="json"), upsert=True)
        return run

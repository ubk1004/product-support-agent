from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from pymongo import MongoClient

IngestionOutcome = Literal["success", "skipped", "retrying", "failed", "dead_letter"]


class IngestionRun(BaseModel):
    run_id: str
    manifest_version: str
    status: Literal["running", "completed", "completed_with_errors"] = "running"
    started_at: str
    finished_at: str | None = None
    processed: int = 0
    successful: int = 0
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
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class InMemoryIngestionStore:
    def __init__(self) -> None:
        self.runs: dict[str, IngestionRun] = {}
        self.products: dict[tuple[str, str], ProductIngestionStatus] = {}

    def start_run(self, run: IngestionRun) -> None:
        self.runs[run.run_id] = run

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
        run.status = (
            "completed_with_errors"
            if run.skipped or run.failed or run.dead_lettered
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

    def start_run(self, run: IngestionRun) -> None:
        self.runs.replace_one(
            {"run_id": run.run_id},
            run.model_dump(mode="json"),
            upsert=True,
        )

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
        run.status = (
            "completed_with_errors"
            if run.skipped or run.failed or run.dead_lettered
            else "completed"
        )
        self.runs.replace_one({"run_id": run_id}, run.model_dump(mode="json"), upsert=True)
        return run

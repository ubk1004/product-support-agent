from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel, field_validator
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

FetchStateOutcome = Literal[
    "discovered", "indexed", "unchanged", "not_modified", "removed", "failed"
]
FailureClass = Literal["permanent", "transient"]

PERMANENT_FAILURE_REASONS = frozenset(
    {
        "invalid_url",
        "oversized",
        "protected_401",
        "protected_403",
        "protected_redirect",
        "protected_login_content",
        "robots_disallowed",
        "normalization_failed",
        "discovery_malformed",
        "discovery_empty",
        "consecutive_permanent_page_failures",
    }
)


def classify_failure(reason_category: str) -> FailureClass:
    if reason_category in PERMANENT_FAILURE_REASONS:
        return "permanent"
    if reason_category.startswith("http_"):
        status = reason_category.removeprefix("http_")
        if status.isdigit() and (status.startswith("3") or status.startswith("4")):
            return "permanent"
    return "transient"


def fetch_state_key(product_id: str, citation_url: str) -> str:
    return hashlib.sha256(f"{product_id}\0{citation_url}".encode()).hexdigest()


class DiscoveredPage(BaseModel):
    fetch_url: str
    citation_url: str
    title: str | None = None
    revision: str | None = None


class FetchStateRecord(BaseModel):
    """Durable per-URL memory that lets a restarted or periodic run resume without refetching."""

    key: str
    product_id: str
    kind: Literal["seed", "page", "product"]
    fetch_url: str
    citation_url: str
    last_outcome: FetchStateOutcome
    reason_category: str
    http_status: int | None = None
    last_attempt_at: datetime
    last_success_at: datetime | None = None
    next_eligible_at: datetime | None = None
    consecutive_failures: int = 0
    etag: str | None = None
    last_modified: str | None = None
    body_hash: str | None = None
    revision: str | None = None
    document_id: str | None = None
    source_map_version: str | None = None
    source_config_hash: str | None = None
    discovered_pages: list[DiscoveredPage] | None = None

    @field_validator("last_attempt_at", "last_success_at", "next_eligible_at", mode="after")
    @classmethod
    def assume_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


@dataclass(frozen=True)
class FreshnessPolicy:
    success_freshness: timedelta = timedelta(hours=24)
    permanent_failure_backoff: timedelta = timedelta(days=30)
    transient_failure_backoff: timedelta = timedelta(hours=24)
    max_transient_failure_backoff: timedelta = timedelta(days=7)

    def skip_reason(
        self,
        record: FetchStateRecord | None,
        *,
        now: datetime,
        revision: str | None = None,
    ) -> str | None:
        """Return why a fetch should be skipped, or None when it is due."""
        if record is None:
            return None
        if record.next_eligible_at is not None and record.next_eligible_at > now:
            return "failure_backoff"
        if record.last_success_at is not None:
            if now - record.last_success_at < self.success_freshness:
                return "recently_fetched"
            if revision is not None and record.revision == revision and record.body_hash:
                return "unchanged_revision"
        return None

    def after_success(
        self,
        previous: FetchStateRecord | None,
        *,
        base: dict[str, Any],
        now: datetime,
        outcome: FetchStateOutcome,
    ) -> FetchStateRecord:
        merged = _merge(previous, base)
        merged.update(
            last_outcome=outcome,
            last_attempt_at=now,
            last_success_at=now,
            next_eligible_at=None,
            consecutive_failures=0,
        )
        return FetchStateRecord(**merged)

    def after_failure(
        self,
        previous: FetchStateRecord | None,
        *,
        base: dict[str, Any],
        now: datetime,
    ) -> FetchStateRecord:
        failures = (previous.consecutive_failures if previous else 0) + 1
        if classify_failure(str(base["reason_category"])) == "permanent":
            delay = self.permanent_failure_backoff
        else:
            delay = min(
                self.transient_failure_backoff * (2 ** (failures - 1)),
                self.max_transient_failure_backoff,
            )
        merged = _merge(previous, base)
        merged.update(
            http_status=base.get("http_status"),
            last_outcome="failed",
            last_attempt_at=now,
            next_eligible_at=now + delay,
            consecutive_failures=failures,
        )
        return FetchStateRecord(**merged)


def _merge(previous: FetchStateRecord | None, base: dict[str, Any]) -> dict[str, Any]:
    """Keep validators (ETag, hashes, document ID) from the last good fetch unless replaced."""
    merged = previous.model_dump() if previous is not None else {}
    merged.update({key: value for key, value in base.items() if value is not None})
    merged["reason_category"] = base["reason_category"]
    return merged


class FetchStateStore(Protocol):
    def get(self, key: str) -> FetchStateRecord | None: ...

    def put(self, record: FetchStateRecord) -> None: ...

    def list_for_product(self, product_id: str) -> list[FetchStateRecord]: ...

    def list_all(self) -> list[FetchStateRecord]: ...


class RunLeaseStore(Protocol):
    def acquire_lease(self, name: str, holder: str, *, now: datetime, ttl: timedelta) -> bool: ...

    def release_lease(self, name: str, holder: str) -> None: ...


class InMemoryFetchStateStore:
    def __init__(self) -> None:
        self.records: dict[str, FetchStateRecord] = {}
        self.leases: dict[str, tuple[str, datetime]] = {}

    def get(self, key: str) -> FetchStateRecord | None:
        return self.records.get(key)

    def put(self, record: FetchStateRecord) -> None:
        self.records[record.key] = record

    def list_for_product(self, product_id: str) -> list[FetchStateRecord]:
        return [record for record in self.records.values() if record.product_id == product_id]

    def list_all(self) -> list[FetchStateRecord]:
        return list(self.records.values())

    def acquire_lease(self, name: str, holder: str, *, now: datetime, ttl: timedelta) -> bool:
        current = self.leases.get(name)
        if current is not None and current[0] != holder and current[1] > now:
            return False
        self.leases[name] = (holder, now + ttl)
        return True

    def release_lease(self, name: str, holder: str) -> None:
        current = self.leases.get(name)
        if current is not None and current[0] == holder:
            del self.leases[name]


class MongoFetchStateStore:
    def __init__(
        self,
        mongo_uri: str,
        database_name: str = "product_support",
        *,
        client: MongoClient[Any] | None = None,
    ) -> None:
        self.client = client or MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5_000,
            tz_aware=True,
        )
        self.records: Collection[dict[str, Any]] = self.client[database_name]["source_fetch_state"]
        self.leases: Collection[dict[str, Any]] = self.client[database_name]["ingestion_leases"]

    def ensure_indexes(self) -> None:
        self.records.create_index("key", unique=True)
        self.records.create_index("product_id")

    def get(self, key: str) -> FetchStateRecord | None:
        record = self.records.find_one({"key": key})
        return FetchStateRecord.model_validate(record) if record is not None else None

    def put(self, record: FetchStateRecord) -> None:
        self.records.replace_one(
            {"key": record.key},
            {**record.model_dump(), "_id": record.key},
            upsert=True,
        )

    def list_for_product(self, product_id: str) -> list[FetchStateRecord]:
        return [
            FetchStateRecord.model_validate(record)
            for record in self.records.find({"product_id": product_id})
        ]

    def list_all(self) -> list[FetchStateRecord]:
        return [FetchStateRecord.model_validate(record) for record in self.records.find({})]

    def acquire_lease(self, name: str, holder: str, *, now: datetime, ttl: timedelta) -> bool:
        """Atomically take or renew a named lease; an expired lease can be taken over."""
        try:
            self.leases.update_one(
                {"_id": name, "$or": [{"holder": holder}, {"expires_at": {"$lte": now}}]},
                {"$set": {"holder": holder, "expires_at": now + ttl}},
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return True

    def release_lease(self, name: str, holder: str) -> None:
        self.leases.delete_one({"_id": name, "holder": holder})

    def close(self) -> None:
        self.client.close()

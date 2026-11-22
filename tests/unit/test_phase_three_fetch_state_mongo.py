from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from product_support_agent.fetch_state import FetchStateRecord, MongoFetchStateStore

NOW = datetime(2026, 11, 22, tzinfo=UTC)


class FakeCollection:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.indexes: list[tuple[str, bool]] = []

    def create_index(self, field: str, *, unique: bool = False) -> None:
        self.indexes.append((field, unique))

    def find_one(self, query):
        for record in self.records.values():
            if all(record.get(key) == value for key, value in query.items()):
                return dict(record)
        return None

    def find(self, query):
        return [
            dict(record)
            for record in self.records.values()
            if all(record.get(key) == value for key, value in query.items())
        ]

    def replace_one(self, query, replacement, *, upsert: bool) -> None:
        self.records[replacement["_id"]] = dict(replacement)

    def update_one(self, query, update, *, upsert: bool) -> None:
        existing = self.records.get(query["_id"])
        if existing is not None:
            matches = any(
                ("holder" in clause and existing["holder"] == clause["holder"])
                or (
                    "expires_at" in clause
                    and existing["expires_at"] <= clause["expires_at"]["$lte"]
                )
                for clause in query["$or"]
            )
            if not matches:
                raise DuplicateKeyError("lease held")
        self.records[query["_id"]] = {"_id": query["_id"], **update["$set"]}

    def delete_one(self, query) -> None:
        record = self.records.get(query["_id"])
        if record is not None and record.get("holder") == query["holder"]:
            del self.records[query["_id"]]


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeClient:
    def __init__(self) -> None:
        self.database = FakeDatabase()
        self.closed = False

    def __getitem__(self, name: str) -> FakeDatabase:
        return self.database

    def close(self) -> None:
        self.closed = True


def record(key: str, product_id: str = "p1") -> FetchStateRecord:
    return FetchStateRecord(
        key=key,
        product_id=product_id,
        kind="page",
        fetch_url="https://docs.microfocus.com/a/default-1.json",
        citation_url="https://docs.microfocus.com/doc/a",
        last_outcome="indexed",
        reason_category="indexed",
        last_attempt_at=NOW,
        last_success_at=NOW,
    )


def test_mongo_fetch_state_round_trip_indexes_and_lease() -> None:
    client = FakeClient()
    store = MongoFetchStateStore("mongodb://unused", client=client)
    store.ensure_indexes()
    store.put(record("k1"))
    store.put(record("k2", product_id="p2"))

    assert store.get("k1") == record("k1")
    assert store.get("missing") is None
    assert [item.key for item in store.list_for_product("p2")] == ["k2"]
    assert ("key", True) in store.records.indexes

    ttl = timedelta(hours=1)
    assert store.acquire_lease("run", "a", now=NOW, ttl=ttl)
    assert not store.acquire_lease("run", "b", now=NOW, ttl=ttl)
    assert store.acquire_lease("run", "b", now=NOW + timedelta(hours=2), ttl=ttl)
    store.release_lease("run", "b")
    assert store.acquire_lease("run", "a", now=NOW + timedelta(hours=2), ttl=ttl)
    store.close()
    assert client.closed


def test_naive_datetimes_from_storage_are_treated_as_utc() -> None:
    naive = record("k").model_dump()
    naive["last_success_at"] = datetime(2026, 11, 22)
    assert FetchStateRecord.model_validate(naive).last_success_at == NOW

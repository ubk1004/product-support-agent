from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from pymongo import MongoClient, ReplaceOne
from pymongo.collection import Collection

from product_support_agent.documents import CanonicalChunk, CanonicalDocument


class CanonicalDocumentRepository(Protocol):
    def replace_document(
        self,
        document: CanonicalDocument,
        chunks: Sequence[CanonicalChunk],
    ) -> None: ...

    def get_document(
        self,
        document_id: str,
    ) -> tuple[CanonicalDocument, list[CanonicalChunk]] | None: ...

    def delete_document(self, document_id: str) -> None: ...

    def list_document_ids(self) -> list[str]: ...


def _validate_document_chunks(
    document: CanonicalDocument,
    chunks: Sequence[CanonicalChunk],
) -> None:
    seen_ids: set[str] = set()
    seen_indexes: set[int] = set()
    for chunk in chunks:
        if chunk.document_id != document.document_id:
            raise ValueError("all chunks must belong to the canonical document")
        if chunk.product_id != document.product_id or chunk.source_id != document.source_id:
            raise ValueError("chunk provenance must match the canonical document")
        if chunk.source_url != document.source_url:
            raise ValueError("chunk URL must match the canonical document")
        if chunk.chunk_id in seen_ids or chunk.chunk_index in seen_indexes:
            raise ValueError("chunk IDs and indexes must be unique")
        seen_ids.add(chunk.chunk_id)
        seen_indexes.add(chunk.chunk_index)


class InMemoryCanonicalDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[str, CanonicalDocument] = {}
        self.chunks: dict[str, dict[str, CanonicalChunk]] = {}

    def replace_document(
        self,
        document: CanonicalDocument,
        chunks: Sequence[CanonicalChunk],
    ) -> None:
        _validate_document_chunks(document, chunks)
        self.documents[document.document_id] = document
        self.chunks[document.document_id] = {chunk.chunk_id: chunk for chunk in chunks}

    def get_document(
        self,
        document_id: str,
    ) -> tuple[CanonicalDocument, list[CanonicalChunk]] | None:
        document = self.documents.get(document_id)
        if document is None:
            return None
        chunks = sorted(
            self.chunks.get(document_id, {}).values(),
            key=lambda chunk: chunk.chunk_index,
        )
        return document, chunks

    def delete_document(self, document_id: str) -> None:
        self.documents.pop(document_id, None)
        self.chunks.pop(document_id, None)

    def list_document_ids(self) -> list[str]:
        return sorted(self.documents)


class MongoCanonicalDocumentRepository:
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
        )
        database = self.client[database_name]
        self.documents: Collection[dict[str, Any]] = database["canonical_documents"]
        self.chunks: Collection[dict[str, Any]] = database["canonical_chunks"]

    def ensure_indexes(self) -> None:
        self.documents.create_index("document_id", unique=True)
        self.chunks.create_index("chunk_id", unique=True)
        self.chunks.create_index("document_id")

    def replace_document(
        self,
        document: CanonicalDocument,
        chunks: Sequence[CanonicalChunk],
    ) -> None:
        _validate_document_chunks(document, chunks)
        document_record = document.model_dump(mode="json")
        document_record["_id"] = document.document_id
        self.documents.replace_one(
            {"document_id": document.document_id},
            document_record,
            upsert=True,
        )

        if chunks:
            operations = [
                ReplaceOne(
                    {"chunk_id": chunk.chunk_id},
                    {
                        **chunk.model_dump(mode="json"),
                        "_id": chunk.chunk_id,
                    },
                    upsert=True,
                )
                for chunk in chunks
            ]
            self.chunks.bulk_write(operations, ordered=True)
            self.chunks.delete_many(
                {
                    "document_id": document.document_id,
                    "chunk_id": {"$nin": [chunk.chunk_id for chunk in chunks]},
                }
            )
        else:
            self.chunks.delete_many({"document_id": document.document_id})

    def get_document(
        self,
        document_id: str,
    ) -> tuple[CanonicalDocument, list[CanonicalChunk]] | None:
        record = self.documents.find_one({"document_id": document_id})
        if record is None:
            return None
        chunks = [
            CanonicalChunk.model_validate(item)
            for item in self.chunks.find({"document_id": document_id}).sort("chunk_index", 1)
        ]
        return CanonicalDocument.model_validate(record), chunks

    def delete_document(self, document_id: str) -> None:
        self.documents.delete_one({"document_id": document_id})
        self.chunks.delete_many({"document_id": document_id})

    def list_document_ids(self) -> list[str]:
        return sorted(
            str(record["document_id"]) for record in self.documents.find({}, {"document_id": 1})
        )

    def close(self) -> None:
        self.client.close()

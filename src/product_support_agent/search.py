from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from azure.search.documents.aio import SearchClient as AsyncSearchClient
from azure.search.documents.indexes.aio import SearchIndexClient as AsyncSearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchAlgorithmMetric,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from product_support_agent.catalog import validate_source_url
from product_support_agent.documents import (
    CanonicalChunk,
    stable_chunk_id,
    stable_document_id,
)

INDEX_SCHEMA_VERSION = "1"
VECTOR_FIELD_NAME = "embedding_vector"
VECTOR_PROFILE_NAME = "product-support-vector-profile"
VECTOR_ALGORITHM_NAME = "product-support-hnsw"
DEFAULT_SEARCH_TOP = 5
MAX_SEARCH_TOP = 50
MAX_SEARCH_QUERY_CHARS = 4_096
MAX_PRODUCT_FILTER_COUNT = 100
MAX_INDEX_BATCH_SIZE = 500
_INDEX_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_QUERY_TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    source_id: str
    product_id: str
    source_url: HttpUrl
    title: str = Field(min_length=1, max_length=512)
    excerpt: str = Field(min_length=1, max_length=240)
    content_hash: str
    chunk_index: int = Field(ge=0)
    score: float

    @model_validator(mode="after")
    def validate_source_and_score(self) -> SearchResult:
        if not validate_source_url(str(self.source_url)):
            raise ValueError("search result source URL is not allowlisted")
        if self.source_id != self.product_id:
            raise ValueError("search result source ID must preserve its product ID")
        if self.document_id != stable_document_id(self.product_id, str(self.source_url)):
            raise ValueError("search result document ID does not match its canonical source")
        if self.chunk_id != stable_chunk_id(self.document_id, self.chunk_index):
            raise ValueError("search result chunk ID does not match its document and index")
        if not math.isfinite(self.score):
            raise ValueError("search result score must be finite")
        if not self.chunk_id or not self.source_id or not self.excerpt.strip():
            raise ValueError("search result is missing citation provenance")
        return self


class SearchProvider(Protocol):
    async def replace_document(
        self,
        document_id: str,
        chunks: Sequence[CanonicalChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...

    async def delete_document(self, document_id: str) -> None: ...

    async def search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top: int = DEFAULT_SEARCH_TOP,
        product_ids: Sequence[str] | None = None,
    ) -> list[SearchResult]: ...


class SearchIndexError(RuntimeError):
    pass


def build_versioned_index_name(
    base_name: str,
    *,
    embedding_model_version: str,
    embedding_dimensions: int,
    schema_version: str = INDEX_SCHEMA_VERSION,
    parser_version: str,
) -> str:
    if not base_name.strip():
        raise ValueError("index base name cannot be empty")
    if not embedding_model_version.strip() or not parser_version.strip():
        raise ValueError("embedding model and parser versions are required")
    if embedding_dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")

    normalized_base = re.sub(r"[^a-z0-9-]+", "-", base_name.lower()).strip("-")
    if not normalized_base:
        raise ValueError("index base name contains no supported characters")
    version_material = (
        f"{schema_version}\0{parser_version}\0{embedding_model_version}\0{embedding_dimensions}"
    )
    version_hash = hashlib.sha256(version_material.encode()).hexdigest()[:10]
    suffix = (
        f"-s{schema_version.lower()}-p{parser_version.lower()}-"
        f"d{embedding_dimensions}-{version_hash}"
    )
    suffix = re.sub(r"[^a-z0-9-]+", "-", suffix).strip("-")
    available_base_length = 128 - len(suffix)
    if available_base_length < 1:
        raise ValueError("index version metadata exceeds the supported index name length")
    index_name = f"{normalized_base[:available_base_length].rstrip('-')}{suffix}"
    if not _INDEX_NAME_PATTERN.fullmatch(index_name):
        raise ValueError("generated index name is invalid")
    return index_name


def build_search_index(
    index_name: str,
    *,
    embedding_dimensions: int,
    embedding_metric: str = "cosine",
) -> SearchIndex:
    if not _INDEX_NAME_PATTERN.fullmatch(index_name):
        raise ValueError("index name must use lowercase letters, digits, or hyphens")
    if embedding_dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")
    try:
        metric = VectorSearchAlgorithmMetric(embedding_metric)
    except ValueError as error:
        raise ValueError("unsupported vector similarity metric") from error

    fields = [
        SimpleField(
            name="id",
            type=SearchFieldDataType.STRING,
            key=True,
            filterable=True,
        ),
        SimpleField(name="document_id", type=SearchFieldDataType.STRING, filterable=True),
        SimpleField(name="source_id", type=SearchFieldDataType.STRING, filterable=True),
        SimpleField(name="product_id", type=SearchFieldDataType.STRING, filterable=True),
        SimpleField(name="source_url", type=SearchFieldDataType.STRING),
        SearchableField(name="title", type=SearchFieldDataType.STRING),
        SearchableField(name="content", type=SearchFieldDataType.STRING),
        SimpleField(name="excerpt", type=SearchFieldDataType.STRING),
        SimpleField(name="content_hash", type=SearchFieldDataType.STRING, filterable=True),
        SimpleField(
            name="chunk_index",
            type=SearchFieldDataType.INT32,
            sortable=True,
        ),
        SimpleField(name="schema_version", type=SearchFieldDataType.STRING, filterable=True),
        SimpleField(name="parser_version", type=SearchFieldDataType.STRING, filterable=True),
        SimpleField(
            name="embedding_model_version",
            type=SearchFieldDataType.STRING,
            filterable=True,
        ),
        SearchField(
            name=VECTOR_FIELD_NAME,
            type=SearchFieldDataType.Collection(SearchFieldDataType.SINGLE),
            searchable=True,
            retrievable=False,
            vector_search_dimensions=embedding_dimensions,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name=VECTOR_ALGORITHM_NAME,
                parameters=HnswParameters(metric=metric),
            )
        ],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE_NAME,
                algorithm_configuration_name=VECTOR_ALGORITHM_NAME,
            )
        ],
    )
    return SearchIndex(name=index_name, fields=fields, vector_search=vector_search)


async def apply_search_index(
    client: AsyncSearchIndexClient,
    index: SearchIndex,
) -> SearchIndex:
    return await client.create_or_update_index(index=index)


def _validate_search_input(
    query_text: str,
    query_embedding: Sequence[float],
    *,
    top: int,
    embedding_dimensions: int,
    product_ids: Sequence[str] | None,
) -> tuple[list[float], list[str] | None]:
    if not query_text.strip() or len(query_text) > MAX_SEARCH_QUERY_CHARS:
        raise ValueError(f"query text must contain 1 to {MAX_SEARCH_QUERY_CHARS} characters")
    if not 1 <= top <= MAX_SEARCH_TOP:
        raise ValueError(f"top must be between 1 and {MAX_SEARCH_TOP}")
    vector = [float(value) for value in query_embedding]
    if len(vector) != embedding_dimensions:
        raise ValueError("query embedding dimensions do not match the index")
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("query embedding values must be finite")

    normalized_product_ids: list[str] | None = None
    if product_ids is not None:
        normalized_product_ids = list(
            dict.fromkeys(product_id.strip() for product_id in product_ids)
        )
        if len(normalized_product_ids) > MAX_PRODUCT_FILTER_COUNT:
            raise ValueError(
                f"product ID filters cannot contain more than {MAX_PRODUCT_FILTER_COUNT} values"
            )
        if any(not product_id for product_id in normalized_product_ids):
            raise ValueError("product ID filters cannot contain empty values")
    return vector, normalized_product_ids


def _validate_document_embeddings(
    document_id: str,
    chunks: Sequence[CanonicalChunk],
    embeddings: Sequence[Sequence[float]],
    *,
    embedding_dimensions: int,
) -> list[list[float]]:
    if not document_id.strip():
        raise ValueError("document ID cannot be empty")
    if len(chunks) != len(embeddings):
        raise ValueError("each indexed chunk must have one embedding")
    chunk_ids: set[str] = set()
    normalized_embeddings: list[list[float]] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        if chunk.document_id != document_id:
            raise ValueError("all chunks must belong to the replaced document")
        if chunk.chunk_id in chunk_ids:
            raise ValueError("chunk IDs must be unique within a document")
        chunk_ids.add(chunk.chunk_id)
        vector = [float(value) for value in embedding]
        if len(vector) != embedding_dimensions:
            raise ValueError("chunk embedding dimensions do not match the index")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("chunk embedding values must be finite")
        normalized_embeddings.append(vector)
    return normalized_embeddings


def _odata_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _product_filter(product_ids: Sequence[str] | None) -> str | None:
    if product_ids is None:
        return None
    expressions = [f"product_id eq {_odata_string(value)}" for value in product_ids]
    return " or ".join(expressions)


def _document_filter(document_id: str) -> str:
    return f"document_id eq {_odata_string(document_id)}"


def _index_payload(
    chunk: CanonicalChunk,
    embedding: Sequence[float],
    *,
    embedding_model_version: str,
) -> dict[str, str | int | list[float]]:
    return {
        "id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "source_id": chunk.source_id,
        "product_id": chunk.product_id,
        "source_url": str(chunk.source_url),
        "title": chunk.title,
        "content": chunk.content,
        "excerpt": chunk.excerpt,
        "content_hash": chunk.content_hash,
        "chunk_index": chunk.chunk_index,
        "schema_version": chunk.schema_version,
        "parser_version": chunk.parser_version,
        "embedding_model_version": embedding_model_version,
        VECTOR_FIELD_NAME: list(embedding),
    }


def _check_indexing_results(results: Sequence[object], operation: str) -> None:
    failures = [
        getattr(result, "status_code", None)
        for result in results
        if not getattr(result, "succeeded", False)
    ]
    if failures:
        statuses = ", ".join(str(status) for status in failures)
        raise SearchIndexError(
            f"Azure AI Search {operation} failed for {len(failures)} item(s): {statuses}"
        )


class InMemorySearchProvider:
    def __init__(
        self,
        *,
        embedding_dimensions: int,
    ) -> None:
        if embedding_dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.embedding_dimensions = embedding_dimensions
        self._chunks: dict[str, tuple[CanonicalChunk, list[float]]] = {}

    async def replace_document(
        self,
        document_id: str,
        chunks: Sequence[CanonicalChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        vectors = _validate_document_embeddings(
            document_id,
            chunks,
            embeddings,
            embedding_dimensions=self.embedding_dimensions,
        )
        retained_ids = {chunk.chunk_id for chunk in chunks}
        stale_ids = [
            chunk_id
            for chunk_id, (chunk, _) in self._chunks.items()
            if chunk.document_id == document_id and chunk_id not in retained_ids
        ]
        for chunk_id in stale_ids:
            del self._chunks[chunk_id]
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._chunks[chunk.chunk_id] = (chunk, vector)

    async def delete_document(self, document_id: str) -> None:
        stale_ids = [
            chunk_id
            for chunk_id, (chunk, _) in self._chunks.items()
            if chunk.document_id == document_id
        ]
        for chunk_id in stale_ids:
            del self._chunks[chunk_id]

    async def search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top: int = DEFAULT_SEARCH_TOP,
        product_ids: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        vector, filters = _validate_search_input(
            query_text,
            query_embedding,
            top=top,
            embedding_dimensions=self.embedding_dimensions,
            product_ids=product_ids,
        )
        if filters == []:
            return []

        candidates = [
            (chunk, embedding)
            for chunk, embedding in self._chunks.values()
            if filters is None or chunk.product_id in filters
        ]
        if not candidates:
            return []

        terms = {term.casefold() for term in _QUERY_TOKEN_PATTERN.findall(query_text)}
        keyword_scores = {
            chunk.chunk_id: sum(
                term in f"{chunk.title} {chunk.content}".casefold() for term in terms
            )
            for chunk, _ in candidates
        }
        keyword_rank = {
            chunk_id: rank
            for rank, (chunk_id, score) in enumerate(
                sorted(
                    ((chunk_id, score) for chunk_id, score in keyword_scores.items() if score),
                    key=lambda item: (-item[1], item[0]),
                ),
                start=1,
            )
        }
        vector_rank = {
            chunk_id: rank
            for rank, (chunk_id, _) in enumerate(
                sorted(
                    (
                        (chunk.chunk_id, _cosine_similarity(embedding, vector))
                        for chunk, embedding in candidates
                    ),
                    key=lambda item: (-item[1], item[0]),
                ),
                start=1,
            )
        }

        ranked: list[tuple[float, CanonicalChunk]] = []
        for chunk, _ in candidates:
            score = 0.0
            if chunk.chunk_id in keyword_rank:
                score += 1.0 / (60 + keyword_rank[chunk.chunk_id])
            if chunk.chunk_id in vector_rank:
                score += 1.0 / (60 + vector_rank[chunk.chunk_id])
            ranked.append((score, chunk))

        ranked.sort(key=lambda result: (-result[0], result[1].chunk_id))
        return [
            SearchResult(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source_id=chunk.source_id,
                product_id=chunk.product_id,
                source_url=chunk.source_url,
                title=chunk.title,
                excerpt=chunk.excerpt,
                content_hash=chunk.content_hash,
                chunk_index=chunk.chunk_index,
                score=score,
            )
            for score, chunk in ranked[:top]
        ]


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class AzureAISearchProvider:
    def __init__(
        self,
        client: AsyncSearchClient,
        *,
        embedding_dimensions: int,
        embedding_model_version: str,
    ) -> None:
        if embedding_dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        if not embedding_model_version.strip():
            raise ValueError("embedding model version is required")
        self.client = client
        self.embedding_dimensions = embedding_dimensions
        self.embedding_model_version = embedding_model_version

    async def replace_document(
        self,
        document_id: str,
        chunks: Sequence[CanonicalChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        vectors = _validate_document_embeddings(
            document_id,
            chunks,
            embeddings,
            embedding_dimensions=self.embedding_dimensions,
        )
        existing_ids = await self._find_document_chunk_ids(document_id)
        new_ids = {chunk.chunk_id for chunk in chunks}
        for offset in range(0, len(chunks), MAX_INDEX_BATCH_SIZE):
            documents = [
                _index_payload(chunk, vector, embedding_model_version=self.embedding_model_version)
                for chunk, vector in zip(
                    chunks[offset : offset + MAX_INDEX_BATCH_SIZE],
                    vectors[offset : offset + MAX_INDEX_BATCH_SIZE],
                    strict=True,
                )
            ]
            results = await self.client.merge_or_upload_documents(documents=documents)
            _check_indexing_results(results, "upsert")

        stale_ids = sorted(existing_ids - new_ids)
        for offset in range(0, len(stale_ids), MAX_INDEX_BATCH_SIZE):
            documents = [
                {"id": chunk_id} for chunk_id in stale_ids[offset : offset + MAX_INDEX_BATCH_SIZE]
            ]
            results = await self.client.delete_documents(documents=documents)
            _check_indexing_results(results, "delete")

    async def delete_document(self, document_id: str) -> None:
        existing_ids = sorted(await self._find_document_chunk_ids(document_id))
        for offset in range(0, len(existing_ids), MAX_INDEX_BATCH_SIZE):
            documents = [
                {"id": chunk_id}
                for chunk_id in existing_ids[offset : offset + MAX_INDEX_BATCH_SIZE]
            ]
            results = await self.client.delete_documents(documents=documents)
            _check_indexing_results(results, "delete")

    async def search(
        self,
        query_text: str,
        query_embedding: Sequence[float],
        *,
        top: int = DEFAULT_SEARCH_TOP,
        product_ids: Sequence[str] | None = None,
    ) -> list[SearchResult]:
        vector, filters = _validate_search_input(
            query_text,
            query_embedding,
            top=top,
            embedding_dimensions=self.embedding_dimensions,
            product_ids=product_ids,
        )
        if filters == []:
            return []

        vector_query = VectorizedQuery(
            vector=vector,
            k_nearest_neighbors=max(top * 4, DEFAULT_SEARCH_TOP),
            fields=VECTOR_FIELD_NAME,
        )
        results = await self.client.search(
            search_text=query_text,
            vector_queries=[vector_query],
            filter=_product_filter(filters),
            select=[
                "id",
                "document_id",
                "source_id",
                "product_id",
                "source_url",
                "title",
                "excerpt",
                "content_hash",
                "chunk_index",
            ],
            top=top,
        )
        return [
            SearchResult(
                chunk_id=str(result["id"]),
                document_id=str(result["document_id"]),
                source_id=str(result["source_id"]),
                product_id=str(result["product_id"]),
                source_url=HttpUrl(str(result["source_url"])),
                title=str(result["title"]),
                excerpt=str(result["excerpt"]),
                content_hash=str(result["content_hash"]),
                chunk_index=int(result["chunk_index"]),
                score=float(result["@search.score"]),
            )
            async for result in results
        ]

    async def _find_document_chunk_ids(self, document_id: str) -> set[str]:
        results = await self.client.search(
            search_text="*",
            filter=_document_filter(document_id),
            select=["id"],
        )
        return {str(result["id"]) async for result in results}

    async def close(self) -> None:
        await self.client.close()

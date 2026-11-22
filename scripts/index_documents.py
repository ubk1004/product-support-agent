"""Embed canonical chunks from MongoDB and index them into an Azure AI Search index.

Creates or updates the versioned index, then reprocesses every stored canonical document.
Unchanged documents are re-uploaded idempotently (stable chunk IDs). Run after
`run_source_ingestion.py`; rerun whenever new documents are stored.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient

from product_support_agent.config import ModelAndSearchSettings, Settings
from product_support_agent.document_store import MongoCanonicalDocumentRepository
from product_support_agent.documents import HTML_PARSER_VERSION
from product_support_agent.embeddings import OpenAICompatibleEmbedder
from product_support_agent.indexing import DocumentIndexingService
from product_support_agent.search import (
    AzureAISearchProvider,
    apply_search_index,
    build_search_index,
    build_versioned_index_name,
)


def index_name_for(base: str, settings: ModelAndSearchSettings) -> str:
    return build_versioned_index_name(
        base,
        embedding_model_version=settings.embedding_model_version,
        embedding_dimensions=settings.embedding_dimensions,
        parser_version=HTML_PARSER_VERSION,
    )


def build_embedder(settings: ModelAndSearchSettings) -> OpenAICompatibleEmbedder:
    return OpenAICompatibleEmbedder(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key.get_secret_value(),
        deployment=settings.embedding_deployment,
        model_version=settings.embedding_model_version,
        dimensions=settings.embedding_dimensions,
    )


async def _run(index_base: str) -> int:
    app_settings = Settings()
    settings = ModelAndSearchSettings()  # type: ignore[call-arg]
    mongo_uri = (
        app_settings.mongodb_uri.get_secret_value().strip() if app_settings.mongodb_uri else ""
    )
    if not mongo_uri:
        print("PRODUCT_SUPPORT_MONGODB_URI must be set", file=sys.stderr)
        return 2

    index_name = index_name_for(index_base, settings)
    credential = AzureKeyCredential(settings.search_key.get_secret_value())
    index_client = SearchIndexClient(settings.search_endpoint, credential)
    try:
        await apply_search_index(
            index_client,
            build_search_index(index_name, embedding_dimensions=settings.embedding_dimensions),
        )
    finally:
        await index_client.close()

    repository = MongoCanonicalDocumentRepository(mongo_uri)
    provider = AzureAISearchProvider(
        SearchClient(settings.search_endpoint, index_name, credential),
        embedding_dimensions=settings.embedding_dimensions,
        embedding_model_version=settings.embedding_model_version,
    )
    try:
        service = DocumentIndexingService(
            repository=repository,
            search=provider,
            embedder=build_embedder(settings),
        )
        count = await service.reconcile_all()
    finally:
        await provider.close()
        repository.close()
    print(f"Indexed {count} canonical documents into {index_name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index-base",
        default=None,
        help="index base name (defaults to PRODUCT_SUPPORT_SEARCH_DEMO_INDEX_BASE)",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    base = args.index_base or ModelAndSearchSettings().demo_index_base  # type: ignore[call-arg]
    return asyncio.run(_run(base))


if __name__ == "__main__":
    raise SystemExit(main())

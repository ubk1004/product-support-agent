from __future__ import annotations

import asyncio
import os
import re
import sys

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes.aio import SearchIndexClient

from product_support_agent.documents import HTML_PARSER_VERSION
from product_support_agent.search import (
    INDEX_SCHEMA_VERSION,
    apply_search_index,
    build_search_index,
    build_versioned_index_name,
)


def _required_environment_variable(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be set")
    return value


async def _apply(
    *,
    endpoint: str,
    admin_key: str,
    index_name: str,
    embedding_dimensions: int,
) -> str:
    client = SearchIndexClient(endpoint, AzureKeyCredential(admin_key))
    try:
        result = await apply_search_index(
            client,
            build_search_index(
                index_name,
                embedding_dimensions=embedding_dimensions,
            ),
        )
        return result.name
    finally:
        await client.close()


def main() -> int:
    try:
        endpoint = _required_environment_variable("PRODUCT_SUPPORT_SEARCH_ENDPOINT")
        admin_key = _required_environment_variable("PRODUCT_SUPPORT_SEARCH_ADMIN_KEY")
        embedding_model_version = _required_environment_variable(
            "PRODUCT_SUPPORT_SEARCH_EMBEDDING_MODEL_VERSION"
        )
        index_base = _required_environment_variable("PRODUCT_SUPPORT_SEARCH_TEST_INDEX_BASE")
        dimensions_text = _required_environment_variable(
            "PRODUCT_SUPPORT_SEARCH_EMBEDDING_DIMENSIONS"
        )
        if not re.search(r"(?:^|-)test(?:-|$)", index_base.lower()):
            raise ValueError("the index base name must identify a dedicated test index")
        try:
            dimensions = int(dimensions_text)
        except ValueError as error:
            raise ValueError("embedding dimensions must be a positive integer") from error

        index_name = build_versioned_index_name(
            index_base,
            embedding_model_version=embedding_model_version,
            embedding_dimensions=dimensions,
            schema_version=INDEX_SCHEMA_VERSION,
            parser_version=HTML_PARSER_VERSION,
        )
        applied_name = asyncio.run(
            _apply(
                endpoint=endpoint,
                admin_key=admin_key,
                index_name=index_name,
                embedding_dimensions=dimensions,
            )
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    print(f"Applied Azure AI Search test index: {applied_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

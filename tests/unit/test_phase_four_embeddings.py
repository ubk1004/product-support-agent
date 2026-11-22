import asyncio
import json

import httpx
import pytest

from product_support_agent.embeddings import OpenAICompatibleEmbedder
from product_support_agent.indexing import DocumentIndexingError


def embedder(handler, **overrides) -> OpenAICompatibleEmbedder:
    values = {
        "base_url": "https://example.services.ai.azure.com/openai/v1/",
        "api_key": "test-key",
        "deployment": "text-embedding-3-small",
        "model_version": "text-embedding-3-small",
        "dimensions": 2,
        "transport": httpx.MockTransport(handler),
    }
    values.update(overrides)
    return OpenAICompatibleEmbedder(**values)


def ok(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(body["input"]))]
    return httpx.Response(200, json={"data": list(reversed(data))})


def test_embeds_in_order_with_deployment_as_model_and_api_key_header(monkeypatch) -> None:
    seen = []

    def handler(request):
        seen.append(request)
        return ok(request)

    vectors = asyncio.run(embedder(handler).embed_documents(["a", "b", "c"]))

    assert vectors == [[0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]
    assert str(seen[0].url) == "https://example.services.ai.azure.com/openai/v1/embeddings"
    assert seen[0].headers["api-key"] == "test-key"
    assert json.loads(seen[0].content)["model"] == "text-embedding-3-small"


def test_batches_large_inputs(monkeypatch) -> None:
    sizes = []

    def handler(request):
        sizes.append(len(json.loads(request.content)["input"]))
        return ok(request)

    asyncio.run(embedder(handler).embed_documents(["x"] * 130))
    assert sizes == [64, 64, 2]


def test_retries_429_then_succeeds(monkeypatch) -> None:
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("product_support_agent.embeddings.asyncio.sleep", sleep)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "3"})
        return ok(request)

    assert asyncio.run(embedder(handler).embed_query("q")) == [0.0, 1.0]
    assert sleeps == [3.0]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401),
        httpx.Response(200, json={"nope": []}),
        httpx.Response(200, json={"data": []}),
    ],
)
def test_failures_raise_indexing_error_without_leaking_key(response) -> None:
    with pytest.raises(DocumentIndexingError) as error:
        asyncio.run(embedder(lambda request: response).embed_documents(["a"]))
    assert "test-key" not in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": "http://example.com/v1"},
        {"api_key": ""},
        {"dimensions": 0},
        {"deployment": " "},
    ],
)
def test_rejects_unsafe_or_incomplete_configuration(overrides) -> None:
    with pytest.raises(ValueError):
        embedder(ok, **overrides)


def test_allows_loopback_gateway() -> None:
    assert embedder(ok, base_url="http://127.0.0.1:4000/v1").dimensions == 2

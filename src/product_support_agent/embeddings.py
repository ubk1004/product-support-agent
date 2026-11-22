from __future__ import annotations

import asyncio
import secrets
from collections.abc import Sequence

import httpx

from product_support_agent.indexing import DocumentIndexingError

MAX_BATCH_SIZE = 64
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


class OpenAICompatibleEmbedder:
    """Embedding provider for any OpenAI-compatible `/embeddings` endpoint.

    The base URL points at Microsoft Foundry today and at LiteLLM when the gateway is added;
    only configuration changes. The deployment name is sent as the model.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        deployment: str,
        model_version: str,
        dimensions: int,
        auth_header: str = "api-key",
        timeout_seconds: float = 30.0,
        max_attempts: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1"):
            raise ValueError("embedding base URL must be HTTPS (or loopback for a local gateway)")
        if not api_key or not deployment.strip() or not model_version.strip() or dimensions <= 0:
            raise ValueError("API key, deployment, model version, and dimensions are required")
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._headers = {auth_header: api_key}
        self._deployment = deployment
        self._model_version = model_version
        self._dimensions = dimensions
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts
        self._transport = transport

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for offset in range(0, len(texts), MAX_BATCH_SIZE):
                batch = list(texts[offset : offset + MAX_BATCH_SIZE])
                vectors.extend(await self._embed_batch(client, batch))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]

    async def _embed_batch(
        self,
        client: httpx.AsyncClient,
        batch: list[str],
    ) -> list[list[float]]:
        payload = {"model": self._deployment, "input": batch}
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await client.post(self._url, headers=self._headers, json=payload)
            except httpx.HTTPError as error:
                if attempt >= self._max_attempts:
                    raise DocumentIndexingError("embedding service is unreachable") from error
                await asyncio.sleep(_delay(attempt, None))
                continue
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_attempts:
                await asyncio.sleep(_delay(attempt, response.headers.get("retry-after")))
                continue
            if response.status_code != 200:
                raise DocumentIndexingError(
                    f"embedding request failed: HTTP {response.status_code}"
                )
            return _parse(response, expected=len(batch))
        raise DocumentIndexingError("embedding request failed")


def _delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), 60.0)
        except ValueError:
            pass
    return min(2.0**attempt, 16.0) + secrets.randbelow(251) / 1000.0


def _parse(response: httpx.Response, *, expected: int) -> list[list[float]]:
    try:
        items = response.json()["data"]
        ordered = sorted(items, key=lambda item: int(item["index"]))
        vectors = [[float(value) for value in item["embedding"]] for item in ordered]
    except (KeyError, TypeError, ValueError) as error:
        raise DocumentIndexingError("embedding response was malformed") from error
    if len(vectors) != expected:
        raise DocumentIndexingError("embedding response had an unexpected item count")
    return vectors

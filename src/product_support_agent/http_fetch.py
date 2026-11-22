from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx

from product_support_agent.catalog import is_login_content, is_login_redirect, validate_source_url

FetchOutcome = Literal["success", "not_modified", "skipped", "failed"]


@dataclass(frozen=True)
class FetchResponse:
    outcome: FetchOutcome
    reason_category: str
    http_status: int | None
    attempt_count: int
    body: bytes = b""
    content_type: str = ""
    etag: str | None = None
    last_modified: str | None = None


def retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            date = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT")
            now = datetime.now(UTC)
            delay = (date.replace(tzinfo=UTC) - now).total_seconds()
            return max(0.0, delay)
        except ValueError:
            return None


def retry_delay(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return retry_after
    base = min(2.0**attempt, 8.0)
    jitter = secrets.randbelow(251) / 1000.0
    return base + jitter


class BoundedFetcher:
    """Anonymous, allowlisted, redirect-free GET with bounded retries and downloads."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 4,
        timeout_seconds: float = 10.0,
        max_download_bytes: int = 4_194_304,
        user_agent: str | None = None,
        max_retry_after_seconds: float | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.transport = transport
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.user_agent = user_agent
        self.max_retry_after_seconds = max_retry_after_seconds

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        check_login_content: bool = True,
        max_attempts: int | None = None,
    ) -> FetchResponse:
        if not validate_source_url(url):
            return FetchResponse("skipped", "invalid_url", None, 0)
        attempts = min(max_attempts or self.max_attempts, self.max_attempts)
        request_headers = dict(headers or {})
        if self.user_agent:
            request_headers["user-agent"] = self.user_agent

        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            for attempt in range(1, attempts + 1):
                try:
                    async with client.stream("GET", url, headers=request_headers) as response:
                        status = response.status_code
                        if is_login_redirect(response):
                            return FetchResponse("skipped", "protected_redirect", status, attempt)
                        if status in (401, 403):
                            return FetchResponse("skipped", f"protected_{status}", status, attempt)
                        if status == 304:
                            return FetchResponse(
                                "not_modified",
                                "not_modified",
                                304,
                                attempt,
                                etag=response.headers.get("etag"),
                                last_modified=response.headers.get("last-modified"),
                            )
                        if status == 429:
                            retry_after = retry_after_seconds(response)
                            if (
                                self.max_retry_after_seconds is not None
                                and retry_after is not None
                                and retry_after > self.max_retry_after_seconds
                            ):
                                return FetchResponse("failed", "rate_limited", 429, attempt)
                            if attempt >= attempts:
                                return FetchResponse("failed", "retry_limit", 429, attempt)
                            await asyncio.sleep(retry_delay(attempt, retry_after))
                            continue
                        if 500 <= status < 600:
                            if attempt >= attempts:
                                return FetchResponse("failed", "server_error", status, attempt)
                            await asyncio.sleep(retry_delay(attempt, None))
                            continue
                        if status not in range(200, 300):
                            return FetchResponse("failed", f"http_{status}", status, attempt)

                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(content) + len(chunk) > self.max_download_bytes:
                                return FetchResponse("skipped", "oversized", status, attempt)
                            content.extend(chunk)
                        if check_login_content:
                            text = content.decode(response.encoding or "utf-8", errors="replace")
                            if is_login_content(text):
                                return FetchResponse(
                                    "skipped", "protected_login_content", status, attempt
                                )
                        return FetchResponse(
                            "success",
                            "downloaded",
                            status,
                            attempt,
                            body=bytes(content),
                            content_type=response.headers.get("content-type", ""),
                            etag=response.headers.get("etag"),
                            last_modified=response.headers.get("last-modified"),
                        )
                except httpx.HTTPError:
                    if attempt >= attempts:
                        return FetchResponse("failed", "network_error", None, attempt)
                    await asyncio.sleep(retry_delay(attempt, None))
        return FetchResponse("failed", "retry_limit", None, attempts)

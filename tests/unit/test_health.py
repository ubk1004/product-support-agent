import asyncio
import uuid

import httpx

from product_support_agent.api.app import app


def test_health_endpoint_returns_process_status() -> None:
    async def get_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/healthz")

    response = asyncio.run(get_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    request_id = response.headers["x-request-id"]
    assert str(uuid.UUID(request_id)) == request_id

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from product_support_agent.catalog import CatalogClient
from product_support_agent.config import Settings
from product_support_agent.logging import configure_redacted_logging
from product_support_agent.orchestration import PhaseTwoService
from product_support_agent.queue import InMemoryQueue
from product_support_agent.request_context import create_request_id, request_id_context
from product_support_agent.store import InMemoryIngestionStore

configure_redacted_logging()

app = FastAPI(title="Product Support Agent")

settings = Settings()
_phase_two_store = InMemoryIngestionStore()
_phase_two_queue = InMemoryQueue()
_phase_two_catalog = CatalogClient(
    listing_url=settings.catalog_listing_url,
    search_url=settings.catalog_search_url,
    feed_url=settings.catalog_feed_url,
    max_pages=settings.catalog_max_pages,
    timeout_seconds=settings.catalog_timeout_seconds,
    max_response_bytes=settings.catalog_max_response_bytes,
)
phase_two_service = PhaseTwoService(
    catalog=_phase_two_catalog,
    store=_phase_two_store,
    queue=_phase_two_queue,
    manifest_seed=settings.manifest_seed,
    max_demo_products=settings.max_demo_products,
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = create_request_id()
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context.reset(token)


app.add_middleware(RequestIdMiddleware)


@app.get("/healthz", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/catalog/manifest", tags=["catalog"])
async def catalog_manifest() -> dict[str, object]:
    if phase_two_service.manifest is None:
        return {"manifest": None, "catalog": phase_two_service.catalog_outcome}
    return {
        "manifest": phase_two_service.manifest.model_dump(mode="json"),
        "catalog": phase_two_service.catalog_outcome,
    }


@app.get("/ingestion/runs/{run_id}", tags=["ingestion"])
async def ingestion_run(run_id: str) -> dict[str, object]:
    run = _phase_two_store.runs.get(run_id)
    if run is None:
        return {"run": None}
    products = [
        status.model_dump(mode="json")
        for (status_run_id, _), status in _phase_two_store.products.items()
        if status_run_id == run_id
    ]
    return {"run": run.model_dump(mode="json"), "products": products}

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from pymongo.errors import PyMongoError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from product_support_agent.catalog import CatalogClient
from product_support_agent.chat import (
    ChatExecution,
    ChatModelUnavailable,
    ChatService,
    SearchUnavailable,
    UncoveredProductError,
    build_chat_service,
)
from product_support_agent.config import Settings
from product_support_agent.coverage import CoverageReport, build_coverage_report, load_manifest
from product_support_agent.fetch_state import FetchStateRecord, MongoFetchStateStore
from product_support_agent.logging import configure_redacted_logging
from product_support_agent.orchestration import PhaseTwoService
from product_support_agent.queue import InMemoryQueue
from product_support_agent.request_context import create_request_id, request_id_context
from product_support_agent.sources import load_source_map
from product_support_agent.store import InMemoryIngestionStore
from product_support_agent.telemetry import (
    TelemetrySettings,
    configure_telemetry,
    current_span_set,
    instrument_fastapi,
    record_chat,
)

configure_redacted_logging()
logger = logging.getLogger(__name__)
_telemetry = configure_telemetry(TelemetrySettings(), service_name="product-support-api")

CHAT_TIMEOUT_SECONDS = 30.0
MAX_CONCURRENT_CHAT_REQUESTS = 4
_chat_concurrency = asyncio.Semaphore(MAX_CONCURRENT_CHAT_REQUESTS)
_chat_service: ChatService | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    if _chat_service is not None:
        await _chat_service.close()
    _telemetry.shutdown()


app = FastAPI(title="Product Support Agent", lifespan=lifespan)
instrument_fastapi(app, _telemetry)

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


def _read_fetch_state() -> list[FetchStateRecord] | None:
    mongo_uri = settings.mongodb_uri.get_secret_value().strip() if settings.mongodb_uri else ""
    if not mongo_uri:
        return None
    store = MongoFetchStateStore(mongo_uri)
    try:
        return store.list_all()
    except PyMongoError:
        logger.warning("fetch state unavailable for coverage report")
        return None
    finally:
        store.close()


fetch_state_reader: Callable[[], list[FetchStateRecord] | None] = _read_fetch_state


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


@app.get("/catalog/coverage", tags=["catalog"])
async def catalog_coverage() -> CoverageReport:
    """Which manifest products have indexed documentation. Metadata only."""
    try:
        manifest = load_manifest(Path(settings.manifest_path))
        source_map = load_source_map(Path(settings.source_map_path))
    except (OSError, ValueError) as error:
        logger.warning("coverage inputs unavailable: %s", type(error).__name__)
        raise HTTPException(status_code=503, detail="coverage data unavailable") from error
    records = await asyncio.to_thread(fetch_state_reader)
    return build_coverage_report(manifest, source_map, records, retrieval_enabled=True)


def _chat_outcome(execution: ChatExecution) -> str:
    if execution.content_filtered:
        return "content_filtered"
    return "grounded" if execution.response.grounded else "no_evidence"


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = build_chat_service(settings)
    return _chat_service


@app.post("/chat", tags=["chat"])
async def chat(payload: dict[str, object]) -> dict[str, object]:
    from product_support_agent.chat import ChatRequest

    try:
        chat_request = ChatRequest.model_validate(payload)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="invalid chat request") from error

    started_at = time.perf_counter()
    request_id = request_id_context.get()
    current_span_set({"psa.request_id": request_id, "psa.history_turns": len(chat_request.history)})
    try:
        async with _chat_concurrency:
            service = get_chat_service()
            execution = await asyncio.wait_for(
                service.answer(
                    chat_request.message,
                    chat_request.product_ids,
                    chat_request.history,
                ),
                timeout=CHAT_TIMEOUT_SECONDS,
            )
    except UncoveredProductError as error:
        _finish_chat("uncovered_product", started_at, logging.INFO)
        raise HTTPException(
            status_code=422,
            detail={"code": "uncovered_product"},
        ) from error
    except SearchUnavailable as error:
        _finish_chat("search_unavailable", started_at, logging.WARNING)
        raise HTTPException(status_code=503, detail="search service unavailable") from error
    except ChatModelUnavailable as error:
        _finish_chat("model_unavailable", started_at, logging.WARNING)
        raise HTTPException(status_code=502, detail="chat model unavailable") from error
    except TimeoutError as error:
        _finish_chat("timeout", started_at, logging.WARNING)
        raise HTTPException(status_code=504, detail="chat request timed out") from error
    except ValidationError as error:
        _finish_chat("configuration_error", started_at, logging.ERROR)
        raise HTTPException(status_code=503, detail="chat service unavailable") from error

    _finish_chat(
        _chat_outcome(execution),
        started_at,
        logging.INFO,
        citations=len(execution.response.citations),
        input_tokens=execution.input_tokens,
        output_tokens=execution.output_tokens,
    )
    response = execution.response.model_copy(update={"request_id": request_id})
    return response.model_dump(mode="json")


def _finish_chat(
    outcome: str,
    started_at: float,
    level: int,
    *,
    citations: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Log, measure, and tag the request span with one metadata-only outcome."""
    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.log(
        level,
        "chat completed outcome=%s latency_ms=%d input_tokens=%s output_tokens=%s",
        outcome,
        round(duration_ms),
        input_tokens,
        output_tokens,
    )
    record_chat(
        outcome,
        duration_ms,
        citations=citations,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    current_span_set({"psa.chat.outcome": outcome, "psa.chat.citations": citations})

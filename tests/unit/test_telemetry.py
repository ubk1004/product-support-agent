import asyncio
import logging

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from product_support_agent import telemetry
from product_support_agent.chat import ChatRun, ChatService, ChatTools, EmbeddedSearchRetriever
from product_support_agent.documents import stable_chunk_id, stable_document_id
from product_support_agent.product_catalog import CatalogProduct, ProductCatalog
from product_support_agent.search import SearchResult
from product_support_agent.telemetry import (
    Exporters,
    TelemetrySettings,
    configure_telemetry,
    exporters_from_settings,
    instrument_fastapi,
    omit_personal_attributes,
)

SECRET_QUESTION = "How do I reset the admin password for tenant ACME-7781?"
SOURCE_URL = "https://docs.microfocus.com/doc/telemetry/test"


def settings(**values: object) -> TelemetrySettings:
    return TelemetrySettings.model_validate(values)


def test_no_exporters_means_no_providers_are_installed() -> None:
    result = configure_telemetry(settings(), service_name="test", set_global=False)

    assert result.enabled is False


def test_disabled_flag_wins_over_configured_endpoint() -> None:
    result = configure_telemetry(
        settings(PRODUCT_SUPPORT_TELEMETRY_ENABLED=False, OTEL_EXPORTER_OTLP_ENDPOINT="http://x"),
        service_name="test",
        set_global=False,
    )

    assert result.enabled is False


def test_otlp_endpoint_creates_http_exporters_for_every_signal() -> None:
    exporters = exporters_from_settings(
        settings(OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318/")
    )

    assert len(exporters.spans) == len(exporters.metrics) == len(exporters.logs) == 1
    assert exporters.spans[0]._endpoint == "http://collector:4318/v1/traces"  # type: ignore[attr-defined]


def test_blank_values_are_treated_as_unset() -> None:
    exporters = exporters_from_settings(
        settings(OTEL_EXPORTER_OTLP_ENDPOINT="  ", APPLICATIONINSIGHTS_CONNECTION_STRING="")
    )

    assert not exporters


def test_azure_monitor_exporters_use_managed_identity_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, object]] = []

    class FakeExporter:
        def __init__(self, **options: object) -> None:
            created.append(options)

    import azure.monitor.opentelemetry.exporter as azure_monitor

    for name in (
        "AzureMonitorTraceExporter",
        "AzureMonitorMetricExporter",
        "AzureMonitorLogExporter",
    ):
        monkeypatch.setattr(azure_monitor, name, FakeExporter)

    exporters_from_settings(
        settings(
            APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=00000000-0000-0000-0000-000000000000",
            PRODUCT_SUPPORT_TELEMETRY_USE_MANAGED_IDENTITY=True,
            AZURE_CLIENT_ID="11111111-1111-1111-1111-111111111111",
        )
    )

    assert len(created) == 3
    assert all("credential" in options for options in created)


class Captured:
    def __init__(self) -> None:
        self.spans = InMemorySpanExporter()
        self.logs = InMemoryLogRecordExporter()
        self.metrics = InMemoryMetricReader()


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch):
    sink = Captured()
    result = configure_telemetry(
        settings(),
        service_name="test",
        exporters=Exporters(logs=[sink.logs]),
        set_global=False,
    )
    assert result.tracer_provider is not None
    result.tracer_provider.add_span_processor(SimpleSpanProcessor(sink.spans))
    monkeypatch.setattr(telemetry, "tracer", lambda: result.tracer_provider.get_tracer("test"))
    yield sink, result
    result.shutdown()


def search_result() -> SearchResult:
    document_id = stable_document_id("22", SOURCE_URL)
    return SearchResult(
        chunk_id=stable_chunk_id(document_id, 0),
        document_id=document_id,
        source_id="22",
        product_id="22",
        source_url=SOURCE_URL,
        title="Reset passwords",
        excerpt="Use the admin console to reset a password.",
        content_hash="a" * 64,
        chunk_index=0,
        score=1.0,
    )


class FakeEmbedder:
    async def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]


class FakeSearch:
    async def search(self, query_text, query_embedding, *, top, product_ids):
        return [search_result()]


class SearchingRunner:
    async def run(self, message: str, tools: ChatTools, history) -> ChatRun:
        await tools.search_documentation(message, None)
        return ChatRun("Use the admin console [E1].", 10, 5)


def test_chat_spans_carry_counts_but_never_the_question(captured, monkeypatch) -> None:
    import product_support_agent.chat as chat_module

    sink, result = captured
    monkeypatch.setattr(chat_module, "tracer", lambda: result.tracer_provider.get_tracer("test"))
    service = ChatService(
        runner=SearchingRunner(),
        retriever=EmbeddedSearchRetriever(embedder=FakeEmbedder(), search=FakeSearch()),
        catalog=ProductCatalog([CatalogProduct("22", "ValueEdge", "https://x/22", True)]),
    )

    asyncio.run(service.answer(SECRET_QUESTION, None))

    spans = {span.name: span for span in sink.spans.get_finished_spans()}
    assert {"psa.answer", "psa.tool.search_documentation", "psa.retrieve"} <= set(spans)
    assert spans["psa.retrieve"].attributes["psa.search.results"] == 1
    assert spans["psa.answer"].attributes["psa.evidence_items"] == 1
    for span in spans.values():
        flattened = " ".join(str(value) for value in (span.attributes or {}).values())
        assert "ACME-7781" not in flattened
        assert "password" not in flattened


def test_exported_logs_are_redacted(captured) -> None:
    sink, result = captured
    log = logging.getLogger("product_support_agent.telemetry_test")
    log.setLevel(logging.INFO)

    log.info("api_key=%s contact=%s", "super-secret-value", "person@example.com")
    assert result.logger_provider is not None
    result.logger_provider.force_flush()

    bodies = " ".join(str(item.log_record.body) for item in sink.logs.get_finished_logs())
    assert "super-secret-value" not in bodies
    assert "person@example.com" not in bodies
    assert "[REDACTED]" in bodies


def test_fastapi_server_spans_drop_client_addresses(captured) -> None:
    sink, result = captured
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    instrument_fastapi(app, result)

    async def call() -> None:
        transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 51234))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/ping", headers={"user-agent": "Mozilla/5.0 personal"})
            await client.get("/healthz")

    asyncio.run(call())

    server_spans = [span for span in sink.spans.get_finished_spans() if span.kind.name == "SERVER"]
    assert [span.name for span in server_spans] == ["GET /ping"]
    attributes = " ".join(str(value) for value in server_spans[0].attributes.values())
    assert "203.0.113.9" not in attributes
    assert "Mozilla/5.0 personal" not in attributes


def test_omit_personal_attributes_only_touches_known_keys() -> None:
    class FakeSpan:
        def __init__(self) -> None:
            self.attributes = {"client.address": "198.51.100.7", "http.route": "/chat"}

        def set_attribute(self, key: str, value: object) -> None:
            self.attributes[key] = value

    span = FakeSpan()
    omit_personal_attributes(span, {})  # type: ignore[arg-type]

    assert span.attributes == {"client.address": "[omitted]", "http.route": "/chat"}


def test_metric_helpers_do_not_raise_without_an_sdk_provider() -> None:
    telemetry.record_chat("grounded", 12.5, citations=2, input_tokens=10, output_tokens=4)
    telemetry.record_search(3.0, 5)
    telemetry.record_search(3.0, 0, failed=True)
    telemetry.record_ingestion_pages({"indexed": 3, "failed": 0})

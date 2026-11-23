"""OpenTelemetry traces, metrics, and logs for the API, the agent, and the ingestion job.

Telemetry is metadata only. Spans, metrics, and exported logs carry request IDs, outcomes,
counts, token totals, and durations. They never carry questions, answers, retrieved text, or
prompts. Agent Framework's sensitive-data capture is forced off here, and logs pass through the
same redaction filter as the console logs before export.

Exporters are chosen by environment:

* ``OTEL_EXPORTER_OTLP_ENDPOINT`` sends OTLP over HTTP (``/v1/traces``, ``/v1/metrics``,
  ``/v1/logs``), for example to the Aspire dashboard or Arize Phoenix.
* ``APPLICATIONINSIGHTS_CONNECTION_STRING`` sends to Azure Monitor. Set
  ``PRODUCT_SUPPORT_TELEMETRY_USE_MANAGED_IDENTITY=true`` to authenticate with a managed identity
  instead of the instrumentation key.

With neither set, no SDK providers are installed and the instrumentation calls are no-ops.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent_framework.observability import enable_instrumentation
from fastapi import FastAPI
from opentelemetry import _logs, metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from product_support_agent.logging import RedactingFilter

INSTRUMENTATION_NAME = "product_support_agent"

# Client address and user-agent attributes that the HTTP instrumentation records by default.
# They can identify a person, so they are overwritten before the span ends.
_PERSONAL_SPAN_ATTRIBUTES = (
    "client.address",
    "client.port",
    "network.peer.address",
    "network.peer.port",
    "http.client_ip",
    "net.peer.ip",
    "net.peer.port",
    "user_agent.original",
    "http.user_agent",
)
_OMITTED = "[omitted]"
_EXCLUDED_URLS = "healthz"

logger = logging.getLogger(__name__)


class TelemetrySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    enabled: bool = Field(default=True, validation_alias="PRODUCT_SUPPORT_TELEMETRY_ENABLED")
    otlp_endpoint: str | None = Field(default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    azure_monitor_connection_string: SecretStr | None = Field(
        default=None, validation_alias="APPLICATIONINSIGHTS_CONNECTION_STRING"
    )
    use_managed_identity: bool = Field(
        default=False, validation_alias="PRODUCT_SUPPORT_TELEMETRY_USE_MANAGED_IDENTITY"
    )
    managed_identity_client_id: str | None = Field(default=None, validation_alias="AZURE_CLIENT_ID")
    console: bool = Field(default=False, validation_alias="PRODUCT_SUPPORT_TELEMETRY_CONSOLE")
    metric_export_interval_ms: int = Field(
        default=15_000, gt=0, validation_alias="PRODUCT_SUPPORT_TELEMETRY_METRIC_INTERVAL_MS"
    )
    environment: str = Field(default="local", validation_alias="PRODUCT_SUPPORT_ENVIRONMENT")

    @field_validator("otlp_endpoint", "managed_identity_client_id", mode="before")
    @classmethod
    def blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("azure_monitor_connection_string", mode="before")
    @classmethod
    def blank_secret_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


@dataclass(frozen=True)
class Exporters:
    spans: list[SpanExporter] = field(default_factory=list)
    metrics: list[MetricExporter] = field(default_factory=list)
    logs: list[LogRecordExporter] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.spans or self.metrics or self.logs)


@dataclass
class Telemetry:
    """The providers this process installed, so they can be flushed on shutdown."""

    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    logger_provider: LoggerProvider | None = None
    log_handler: logging.Handler | None = None

    @property
    def enabled(self) -> bool:
        return self.tracer_provider is not None

    def shutdown(self) -> None:
        if self.log_handler is not None:
            logging.getLogger().removeHandler(self.log_handler)
        for provider in (self.tracer_provider, self.meter_provider, self.logger_provider):
            if provider is not None:
                provider.shutdown()


def exporters_from_settings(settings: TelemetrySettings) -> Exporters:
    exporters = Exporters()
    if settings.otlp_endpoint:
        base = settings.otlp_endpoint.rstrip("/")
        exporters.spans.append(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))
        exporters.metrics.append(OTLPMetricExporter(endpoint=f"{base}/v1/metrics"))
        exporters.logs.append(OTLPLogExporter(endpoint=f"{base}/v1/logs"))
    if settings.azure_monitor_connection_string is not None:
        _add_azure_monitor_exporters(exporters, settings)
    if settings.console:
        from opentelemetry.sdk._logs.export import ConsoleLogRecordExporter
        from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        exporters.spans.append(ConsoleSpanExporter())
        exporters.metrics.append(ConsoleMetricExporter())
        exporters.logs.append(ConsoleLogRecordExporter())
    return exporters


def _add_azure_monitor_exporters(exporters: Exporters, settings: TelemetrySettings) -> None:
    from azure.monitor.opentelemetry.exporter import (
        AzureMonitorLogExporter,
        AzureMonitorMetricExporter,
        AzureMonitorTraceExporter,
    )

    connection_string = settings.azure_monitor_connection_string
    if connection_string is None:
        return
    options: dict[str, Any] = {"connection_string": connection_string.get_secret_value()}
    if settings.use_managed_identity:
        from azure.identity import ManagedIdentityCredential

        options["credential"] = ManagedIdentityCredential(
            client_id=settings.managed_identity_client_id
        )
    exporters.spans.append(AzureMonitorTraceExporter(**options))
    exporters.metrics.append(AzureMonitorMetricExporter(**options))
    exporters.logs.append(AzureMonitorLogExporter(**options))


def configure_telemetry(
    settings: TelemetrySettings,
    *,
    service_name: str,
    service_version: str = "0.1.0",
    exporters: Exporters | None = None,
    set_global: bool = True,
) -> Telemetry:
    """Install tracing, metrics, and log export when at least one exporter is configured.

    Call once at process start. Exporter failures never raise into the application: batch
    processors export on a background thread and log their own errors.
    """
    if not settings.enabled:
        return Telemetry()
    chosen = exporters if exporters is not None else exporters_from_settings(settings)
    if not chosen:
        return Telemetry()

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment.name": settings.environment,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    for span_exporter in chosen.spans:
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                metric_exporter, export_interval_millis=settings.metric_export_interval_ms
            )
            for metric_exporter in chosen.metrics
        ],
    )

    logger_provider = LoggerProvider(resource=resource)
    for log_exporter in chosen.logs:
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    # Redact before export, exactly as for the console handler.
    handler.addFilter(RedactingFilter())
    logging.getLogger().addHandler(handler)

    if set_global:
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)
        _logs.set_logger_provider(logger_provider)
        # Agent Framework spans and metrics (agent runs, model calls, tool calls) follow the
        # global providers. Prompts and responses are never captured, whatever the environment.
        enable_instrumentation(enable_sensitive_data=False, enable_message_events=False)
        HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)

    return Telemetry(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        log_handler=handler,
    )


def omit_personal_attributes(span: Span, _scope: Mapping[str, Any]) -> None:
    """Server-request hook: replace client address and user-agent values on the span."""
    attributes = getattr(span, "attributes", None) or {}
    for key in _PERSONAL_SPAN_ATTRIBUTES:
        if key in attributes:
            span.set_attribute(key, _OMITTED)


def instrument_fastapi(app: FastAPI, telemetry: Telemetry) -> None:
    """Trace FastAPI requests, minus health checks and personal client details."""
    if not telemetry.enabled:
        return
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        excluded_urls=_EXCLUDED_URLS,
        server_request_hook=omit_personal_attributes,
    )


def tracer() -> trace.Tracer:
    return trace.get_tracer(INSTRUMENTATION_NAME)


_meter = metrics.get_meter(INSTRUMENTATION_NAME)
_chat_requests = _meter.create_counter(
    "psa.chat.requests", unit="{request}", description="Chat requests by outcome"
)
_chat_duration = _meter.create_histogram(
    "psa.chat.duration", unit="ms", description="End-to-end chat request time"
)
_chat_tokens = _meter.create_counter(
    "psa.chat.tokens", unit="{token}", description="Model tokens used by chat requests"
)
_chat_citations = _meter.create_histogram(
    "psa.chat.citations", unit="{citation}", description="Citations returned per answer"
)
_search_duration = _meter.create_histogram(
    "psa.search.duration", unit="ms", description="Embedding plus hybrid search time"
)
_search_results = _meter.create_histogram(
    "psa.search.results", unit="{result}", description="Search results returned per query"
)
_ingestion_pages = _meter.create_counter(
    "psa.ingestion.pages", unit="{page}", description="Ingestion page outcomes"
)


def record_chat(
    outcome: str,
    duration_ms: float,
    *,
    citations: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    attributes = {"outcome": outcome}
    _chat_requests.add(1, attributes)
    _chat_duration.record(duration_ms, attributes)
    _chat_citations.record(citations, attributes)
    if input_tokens is not None:
        _chat_tokens.add(input_tokens, {"direction": "input"})
    if output_tokens is not None:
        _chat_tokens.add(output_tokens, {"direction": "output"})


def record_search(duration_ms: float, results: int, *, failed: bool = False) -> None:
    attributes = {"outcome": "failed" if failed else "ok"}
    _search_duration.record(duration_ms, attributes)
    if not failed:
        _search_results.record(results)


def record_ingestion_pages(counts: Mapping[str, int]) -> None:
    for outcome, count in counts.items():
        if count:
            _ingestion_pages.add(count, {"outcome": outcome})


def current_span_set(attributes: Mapping[str, Any]) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        for key, value in attributes.items():
            span.set_attribute(key, value)

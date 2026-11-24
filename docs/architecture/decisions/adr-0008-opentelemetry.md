---
title: ADR-0008 OpenTelemetry for Traces, Metrics, and Logs
description: Vendor-neutral, content-free telemetry, exported to the Aspire dashboard locally and to Azure Monitor in Azure
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - OpenTelemetry
  - monitoring
---

## Status

Accepted.

## Context

The brief asks for OpenTelemetry-based tracing, logging, and metrics for AI
requests, sent to a product such as Aspire or Arize Phoenix. It also asks that
personal and secret data never reach logs.

## Decision

* Instrument the API, the ingestion job, and the web app with OpenTelemetry.
  * The API traces each FastAPI request, outbound HTTP call, the agent run,
    each tool call, retrieval, and each model call (Agent Framework's built-in
    instrumentation).
  * The ingestion job traces each run and each product.
  * The web app traces each request and propagates the trace context to the API
    only, so a chat request is one trace across both services.
* Export with OTLP over HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Compose
  runs the Aspire dashboard as the local backend at `http://127.0.0.1:18888`.
  Any OTLP backend, such as Arize Phoenix, works with the same setting.
* Export to Azure Monitor when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set,
  authenticated with the workload's managed identity in Azure.
* Keep telemetry content-free:
  * Agent Framework's sensitive-data capture is forced off.
  * Spans and metrics carry IDs, outcomes, counts, durations, and token totals
    only, never questions, answers, prompts, or retrieved text.
  * Client addresses and user agents are removed from server spans.
  * Logs pass through the same redaction filter before export as before console
    output.
  * Health checks are not traced.
* Emit application metrics with the `psa.` prefix: chat requests, duration,
  tokens, and citations; search duration and result count; ingestion page
  outcomes.

## Rationale

OpenTelemetry keeps instrumentation independent of the backend, so the same
code reports to a local dashboard and to Azure Monitor. Removing content at the
source is safer than filtering it later.

## Alternatives considered

* Azure Monitor distro only: simpler in Azure, but ties local development to a
  cloud resource.
* Logging only: no request-level timing across the web app, API, and model.
* Capture prompts and responses in traces for debugging: rejected; it would
  store user content without the privacy controls it requires.

## Consequences

* Telemetry cannot be used to review what users asked; that needs the separate
  retention feature.
* The local dashboard keeps data in memory only and is cleared on restart. It
  runs without authentication and is bound to `127.0.0.1`.
* Alerts, dashboards, and service level objectives are not yet defined.

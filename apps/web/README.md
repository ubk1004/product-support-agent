---
title: Product Support Agent web app
description: The Next.js chat and coverage interface, its server routes, configuration, and commands
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
---

Next.js (App Router, TypeScript) front end. The browser talks only to this app;
the app calls the FastAPI service from its server, so the API needs no CORS
policy and is never exposed to the browser. See the
[local development guide](../../docs/operations/local-development.md) to run
it, and [ADR-0005](../../docs/architecture/decisions/adr-0005-ui-and-backend-technology.md)
for the reasoning.

## What it shows

* **Coverage.** The home page is a Server Component that calls
  `GET /catalog/coverage` at request time. It shows how many of the 100 demo
  products have indexed documentation, a table with the indexed products first,
  and a "Demo coverage could not be loaded" notice, assuming nothing is covered,
  when the API cannot be reached.
* **Chat.** A conversation panel with starter questions, a product filter
  limited to indexed products, plain-text answers with numbered source links,
  and guidance when the assistant cannot answer. The conversation lives only in
  the browser tab; nothing is stored.

## Server routes

| Route | Purpose |
|---|---|
| `POST /api/chat` | Validates the request (message up to 2,000 characters, 8 earlier turns of up to 4,000 characters, 48,000-character body, 35-second timeout), calls the API's `/chat` without following redirects, checks the shape of the reply, and returns it. Failures become one of `invalid_request`, `uncovered_product`, `service_unavailable`, or `request_failed`, with no internal detail |
| `GET /api/healthz` | Container health probe; not traced |

Links in answers come only from the server-provided citation list; the app does
not render model-written links, HTML, or markdown.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PRODUCT_SUPPORT_API_BASE_URL` | `http://127.0.0.1:8000` | FastAPI base URL, read on the server only. Compose sets `http://api:8000`; in Azure it is the API's internal address. Never expose it as `NEXT_PUBLIC_*` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP collector; the app exports telemetry only when it is set |
| `OTEL_SERVICE_NAME` | `product-support-web` | Service name in traces |
| `PRODUCT_SUPPORT_ENVIRONMENT` | `local` | Environment label for telemetry |

Telemetry comes from `src/instrumentation.ts` (`@vercel/otel`). It traces
server requests and propagates the trace context to the API only, so a chat
request is one trace across both services. Health checks are dropped.

## Commands

```powershell
npm ci
npm run dev        # http://localhost:3000, needs the API running
npm run lint       # Biome
npm run typecheck  # next typegen and tsc
npm run build
```

The web app has no unit tests; lint, type checking, and the production build
are its automated checks, and the recorded demo shows its behaviour.
`next dev` writes `AGENTS.md` with notes for coding assistants about this
Next.js version; it is generated, not project documentation.

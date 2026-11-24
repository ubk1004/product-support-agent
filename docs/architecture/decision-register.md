---
title: Architecture Decision Register
description: One-page summary of the architecture decisions, with links to the decision records
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: reference
keywords:
  - architecture decisions
  - product support
estimated_reading_time: 6
---

Each row is a decision in force. The linked ADR holds the context, the
alternatives, and the consequences.

## Product and scope

| Topic | Decision | Record |
|---|---|---|
| Users and tasks | Support engineers and product support analysts. Five tasks: confirm a product is in the demo catalog, find a public resource, get a cited answer to a product question, learn when no indexed source exists, and recognise an unsupported request. | [Solution architecture](architecture-overview.md#purpose-and-scope) |
| Demo catalog | A reproducible random sample of 100 products from the OpenText product feed (hard maximum 100), reused for every run. Products without an approved source are shown as not covered. | [ADR-0002](decisions/adr-0002-source-access-and-manifest.md) |
| Catalog discovery | Listing, then search API, then feed. A protected source (401, 403, sign-in redirect, or sign-in content) is skipped, recorded, and never retried with credentials. | [ADR-0002](decisions/adr-0002-source-access-and-manifest.md) |
| Content sources | Anonymous requests to allowlisted hosts only, from an explicit, versioned source map; `robots.txt` honoured. | [ADR-0002](decisions/adr-0002-source-access-and-manifest.md), [ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md) |
| Scope guardrails | Guardrails that always apply, changes that need an owner, and controls reserved for production. | [ADR-0007](decisions/adr-0007-demo-delivery-mode.md) |

## Application

| Topic | Decision | Record |
|---|---|---|
| Technology | Next.js and TypeScript for the interface; Python, FastAPI, and Microsoft Agent Framework for the API and agent. | [ADR-0005](decisions/adr-0005-ui-and-backend-technology.md) |
| Interface boundary | The browser talks only to Next.js; Next.js calls the API from the server, so no CORS policy is needed. | [ADR-0005](decisions/adr-0005-ui-and-backend-technology.md) |
| Agent tools | Two read-only tools: `search_documentation` and `list_products`. | [Solution architecture](architecture-overview.md#model-interaction) |
| Citations | The model may cite only evidence IDs from the current request; the server resolves them to stored URLs and drops anything else. An answer with no valid citation becomes the standard refusal. | [Solution architecture](architecture-overview.md#model-interaction) |
| Conversation | Kept in the browser tab only, up to 8 earlier turns sent with each question; never shown across sessions. | [ADR-0004](decisions/adr-0004-data-ownership-and-privacy.md) |
| End-user sign-in | None in this version. Local services bind to `127.0.0.1`. | [ADR-0007](decisions/adr-0007-demo-delivery-mode.md) |
| Caching | No response cache. Fetch state and conditional requests are ingestion controls, not a cache. | [ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md) |
| Accessibility | Target WCAG 2.2 AA. | [Production gap register](../operations/production-gap-register.md) |

## Retrieval and models

| Topic | Decision | Record |
|---|---|---|
| Search | Azure AI Search everywhere; hybrid keyword and vector retrieval with product filters; semantic ranking off; versioned index names. | [ADR-0001](decisions/adr-0001-search-and-model-gateway.md) |
| Models | `gpt-5` for chat and `text-embedding-3-small` (1,536 dimensions) for embeddings, called directly through Foundry's OpenAI-compatible endpoint; no model gateway in this version. | [ADR-0001](decisions/adr-0001-search-and-model-gateway.md) |
| Evaluation | A versioned synthetic set of 15 answerable and 6 unanswerable or adversarial questions, measuring expected-source hits, citation validity, model-judged claim support, and refusals. | [Evaluation report](../operations/phase-6-evaluation-v2.md) |

## Data and ingestion

| Topic | Decision | Record |
|---|---|---|
| Data ownership | The Mongo-compatible store is the system of record; the Search index is derived and rebuildable; queue messages hold references only; no user content is stored. | [ADR-0004](decisions/adr-0004-data-ownership-and-privacy.md) |
| Retention | Query and response retention is not built and stays off. | [ADR-0004](decisions/adr-0004-data-ownership-and-privacy.md) |
| Ingestion worker | Resumable, request-bounded, polite fetching with per-URL fetch state, freshness rules, backoff, fail-fast, and a single-run lease; Search kept in step with the store. | [ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md) |
| Ingestion queue | One message per product, one message at a time, outcome recorded before the message is deleted, poison queue after five deliveries. | [ADR-0009](decisions/adr-0009-queue-driven-ingestion.md) |

## Platform and operations

| Topic | Decision | Record |
|---|---|---|
| Local environment | Podman Compose with the web app, API, MongoDB, Azurite, and the Aspire dashboard, bound to `127.0.0.1`. | [ADR-0003](decisions/adr-0003-local-first-boundaries.md) |
| Azure environment | Container Apps in a virtual network, private data services, Key Vault, private registry, two-stage Bicep deployment. | [ADR-0010](decisions/adr-0010-azure-platform-and-api-management.md) |
| API gateway | Classic API Management in external VNet mode: Developer for `dev` and `tst`, Premium for `prd`. | [ADR-0010](decisions/adr-0010-azure-platform-and-api-management.md) |
| Identity | Managed identity for Key Vault, the queue, telemetry, and image pulls; keys from Key Vault for Search and Foundry; OIDC for GitHub Actions. | [Solution architecture](architecture-overview.md#identity-and-access) |
| Monitoring | OpenTelemetry traces, metrics, and logs with no user content; Aspire locally, Azure Monitor in Azure. | [ADR-0008](decisions/adr-0008-opentelemetry.md) |
| CI/CD | GitHub Actions: validation on every pull request; images built on every push to `main`; publishing and deployment from runners inside the virtual network; infrastructure deployed manually in two stages behind a what-if. | [Cloud setup guide](../../infra/README.md#pipelines) |

---
title: Product Support Agent
description: Local-first product support assistant project using a React and Next.js interface with a Python API
---

# Product Support Agent

This repository contains a local-first product support assistant demo that runs
against real Azure resources (Microsoft Foundry and Azure AI Search). It is built
in **demo delivery mode** ([ADR-0007](docs/architecture/decisions/adr-0007-demo-delivery-mode.md)):
it aims for a working demo and records production-only controls instead of
blocking on them.
The approved foundation uses a TypeScript React/Next.js frontend and a Python
FastAPI backend. Phase 2 adds bounded catalog discovery, reproducible manifest
selection, Azure Storage Queue-compatible product references, ingestion status,
and a poison queue contract. The user approved Phase 2 on 2026-11-21 after
reviewing the live manifest and source outcome report under `docs/operations/`.
Phase 3 adds canonical document normalization and
Azure AI Search indexing/retrieval. A dedicated test-index definition was
applied and read back on 2026-11-22, but indexing and retrieval have not been
tested live. The OpenText product pages are client-rendered and are used as
the catalog only. Documentation for 10 manifest products comes from a versioned
[source map](docs/operations/phase-3-source-map-v1.json) of anonymous
documentation-portal JSON and sitemaps. A periodic, resumable source worker
([ADR-0006](docs/architecture/decisions/adr-0006-periodic-resumable-source-ingestion.md))
skips URLs fetched within 24 hours and fails fast on unavailable content. It is
tested offline, and its first live run on 2026-11-22 stored 300 pages for the
10 products with 0 failures.
The home page shows which demo products have indexed documentation, from
`GET /catalog/coverage`. The local suite passes 242 tests, and Ruff, mypy, and
Bandit pass. Phases 0 to 3 are complete. Phase 4 (grounded agent and chat API)
is next; the [implementation plan](docs/implementation-plan.md) lists its work
packages, starting with indexing the corpus into Azure AI Search.

See the [architecture overview](docs/architecture/architecture-overview.md) for
the current process and component diagrams.

See the [implementation plan](docs/implementation-plan.md) for phase gates and
the [local development guide](docs/operations/local-development.md) for setup
and validation commands.
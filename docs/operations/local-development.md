---
title: Local Development Runbook
description: Run the product support demo locally with Podman Compose
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: how-to
keywords:
  - local development
  - Podman
  - Next.js
  - FastAPI
---

This runbook starts the local demo against the existing Microsoft Foundry and
Azure AI Search services. The browser talks only to Next.js; Next.js calls
FastAPI over the Compose network. No query or response history is stored.

## Prerequisites and environment

* Podman with a running machine and a working `podman compose` provider.
* Network access to the user's Foundry and Azure AI Search endpoints.
* Valid deployment and Search credentials in a local `.env` file.
* `uv` 0.13.9 or later for running the evaluation and Python checks.

From a clean checkout, copy `.env.example` once, then fill in the existing
deployment and Search values locally. Do not overwrite an existing `.env`:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Required settings in `.env` are:

* `AZURE_OPENAI_ENDPOINT` (OpenAI-compatible endpoint ending in `/openai/v1`),
  `AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_CHAT_DEPLOYMENT`.
* `AZURE_OPENAI_EMBEDDING_ENDPOINT` and
  `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`.
* `AZURE_AI_SEARCH_ENDPOINT` and `AZURE_AI_SEARCH_API_KEY`.
* `PRODUCT_SUPPORT_SEARCH_EMBEDDING_MODEL_VERSION`,
  `PRODUCT_SUPPORT_SEARCH_EMBEDDING_DIMENSIONS` (`1536`), and
  `PRODUCT_SUPPORT_SEARCH_DEMO_INDEX_BASE` (`product-support-demo`).
* `PRODUCT_SUPPORT_MONGODB_URI` may remain
  `mongodb://127.0.0.1:27017` in the host `.env`; Compose overrides it inside
  the API container with `mongodb://mongodb:27017`.

Leave `CHAT_TEMPERATURE` empty. The gpt-5 chat deployment rejects a temperature
parameter, so the chat client omits it. Query/response retention must remain
disabled.

Compose passes `.env` only to the API service using `env_file`; secrets are not
baked into either image. The web service receives only
`PRODUCT_SUPPORT_API_BASE_URL=http://api:8000`. The API image contains the
approved manifest and source map JSON files, not the rest of `docs/`.

## Start the demo

Start the Podman machine only if it is stopped:

```powershell
podman machine list
# If it is not running:
podman machine start
```

From the repository root, one command builds and starts MongoDB, Azurite, the
API, and the web app. Health checks gate startup order, and published ports bind
only to loopback:

```powershell
podman compose up --build -d
```

Open `http://127.0.0.1:3000`. The coverage page reports the 100-product
manifest, the 10 products with approved public sources, and the current
indexed-page count. The API health endpoint is `http://127.0.0.1:8000/healthz`;
coverage metadata is at `http://127.0.0.1:8000/catalog/coverage`. The browser
does not call FastAPI directly.

An existing local database volume may already contain the 300 canonical
pages ingested for the 10 covered products. A new empty MongoDB volume needs a
bounded ingestion and indexing pass before chat can answer:

```powershell
podman compose run --rm api uv run --no-sync python scripts/run_source_ingestion.py
podman compose run --rm api uv run --no-sync python scripts/index_documents.py
```

Ingestion uses only
[`phase-3-source-map-v1.json`](./phase-3-source-map-v1.json), the configured
request budget, robots policy, freshness checks, and backoff. Indexing creates
or updates the `product-support-demo-*` Search index from canonical MongoDB
documents using the Foundry embedding deployment. These commands do not
provision Azure resources. Rerun indexing after ingesting new or changed pages.

Ask a question in the web page and optionally filter to an indexed product.
Answers are plain text; citation links come from retrieved evidence. If no
indexed evidence answers a question, the UI shows
“No indexed documentation answers this.” Do not assume products without an
approved source are supported.

## Evaluation

The versioned set contains 15 answerable questions across the 10 covered
products and 3 unanswerable questions. The runner queries hybrid retrieval and
the local API, then writes metrics and per-case outcomes only; it does not
write question or response text to the report.

```powershell
uv sync --all-groups
uv run python scripts/run_evaluation.py --api-url http://127.0.0.1:8000
```

Results are recorded in
[`phase-6-evaluation-v1.md`](./phase-6-evaluation-v1.md). Semantic reranking
was not enabled because the Search service tier and billing plan could not be
verified; no service setting was changed.

## Stop and preserve local data

Stop the containers gracefully while keeping the named data volumes:

```powershell
podman compose stop --timeout 30
```

Restart them with `podman compose start`. To remove project containers while
preserving data, use `podman compose down --timeout 30`. Do not add `--volumes`
unless you intentionally want to delete the MongoDB and Azurite data. Leave
containers from other projects alone.

## Routine validation

From the repository root:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src/product_support_agent scripts
uv run pytest
uv run bandit -q -r src scripts
```

In `apps/web`:

```powershell
npm run lint
npm run typecheck
npm run build
```

## Production-only

This runbook is for a local demo, not a public or production service. Identity,
private networking, rate and cost controls, reviewed evaluation, full
accessibility and red-team audits, query/response retention approval,
observability export, image provenance, and MongoDB backup/restore remain
documented gaps in the
[production gap register](./production-gap-register.md).

---
title: Local Development Guide
description: Set up, run, ingest, test, and debug the Product Support Agent on a developer machine with Podman Compose
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: how-to
keywords:
  - local development
  - Podman
  - Next.js
  - FastAPI
estimated_reading_time: 9
---

This guide gets the whole application running on your machine and shows how to
work on it. For the Azure environment, see the
[cloud setup guide](../../infra/README.md).

## What runs where

Five containers run in Podman Compose, with every published port bound to
`127.0.0.1`:

| Service | Port | Purpose |
|---|---|---|
| `web` | 3000 | Next.js chat interface and coverage page |
| `api` | 8000 | FastAPI service and the agent |
| `mongodb` | 27017 | Canonical documents, fetch state, and ingestion records |
| `azurite` | 10000, 10001 | Local Azure Storage emulator; the ingestion queue lives here |
| `aspire-dashboard` | 18888 (UI), 4318 (OTLP) | Local traces, metrics, and logs |

Two services are **not** local and must exist in Azure: a Microsoft Foundry
resource with a chat and an embedding deployment, and an Azure AI Search
service. The browser talks only to the web app; the web app calls the API from
its server.

## Prerequisites

* Podman with a running machine and a working `podman compose` provider.
* Git.
* Foundry endpoint, key, and deployments: a chat deployment (the project uses
  `gpt-5`) and an embedding deployment (`text-embedding-3-small`, 1,536
  dimensions). Record the OpenAI-compatible endpoint ending in `/openai/v1`.
* An Azure AI Search service with vector search, and its endpoint and an admin
  key.
* For development outside containers and for the checks: Python 3.11 or later
  with [`uv`](https://docs.astral.sh/uv/) 0.13.9 or later, and Node.js 22 or
  later.

Creating Azure resources or model deployments costs money. Ask the project
owner for existing ones, or follow Microsoft's guides:

* [Create an Azure AI Search service](https://learn.microsoft.com/azure/search/search-create-service-portal)
* [Create a Foundry project and deploy a model](https://learn.microsoft.com/azure/foundry/tutorials/quickstart-create-foundry-resources)

## 1. Configure

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` and set:

| Setting | Value |
|---|---|
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_EMBEDDING_ENDPOINT` | Foundry OpenAI-compatible endpoint, ending in `/openai/v1` |
| `AZURE_OPENAI_API_KEY` | Foundry key |
| `AZURE_OPENAI_CHAT_DEPLOYMENT`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Exact deployment names |
| `AZURE_AI_SEARCH_ENDPOINT`, `AZURE_AI_SEARCH_API_KEY` | Search endpoint and admin key |
| `PRODUCT_SUPPORT_SEARCH_EMBEDDING_DIMENSIONS` | `1536` for `text-embedding-3-small` |

Leave the rest at their defaults; they are listed in the
[configuration reference](configuration-reference.md). Do not commit `.env`.
Compose gives `.env` only to the API container and overrides the database,
queue, and file paths for the container network. Secrets are never baked into
an image.

## 2. Start

```powershell
podman machine list
# If the machine is stopped:
podman machine start
podman compose up --build -d
```

Wait until `podman compose ps` shows all services healthy, then open:

| URL | What you see |
|---|---|
| <http://127.0.0.1:3000> | The chat interface and the coverage of the 100-product demo catalog |
| <http://127.0.0.1:8000/healthz> | API health |
| <http://127.0.0.1:8000/catalog/coverage> | Coverage metadata as JSON |
| <http://127.0.0.1:8000/docs> | API reference (FastAPI) |
| <http://127.0.0.1:18888> | Aspire dashboard |

## 3. Ingest the documentation

A new MongoDB volume is empty, so the agent has nothing to answer from until a
queue-driven ingestion run has finished. Run these inside the API container
with `python`, not `uv run`: the image runs as a non-root user with no
writable uv cache.

```powershell
podman compose run --rm api python scripts/run_queue_ingestion.py run
podman compose run --rm api python scripts/run_queue_ingestion.py status
```

`run` puts one message per manifest product on the `product-ingestion` queue,
then works through them one at a time. For each product it fetches the pages in
the [source map](phase-3-source-map-v1.json), embeds and indexes them in Azure
AI Search (creating the versioned `product-support-demo-*` index on first use),
and records an outcome. A complete run reports 10 products `success` and 90
`skipped` with `no_public_source`. Pages fetched in the last 24 hours are
skipped, so repeating the command is cheap. The same status is at
<http://127.0.0.1:8000/ingestion/runs/latest>.

Useful variations:

| Goal | Command |
|---|---|
| Queue a run now, process it later | `... run_queue_ingestion.py enqueue`, then `... work` |
| One product only | add `--product <id>` |
| Ignore freshness and backoff | add `--force` (needs the product owner's approval) |
| Store pages in MongoDB only, skip embeddings and Search | add `--repository-only` |
| Rebuild the Search index from MongoDB, for example after an embedding model change | `python scripts/index_documents.py` |
| Run the source worker without the queue | `python scripts/run_source_ingestion.py` |

Ingestion makes requests to real public sites. The worker obeys `robots.txt`, a
request budget (400 per run by default), a one-second gap between requests to a
host, and backoff, so do not bypass it. Only the hosts in the source map are
contacted.

## 4. Use and check the application

Ask a question in the web page and optionally filter to an indexed product.
Answers are plain text with numbered source links, and every link comes from
retrieved evidence. If nothing indexed answers, the assistant says it could not find the answer in the indexed documentation. The 90 products
without a source are listed as not covered.

Traces, metrics, and logs for the web app, API, and ingestion job are in the
Aspire dashboard. They contain metadata only. The dashboard keeps them in
memory, so they disappear when its container restarts.

## Create or replace the demo catalog (rare)

The catalog is the committed
[`phase-2-product-manifest-v1.json`](phase-2-product-manifest-v1.json). To draw
a new sample from the OpenText feed (needs network access to `my.opentext.com`;
it refuses to overwrite an existing file without `--replace`):

```powershell
uv run python scripts/create_manifest.py --manifest-version opentext-YYYY-MM-DD-v2 --output docs/operations/manifest-new.json
```

A new manifest changes which products are queued and shown. Adding a product
that has documentation also needs an entry in the source map, and both changes
need the product owner's approval.

## Evaluate answer quality

The offline evaluation runs 21 questions (15 answerable, 6 that should be
refused) through retrieval and the running API, and uses a model to judge
whether each cited page supports the answer. It needs Compose healthy, a
completed ingestion, and the `.env` values above.

```powershell
uv sync --all-groups
uv run python scripts/run_evaluation.py --api-url http://127.0.0.1:8000 --report evaluation-local.md
```

Without `--report` the command overwrites the committed
[evaluation report](phase-6-evaluation-v2.md). The report holds metrics only,
never question or answer text. Results vary between runs, so compare ranges and
not single numbers.

## Run the checks

From the repository root:

```powershell
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src/product_support_agent scripts
uv run pytest
uv run bandit -q -r src scripts
```

`pytest` is offline by default. Tests marked `live` call real Azure AI Search
and create a disposable `product-support-test-*` index; run them with
`uv run pytest -m live`.

For the web app, from `apps/web`:

```powershell
npm ci
npm run lint
npm run typecheck
npm run build
```

To run the web app on the host against a containerised API, set
`PRODUCT_SUPPORT_API_BASE_URL=http://127.0.0.1:8000` and run `npm run dev` in
`apps/web`.

## Stop and clean up

Stop the containers and keep the data:

```powershell
podman compose stop --timeout 30
podman compose start
```

`podman compose down --timeout 30` removes the containers but keeps the named
volumes. Add `--volumes` only when you want to delete the MongoDB and Azurite
data, which means ingesting again.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The page says "Demo coverage could not be loaded" | The API is not healthy yet, or MongoDB is empty; check `podman compose ps` and `podman compose logs api` |
| Every question gets the "couldn't find this in the indexed documentation" refusal | Ingestion has not run or the index name or dimensions do not match; run `status` |
| Chat shows "The assistant is temporarily unavailable" | Foundry rejected the call (often 429 throttling) or Search is unreachable; check the key, endpoint, and deployment capacity |
| `another ingestion run holds the lease` | A previous run was killed; follow the [runbook](../architecture/support-ownership.md#runbooks) |
| Queue commands fail with an API version error | The Azurite image and `PRODUCT_SUPPORT_QUEUE_API_VERSION` are out of step; Compose pins `2026-06-06` for Azurite 3.38 |
| API refuses to start with an environment error | `PRODUCT_SUPPORT_ENVIRONMENT` must be `local`, `test`, or `production` |

## Before sharing the demo

This setup is for local use. It has no user sign-in, so keep it on
`127.0.0.1`. The controls that a shared or production service needs are in the
[production gap register](production-gap-register.md).

---
title: Local Development
description: Set up and validate the local product support agent foundation
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: how-to
keywords:
  - local development
  - Podman
  - Next.js
  - FastAPI
---

## Prerequisites

* Python 3.11 or later
* `uv` 0.13.9 or later
* Node.js 20.9 or later and npm
* Podman with a working `podman compose` provider for local MongoDB and Azurite

The local application stack is not deployed to Azure. Routine catalog and
worker tests use synthetic local HTTP/queue fixtures. The live Phase 2 source
check is documented in the [manifest](./phase-2-product-manifest-v1.json) and
[outcome report](./phase-2-ingestion-outcome-v1.md); it did not persist source
content. Phase 3 adds canonical HTML normalization, chunking, Azure AI Search
indexing/retrieval providers, and in-memory test doubles. A dedicated live
Search test-index definition was applied and read back on 2026-11-22; no
documents were uploaded. No embedding deployment has been tested. Model calls
and query/response retention remain disabled. The later
[linked-source outcome](./phase-3-linked-source-verification-2026-11-22.json)
records public documentation observations for 10 manifest products, but no
source bodies were retained or indexed. Source terms remain unverified.

## Configure the Python environment

Copy `.env.example` to `.env` only if you need to change local settings. Do not
commit `.env` or put user content in it, tests, or logs. Keep provider
credentials in approved local environment configuration outside source control.

```powershell
uv sync --all-groups
uv run uvicorn product_support_agent.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

The process health endpoint is available at
`http://127.0.0.1:8000/healthz`. It reports API process health only; it does not
validate databases, queues, search, or model-provider connectivity.
The health response includes a generated `X-Request-ID`. Application log
records use JSON fields for timestamp, level, logger, message, and request ID.

The demo coverage endpoint is available at
`http://127.0.0.1:8000/catalog/coverage`. It reads the approved manifest and
source map (`PRODUCT_SUPPORT_MANIFEST_PATH`, `PRODUCT_SUPPORT_SOURCE_MAP_PATH`)
and, when `PRODUCT_SUPPORT_MONGODB_URI` is set, the source fetch state. It
returns product-level status and counts only.

The Phase 2 manifest endpoint is available at
`http://127.0.0.1:8000/catalog/manifest`. Before catalog discovery is prepared,
it returns a `null` manifest and the last catalog outcome. Ingestion run details
are available at `/ingestion/runs/{run_id}`. Routine catalog and worker tests use
HTTP mocks and in-memory fakes; they do not contact OpenText or Azure services.

## Phase 3 search foundation

The indexer accepts HTML only, limits a document to 4 MiB, creates stable
document and chunk IDs, and stores canonical documents and chunks in MongoDB
before updating the derived Search index. Default chunks contain up to 1,200
characters with 150 characters of overlap. Search results preserve the product
ID, source URL, chunk ID, and content hash. The index definition uses a versioned
name that includes schema, parser, embedding model version, and vector dimension.
The embedding provider remains an injected interface; this repository does not
configure a model deployment. The worker does not follow redirects. The
documentation-portal JSON is handled by the source worker described below. The
login-content heuristic flags password fields, login forms, SAML requests, and
short sign-in pages, not documentation that mentions logging in.

The local retrieval evaluator checks whether relevant evidence appears in the
top five and whether every recorded citation resolves to a retrieved chunk with
the same URL. Its thresholds are 90% top-five relevance and 100% citation
resolution. Passing local tests does not satisfy the controlled Azure Search
relevance gate; that gate requires a reviewed test set and a dedicated approved
test index.

The index application script requires these environment variables:

* `PRODUCT_SUPPORT_SEARCH_ENDPOINT`
* `PRODUCT_SUPPORT_SEARCH_ADMIN_KEY`
* `PRODUCT_SUPPORT_SEARCH_EMBEDDING_MODEL_VERSION`
* `PRODUCT_SUPPORT_SEARCH_EMBEDDING_DIMENSIONS`
* `PRODUCT_SUPPORT_SEARCH_TEST_INDEX_BASE`

Run the script only after the dedicated Search test index and controlled live
test are approved:

```powershell
uv run python scripts/apply_search_index.py
```

The script rejects a base name that does not identify a test index. It applies
the versioned index definition in the configured Search service; it does not
provision Azure services or deploy the application. Do not run it without
explicit approval for the target index.

On 2026-11-22, the authorized test-index definition was applied and read back
with 14 fields and 1,536 vector dimensions. This verifies index creation or
update and schema readback only, not document indexing, hybrid retrieval,
relevance, or deletion behavior.

## Periodic documentation ingestion

The source worker ingests only the products listed in the
[source map](./phase-3-source-map-v1.json); see
[ADR-0006](../architecture/decisions/adr-0006-periodic-resumable-source-ingestion.md).
It needs MongoDB (`PRODUCT_SUPPORT_MONGODB_URI`) and stores canonical documents
and chunks. It does not call an embedding model or Azure AI Search; run
`DocumentIndexingService.reconcile_all` after an embedding deployment is
approved.

Runs within the default budget, at most one per day, are pre-authorized for
the demo. The source-terms legal review is production-only. A discovery-only
pass fetches only `robots.txt` and the seed files, about 12 requests:

```powershell
podman compose up -d mongodb
$env:PRODUCT_SUPPORT_MONGODB_URI = "mongodb://127.0.0.1:27017"
uv run python scripts/run_source_ingestion.py --discover-only --report discovery.json
uv run python scripts/run_source_ingestion.py --report run.json
```

Behavior on reruns and failures:

* A rerun within 24 hours makes no requests for pages that already succeeded.
  This holds even if the previous run crashed, because state is written after
  every request. If a state write was lost, the document's `fetched_at`
  timestamp is the fallback check.
* Weekly runs skip pages whose TOC revision is unchanged and send conditional
  requests for the rest.
* Failures back off. Permanent failures (protected, robots-disallowed, other
  4xx) wait 30 days. Transient failures wait 1 to 7 days.
* A product stops after three consecutive page failures. A 429 response, or a
  `robots.txt` that cannot be fetched, abandons that host for the run.
* Only one run can proceed at a time; a second concurrent run exits with code 3.
* Use `--product <id>` to limit a run, and `--force` only after deciding to
  reset freshness and backoff.

Settings are prefixed `PRODUCT_SUPPORT_SOURCE_` in `.env.example`. Schedule the
command with a weekly task. The run report contains outcomes and counts only,
never page content.

## Index the corpus into Azure AI Search

`scripts/index_documents.py` creates or updates a versioned
`product-support-demo-*` index. It then embeds every canonical chunk in
MongoDB, using the Foundry embedding deployment, and uploads it. It reads the
`AZURE_OPENAI_*` and `AZURE_AI_SEARCH_*` / `PRODUCT_SUPPORT_SEARCH_*` variables
from `.env`:

```powershell
$env:PRODUCT_SUPPORT_MONGODB_URI = "mongodb://127.0.0.1:27017"
uv run python scripts/index_documents.py
```

This is Phase 4, work package 1; it had not been run as of 2026-11-22. The
first live ingestion on 2026-11-22 stored 300 pages for the 10 covered
products, so about 300 documents will be indexed. Live runs and index
creation within the `product-support-*` prefix are pre-authorized for the demo
([ADR-0007](../architecture/decisions/adr-0007-demo-delivery-mode.md)).

## Run the frontend

Start the API first, then the frontend:

```powershell
Set-Location apps/web
npm ci
npm run dev
```

Open `http://localhost:3000`. The home page shows demo coverage: how many of
the 100 manifest products have indexed documentation, and a table of every
product with indexed products first. The page fetches
`GET /catalog/coverage` on the server from `PRODUCT_SUPPORT_API_BASE_URL`
(default `http://127.0.0.1:8000`). If MongoDB is not configured, the page says
ingestion state cannot be read and lists approved sources as pending. If the
API is unreachable, it says that no product should be assumed covered. Chat is
not available yet.

## Start local data services

From the repository root, start the emulated services when needed:

```powershell
podman compose up -d mongodb azurite
```

The services bind only to loopback. Stop and start them gracefully to preserve
emulator metadata:

```powershell
podman compose stop --timeout 30 mongodb azurite
podman compose start mongodb azurite
```

Azurite has a 30-second shutdown grace period in Compose. During verification,
a bare `podman restart` lost newly written Azurite metadata; explicit graceful
stop/start preserved it. Do not use a forced stop or bare restart for emulator
data you need to keep. This emulator does not provide production durability.

`podman compose down --timeout 30` stops and removes the project containers
while preserving their named volumes. Adding `--volumes` removes their local
data.

### Podman verification record

Local verification passed on 2026-11-21 with Podman 5.6.2, a running WSL
machine, and Docker Compose 2.34.0 as the external provider:

* Compose validation, image pulls, and startup of MongoDB and Azurite passed.
* Host listeners for ports 27017, 10000, and 10001 bound only to `127.0.0.1`.
* MongoDB ping, synthetic document write/read, and restart persistence passed.
* Authenticated Azurite queue and blob write/read through the host ports passed.
* Azurite graceful stop/start preserved the message and blob. Message receipt,
  acknowledgement, and an empty-queue check passed.
* Synthetic databases, queues, and blob containers were removed after testing.

Only this project's containers were stopped after verification; named volumes
and unrelated workloads were preserved. No OpenText or cloud services were
accessed during that Podman verification. The separate live OpenText source
check is recorded in the [Phase 2 outcome report](./phase-2-ingestion-outcome-v1.md).
GitHub-hosted CI and repository branch protection remain separate verification
items in the [operations backlog](./backlog.md).

## Validate changes

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src/product_support_agent
uv run pytest
uv run bandit -q -r src scripts
uv run pip-audit --skip-editable
```

```powershell
Set-Location apps/web
npm run lint
npm run typecheck
npm run build
npm audit --audit-level=high
```

`npm run lint` runs Biome's formatting and lint checks on frontend source.

Query and response retention defaults to off. Do not enable it until the
privacy notice, reviewer identity, redaction behavior, deletion, TTL, and
provider-handling approvals are complete. The Phase 1 app does not persist
queries or responses.

The logging filter redacts common labeled secrets (for example `api_key`,
`client_secret`, `AccountKey`, and SAS `sig`), credentials in connection-string
URIs, bearer tokens, JWTs, cookies, and email addresses. It also applies to the
uvicorn server and access logs, which include request query strings. It is
pattern-based and not a general-purpose PII detector, so never log query or
response content.

`npm run typecheck` runs `next typegen` first, so it works on a clean checkout
before any `next build`. The repository's `.gitattributes` keeps LF line endings
on Windows so that Biome and Ruff formatting checks match CI.

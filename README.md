---
title: Product Support Agent
description: Local demo of a grounded product support assistant, including architecture, setup, configuration, Azure prerequisites, and quality checks
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: overview
keywords:
  - product support
  - local demo
  - Microsoft Foundry
  - Azure AI Search
---

## Executive summary

Product Support Agent is a local-first demonstration of a web and agentic
support assistant. It answers questions from anonymously accessible product
documentation, retrieves evidence from Azure AI Search, and returns links
resolved by the server from that evidence.

The browser calls only the TypeScript/Next.js server. Next.js calls the Python
FastAPI service, which uses Microsoft Foundry for chat and embeddings and Azure
AI Search for hybrid retrieval. MongoDB stores canonical documents and
ingestion state. The API currently uses an in-memory queue for catalog
processing; Azurite starts in Compose but is not wired into the current
workflow. MongoDB and Azurite run in Podman, not in Azure.

The approved source map covers 10 of the 100 manifest products. It has ingested
300 pages and indexed 952 chunks. The Phase 6 evaluation reached 80.0% expected
source hits in the top five, 100% citation URL matches, and 3/3 refusals for
unanswerable questions. See the [evaluation report](docs/operations/phase-6-evaluation-v1.md).

This is a local demo, not a production service. The cloud application stack is
not deployed. Production-only controls and blocking triggers are listed in the
[production gap register](docs/operations/production-gap-register.md), and the
delivery boundaries are recorded in [ADR-0007](docs/architecture/decisions/adr-0007-demo-delivery-mode.md).

## Quick links by audience

| Audience | Start here |
|---|---|
| Executive and product stakeholders | This overview, [demo outcomes](docs/operations/phase-6-evaluation-v1.md), [implementation status](docs/implementation-plan.md), and [production gap register](docs/operations/production-gap-register.md) |
| Technical architects | [Architecture overview](docs/architecture/architecture-overview.md), [decision register](docs/architecture/decision-register.md), [ADRs](docs/architecture/decisions/), [risk assumptions](docs/architecture/risk-assumptions.md), and [security posture](docs/security/security-posture.md) |
| Developers | [Local development runbook](docs/operations/local-development.md), [environment configuration](#configuration-and-environment-variables), [backend](src/product_support_agent/), and [web app](apps/web/) |
| Quality assurance | [Test and evaluation guidance](#quality-assurance), [evaluation report](docs/operations/phase-6-evaluation-v1.md), [test suite](tests/), and [threat register](docs/security/threat-register.md) |

## What the demo includes

* A Next.js interface with coverage disclosure, chat, transient client-side
  exchange state, and citation links.
* A FastAPI endpoint that coordinates Microsoft Agent Framework, hybrid search,
  request limits, metadata-only logs, and server-side citation binding.
* A resumable, request-bounded ingestion worker that reads only the versioned
  source map and respects source access controls.
* A synthetic evaluation set covering 15 answerable questions and 3
  unanswerable questions.
* A Podman Compose stack that binds published ports to `127.0.0.1`.

The model is not allowed to supply citation URLs. Retrieved source text and
user input are untrusted. Query and response retention is disabled. See the
[threat register](docs/security/threat-register.md) and
[privacy impact assessment](docs/security/privacy-impact-assessment.md).

## Local demo prerequisites

* Windows PowerShell, Git, and Podman with a running Podman machine and a
  working `podman compose` provider.
* Network access from the developer machine to the configured Microsoft
  Foundry and Azure AI Search endpoints.
* An existing Microsoft Foundry deployment for chat and an embedding
  deployment, plus an Azure AI Search service.
* `uv` 0.13.9 or later for the evaluation and Python checks. Node.js is not
  required to run the containerized demo; it is required to work on the web app
  directly.
* For local development outside the containers, Python 3.11 or later and
  Node.js 22 or later.

The [local development runbook](docs/operations/local-development.md) contains
the clean-checkout setup, first-run ingestion and indexing, evaluation, and
data-preserving stop commands.

### Azure resources for a local-only demo

The application still calls two Azure services from the developer machine.
Only the Foundry models and Azure AI Search need to be provisioned in Azure for
the local demo. MongoDB and Azurite run locally in Compose.

| Azure service | Set up or verify | Values needed by this repository |
|---|---|---|
| Microsoft Foundry | Use an existing Foundry resource/project with a chat deployment (`gpt-5`) and an embedding deployment (`text-embedding-3-small`). Verify region availability, quota, and that both deployments are ready. Creating a resource or model deployment can incur cost and needs the appropriate authorization. | The OpenAI-compatible `.../openai/v1` endpoint, API key, and the exact chat and embedding deployment names |
| Azure AI Search | Use an existing Search service with vector-search support. The indexer script creates versioned `product-support-demo-*` indexes; a separate `product-support-test-*` index is used for opt-in live tests. Capture the service endpoint and an admin key for server-side indexing and query operations. Never put this key in browser code. | Search endpoint and admin API key; embedding model version and dimensions must match the Foundry embedding deployment (`1536` for the supplied example) |

The current Azure documentation lists vector search across service tiers, but
service quotas, capacity, pricing, and other features vary. Check current
regional availability and costs before creating or changing a service. Semantic
ranking was not evaluated for this demo because the Search tier and billing
plan could not be verified.

No Azure Storage account, MongoDB service, Container Apps, API Management,
virtual network, private endpoint, or Application Insights resource is needed
to run this local demo. Do not create new Azure resources, change SKUs, or
deploy new models without authorization. The project’s authorization boundary
is documented in [ADR-0007](docs/architecture/decisions/adr-0007-demo-delivery-mode.md).

Official setup references:

* [Create an Azure AI Search service](https://learn.microsoft.com/azure/search/search-create-service-portal)
* [Vector search in Azure AI Search](https://learn.microsoft.com/azure/search/vector-search-overview)
* [Create a Microsoft Foundry project and deploy a model](https://learn.microsoft.com/azure/foundry/tutorials/quickstart-create-foundry-resources)

### Start the stack

From the repository root, copy the example configuration only if you do not
already have a local `.env` file. Fill the Foundry and Search values in `.env`;
do not commit it or print its contents:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

The chat client does not send a temperature parameter to `gpt-5` or other
reasoning deployments. Query/response retention is not implemented and remains
off.

Start the Podman machine if it is stopped, then build and start the services:

```powershell
podman machine list
# Run only when the machine is stopped:
podman machine start
podman compose up --build -d
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). Check the API at
[http://127.0.0.1:8000/healthz](http://127.0.0.1:8000/healthz) and coverage at
[http://127.0.0.1:8000/catalog/coverage](http://127.0.0.1:8000/catalog/coverage).
The browser never calls FastAPI directly.

If the local MongoDB volume is empty, run the bounded ingestion pass and then
index the canonical pages into Azure AI Search:

```powershell
podman compose run --rm api uv run --no-sync python scripts/run_source_ingestion.py
podman compose run --rm api uv run --no-sync python scripts/index_documents.py
```

These commands use only the approved source map, robots policy, freshness
checks, request budget, and backoff. The index script creates or updates the
versioned demo index. Ingestion uses real public sources and configured Foundry
deployments, so follow the budgets and limits in the
[local runbook](docs/operations/local-development.md).

Stop the project while preserving its MongoDB and Azurite volumes:

```powershell
podman compose stop --timeout 30
```

Do not use `podman compose down --volumes` unless you intend to delete local
data. See the runbook for restart and cleanup details.

## Configuration and environment variables

`.env.example` is the canonical template. The table covers the variables in
that file plus runtime and script aliases used by the repository. Values shown
in the template are examples; edit a local `.env` and never commit credentials.
Compose passes `.env` only to the API container and overrides the MongoDB and
manifest/source-map paths for the container network. Query/response retention
is not implemented in the demo and must remain off.

### Catalog workflow

These settings configure catalog discovery. They are not needed for normal
chat startup or the source-map-based documentation ingestion job. The current
API uses an in-memory queue; the Azurite service started by Compose is not
connected to this workflow.

| Variable | Purpose and local-demo guidance |
|---|---|
| `PRODUCT_SUPPORT_CATALOG_LISTING_URL` | Product listing endpoint used by catalog discovery. |
| `PRODUCT_SUPPORT_CATALOG_SEARCH_URL` | Catalog search endpoint. Do not add authentication or bypass access controls. |
| `PRODUCT_SUPPORT_CATALOG_FEED_URL` | Catalog feed endpoint used by the catalog fallback. |
| `PRODUCT_SUPPORT_CATALOG_MAX_PAGES` | Maximum catalog pages to process. |
| `PRODUCT_SUPPORT_CATALOG_TIMEOUT_SECONDS` | Timeout for catalog HTTP requests. |
| `PRODUCT_SUPPORT_CATALOG_MAX_RESPONSE_BYTES` | Maximum catalog response body size. |
| `PRODUCT_SUPPORT_MAX_DEMO_PRODUCTS` | Maximum manifest size; hard-limited to 100. |
| `PRODUCT_SUPPORT_MANIFEST_SEED` | Stable seed used when selecting a reproducible manifest sample. |

### Source ingestion and local storage

| Variable | Purpose and local-demo guidance |
|---|---|
| `PRODUCT_SUPPORT_MANIFEST_PATH` | Approved product manifest JSON path. Compose overrides it with the path copied into the API image. |
| `PRODUCT_SUPPORT_SOURCE_MAP_PATH` | Approved documentation source map JSON path. Compose overrides it with the path copied into the API image. |
| `PRODUCT_SUPPORT_MONGODB_URI` | MongoDB connection string. Use `mongodb://127.0.0.1:27017` from the host; Compose overrides it inside the API container to `mongodb://mongodb:27017`. |
| `PRODUCT_SUPPORT_SOURCE_USER_AGENT` | User-Agent sent by the bounded source ingestion worker. |
| `PRODUCT_SUPPORT_SOURCE_REQUEST_BUDGET` | Maximum HTTP requests per ingestion run; default 400, hard maximum 2,000. |
| `PRODUCT_SUPPORT_SOURCE_MIN_REQUEST_INTERVAL_SECONDS` | Minimum delay between requests to a host. The configured minimum is one second. |
| `PRODUCT_SUPPORT_SOURCE_MAX_RETRY_AFTER_SECONDS` | Maximum delay honored from a source `Retry-After` header. |
| `PRODUCT_SUPPORT_SOURCE_SUCCESS_FRESHNESS_HOURS` | Period during which a successfully fetched page is reused without another request. |
| `PRODUCT_SUPPORT_SOURCE_TRANSIENT_FAILURE_BACKOFF_HOURS` | Backoff after a transient source failure. |
| `PRODUCT_SUPPORT_SOURCE_PERMANENT_FAILURE_BACKOFF_DAYS` | Backoff after a permanent or protected-source failure. |
| `PRODUCT_SUPPORT_SOURCE_FAIL_FAST_CONSECUTIVE_FAILURES` | Consecutive page failures before the worker stops processing that product. |

### Foundry models and chat

| Variable | Purpose and local-demo guidance |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Foundry OpenAI-compatible chat endpoint, ending in `/openai/v1`. |
| `AZURE_OPENAI_API_KEY` | Key used by the server for Foundry chat and embeddings. Keep it in `.env` only. |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Exact Foundry chat deployment name. The template uses `gpt-5`. |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Exact Foundry embedding deployment name. The template uses `text-embedding-3-small`. |
| `AZURE_OPENAI_EMBEDDING_ENDPOINT` | OpenAI-compatible embedding endpoint. Use the endpoint for the configured Foundry resource. |

Chat requests do not include a temperature parameter because `gpt-5` and other
reasoning deployments reject it.

### Azure AI Search

| Variable | Purpose and local-demo guidance |
|---|---|
| `AZURE_AI_SEARCH_ENDPOINT` | Azure AI Search service endpoint, such as `https://<service>.search.windows.net`. |
| `AZURE_AI_SEARCH_API_KEY` | Server-side Search key used by the application for indexing and retrieval. Keep it out of browser code and source control. |
| `PRODUCT_SUPPORT_SEARCH_EMBEDDING_MODEL_VERSION` | Embedding model identifier included in the versioned Search index configuration. |
| `PRODUCT_SUPPORT_SEARCH_EMBEDDING_DIMENSIONS` | Vector size expected by the Search schema; use `1536` for `text-embedding-3-small` in this demo. |
| `PRODUCT_SUPPORT_SEARCH_DEMO_INDEX_BASE` | Base name for the versioned demo index. Keep it under the `product-support-*` namespace. |
| `PRODUCT_SUPPORT_SEARCH_TEST_INDEX_BASE` | Base name for disposable live-test indexes. Keep it under the `product-support-test-*` namespace. |

### Additional runtime and script settings

| Variable | Purpose and local-demo guidance |
|---|---|
| `PRODUCT_SUPPORT_API_BASE_URL` | Server-side URL used by Next.js to call FastAPI. Compose sets `http://api:8000`; when running Next.js on the host, use `http://127.0.0.1:8000`. Never expose it as a `NEXT_PUBLIC_*` variable. |
| `PRODUCT_SUPPORT_SEARCH_ENDPOINT` | Optional Search endpoint alias. `scripts/apply_search_index.py` requires this variable. It can also override `AZURE_AI_SEARCH_ENDPOINT` in application settings. |
| `PRODUCT_SUPPORT_SEARCH_ADMIN_KEY` | Optional Search admin-key alias. `scripts/apply_search_index.py` requires this variable; it can also override `AZURE_AI_SEARCH_API_KEY`. |
| `PRODUCT_SUPPORT_EMBEDDING_BASE_URL` | Optional alias that overrides `AZURE_OPENAI_EMBEDDING_ENDPOINT` in application settings. |
| `PRODUCT_SUPPORT_EMBEDDING_API_KEY` | Optional alias that overrides `AZURE_OPENAI_API_KEY` for embedding requests. |

## Repository structure

```text
product-support-agent/
├── .github/
│   ├── agents/                 # Repository-specific Copilot agents
│   ├── instructions/           # Python, Bicep, and CI security guidance
│   ├── licenses/               # Third-party license notices
│   ├── prompts/                # Review and threat-model prompts
│   ├── skills/
│   │   └── microsoft-agent-framework/ # Agent Framework project guidance
│   └── workflows/              # GitHub Actions validation workflow
├── apps/
│   └── web/                    # Next.js app, package lock, and build configuration
│       └── src/
│           ├── app/            # Pages, server route handlers, and styles
│           ├── components/     # Chat and UI components
│           └── lib/            # Server-side API clients and helpers
├── docs/
│   ├── architecture/           # Architecture, decisions, risks, and requirements
│   │   └── decisions/          # ADRs
│   ├── chat-sessions/          # Sanitized conversation records
│   ├── operations/             # Runbooks, manifests, source map, and evaluation
│   └── security/               # Threat model, privacy, and security posture
├── scripts/                    # Ingestion, indexing, evaluation, and maintenance
├── src/
│   └── product_support_agent/  # Python domain logic and FastAPI backend
│       └── api/                # HTTP application and endpoint wiring
├── tests/
│   ├── evaluation/             # Versioned evaluation questions
│   ├── integration/            # Opt-in live Search integration tests
│   └── unit/                   # Offline deterministic tests
├── .env.example                # Documented local environment template
├── Containerfile               # API container image
├── apps/web/Containerfile      # Web container image
├── compose.yaml                # Loopback-bound local demo stack
├── Instructions.md             # Product requirements and project constraints
├── pyproject.toml              # Python dependencies and tool configuration
└── uv.lock                     # Locked Python dependency graph
```

There is currently no `infra/` directory or deployed Azure application stack.
The Azure architecture and future infrastructure work are documented in the
[implementation plan](docs/implementation-plan.md) and
[architecture overview](docs/architecture/architecture-overview.md).

## Architecture and data flow

1. The source worker reads only
   [`phase-3-source-map-v1.json`](docs/operations/phase-3-source-map-v1.json)
   and stores permitted canonical pages and fetch state in local MongoDB.
2. `scripts/index_documents.py` creates or updates a versioned Azure AI Search
   index and writes chunks/vectors using the Foundry embedding deployment.
3. The browser sends chat requests to Next.js. The server-side route calls
   FastAPI; the agent retrieves filtered evidence from Azure AI Search and
   calls the Foundry chat deployment.
4. The API binds cited evidence IDs to retrieved source URLs. The UI renders
   answers as plain text and links from the citation list only.

See the [architecture overview](docs/architecture/architecture-overview.md)
for diagrams and [ADR-0005](docs/architecture/decisions/adr-0005-ui-and-backend-technology.md)
for the UI/backend boundary.

## Quality assurance

Install the Python development dependencies from the repository root:

```powershell
uv sync --all-groups
```

Routine Python validation is offline by default:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src/product_support_agent scripts
uv run pytest
uv run bandit -q -r src scripts
```

For web changes, run from `apps/web`:

```powershell
npm ci
npm run lint
npm run typecheck
npm run build
```

The default pytest configuration excludes live tests. The marked Search
integration test creates a dedicated `product-support-test-*` index and removes
it after the test:

```powershell
uv run pytest -m live
```

Run the local evaluation after Compose is healthy:

```powershell
uv run python scripts/run_evaluation.py --api-url http://127.0.0.1:8000
```

See the [evaluation report](docs/operations/phase-6-evaluation-v1.md) for the
current baseline and [implementation plan](docs/implementation-plan.md) for
phase completion evidence.

## Key documentation

* [Local development runbook](docs/operations/local-development.md): setup,
  environment, ingestion, indexing, chat, evaluation, and teardown.
* [Implementation plan](docs/implementation-plan.md): scope, work packages,
  phase statuses, evidence, and production-only notes.
* [Architecture overview](docs/architecture/architecture-overview.md): system
  context, components, data ownership, and trust boundaries.
* [Decision register](docs/architecture/decision-register.md) and
  [architecture decision records](docs/architecture/decisions/): accepted
  choices and rationale.
* [Threat register](docs/security/threat-register.md),
  [privacy impact assessment](docs/security/privacy-impact-assessment.md), and
  [security posture](docs/security/security-posture.md): trust, privacy, and
  security controls.
* [Production gap register](docs/operations/production-gap-register.md):
  production work, owners, and blocking triggers.
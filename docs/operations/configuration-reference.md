---
title: Configuration Reference
description: Every environment variable the Product Support Agent reads, with its purpose and local guidance
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - configuration
  - environment variables
estimated_reading_time: 5
---

`.env.example` is the template. Copy it to `.env` and edit the copy; never
commit credentials. Compose passes `.env` only to the API container and
overrides the MongoDB, queue, and manifest and source-map paths for the
container network. In Azure the same settings are supplied by the Container Apps
definitions in `infra/bicep/modules/container-apps.bicep`, with secrets from
Key Vault.

**Required to chat and ingest:** the Foundry variables, the Azure AI Search
variables, and the MongoDB URI. Everything else has a default.

## Ingestion queue

| Variable | Purpose and local-demo guidance |
|---|---|
| `PRODUCT_SUPPORT_QUEUE_CONNECTION_STRING` | Queue connection string. Compose sets Azurite's published development key; do not use a real storage key here. `PRODUCT_SUPPORT_AZURITE_QUEUE_CONNECTION_STRING` is accepted as an alias. |
| `PRODUCT_SUPPORT_QUEUE_ACCOUNT_URL` | Azure: the storage account queue URL. The job signs in with its managed identity; shared keys are disabled on the account. |
| `PRODUCT_SUPPORT_QUEUE_API_VERSION` | Storage API version for the queue client. Compose pins `2026-06-06`, the newest version Azurite 3.38 accepts. Leave unset in Azure. |
| `PRODUCT_SUPPORT_INGESTION_QUEUE_NAME` | Queue name, default `product-ingestion`. The poison queue is this name plus `-poison`. |
| `PRODUCT_SUPPORT_POISON_DEQUEUE_COUNT` | Deliveries before a message is moved to the poison queue, default 5. |

## Catalog workflow

These settings configure catalog discovery (`scripts/create_manifest.py`). They are
not needed to chat or to ingest documentation.

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

## Source ingestion and local storage

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

## Foundry models and chat

| Variable | Purpose and local-demo guidance |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Foundry OpenAI-compatible chat endpoint, ending in `/openai/v1`. |
| `AZURE_OPENAI_API_KEY` | Key used by the server for Foundry chat and embeddings. Keep it in `.env` only. |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Exact Foundry chat deployment name. The template uses `gpt-5`. |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Exact Foundry embedding deployment name. The template uses `text-embedding-3-small`. |
| `AZURE_OPENAI_EMBEDDING_ENDPOINT` | OpenAI-compatible embedding endpoint. Use the endpoint for the configured Foundry resource. |

Chat requests do not include a temperature parameter because `gpt-5` and other
reasoning deployments reject it.

## Azure AI Search

| Variable | Purpose and local-demo guidance |
|---|---|
| `AZURE_AI_SEARCH_ENDPOINT` | Azure AI Search service endpoint, such as `https://<service>.search.windows.net`. |
| `AZURE_AI_SEARCH_API_KEY` | Server-side Search key used by the application for indexing and retrieval. Keep it out of browser code and source control. |
| `PRODUCT_SUPPORT_SEARCH_EMBEDDING_MODEL_VERSION` | Embedding model identifier included in the versioned Search index configuration. |
| `PRODUCT_SUPPORT_SEARCH_EMBEDDING_DIMENSIONS` | Vector size expected by the Search schema; use `1536` for `text-embedding-3-small` in this demo. |
| `PRODUCT_SUPPORT_SEARCH_DEMO_INDEX_BASE` | Base name for the versioned demo index. Keep it under the `product-support-*` namespace. |
| `PRODUCT_SUPPORT_SEARCH_TEST_INDEX_BASE` | Base name for disposable live-test indexes. Keep it under the `product-support-test-*` namespace. |

## Telemetry and environment

Telemetry carries metadata only, never question or answer text.

| Variable | Purpose and local-demo guidance |
|---|---|
| `PRODUCT_SUPPORT_ENVIRONMENT` | Deployment environment label: `local` (default), `test`, or `production`. Any other value stops the API at startup. Bicep sets `production` for `prd` and `test` otherwise. The web app also reads it for its telemetry resource attributes. |
| `PRODUCT_SUPPORT_TELEMETRY_ENABLED` | Turns OpenTelemetry export on or off, default `true`. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint. Compose points it at the bundled Aspire dashboard. Leave empty to skip OTLP export; the web app exports only when it is set. |
| `PRODUCT_SUPPORT_TELEMETRY_CONSOLE` | Also write traces, metrics, and logs to the console, default `false`. |
| `PRODUCT_SUPPORT_TELEMETRY_METRIC_INTERVAL_MS` | Metric export interval in milliseconds, default 15000. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Azure Monitor export. Treat it as configuration, not a credential, when `PRODUCT_SUPPORT_TELEMETRY_USE_MANAGED_IDENTITY` is `true`. |
| `PRODUCT_SUPPORT_TELEMETRY_USE_MANAGED_IDENTITY` | Authenticate Azure Monitor export with a managed identity, default `false`. |
| `AZURE_CLIENT_ID` | Client ID of the user-assigned managed identity used for Azure Monitor export. |
| `OTEL_SERVICE_NAME` | Service name reported by the web app, default `product-support-web`. |

The settings `PRODUCT_SUPPORT_QUERY_RESPONSE_RETENTION_ENABLED`,
`PRODUCT_SUPPORT_QUERY_RESPONSE_RETENTION_DAYS`, and
`PRODUCT_SUPPORT_QUERY_REVIEWER_ROLE` exist for a future retention feature.
Leave retention disabled; enabling it requires a reviewer role and privacy
approval.

## Additional runtime and script settings

| Variable | Purpose and local-demo guidance |
|---|---|
| `PRODUCT_SUPPORT_API_BASE_URL` | Server-side URL used by Next.js to call FastAPI. Compose sets `http://api:8000`; when running Next.js on the host, use `http://127.0.0.1:8000`. Never expose it as a `NEXT_PUBLIC_*` variable. |
| `PRODUCT_SUPPORT_SEARCH_ENDPOINT` | Optional Search endpoint alias. `scripts/apply_search_index.py` requires this variable. It can also override `AZURE_AI_SEARCH_ENDPOINT` in application settings. |
| `PRODUCT_SUPPORT_SEARCH_ADMIN_KEY` | Optional Search admin-key alias. `scripts/apply_search_index.py` requires this variable; it can also override `AZURE_AI_SEARCH_API_KEY`. |
| `PRODUCT_SUPPORT_EMBEDDING_BASE_URL` | Optional alias that overrides `AZURE_OPENAI_EMBEDDING_ENDPOINT` in application settings. |
| `PRODUCT_SUPPORT_EMBEDDING_API_KEY` | Optional alias that overrides `AZURE_OPENAI_API_KEY` for embedding requests. |

---
title: Product Support Agent Support Ownership
description: Roles, responsibilities, escalation rules, and runbooks for operating the demo locally and in Azure
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - support ownership
  - RACI
  - operations
  - runbook
estimated_reading_time: 7
---

## Status

The demo has no service level, on-call rotation, or incident commitment. The
product owner holds every role until named owners are assigned; one person may
hold several roles, but each responsibility stays explicit.

## Roles

| Role | Responsibility |
|---|---|
| Product owner | User outcomes, scope, the 100-product sample, source map changes, and release decisions |
| Application maintainer | Code, tests, pipelines, defect triage, and these runbooks |
| Ingestion and data owner | Source policy, the manifest, ingestion runs and their outcomes, the store, and the index |
| AI and evaluation owner | Model deployments, prompts, citation behaviour, the evaluation set, and its thresholds |
| Privacy and security reviewer | Telemetry content, retention decisions, the threat register, and incident handling |
| Cloud platform owner | The Azure subscription, Bicep, identities, networking, runners, and cost |
| Demo operator | Local prerequisites, service health, and demo readiness |

## Responsibilities

| Activity | Accountable | Responsible | Consulted |
|---|---|---|---|
| Change the product sample or the source map | Product owner | Ingestion and data owner | Privacy and security reviewer |
| Run ingestion and review outcomes | Ingestion and data owner | Demo operator | Product owner |
| Force a refetch (`--force`) | Product owner | Ingestion and data owner | — |
| Change the model, prompts, or evaluation thresholds | Product owner | AI and evaluation owner | Application maintainer |
| Change telemetry content or enable retention | Privacy and security reviewer | Application maintainer | Product owner |
| Deploy infrastructure or change Azure resources | Cloud platform owner | Cloud platform owner | Privacy and security reviewer |
| Publish and deploy application images | Application maintainer | Application maintainer | Cloud platform owner |
| Triage demo failures | Product owner | Application maintainer, demo operator | Ingestion and AI owners |
| Respond to a security incident | Privacy and security reviewer | Application maintainer | Cloud platform owner |

## Escalation rules

* **Source behaviour.** On unexpected authentication prompts, redirects, rate
  limits, or response sizes, stop ingestion. The worker already backs off. Do
  not clear fetch state or use `--force` to retry a protected or rate-limited
  source.
* **Grounding.** If citations stop resolving to retrieved evidence, stop the
  demo and treat it as a defect.
* **Leaks.** If a log or trace shows a secret or user content, stop the
  affected service, rotate the secret, and purge the telemetry.
* **Azure services.** Escalate quota, capacity, and availability problems to the
  cloud platform owner. Do not change subscription-level settings or
  credentials from the application.

## Runbooks

Commands run from the repository root. Locally, run them inside the API
container with `podman compose run --rm api python scripts/...`; in Azure, start
the ingestion job instead.

### Check the last ingestion run

```bash
podman compose run --rm api python scripts/run_queue_ingestion.py status
curl -s http://127.0.0.1:8000/ingestion/runs/latest
```

A run is `completed` when every product has an outcome, and
`completed_with_errors` when any product is `partial`, `failed`, or
`dead_letter`. The per-product records are in the `product_ingestion_status`
collection.

### Re-run ingestion

```bash
podman compose run --rm api python scripts/run_queue_ingestion.py run
```

In Azure:

```bash
az containerapp job start --name <ingestion-job> --resource-group <resource-group>
az containerapp job execution list --name <ingestion-job> --resource-group <resource-group> -o table
```

Fresh pages (fetched in the last 24 hours) and pages under backoff are skipped,
so a re-run is cheap. Use `--product <id>` to limit a run.

### A run will not start: "another ingestion run holds the lease"

A run that was killed keeps its lease for up to 6 hours. First confirm that no
worker is running (`podman ps`, or the job's execution list in Azure). Then
delete the lease from the `ingestion_leases` collection in the
`product_support` database:

```javascript
db.ingestion_leases.deleteOne({ _id: "source-ingestion" })
```

Locally, open the shell with `podman compose exec mongodb mongosh product_support`.

### Messages in the poison queue

A product whose message was delivered five times is recorded as `dead_letter`
and its message is moved to `product-ingestion-poison`. Find the product in the
run status, fix the cause (usually a source change or an outage), then run
ingestion again for that product with `--product <id>`. Clear the poison queue
after review.

### The chat returns errors

| Response | Meaning | Check |
|---|---|---|
| 502 `chat model unavailable` | Foundry rejected or failed the call, often 429 throttling | Deployment capacity and quota; Foundry key |
| 503 `search service unavailable` | Azure AI Search failed | Search endpoint, key, and index name |
| 504 `chat request timed out` | No answer within 30 seconds | Model latency in the trace |
| 422 `uncovered_product` | A product filter names a product with no indexed source | Expected behaviour |

Each API response has an `X-Request-ID` header; search for it as the
`psa.request_id` span attribute in Aspire or Application Insights.

### Rotate a secret

In Azure, the apps read three Key Vault secrets: `mongodb-connection-string`,
`azure-ai-search-api-key`, and `azure-openai-api-key`. Set a new version in Key
Vault, then restart the API revision and let the next ingestion run pick it up.
Locally, update `.env` and run `podman compose up -d`.

### Retire an Azure environment

Delete the resource group, then purge the soft-deleted Key Vault and, if
deployed, the Foundry account and API Management instance, so that names can
be reused. See the [cloud setup guide](../../infra/README.md).

## Before a production service

Assign named owners and on-call cover, define service level objectives and
alerts, write incident and restore procedures, and test them. These items are in
the [production gap register](../operations/production-gap-register.md).

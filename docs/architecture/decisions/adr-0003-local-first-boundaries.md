---
title: ADR-0003 Local-First Development with an Azure Counterpart
description: Podman Compose for local development, and a matching Azure deployment from Bicep
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - local development
  - Podman
  - Azure
---

## Status

Accepted.

## Context

The brief asks for Podman locally, MongoDB locally and Azure Cosmos DB for
MongoDB in the cloud, Azurite locally and Azure Storage Queue in the cloud, and
the user-provided Azure AI Search in both. The backend is hosted on Azure
Container Apps.

## Decision

* Run the whole application locally with Podman Compose: the web app, the API,
  MongoDB, Azurite, and an Aspire dashboard for telemetry. Published ports bind
  to `127.0.0.1` only, because the demo has no end-user sign-in.
* Use Azure AI Search and Microsoft Foundry as the only cloud dependencies of
  local development.
* Run ingestion as a one-shot job, not a long-running service. Locally it is
  `podman compose run`; in Azure it is a Container Apps job on a weekly
  schedule. A lease in the store prevents overlapping runs.
* Give every local component a cloud counterpart:

| Local | Azure |
|---|---|
| `web` container | Container App with external ingress |
| `api` container | Container App with internal ingress |
| Ingestion command | Container Apps job |
| MongoDB 8 | Azure Cosmos DB for MongoDB, or Azure DocumentDB Free |
| Azurite queue | Azure Storage Queue |
| Aspire dashboard | Application Insights and Log Analytics |
| `.env` file | Key Vault secrets read with managed identity |

## Rationale

The same images, configuration names, and code paths run in both places, so a
change tested locally behaves the same in Azure. Only connection settings and
credentials differ.

## Alternatives considered

* Develop against shared Azure resources only: rejected, because it is slower
  to iterate and costs money for every developer.
* Bind local services to all interfaces: rejected, because the demo has no
  sign-in.

## Consequences

* Local development depends on network access and quota for the Foundry and
  Search services.
* Azurite can lag the Storage service API version; Compose pins a supported
  version (`PRODUCT_SUPPORT_QUEUE_API_VERSION`).
* The Azure stack is defined in [ADR-0010](adr-0010-azure-platform-and-api-management.md).

---
title: ADR-0003 Local-First Hosting Boundaries
description: Proposed local MVP boundary and conceptual Azure deployment posture
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: decision
keywords:
  - ADR
  - local-first
  - deployment
---

## Status

Phase 0 direction approved; cloud design and deployment gates remain in Phase 7.

## Context

The demonstration should run locally with Podman. The Azure architecture is a
blueprint for Canada Central, and the application stack is not part of MVP
deployment. A separately gated network slice is planned for Phase 7.

## Proposed decision

* Keep the MVP local-first and organize the Next.js frontend, FastAPI/agent,
  catalog, and worker as distinct logical components.
* Use Podman for local orchestration, Azurite for local queue emulation, and
  MongoDB for local metadata and canonical records.
* Keep user-provided Azure AI Search and Foundry services external to the local
  Podman network.
* Do not deploy APIM, the application stack, Cosmos DB, Azure AI Search, or
  Container Apps as part of the MVP.
* Treat the network slice as a separate Phase 7 operation requiring explicit
  subscription, cost, and deployment approval.

## Alternatives considered

* Deploy the full stack to Azure during the MVP: rejected because it adds
  significant cost and exceeds the local-first scope.
* Bind the local UI to a public interface: rejected because the local MVP has
  no end-user authentication.

## Consequences

Local demo operation depends on the developer's network, user-supplied
credentials, service availability, quota, and Azure AI Search access policy.
The exact local process/container split and cloud topology remain subject to
Phase 0 and Phase 7 review.

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
The TypeScript React/Next.js frontend and Python FastAPI backend now provide a
grounded chat demo. The browser talks only to Next.js; the server-side route
calls FastAPI. Chat and embeddings use the user's Microsoft Foundry deployments
directly through the OpenAI-compatible endpoint, and retrieval uses the user's
Azure AI Search service. Search citations are resolved from retrieved evidence;
the model cannot author their URLs.

The approved source map covers 10 of the 100 manifest products. The resumable
worker ([ADR-0006](docs/architecture/decisions/adr-0006-periodic-resumable-source-ingestion.md))
stored 300 pages in MongoDB, and Phase 4 indexed 952 chunks into the demo Search
index. The local Compose stack includes MongoDB, Azurite, FastAPI, and Next.js.
The Phase 6 evaluation reached an 80% expected-source hit rate in the top five,
100% citation URL matches, and 3/3 refusals for unanswerable questions; see the
[evaluation report](docs/operations/phase-6-evaluation-v1.md).

Phases 0 to 6 are complete. The [local runbook](docs/operations/local-development.md)
starts the stack with `podman compose up --build -d`. This is a local demo, not
a production deployment; see the [production gap register](docs/operations/production-gap-register.md)
for deferred controls and their blocking triggers.

See the [architecture overview](docs/architecture/architecture-overview.md) for
the current process and component diagrams.

See the [implementation plan](docs/implementation-plan.md) for phase status and
the [local development guide](docs/operations/local-development.md) for setup
and validation commands.
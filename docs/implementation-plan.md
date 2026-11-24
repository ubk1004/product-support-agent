---
title: Delivery History and How This Was Built
description: How the Product Support Agent was delivered in phases, what each phase produced, and where the working conversations are recorded
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: concept
keywords:
  - delivery history
  - phases
  - implementation
estimated_reading_time: 6
---

This page explains how the repository reached its current state. It is a
history, not a specification. For what the system is and does, read the
[solution architecture](architecture/architecture-overview.md); for how each
original requirement was met, read the
[requirements traceability](architecture/requirements-traceability.md).

## Starting point

The work began with the brief in [Instructions.md](../Instructions.md): build a
working AI agent that answers questions about OpenText products and their
resources, from anonymous public sources, with grounded and cited answers, and
show the production path. The brief also set the stack (Next.js, FastAPI,
Microsoft Agent Framework, MongoDB or Cosmos DB, Azure AI Search, a queue,
OpenTelemetry, Bicep, GitHub Actions, Podman) and asked for a 100-product
sample, a queue with one product per message, and architecture and decision
documents.

## Method

The delivery used AI coding assistants (GitHub Copilot, then Claude Code) under
the author's direction:

1. **Plan before building.** The assistant first turned the brief into a
   phased plan with exit criteria, and the author critiqued and approved it
   phase by phase before any implementation.
2. **Decide and record.** Each significant choice became an
   [architecture decision record](architecture/decisions/) and a row in the
   [decision register](architecture/decision-register.md). Threats, risks, and
   privacy questions were written down before the code that touched them.
3. **Test each phase.** A phase finished when its tests passed. Routine tests
   run offline against fakes and emulators; live checks against Azure were
   opt-in.
4. **Check against the real sources.** Live probes of the OpenText endpoints
   changed the design: the product pages hold no documentation text, and the
   search API needs authentication, so the content comes from a reviewed source
   map instead ([ADR-0002](architecture/decisions/adr-0002-source-access-and-manifest.md)).
5. **Review against the brief, then harden.** A review of the demo against the
   original requirements led to the later work: a `list_products` tool and
   conversation context, claim-support evaluation, queue-driven ingestion,
   OpenTelemetry, API Management, and the Azure pipelines.

## Phases

| Phase | Outcome |
|---|---|
| 0. Discovery and decisions | Users, tasks, scope, data ownership, source policy, and the first ADRs |
| 0b. Threat model and privacy | Assets, trust boundaries, rated threats, and the privacy assessment |
| 1. Repository foundation | Layout, Podman Compose stack, configuration, log redaction, CI validation workflow |
| 2. Catalog and resilient ingestion | Catalog discovery with feed fallback, the 100-product manifest, the first ingestion worker, 401 and 429 handling |
| 3. Canonical documents and retrieval | Document schema, source map, resumable source worker with freshness, backoff, and lease, hybrid Azure AI Search index, coverage view |
| 4. API and agent | FastAPI chat endpoint, Microsoft Agent Framework agent, server-side citation binding, limits and refusals |
| 5. Chat interface | Next.js chat with coverage disclosure, product filter, numbered citations, and no stored history |
| 6. Local demo and evaluation | Integrated stack, evaluation set, runbook |
| 7. Cloud design | Bicep for the Azure estate; build, infrastructure, and deployment workflows |
| Hardening | `list_products` tool, evaluation v2 with claim support, queue-driven ingestion, OpenTelemetry, classic API Management, two-stage deployment, a verified isolated Azure deployment, pipeline fixes, and the documentation set |
| Documentation | Final review of all documents for accuracy, removal of phase-specific evidence, the cloud setup guide, and the requirements traceability |

Phase 8 (a cloud pilot with real users) and phase 9 (the gap register, now the
[production gap register](operations/production-gap-register.md)) describe work
beyond the demo.

## Evidence kept

* **Decisions:** [ADR-0001 to ADR-0010](architecture/decisions/) and the
  [decision register](architecture/decision-register.md).
* **Chat sessions:** [chat-sessions](chat-sessions/) holds eight sanitised
  exports of the assistant conversations that produced the plan and the
  implementation, from the first instruction review to the cloud design. They
  show the prompts, the critique and approvals, and the iterations. They are a
  record of how the work was directed, not documentation of the system; the
  documents listed above are authoritative where they differ. Secrets and
  personal identifiers were removed by `scripts/sanitize_chat_sessions.py`.
* **Evaluation:** the generated [evaluation report](operations/phase-6-evaluation-v2.md).
* **Recorded demo:** [docs/demo](demo/) shows the application end to end.
* **Modernisation note:** [m365-modernization-assessment.md](m365-modernization-assessment.md)
  is a separate assessment kept for reference; it does not describe this system.

## Where the delivered solution differs from the brief

The differences, with reasons, are in the
[requirements traceability](architecture/requirements-traceability.md#where-the-delivered-solution-differs-from-the-brief).
In short: documentation comes from a source map rather than the product pages;
the models are called directly with no LiteLLM gateway; past queries are not
retained; and Search and Foundry use keys.

## Rules the delivery followed

The [guardrails in ADR-0007](architecture/decisions/adr-0007-demo-delivery-mode.md#guardrails-that-always-apply)
applied throughout: no secrets in git, anonymous source access only, the source
map as the only crawl list, citations bound to retrieved evidence, retention
off, local services on loopback, and offline routine tests. Creating Azure
resources, new spending, new source hosts, and retention each needed the
owner's decision.

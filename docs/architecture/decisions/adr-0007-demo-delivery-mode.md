---
title: ADR-0007 Demo Scope and Delivery Guardrails
description: What the demo commits to, the guardrails every contributor follows, and the controls reserved for production
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - governance
  - guardrails
---

## Status

Accepted.

## Context

The project is a working demonstration of an agentic support assistant and its
path to production, not a production service. Some controls protect real
systems and must always hold; others matter only before real users rely on the
service.

## Decision

### Guardrails that always apply

1. Never commit secrets, `.env`, fetched content, or database data.
2. Access sources anonymously only. Never authenticate to, or work around, a
   protected source.
3. Fetch documentation only from the versioned
   [source map](../../operations/phase-3-source-map-v1.json), through the source
   worker, which enforces `robots.txt`, request budgets, and backoff.
4. Keep citations bound to retrieved evidence. The model never authors URLs.
5. Keep query and response retention off.
6. Bind local services to `127.0.0.1`. Do not expose the demo publicly without
   sign-in.
7. Keep routine tests offline. Tests that call Azure are opt-in (`pytest -m live`).
8. Keep Ruff, mypy, pytest, Bandit, and the web checks passing.

### Changes that need an owner's decision

* Creating or changing Azure resources, including deployments from the
  pipelines. Production deployment also needs the environment's required
  reviewers.
* New model deployments, SKU changes, or other new spending.
* Adding a source host or a product to the source map.
* Enabling query and response retention.

### Controls reserved for production

These are designed or recorded, not performed, for the demo:

| Area | Production expectation | Demo treatment |
|---|---|---|
| Source terms | Legal review of documentation reuse terms | Public, `robots.txt`-permitted pages for a private demo |
| Retrieval quality | Reviewed, larger question set with agreed thresholds | 21-question synthetic set with documented thresholds |
| Usability and accessibility | Moderated study; WCAG 2.2 AA audit | Semantic HTML, labels, keyboard operation, visible focus |
| Privacy | Approved notice, reviewer access, redaction, retention period, deletion | Retention off |
| Identity | End-user sign-in; keyless access to Search and Foundry | Anonymous users; keys for Search and Foundry |
| Operations | SLOs, alerts, on-call, incident response, backup and restore | Telemetry collected; no alerts or on-call |
| Supply chain | Branch protection, required checks, image signing and provenance | CI checks defined; branch protection not configured |

Each item is tracked in the
[production gap register](../../operations/production-gap-register.md).

## Consequences

* Any move to a public pilot, real users, or customer data turns the reserved
  controls into blockers.
* The guardrails apply to people and coding assistants alike; they are repeated
  in `.github/copilot-instructions.md`.

---
title: Product Support Agent Risks and Assumptions
description: Phase 0 risk and assumption register for the local-first product support demo
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: reference
keywords:
  - risk register
  - assumptions
  - product support
estimated_reading_time: 6
---

## Status

This Phase 0 risk and assumption register is preliminary. Detailed STRIDE and
AI-specific threats are tracked in the
[Phase 0b threat register](../security/threat-register.md). Ratings are
qualitative and require review.

## Risks

| ID | Risk | Rating | Proposed response | Owner | Phase |
|---|---|---|---|---|---:|
| R-01 | The feed parsed into 1,302 unique products, but the product pages are client-rendered and contain no product text; the old heuristic flagged them on navigation links. | Resolved for content | Product pages are now the catalog only. Documentation comes from the source map, and the heuristic was narrowed to real login walls. | Product owner and ingestion lead | 0, 2, 3 |
| R-02 | The search API returned 401; protected support content could be misclassified as missing or retried with unsafe credentials. | High | Treat 401/403 and login redirects/content as protected skips. Never authenticate or bypass access restrictions. | Ingestion lead | 2 |
| R-03 | Random product selection could vary between runs and make the UI and evaluation irreproducible. | Medium | Parameterize the maximum at 100; persist and version one exact random manifest; require explicit replacement and show product-level ingestion outcomes. | Product owner | 2 |
| R-04 | The user requests query/response retention for demo review, but notice, access, redaction, retention, and deletion rules are not approved. | High | Add global and per-session off controls, default retention off, and do not retain real content until the Phase 0b privacy policy is approved. | Privacy owner, TBD | 0b, 6 |
| R-05 | Local access to Azure AI Search and Foundry depends on user-supplied service configuration, network access, quota, and authentication. | Medium | Keep unit/integration tests deterministic; document connectivity and quota prerequisites for the local demo. | Demo operator, TBD | 1, 6 |
| R-06 | The model may repeat injected source instructions, invent citations, or render unsafe source links. | High | Treat source text as untrusted; render only server-resolved URLs from retrieved evidence; test injection and rendering paths. | Agent lead | 0b, 4, 5 |
| R-07 | The designed cloud network and identity may not match current regional SKU, quota, or service constraints. | Medium | Bicep build and lint pass; the subscription what-if was blocked by an expired token, so validate live service constraints with an authorized session before deployment. | Cloud architect, TBD | 7 |
| R-09 | Documentation source terms are unverified. The `www.microfocus.com/legal` page returned 403 to automated access, and public access does not establish reuse rights. | High | Review the terms manually and record the result before the first ingestion run; until then, run only `--discover-only` or offline tests. | Product owner | 3 |
| R-10 | A scheduled indexer could repeat requests after a crash, overlap with another run, or keep hitting failing sources. | Medium | Durable per-URL fetch state, a 24-hour freshness window, conditional GETs, classified backoff, product fail-fast, host abort on 429, a request budget, and a single-runner lease (ADR-0006). | Ingestion lead | 3 |
| R-11 | The curated source map covers 10 of 100 manifest products and is biased toward the former Micro Focus documentation portals. | Medium | The home page coverage view discloses indexed products first and labels the rest as not covered; no content is invented. | Product owner | 3, 5 |
| R-08 | “Working demo” may not establish that target users can complete useful support tasks. | Medium | Define users, priority tasks, task success measures, and a moderated usability study in Phase 0/5. | Product owner | 0, 5 |

## Assumptions

| ID | Assumption | Validation or decision |
|---|---|---|
| A-01 | Product and support pages may be accessed only when publicly available without authentication. | Confirm source terms and permitted automated access before Phase 2. |
| A-02 | The local demo uses the user's Azure AI Search and Foundry deployments; no local model or vector store is introduced. | Confirm endpoint/deployment configuration and Entra ID or key-based auth in Phase 0. |
| A-03 | The demo catalog uses a random, stable manifest with a parameterized hard maximum of 100 products. | Persist the selected IDs and outcomes; do not exceed the hard maximum or replace a manifest without an explicit operation. |
| A-04 | MongoDB is the local metadata/canonical-data candidate; Azure AI Search is the derived search index. | Approve system-of-record ownership and retention before Phase 2. |
| A-05 | The MVP is local-first. The application stack is not deployed to Azure. | Keep cloud IaC design-only and require separate authorization before any resource or workload deployment. |
| A-06 | Query/response retention is a requested demo feature, but must be disabled until policy approval. | Approve the privacy impact assessment, notice, access, redaction, retention, and deletion controls before enabling it. |
| A-07 | User questions, retrieved text, and provider responses are untrusted inputs. | Enforce validation, provenance, redaction, and abuse-case tests. |

## Source probe evidence

The initial probe is summarized in the
[decision register](./decision-register.md#initial-source-probe). The result is
not sufficient to claim that catalog discovery or fallback behavior is verified.
No product content was stored.

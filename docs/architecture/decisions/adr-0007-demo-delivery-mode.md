---
title: ADR-0007 Demo Delivery Mode
description: Lighter governance for the working local demo, with production-only controls recorded rather than performed
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: decision
keywords:
  - ADR
  - governance
  - delivery
  - production readiness
---

## Status

Accepted by the user on 2026-11-22. This ADR supersedes the per-phase approval
loop described in earlier versions of the
[implementation plan](../../implementation-plan.md).

## Context

The goal is a working local demo that runs end to end against real Azure
resources (Microsoft Foundry models and Azure AI Search). The demo is followed
by CI/CD definitions for IaC and for build and deployment. The demo exists to
show web and agentic architecture skills. It is not meant to be a
production-ready application.

The earlier plan required explicit approval before every phase, every live
request batch, and every exit item. That loop cost more time than the risk it
controlled. Phases stalled on approvals that matter only before a production
release.

## Decision

### Delivery mode

The project runs in **demo delivery mode** until a production decision is
made. In this mode, a contributor, human or coding agent, may proceed through
Phases 4 to 7 without asking for approval, as long as the guardrails below hold.

### Guardrails that always apply

These are cheap, protect real systems, and stay in force in demo mode:

1. Never commit secrets, `.env`, scraped content, or MongoDB data.
2. Anonymous access only. Never authenticate to, or bypass, a protected source.
3. Fetch source content only from the versioned
   [source map](../../operations/phase-3-source-map-v1.json), through the
   source worker, which enforces `robots.txt`, request budgets, and backoff.
4. Keep citations bound to retrieved evidence. The model never authors URLs.
5. Keep query/response retention off (`QUERY_RESPONSE_RETENTION_ENABLED=false`).
6. Bind local services to loopback. Do not expose the demo publicly.
7. Keep routine tests offline (fakes and mocks). Live tests are opt-in with
   `-m live`.
8. Keep `ruff`, `mypy`, `pytest`, `bandit`, and the web checks passing.

### Pre-authorized actions

Actions authorized for the demo without further approval:

| Action | Limit |
|---|---|
| Live documentation ingestion with `scripts/run_source_ingestion.py` | The default budget (400 requests per run), at most one run per day; a weekly schedule is fine |
| Calls to the user-provided Foundry chat and embedding deployments in `.env` | Demo and test traffic only; keep batches small |
| Creating, updating, or deleting indexes in the user-provided Azure AI Search service | Index names must start with `product-support-` |
| Live integration tests against a `product-support-test-*` index | Opt-in with `pytest -m live` |
| Local Podman containers for this project | The project's `compose.yaml` services only; do not touch other projects' containers |
| Authoring Bicep, GitHub Actions workflows, and pipeline definitions | Authoring and static validation (`az bicep build`, `what-if` where possible) |

### Actions that still need the user

* Creating or changing Azure resources other than the Search indexes above,
  including deploying the network slice or the application.
* Spending outside the existing deployments, such as new model deployments or
  SKU changes.
* Adding a new source host or product to the source map.
* Enabling query/response retention.

### Deferred to production

The following controls are part of a production-grade delivery. They are
**recorded and designed, not performed** for the demo, and do not block any
demo phase:

| Area | Production expectation | Demo treatment |
|---|---|---|
| Phase gates | Formal exit review and sign-off per phase | Exit criteria are the definition of done; no sign-off loop |
| Source terms | Legal review of documentation reuse terms | Public, `robots.txt`-permitted docs used for a private, non-commercial demo; review before any public or commercial use |
| Retrieval quality | Reviewed, versioned relevance set with agreed thresholds and sign-off | Small synthetic evaluation set with the documented thresholds (Phase 6); no human review panel |
| Semantic reranking | Measured decision against the reviewed set | Off by default; may be enabled if the Search tier allows it, noted in the plan |
| Usability | Moderated study with representative users | Self-walkthrough of the five demo tasks |
| Accessibility | Automated scans plus manual keyboard and screen-reader review against WCAG 2.2 AA | Semantic HTML, labels, and keyboard checks; a full audit is deferred |
| Privacy | Approved notice, reviewer access, redaction, TTL, and deletion before retention | Retention stays off |
| Threat model | Every high-rated threat tested or formally accepted per phase | Register maintained; tests for the guardrails above; remaining threats noted as production work |
| Identity | Entra ID, managed identity, and keyless access to Search and Foundry | API keys from `.env` |
| Network | Private endpoints, VNet, and controlled egress | Public endpoints from the developer machine |
| Observability | OpenTelemetry to Azure Monitor with retention policy | Structured, redacted logs; optional local tracing |
| Supply chain | Branch protection, required checks, image scanning, provenance | CI workflow runs checks; branch protection is a backlog item |
| Operations | SLOs, on-call, incident response, backup and restore | Not applicable to a local demo |

## Consequences

* Phases 4 to 7 can be completed in sequence without waiting for approvals,
  within the guardrails and pre-authorized actions.
* The documentation still shows the production path: each deferred control has
  a design or an entry in the threat register, the security posture, or the
  production gap register (Phase 9).
* Any move toward production, a public demo, or customer data reopens the
  deferred controls. They then become blocking.

## Alternatives considered

* Keep per-phase approval: rejected, because it was the main delay and
  protected nothing that mattered for a private demo.
* Drop the governance documentation entirely: rejected, because the
  documentation shows that the production controls are understood.

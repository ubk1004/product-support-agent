---
title: Production Readiness Gap Register
description: Known controls and decisions deferred beyond the local demo
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: reference
keywords:
  - production readiness
  - risk
  - security
---

## Intentional demo scope

The controls below are known and documented. This iteration prioritized a
working local system over production readiness; their absence is an intentional
demo-scope decision, not an untracked omission. Completing this register does
not approve a public or production launch.

The register consolidates the deferred controls in
[ADR-0007](../architecture/decisions/adr-0007-demo-delivery-mode.md), the
Phase 4 to 7 **Production-only** notes in the
[implementation plan](../implementation-plan.md), open items in the
[threat register](../security/threat-register.md), and risks in the
[risk-and-assumption register](../architecture/risk-assumptions.md).

| Gap | Owner role | Blocking trigger | Demo treatment and production work |
|---|---|---|---|
| Source terms and reuse rights (R-09) | Product owner / legal | Public or commercial use of indexed content | The demo uses only the approved source map and anonymous access. Review and record reuse terms before expanding beyond this private demo. |
| Retrieval quality and evaluation (D3-3, R-11) | Search and support-content owners | Customer-facing answers or a quality commitment | The 21-question evaluation (v2) reached 80% expected-source hits in the top five, 100% citation URL validity, 6/6 refusals in the latest run, and 83.3% model-judged claim support. Claim support varied between runs (71.4%, 76.9%, 83.3%), so the 80% target is not reliably met. The set is small, synthetic, and not human-reviewed; broaden it, report a range over repeated runs, and add human review of judged answers before launch. |
| Semantic reranking | Search owner | Relevance improvement is required or before a production ranking decision | Not evaluated: the Search service tier and billing plan could not be verified. No setting was changed; confirm availability and billing before testing it. |
| Prompt injection and model-output links (T-01, T-05, T-16, R-06) | Agent and application-security owners | Public exposure or reliance on answers for customer action | Retrieved text is treated as untrusted; citations are evidence-bound, model-authored URLs are removed, and focused prompt-injection and citation-forgery cases pass. Add independent red-team coverage and review output-safety controls. |
| Chat abuse and spend controls (T-08, R-05) | AI platform owner | Public access, shared usage, or a committed cost limit | `/chat` bounds message size, tool calls, concurrency, and elapsed time. Global rate limits, per-user budgets, quota alerts, and cost SLOs are production work. |
| Authentication and least privilege (T-11, T-14) | Identity and application owners | Public demo, customer data, or production launch | The application is anonymous and loopback-bound; local service keys come from `.env`. Add user authentication and managed identity or equivalent least-privilege access before broader exposure. |
| Private networking and egress (T-15, R-07) | Cloud/network architect | Production deployment or access to private data | The local demo reaches user-provided public Foundry and Search endpoints. Validate private endpoints, DNS, service tiers, quota, and allowlisted egress in the cloud design before deployment. |
| Query/response privacy and retention (R-04) | Privacy owner | Any request to retain user content or process customer data | Retention remains off and query/response text is not logged. Approve notice, provider handling, reviewer access, redaction, TTL, and deletion before enabling retention. |
| Observability and service objectives | Operations and security owners | Production launch or a support commitment | Logs carry request IDs, latency, token counts, and outcomes without query/response text. Define latency/cost SLOs, alerting, trace controls, and Azure Monitor export. |
| Usability and accessibility (R-08) | Product and accessibility owners | Public or customer-facing release | The demo has labels, keyboard operation, visible focus, `aria-live`, and a self-walkthrough. Conduct moderated usability and full WCAG 2.2 AA keyboard and screen-reader review. |
| Supply-chain assurance (T-13) | Build and release owner | Publishing images or production deployment | Dependencies are locked and CI checks run; local container images build successfully. Add image scanning, SBOM/provenance, signing, protected release environments, and required branch checks. |
| IaC and CI/CD production gates | Cloud platform and security owners | Production deployment or protected release | Static build and lint validate authoring only. Add PSRule or Checkov, CIDR-overlap and DNS-pairing checks, a detailed cost estimate, APIM SKU selection, and branch protection with required reviewers before deployment. |
| Backup, restore, and incident operations | Data and operations owners | Production launch or any non-recoverable data | MongoDB data is local and no snapshot/restore procedure, on-call rotation, or incident-response process is defined. Establish and test them before production use. |
| Product and source coverage (R-11) | Product owner / ingestion lead | A broader product-support claim or a new source host/product | Only 10 of the 100 manifest products have approved sources. Keep the coverage disclosure; review new products or hosts before adding them. |
| Azure application deployment | Cloud platform owner | Any Azure application workload or new Azure resource | The demo stack is local. Azure deployment, resource creation other than approved Search indexes, and new spend require separate user authorization. |
| API Management in external VNet mode (requirement 18) | Cloud/network architect | Any cloud deployment | The optional APIM module uses the `Consumption` SKU with no VNet integration, so it cannot meet the external-mode requirement. Choose a SKU that supports VNet integration (for example `Developer` or `StandardV2`), add its subnet and NSG, and record the cost decision. |
| OpenTelemetry tracing and metrics (requirement 11) | AI platform and operations owners | Production launch or a support commitment | Not implemented. The app writes metadata-only JSON logs with request IDs, latency, token counts, and outcomes. Add OpenTelemetry export for the API and agent calls to a collector such as Aspire or Arize Phoenix locally and Azure Monitor in the cloud. |
| Query and response retention for review (requirement 8) | Privacy owner | Any request to review user sessions | Not implemented; retention is off, so questions and answers from demo sessions are not kept. Build the access-controlled store only after notice, redaction, TTL, and reviewer access are approved. |
| Ingestion queue scale-out | Platform owner | More than one concurrent ingestion worker | The queue is used: one message per product, at-least-once delivery, poison queue, and per-product outcomes in MongoDB. A run-wide lease allows one worker at a time so that the request budget and per-host spacing hold. Parallel workers need a shared, distributed rate limiter per source host before the lease is relaxed. |
| DAST, IAST, and hosted CI evidence (requirement 13) | Application-security and build owners | Production deployment | CI runs Ruff, mypy, pytest, Bandit, and pip-audit. DAST and IAST are not set up, and hosted GitHub Actions runs were not verified. |

## Current release boundary

The local demo is not approved for public access, customer data, or production
operations. Keep services bound to `127.0.0.1`, use only the versioned
source map, and keep query/response retention disabled.

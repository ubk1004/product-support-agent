---
title: Production Readiness Gap Register
description: Every control the demo does not yet provide, the trigger that makes it a blocker, and the work needed
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - production readiness
  - risk
  - security
estimated_reading_time: 6
---

## Scope

The demo was built to show a working, grounded agent and a deployable Azure
design, not to run a production service. The gaps below are known and
deliberate. Each is linked to its threat (T-), risk (R-), or requirement (AC)
where one exists. Closing the gaps follows the stages in the
[path to production](../architecture/architecture-overview.md#path-from-proof-of-concept-to-production).

## Gaps

| Gap | Becomes a blocker when | Today | Work needed | Owner role |
|---|---|---|---|---|
| End-user authentication (T-14) | Anyone other than the team uses the demo | Anonymous; local services on `127.0.0.1` | Entra ID sign-in on the web app; per-user isolation | Identity and application owners |
| Keyless access to Search and Foundry (T-11, R-09) | Pilot | API keys from `.env` or Key Vault; Foundry endpoint public | Entra ID roles for both services; Foundry private endpoint; retire keys | Cloud platform owner |
| Model gateway (AC9, AC17) | Several models, teams, or cost centres share the service | Direct, configuration-driven calls to Foundry | API Management AI gateway policies or LiteLLM for routing, quotas, and token accounting | AI platform owner |
| API Management hardening (R-10) | API clients outside the team | Subscription key, 30 calls per minute, 48 KB body limit | JWT validation, WAF, and a decision on routing the web app through the gateway | Cloud platform owner |
| Answer quality (R-04, T-05) | Customer-facing answers | 21 synthetic questions; claim support 71–83% across runs against an 80% target | Larger, human-reviewed set; repeated runs with reported ranges; agreed thresholds | AI and evaluation owner |
| Semantic ranking | Relevance needs to improve beyond hybrid search | Off; not evaluated | Evaluate on the Search tier in use and compare with the baseline | Search owner |
| Prompt-injection and output-link assurance (T-01, T-16) | Public exposure | Focused tests pass | Independent red-team testing | Application security owner |
| Spend and abuse controls (T-08) | Shared or public use | Per-request bounds; API Management rate limit | Per-user budgets, quota and cost alerts | AI platform owner |
| Retention of queries and responses (AC8, T-07) | Review of past sessions is required | Not built; retention off | The decisions in the [privacy impact assessment](../security/privacy-impact-assessment.md), then the store | Privacy owner |
| User notice and data residency | Real users | No notice; GlobalStandard deployments | Notice of provider processing; regional or data-zone deployments where required | Privacy owner |
| Source reuse rights (R-05) | Public or commercial use of indexed content | Public, `robots.txt`-honouring pages for a private demo | Legal review of documentation terms | Product owner |
| Source coverage (R-01) | A broader product-support claim | 10 of 100 products indexed | Reviewed source map additions | Ingestion and data owner |
| Ingestion scale-out (R-06) | More than one worker | One worker at a time under a lease | Shared rate limiter per source host | Platform owner |
| Ingestion lease heartbeat (R-07) | Unattended scheduled runs | Killed runs block the next for up to 6 hours | Renew or release the lease on a heartbeat | Application maintainer |
| Alerts and service objectives (R-15) | Support commitment | Telemetry collected; no alerts, dashboards, or SLOs | Latency, error, cost, and poison-queue alerts; SLOs | Operations owner |
| Backup, restore, and incident response (R-15) | Data that cannot be rebuilt, or a support commitment | The index can be rebuilt from the store; the store can be rebuilt by ingestion | Backup policy, restore test, incident runbook, on-call | Operations owner |
| High availability | Production | Single region; API Management Developer has no SLA | Zone redundancy; API Management Premium (`prd`); store and Search replicas | Cloud platform owner |
| DAST and IAST (AC13) | Production | Not set up | DAST against the deployed web app and API; IAST if an agent is available for the runtime | Application security owner |
| Image assurance (T-13, T-18) | Publishing to production | Non-root images, SHA tags | Image scanning, SBOM, signing, and signature checks at deploy time | Build and release owner |
| Repository protection (T-17) | Before the first real deployment | Workflows assume it; not configured | Branch protection with required checks; required reviewers on the `prd` environment | Build and release owner |
| Infrastructure policy checks | Production | Bicep build, lint, and what-if | PSRule or Checkov; cost estimate per environment | Cloud platform owner |
| Pipeline execution (R-16) | Before relying on CI/CD | Workflows tested offline; never run on GitHub | One full run in `tst`: OIDC, VNet runners, publish, deploy, ingestion, smoke test | Build and release owner |
| Browser end-to-end tests (AC15) | Regular releases | Manual checks and the recorded demo | Automated browser tests in CI | Application maintainer |
| Usability and accessibility (R-14, AC14) | Pilot | Labels, keyboard operation, visible focus, live regions | Moderated usability study; WCAG 2.2 AA audit | Product and accessibility owners |
| Named owners (R-15) | Pilot | Product owner holds every role | Assign the roles in [support ownership](../architecture/support-ownership.md) | Product owner |

## Release boundary

Until the blockers for a stage are closed, keep the demo private: bind local
services to `127.0.0.1`, keep Azure environments to the team, use only the
versioned source map, and leave retention off.

---
title: Product Support Agent Risks and Assumptions
description: Open risks, the responses in place, and the assumptions the demo relies on
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - risk register
  - assumptions
  - product support
estimated_reading_time: 6
---

## How to read this register

Ratings are qualitative. The response column describes what exists today, and
**Next** names the work that would retire or reduce the risk. Security threats
are rated in the [threat register](../security/threat-register.md); this
register covers delivery, data, platform, and operational risks.

## Risks

| ID | Risk | Rating | Response in place | Next |
|---|---|---|---|---|
| R-01 | **Narrow source coverage.** Only 10 of the 100 sampled products have an anonymous documentation source in the source map, and those lean toward the former Micro Focus documentation portals. The catalog pages are client-rendered and carry no documentation text. | Medium | The coverage view lists indexed products first and labels the rest "not covered"; the agent refuses rather than guessing; the limit is stated in the README | Add reviewed sources to the source map as they are identified |
| R-02 | **Protected content.** The OpenText search API returns 401 without credentials, and many product resources require a customer account. | High | 401, 403, sign-in redirects, and sign-in content are skipped, recorded with a reason, and backed off for 30 days; the service never authenticates | None; this is a boundary of the demo |
| R-03 | **Irreproducible sample.** A random product selection could differ between runs and break the coverage view and the evaluation. | Medium | One manifest is generated from a fixed seed (`approved-demo-v1`), versioned in git, hard-capped at 100, and replaced only by an explicit script run | None |
| R-04 | **Answer quality.** The latest evaluation found the expected page in the top five for 12 of 15 answerable questions; model-judged claim support ranged from 71% to 83% over repeated runs, against an 80% target. All 6 refusal cases held. The set is small, synthetic, and not human-reviewed. | High | Server-side citation binding guarantees that every link is real; unsupported text is possible but bounded by retrieval-only prompts | A larger, human-reviewed evaluation set and repeated runs before any customer-facing use |
| R-05 | **Source terms.** Public access does not establish a right to reuse documentation content. The legal page returned 403 to automated access. | High | Anonymous, `robots.txt`-honouring, low-volume access for a private demo only | Legal review before any wider use |
| R-06 | **Source load and stale state.** A repeated, overlapping, or retried run could burden the source sites. | Medium | Request budget, 1-second host spacing, freshness window, backoff, fail-fast, and a single-run lease ([ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md), [ADR-0009](decisions/adr-0009-queue-driven-ingestion.md)) | Distributed rate limiting before running more than one worker |
| R-07 | **Stuck ingestion lease.** If a run is killed, its lease blocks the next run for up to 6 hours. | Low | Documented clear-down in [support ownership](support-ownership.md#runbooks) | A heartbeat that renews or releases the lease |
| R-08 | **Model capacity and region.** GPT-5 GlobalStandard is not offered in every region, quotas can be low, and HTTP 429 from the model surfaces to users as an error. GlobalStandard processing is not tied to one region. | Medium | Region and quota prerequisites are in the [cloud setup guide](../../infra/README.md); the API bounds concurrency and returns a 502 without internal detail when the model call fails | Provisioned or data-zone deployments where capacity or residency matters |
| R-09 | **Keys for Search and Foundry.** Both services are called with API keys held in `.env` or Key Vault, and Foundry's endpoint is public. | Medium | Keys stay out of git and logs; in Azure they live in Key Vault behind a private endpoint; Search is private | Entra ID access with least-privilege roles; key rotation |
| R-10 | **Public API Management gateway.** In external VNet mode, the gateway is reachable from the internet and protected by a subscription key and a rate limit only. The web app does not use it. | Medium | Rate limit, body-size limit, only two operations exposed | Entra ID or JWT validation, WAF, and a decision on whether the web app should route through it |
| R-11 | **Private registry needs a runner in the network.** Images cannot be pushed from a hosted runner or a laptop once the registry is private. | Medium | The pipelines publish and deploy from self-hosted runners labelled `<env>-vnet`; infrastructure deploys in two stages | Document or automate runner provisioning |
| R-12 | **Region limits for the Mongo-compatible store.** Azure DocumentDB Free is not offered in every region, and there is no paid fallback in that mode. | Low | Cosmos DB for MongoDB is the default; the free option is explicit and region-checked in the setup guide | None |
| R-13 | **Cost of retained resources.** API Management Developer, Search Basic, the Premium registry, and Foundry deployments bill while they exist. | Medium | Resource sizes are the smallest that meet the design; cleanup steps are in the setup guide | Budgets and cost alerts |
| R-14 | **Demo does not prove usefulness.** A working demo does not show that target users can finish real support tasks. | Medium | Five user tasks are defined in the [solution architecture](architecture-overview.md#purpose-and-scope); the interface follows basic accessibility practice | Moderated usability study and a WCAG 2.2 AA audit before a pilot |
| R-15 | **No operations cover.** There are no alerts, service level objectives, on-call rotation, or backups. | Medium | Telemetry is collected; runbooks cover the known failure modes | Define SLOs and alerts; assign owners |
| R-16 | **CI never run on GitHub.** The workflows are linted and unit-tested offline but have not executed on GitHub-hosted or self-hosted runners. | Medium | Offline tests check the workflow structure, the placeholder guard, the runner labels, and the parameter preparation | Run the pipelines once in a `tst` environment |

## Assumptions

| ID | Assumption | If it fails |
|---|---|---|
| A-01 | Product and support pages are used only when publicly available without authentication. | Skip the source; never authenticate |
| A-02 | The demo uses a Foundry deployment and an Azure AI Search service supplied by the operator; no local model or vector store is added. | The agent cannot answer; local tests still run with fakes |
| A-03 | The demo catalog is a stable random sample with a hard maximum of 100 products. | Regenerate the manifest deliberately and re-ingest |
| A-04 | The Mongo-compatible store is the system of record and Azure AI Search is a derived index that can be rebuilt from it. | Re-run ingestion to rebuild the index |
| A-05 | Query and response retention is off. | Complete the [privacy impact assessment](../security/privacy-impact-assessment.md) decisions first |
| A-06 | User questions, retrieved text, and model output are untrusted. | Controls in the [security posture](../security/security-posture.md) apply |
| A-07 | Operators deploy to a subscription they own, with permission to create resources and role assignments. | The infrastructure workflow fails at what-if |
| A-08 | Azure region availability, quotas, and prices change; the repository records a sample choice, not a guarantee. | Re-check availability before deploying |

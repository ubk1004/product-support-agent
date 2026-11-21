---
title: Phase 0 Architecture Decision Register
description: Proposed decisions and unresolved approvals for the product support agent MVP
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: reference
keywords:
  - architecture decisions
  - product support
  - MVP
estimated_reading_time: 9
---

## Approval status

The user approved Phase 0 and Phase 0b, then approved Phase 1 with a requirement
for an ADR documenting the technology choices. Phase 1 implementation is
authorized. The demo catalog limit is parameterized with a hard maximum of 100,
and the UI will disclose which products were successfully indexed. Query and
response retention must remain disabled until the privacy and provider-handling
conditions are approved. Cloud resource creation and application deployment
remain unauthorized. Source verification and later phase gates remain
prerequisites for ingestion.

The user approved the Phase 0b [threat register](../security/threat-register.md)
and [privacy impact assessment](../security/privacy-impact-assessment.md) with
conditions. Query/response retention remains disabled until provider handling,
reviewer access, notice, redaction, TTL, and deletion are verified.

## Decisions requiring review

| Topic | Proposed decision | Status |
|---|---|---|
| Product users and tasks | Target support engineers and product support analysts. Cover five tasks: confirm a product is in the demo catalog, find a public resource, answer a product question with a citation, explain when no indexed source exists, and identify an unsupported request. Proposed usability bar: at least four of five representative users complete at least four of these five tasks without moderator help. | Approved for planning; usability evidence remains Phase 5 |
| Anonymous source access | Fetch only explicitly allowlisted OpenText hosts with anonymous GET requests. Never submit credentials or bypass a 401/403. Identify login redirects and login content as protected outcomes. | Approved; source terms and catalog behavior still require verification |
| Catalog fallback | Use the feed only when the listing and search API cannot provide a valid catalog. Distinguish authorization failures, malformed responses, and empty catalogs. | Approved safe default; probe remains inconclusive |
| Source request budget | The user authorized up to 100 additional GET requests for bounded source verification/ingestion; one was used for a bounded feed-prefix check, leaving 99. This is not permission for unrestricted crawling. Before Phase 2, define per-run page, concurrency, timeout, response-size, and retry limits. | Approved cap; ingestion remains gated on source verification and Phase 2 approval |
| 100-product manifest | Use `MAX_DEMO_PRODUCTS`, default 100 and hard maximum 100. Select randomly once per manifest version, persist exact product IDs/names/URLs, and reuse for reruns. Sample from the full catalog; report products with no permitted indexed sources. | Approved for planning |
| Ingestion outcome disclosure | Persist product-level outcomes and expose the names of successfully indexed products to demo users, with the limited-catalog disclosure. Do not imply that products without indexed sources are supported. | Approved for planning |
| Data ownership | MongoDB is the system of record for manifests, run/product outcomes, and canonical documents. Azure AI Search is a derived index of traceable chunks. Queue messages carry product references only. | Approved for planning |
| Search | Use the same user-provided Azure AI Search service locally and in the cloud design. Keep a thin interface and in-memory fake for routine tests. Use hybrid text/vector retrieval and preserve metadata filters and provenance. | Approved for planning; endpoint access remains user-provided |
| Search ranking | Start with Azure AI Search hybrid retrieval. Decide semantic reranking, fields, filters, and acceptance thresholds using a reviewed test set before Phase 3 closes. | Approved direction; details remain for Phase 3 |
| Local component boundaries | Run the Next.js frontend, FastAPI with the agent, ingestion worker, LiteLLM, MongoDB, and Azurite as separate local Podman services. Keep the catalog process as a bounded worker/command using the same ingestion package. | Approved; foundation created, Podman runtime verification pending |
| User-interface and backend languages | Use React/Next.js with TypeScript and Python with FastAPI/Microsoft Agent Framework. Record why these choices fit the project and document their toolchain trade-offs in [ADR-0005](decisions/adr-0005-ui-and-backend-technology.md). | Approved for Phase 1 |
| Model gateway | Route chat and embedding requests through local LiteLLM to the user's Foundry deployments. Keep endpoint/deployment configuration outside source control and verify protocol compatibility before Phase 4. | Approved direction; protocol verification remains Phase 4 |
| Citation handling | Retrieval returns stable evidence IDs and source URLs. The model may refer only to evidence IDs; the server resolves IDs to canonical URLs and renders citations. Never accept model-authored URLs as citations. | Approved for planning |
| User authentication | No end-user authentication in the local MVP. Bind the demo to a local interface and do not expose it as a public service. Cloud authentication remains design-only for Phase 7. | Approved for planning |
| Query and response telemetry | The user requests demo query/response retention. Use `QUERY_RESPONSE_RETENTION_ENABLED=false` by default, a per-session opt-out, `QUERY_RESPONSE_RETENTION_DAYS=7` as a configurable default, and a parameterized reviewer role. Do not retain real content until policy, provider handling, notice, access, redaction, retention, and deletion controls are approved. | Phase 0b design approved; implementation remains gated |
| Chat history | Do not display past searches in the MVP. Keep any UI session state transient and document its behavior. | Approved for planning |
| Evaluation | Version a synthetic/reviewed dataset. Proposed gates: 100% of displayed citations resolve to retrieved evidence; zero unsupported product/resource claims in the reviewed set; relevant evidence appears in the top five results for at least 90% of reviewed questions. Agree on latency and cost targets before Phase 6. | Approved for planning; latency and cost targets remain open |
| Accessibility | Target WCAG 2.2 AA, with automated checks plus manual keyboard and screen-reader review before Phase 5 closes. | Approved for planning |
| Caching | No cache in the MVP. Revisit only if baseline measurements show a need and cache data, TTL, and invalidation are approved. | Approved for planning |
| Azure deployment | Keep the application stack conceptual and statically validated only. Do not deploy APIM, AI Search, Cosmos DB, Container Apps, or application workloads. Review the separately deployable network slice only in Phase 7. | Approved for planning |

## Initial source probe

The initial probe used three GETs. After additional budget approval, one more
GET was used to read a bounded feed prefix. Redirects were not followed, and no
response body was stored.

| Endpoint | Result | Interpretation |
|---|---|---|
| [Product listing](https://my.opentext.com/support/products/) | HTTP 200, `text/html`; 3,105 bytes inspected, with no anchor or script tags in the inspected prefix | A successful HTTP status did not establish that the response contains the product catalog. Server-rendering and page semantics remain unverified. |
| [Search results API](https://my.opentext.com/api/web/support/search-results?start=1&maxResults=5&text=%2A) | HTTP 401, `text/plain` | Treat this API response as protected. Do not retry with credentials or treat it as an empty catalog. |
| [Product feed](https://my.opentext.com/api/web/feed/product) | HTTP 200, `application/json`; an additional bounded read reached 16,385 bytes and was truncated | The complete feed was not downloaded or parsed. The response is larger than the probe limit; pagination, size, and parsing remain unverified. No response body was retained. |

The initial three GETs used the approved probe budget. The user then authorized
up to 100 additional GETs; one was used for a bounded feed-prefix check, leaving
99. This evidence is inconclusive for catalog discovery, pagination, fallback
semantics, and anonymous access to product support pages. Do not start ingestion
until the source contract and per-run limits are verified and Phase 2 is approved.

## Proposed manifest and ingestion contract

* Generate a manifest only from a successfully parsed and deduplicated catalog.
* Store a manifest version, selection method, selected product identifiers,
  display names, canonical product URLs, and selection timestamp.
* Reuse the same manifest for normal reruns. Replacing the sample requires an
  explicit operation and a new version.
* Enqueue one product reference per message. Never place source content or
  credentials in queue messages.
* Use stable source/document/chunk identifiers and content hashes for
  idempotency. Record product-level success, protected skip, retry, and failure
  outcomes without retaining protected content.
* Treat changes to source content, parser version, embedding deployment, and
  embedding dimensions as index-versioning events.
* Define retry, poison-message, deletion, stale-content, and partial-run behavior
  before Phase 2 implementation.

## Phase 0 exit review

The user approved the proposed Phase 0 direction with amendments and authorized
Phase 0b. The source probe remains inconclusive, so ingestion stays blocked
until source terms, catalog parsing, pagination, and per-run limits are verified.
The approved additional GET budget supports bounded verification but does not
authorize unrestricted crawling or bypass later phase gates.

The full phase gate is listed in the
[implementation plan](../implementation-plan.md#phase-0-product-discovery-and-architecture-decisions).

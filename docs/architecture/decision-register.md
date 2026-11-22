---
title: Phase 0 Architecture Decision Register
description: Proposed decisions and unresolved approvals for the product support agent MVP
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: reference
keywords:
  - architecture decisions
  - product support
  - MVP
estimated_reading_time: 9
---

## Approval status

Phases 0, 0b, 1, 2, and 3 are approved. Since 2026-11-22 the project runs in
**demo delivery mode** ([ADR-0007](decisions/adr-0007-demo-delivery-mode.md)).
Phases 4 to 7 proceed without per-phase approval within the guardrails and
pre-authorized actions in that ADR. Controls needed only before production are
recorded, not performed, and are collected in the Phase 9 gap register.

The first live documentation ingestion ran on 2026-11-22: 302 of 400 requests,
300 pages for 10 products, 0 failures (Phase 3 deferral D3-1 closed). The
queue-emulator integration test from Phase 2 remains unrun and is
production-only. Query and response retention stays off. Creating Azure
resources other than `product-support-*` Search indexes, and deploying the
application, still need the user.

The user approved the Phase 0b [threat register](../security/threat-register.md)
and [privacy impact assessment](../security/privacy-impact-assessment.md) with
conditions. Query/response retention remains disabled until provider handling,
reviewer access, notice, redaction, TTL, and deletion are verified.

## Decisions requiring review

| Topic | Proposed decision | Status |
|---|---|---|
| Product users and tasks | Target support engineers and product support analysts. Cover five tasks: confirm a product is in the demo catalog, find a public resource, answer a product question with a citation, explain when no indexed source exists, and identify an unsupported request. Proposed usability bar: at least four of five representative users complete at least four of these five tasks without moderator help. | Approved for planning; usability evidence remains Phase 5 |
| Anonymous source access | Fetch only explicitly allowlisted documentation and knowledge hosts with anonymous GET requests. Never submit credentials or bypass a 401/403. Identify login redirects and login content as protected outcomes. Content comes only from entries in the versioned [source map](../operations/phase-3-source-map-v1.json): docs-portal JSON on `docs.microfocus.com` and sitemaps on `admhelp.microfocus.com`. `my.opentext.com` remains the catalog source only, and `support.opentext.com` is excluded because it is login-gated. | The user approved the linked documentation and knowledge hosts. A [delivery probe](../operations/phase-3-source-delivery-probe-2026-11-22.json) confirmed repeatable anonymous fetch paths for 10 manifest products. Source terms remain unverified, and no content is ingested. See [ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md). |
| Catalog fallback | Use the feed only when the listing and search API cannot provide a valid catalog. Distinguish authorization failures, malformed responses, and empty catalogs. | Feed parsed successfully. Product pages are client-rendered and are used as the catalog only; content comes from the source map (ADR-0006) |
| Source request budget | Ingestion runs use `PRODUCT_SUPPORT_SOURCE_REQUEST_BUDGET`: 400 by default and at most 2,000, counting every attempt including `robots.txt`. Under ADR-0007, runs within the default budget, at most one per day, are pre-authorized. This is not permission for unrestricted crawling or new hosts. | The discovery probe used about 35 GETs. The first ingestion run on 2026-11-22 used 302 GETs. Weekly refreshes cost far less because of conditional requests |
| 100-product manifest | Use `MAX_DEMO_PRODUCTS`, default 100 and hard maximum 100. Select randomly once per manifest version, persist exact product IDs/names/URLs, and reuse for reruns. Sample from the full catalog; report products with no permitted indexed sources. | Manifest approved by the user on 2026-11-21. 10 products have approved documentation sources, and the coverage view reports the rest as having no approved public source |
| Ingestion outcome disclosure | Persist product-level outcomes and expose the names of successfully indexed products to demo users, with the limited-catalog disclosure. Do not imply that products without indexed sources are supported. `GET /catalog/coverage` derives a per-product status (`indexed`, `pending`, `unavailable`, `excluded`, `no_public_source`) from the manifest, source map, and fetch state. The home page shows a summary and a table, indexed products first. If coverage cannot be loaded, it says no product should be assumed covered. | Implemented on 2026-11-22 and tested offline; shows 0 of 100 indexed until the first authorized run |
| Data ownership | MongoDB is the system of record for manifests, run/product outcomes, and canonical documents. Azure AI Search is a derived index of traceable chunks. Queue messages carry product references only. | Approved for planning |
| Search | Use the same user-provided Azure AI Search service locally and in the cloud design. Keep a thin interface and in-memory fake for routine tests. Use hybrid text/vector retrieval and preserve metadata filters and provenance. | A dedicated test-index definition was applied and read back on 2026-11-22. The embedder and `scripts/index_documents.py` are built and unit tested. Indexing the demo corpus and the live Search tests are Phase 4 work packages 1 and 2 (D3-2) |
| Search ranking | Start with Azure AI Search hybrid retrieval. Decide semantic reranking, fields, filters, and acceptance thresholds using a reviewed test set. | Hybrid keyword/vector retrieval, HNSW, cosine similarity, and product ID filters are implemented; no semantic configuration exists yet. A local evaluator checks 90% top-five relevance and 100% citation resolution. The reviewed Azure Search set, the semantic reranking decision, and retrieval quality approval are deferred (D3-3) to the Phase 6 evaluation gate |
| Local component boundaries | Run the Next.js frontend, FastAPI with the agent, ingestion worker, LiteLLM, MongoDB, and Azurite as separate local Podman services. Keep the catalog process as a bounded worker/command using the same ingestion package. Documentation ingestion is a scheduled single-instance job. Next.js calls FastAPI from Server Components, so the browser never calls the API directly. | Approved; foundation created. MongoDB and Azurite Podman runtime verified on 2026-11-21 (see [local development](../operations/local-development.md#podman-verification-record)); application services are containerized in later phases |
| User-interface and backend languages | Use React/Next.js with TypeScript and Python with FastAPI/Microsoft Agent Framework. Record why these choices fit the project and document their toolchain trade-offs in [ADR-0005](decisions/adr-0005-ui-and-backend-technology.md). | Approved for Phase 1 |
| Model gateway | Route chat and embedding requests through local LiteLLM to the user's Foundry deployments. Keep endpoint/deployment configuration outside source control. For the demo, calling Foundry's OpenAI-compatible endpoint directly is acceptable; the client takes a base URL, so LiteLLM is a configuration change. | Foundry chat (`gpt-5`) and embeddings (`text-embedding-3-small`, 1,536 dimensions) verified reachable on 2026-11-22. LiteLLM is optional for the demo (Phase 4, work package 7); APIM is the production gateway |
| Citation handling | Retrieval returns stable evidence IDs and source URLs. The model may refer only to evidence IDs; the server resolves IDs to canonical URLs and renders citations. Never accept model-authored URLs as citations. | Approved for planning |
| User authentication | No end-user authentication in the local MVP. Bind the demo to a local interface and do not expose it as a public service. Cloud authentication remains design-only for Phase 7. | Approved for planning |
| Query and response telemetry | The user requests demo query/response retention. Use `QUERY_RESPONSE_RETENTION_ENABLED=false` by default, a per-session opt-out, `QUERY_RESPONSE_RETENTION_DAYS=7` as a configurable default, and a parameterized reviewer role. Do not retain real content until policy, provider handling, notice, access, redaction, retention, and deletion controls are approved. | Phase 0b design approved; implementation remains gated |
| Chat history | Do not display past searches in the MVP. Keep any UI session state transient and document its behavior. | Approved for planning |
| Evaluation | Version a synthetic/reviewed dataset. Proposed gates: 100% of displayed citations resolve to retrieved evidence; zero unsupported product/resource claims in the reviewed set; relevant evidence appears in the top five results for at least 90% of reviewed questions. Agree on latency and cost targets before Phase 6. | Approved for planning; latency and cost targets remain open |
| Accessibility | Target WCAG 2.2 AA, with automated checks plus manual keyboard and screen-reader review before Phase 5 closes. | Approved for planning |
| Caching | No response cache in the MVP. Revisit only if baseline measurements show a need and cache data, TTL, and invalidation are approved. Durable source fetch state, conditional GETs, and a 24-hour freshness window are ingestion idempotency controls, not a response cache. | Approved for planning; fetch-state design proposed in ADR-0006 |
| Periodic ingestion | Run the source indexer on a schedule, for example weekly. Durable per-URL state skips successes from the last 24 hours and unchanged revisions, uses conditional GETs, backs off failures (30 days permanent; 1–7 days transient), fails a product fast after three consecutive page failures, and abandons a host on rate limiting or an unavailable `robots.txt`. A MongoDB lease prevents overlapping runs. | Approved with Phase 3 on 2026-11-22 ([ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md)). First live run completed on 2026-11-22 with 0 failures. The source-terms legal review is production-only (ADR-0007) |
| Azure deployment | Keep the application stack conceptual and statically validated only. Do not deploy APIM, AI Search, Cosmos DB, Container Apps, or application workloads. Review the separately deployable network slice only in Phase 7. | Approved for planning |

## Source verification

The initial probe used three GETs. After additional budget approval, one more
GET was used to read a bounded feed prefix. Redirects were not followed, and no
response body was stored.

| Endpoint | Result | Interpretation |
|---|---|---|
| [Product listing](https://my.opentext.com/support/products/) | HTTP 200, `text/html`; 3,105 bytes inspected, with no anchor or script tags in the inspected prefix | A successful HTTP status did not establish that the response contains the product catalog. Server-rendering and page semantics remain unverified. |
| [Search results API](https://my.opentext.com/api/web/support/search-results?start=1&maxResults=5&text=%2A) | HTTP 401, `text/plain` | Treat this API response as protected. Do not retry with credentials or treat it as an empty catalog. |
| [Product feed](https://my.opentext.com/api/web/feed/product) | HTTP 200, `application/json`; an additional bounded read reached 16,385 bytes and was truncated | The complete feed was not downloaded or parsed. The response is larger than the probe limit; pagination, size, and parsing remain unverified. No response body was retained. |

The initial probe used three GETs. Of the original 100 additional GETs, one was
previously used for a bounded feed-prefix read. The live verification used two
feed GETs and 97 product-page GETs, exhausting that original additional budget.
The user separately authorized one full-feed GET, which was also used in this
verification. This accounts for 100 GETs under the original additional cap plus
one separately authorized full-feed GET; the cumulative count including the
initial three probes is 104.

The full feed parsed into 1,302 unique products and produced the
[100-product manifest](../operations/phase-2-product-manifest-v1.json). Of the
97 product pages checked, all returned HTTP 200 but the login-content heuristic
classified them as protected. Three manifest products were not checked. Since
response bodies were not retained, those classifications are inconclusive. The
[outcome report](../operations/phase-2-ingestion-outcome-v1.md) records the
details. No page content was stored, and the live check did not enqueue products
or persist ingestion run records. The user approved Phase 2 on 2026-11-21.

On 2026-11-22, a separately authorized check issued 100 anonymous GETs, one to
each manifest product page. All returned HTTP 200 and were classified by the
login-content heuristic as protected. No bodies were retained, so these
classifications remain inconclusive. The [metadata-only report](../operations/phase-3-source-check-2026-11-22.json)
records each outcome.

The user then authorized further anonymous checks until ten products with
usable content are found. In 172 GETs across two bounded batches, the follow-up
review checked all 100 manifest product pages and inspected the public feed and
client assets. Product detail is client-rendered; the raw HTML did not establish
product-specific content, and request-capped browser checks were inconclusive.
The feed contains nonempty descriptions for four manifest products, without a
review of their suitability. Most documentation links use hosts outside the
current allowlist; none of those hosts was contacted. The
[follow-up report](../operations/phase-3-anonymous-source-review-2026-11-22.json)
contains request metadata and no response bodies.

On 2026-11-22, the [delivery probe](../operations/phase-3-source-delivery-probe-2026-11-22.json)
used about 35 anonymous GETs to establish how the observed documentation is
delivered. The `docs.microfocus.com` portal serves its table of contents and
page bodies as anonymous JSON. The `admhelp.microfocus.com` help sites serve
server-rendered HTML and publish per-product sitemaps. The `robots.txt` files on
both hosts allow the selected paths. One end-to-end page fetch returned real
text. Fortify SAST returned HTTP 403 and was excluded. Bodies were inspected
only to identify the formats and were not retained.

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
Phase 0b. The live feed is parsed and a manifest is available. The product
pages turned out to be client-rendered and are now the catalog only (see
[ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md)). The
user approved Phase 2 on 2026-11-21 and Phase 3 on 2026-11-22. No further
source request is authorized without explicit approval. The original
additional GET budget is exhausted; source approval does not bypass later phase
gates.

The full phase gate is listed in the
[implementation plan](../implementation-plan.md#phase-0-product-discovery-and-architecture-decisions).

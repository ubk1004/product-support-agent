---
title: Phase 2 Live Source Outcome Report
description: Live OpenText feed and product-page outcome summary for the Phase 2 manifest
author: Udaybhanu Karmakar
ms.date: 2026-11-21
ms.topic: reference
keywords:
  - ingestion
  - OpenText
  - manifest
---

## Summary

This report records live anonymous GET results for the OpenText product feed and the selected product URLs. It contains status metadata only; response bodies were not persisted. The product-page checks used the actual manifest and no mock or stub source data. The source check called the worker's bounded fetch method directly; it did not enqueue messages or persist ingestion run records.

| Item | Result |
|---|---|
| Manifest | [Phase 2 product manifest](./phase-2-product-manifest-v1.json), version `opentext-2026-11-21-v1` |
| Phase 2 review | Approved by the user on 2026-11-21 after manifest review |
| Product catalog | 1,302 unique parseable products from HTTP 200 |
| Manifest size | 100 products |
| Product pages attempted | 97 of 100 |
| Feed GETs in this verification | 3: two within the original cap and one separately authorized |
| Product-page GETs used | 97 |
| Original 100-additional-GET cap | Exhausted: one earlier feed-prefix GET, two current feed GETs, and 97 product-page GETs |
| Separately authorized full-feed GET | 1, used |
| Cumulative GETs including the initial three probes | 104 |
| Stop reason | request_budget_exhausted |
| Login-content classification | Heuristic; not independently confirmed |
| Search indexing | Not performed; indexing belongs to Phase 3 |

### Product-page outcomes

| Outcome | Count |
|---|---:|
| skipped: HTTP 200 with login-content indicator | 97 |
| not_attempted: request budget exhausted | 3 |

### Safety and limitations

* Requests were sequential, used the `my.opentext.com` HTTPS allowlist, did not follow redirects, and were limited to one attempt per product. The run stops on rate limiting, a server error, or a network error.
* The earlier 100-additional-GET approval was exhausted. One additional full-feed request was explicitly authorized; no further source requests were made.
* The response-size limit was 4 MiB. Response bodies were inspected only in memory to classify protected login content; no page content or embeddings were stored.
* All 97 attempted pages returned HTTP 200 and were skipped because the existing heuristic found login-related text. The response bodies were discarded, so this report cannot distinguish a full login page from generic login text in page navigation.
* The live run did not update Azure AI Search. A successful download is not evidence that content was parsed, normalized, indexed, or retrievable.
* The planned queue-emulator integration test remains unrun; Phase 2 approval does not represent that test as passed.
* Products with `not_attempted` outcomes remain unverified. Their records and all HTTP status details are in the [machine-readable outcome report](./phase-2-ingestion-outcome-v1.json).

The feed payload SHA-256 is `8f0ce0794784c2315089e8692d17cf49c1ed5bc15a854e5e81da6d51c75ce526`. The decoded response was 3346806 bytes, within the configured 4 MiB limit.

## Follow-up source check

On 2026-11-22, the user authorized 100 additional anonymous product-page GETs.
The check attempted all 100 manifest pages, starting with the three not attempted
in the earlier run. Every response returned HTTP 200 and was classified as
protected by the login-content heuristic. Response bodies were not retained, so
generic navigation text cannot be ruled out. No queue messages were sent and no
source content was indexed. See the [metadata-only follow-up report](./phase-3-source-check-2026-11-22.json)
for individual outcomes. This was a separate request budget; further source GETs
require explicit approval.

The later [anonymous source review](./phase-3-anonymous-source-review-2026-11-22.json)
found that these product pages are client-rendered. The previous login-content
heuristic cannot distinguish a sign-in link in navigation from a protected
page; its earlier classifications do not prove that the product pages require
authentication. The follow-up did not establish ten usable product sources.

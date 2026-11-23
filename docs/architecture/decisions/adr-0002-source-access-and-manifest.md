---
title: ADR-0002 Source Access and Product Manifest
description: Proposed anonymous source access and stable demo-catalog policy
author: Udaybhanu Karmakar
ms.date: 2026-11-21
ms.topic: decision
keywords:
  - ADR
  - ingestion
  - product manifest
---

## Status

Phase 0 direction approved. The user approved Phase 2 on 2026-11-21 after
reviewing the [manifest](../../operations/phase-2-product-manifest-v1.json).
The live source outcomes remain inconclusive and are recorded in the
[outcome report](../../operations/phase-2-ingestion-outcome-v1.md). The planned
queue-emulator integration test remains unrun. A later
[linked-source review](../../operations/phase-3-linked-source-verification-2026-11-22.json)
observed product-specific public documentation for 10 manifest products;
none has been indexed. The repeatable fetch paths, source map, and periodic
ingestion behavior for those products are proposed in
[ADR-0006](adr-0006-periodic-resumable-source-ingestion.md).

## Context

The demo is limited to 100 products and must not bypass customer authorization
or create undue load on OpenText. Initial probes found an HTML listing response,
a 401 search API response, and an unparsed JSON feed response. The later
approved feed request returned 1,302 unique parseable products. A deterministic
100-product manifest was created. Of the 97 product pages checked within the remaining original request budget,
all returned HTTP 200 but were classified as protected by the login-content
heuristic; three manifest products were not checked. One separately authorized
full-feed GET was also used. Since page bodies were not retained, the
classifications are not independently confirmed.

## Proposed decision

* Request only explicitly allowlisted public URLs with anonymous GETs.
  The approved linked-source hosts are `my.opentext.com`,
  `support.opentext.com`, `docs.microfocus.com`, `www.microfocus.com`,
  `admhelp.microfocus.com`, `liaisontechnologies.service-now.com`, and
  `answers.webroot.com`. Catalog discovery remains limited to
  `my.opentext.com`.
* Treat HTTP 401/403, login redirects, and login content as protected outcomes.
  Never retry them with credentials or follow a redirect to an authentication
  page. Login content means a password field, a login form, a SAML request, or
  a short page that is mostly a sign-in prompt. Documentation that merely
  mentions logging in is not login content.
* Fetch content only from entries in the versioned source map, and honor each
  host's `robots.txt`.
* Use the feed only when the listing and search API cannot yield a valid
  catalog. Do not confuse an authorization failure, parse failure, or empty
  result.
* Generate a reproducible manifest of 100 products once per version and reuse
  it for normal reruns. Replacing the selection requires an explicit action.
* Use `MAX_DEMO_PRODUCTS`, default 100 and hard maximum 100. Preserve the
  selected product IDs, names, and URLs, and display which products were
  successfully indexed.
* Proposed default: sample from the full catalog without filtering for public
  resource availability. Show products with no permitted sources as uncovered,
  not as supported by invented content.
* Keep request, page, concurrency, timeout, and response-size budgets bounded.
  Honor `Retry-After`; stop on unexpected source behavior.

## Alternatives considered

* Resample randomly on every run: rejected because the demo and evaluation set
  would not be reproducible.
* Filter out products without public resources: not selected as the proposed
  default because it can bias the sample and increase discovery traffic. This
  remains an open user decision.
* Authenticate to access protected pages: rejected; outside MVP scope.

## Consequences

The live source check stayed within the original 100-additional-GET cap plus
one separately authorized full-feed GET and did not persist response bodies.
Its report is source verification, not proof of successful parsing or indexing.
A 100-product manifest does not imply that all products have indexed public
resources. The user approved Phase 2 despite the inconclusive login-content
classifications and three unattempted products. The queue-emulator integration
test remains an unrun verification item. The user subsequently approved linked
documentation and knowledge requests in bounded batches. Public access does
not establish reuse rights; source terms remain to be verified before content
is ingested.

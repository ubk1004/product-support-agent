---
title: ADR-0002 Source Access and Product Manifest
description: Proposed anonymous source access and stable demo-catalog policy
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: decision
keywords:
  - ADR
  - ingestion
  - product manifest
---

## Status

Phase 0 direction approved with a safe ingestion gate; the source probe remains
inconclusive.

## Context

The demo is limited to 100 products and must not bypass customer authorization or
create undue load on OpenText. The initial bounded probe found an HTML listing
response, a 401 search API response, and an unparsed JSON feed response.

## Proposed decision

* Request only explicitly allowlisted public URLs with anonymous GETs.
* Treat HTTP 401/403, login redirects, and login content as protected outcomes.
  Never retry them with credentials or follow a redirect to an authentication
  page.
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

The initial source behavior must be resolved before Phase 2. The user authorized
up to 100 additional GET requests for bounded source verification/ingestion;
that cap does not permit unrestricted crawling. A 100-product manifest does
not imply that all products have indexed public resources. Accepted source
terms, host allowlist, and per-run budgets must be recorded before ingestion.

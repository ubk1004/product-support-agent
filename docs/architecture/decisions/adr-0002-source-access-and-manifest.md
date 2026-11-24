---
title: ADR-0002 Source Access and Product Manifest
description: Anonymous source access rules, catalog discovery, and the reproducible 100-product manifest
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - source access
  - manifest
---

## Status

Accepted.

## Context

The brief names three catalog sources: the OpenText product listing page, the
support search API, and, if neither works, the product feed. It requires
anonymous access only, skipping anything behind customer authorization, and a
random sample of 100 products so the demo puts little load on OpenText's
sites.

Checked against live responses:

| Source | Anonymous result |
|---|---|
| `my.opentext.com/support/products/` | HTTP 200, but client-rendered with no usable product data |
| `my.opentext.com/api/web/support/search-results` | HTTP 401 |
| `my.opentext.com/api/web/feed/product` | HTTP 200 with 1,302 parseable products |
| `my.opentext.com/support/products/{slug}` | Client-rendered; no product text |

## Decision

* **Catalog discovery.** Try the listing, then the search API, then the feed.
  A source that answers 401 or 403, redirects to a sign-in page, or returns
  sign-in content is recorded as protected and skipped; it is never retried
  with credentials. The feed is therefore the catalog in practice.
* **Sign-in content** means a password field, a sign-in form, a SAML request,
  or a short page that is mostly a sign-in prompt. A page that only mentions
  signing in is not sign-in content.
* **Host allowlist.** Requests go only to allowlisted hosts. Catalog discovery
  uses `my.opentext.com` only. Documentation comes only from the versioned
  [source map](../../operations/phase-3-source-map-v1.json)
  ([ADR-0006](adr-0006-periodic-resumable-source-ingestion.md)).
* **Manifest.** `scripts/create_manifest.py` selects up to 100 products
  (`PRODUCT_SUPPORT_MAX_DEMO_PRODUCTS`, hard maximum 100) with a deterministic
  hash of the manifest version, seed, and product ID. The manifest stores each
  product's ID, name, slug, and support-page URL and is reused for every run.
  Replacing it needs a new version and an explicit `--replace`.
* **Sampling.** Sample from the whole catalog without filtering for available
  documentation. Products without an approved source are shown as not covered,
  never answered from invented content.
* **Bounds.** Every request has a timeout, a response-size limit, and a
  budget; `Retry-After` is honoured.

## Rationale

The ordered discovery follows the brief, and treating a protected response as
"skip and record" keeps the demo within anonymous access. A deterministic
manifest makes the demo and its evaluation reproducible.

## Alternatives considered

* Resample on every run: rejected, because demos and evaluations would not be
  repeatable.
* Sample only products with known public documentation: rejected, because it
  biases the sample and needs extra discovery traffic.
* Authenticate to reach protected content: rejected; outside the brief.

## Consequences

* The approved manifest (`opentext-2026-11-21-v1`) has 100 products. Ten of
  them have an approved anonymous documentation source; the other 90 are shown
  as "no approved public source". That means no source was verified for them,
  not that none exists.
* Public access does not establish reuse rights. Reviewing the source terms is
  a production gate.

---
title: ADR-0006 Periodic, Resumable Documentation Ingestion
description: Source map, fail-fast behavior, and durable fetch state for a scheduled documentation indexer
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: decision
keywords:
  - ADR
  - ingestion
  - freshness
  - idempotency
---

## Status

Accepted for the demo on 2026-11-22 and amended on 2026-11-23. The code and the
[source map](../../operations/phase-3-source-map-v1.json) are implemented and
tested offline. A live run stored 300 pages for 10 products with 0 failures.
Source terms remain unverified (production-only, see
[ADR-0007](adr-0007-demo-delivery-mode.md)).

Amendment, 2026-11-23: the runner now embeds and indexes each page into Azure AI
Search during the run, and deletes removed pages from Search as well as MongoDB.
The earlier "embeddings are deferred" behavior is available as
`--repository-only`.

## Context

Earlier source checks used the `my.opentext.com` product pages as the content
source. Those pages are client-rendered, so they never yielded product text and
repeatedly classified as protected. The
[delivery probe](../../operations/phase-3-source-delivery-probe-2026-11-22.json)
found two anonymous, documented delivery paths: JSON files behind the
`docs.microfocus.com` single-page app, and per-product sitemaps on
`admhelp.microfocus.com`.

The indexer must run on a schedule, such as weekly. It must not spend requests on
content that is unavailable, and a crash or lost status write must not cause
successful URLs to be fetched again within a day.

## Decision

* **Explicit source map.** A versioned JSON source map lists each product's seed
  URL (a docs-portal `tocflat.json` file or an XML `urlset` sitemap), path
  filters, a TOC depth limit, and a per-product page cap of at most 200 (30 in v1).
  The worker never follows links or sitemap indexes. A product without an entry
  stays uncovered.
* **Separate fetch and citation URLs.** The docs-portal JSON is fetched, while
  the `/doc/...` page URL is stored and cited. Document IDs derive from the
  citation URL. Both URLs must pass the host allowlist and `robots.txt`.
* **Durable per-URL fetch state** lives in the MongoDB collection
  `source_fetch_state`. It is written after every request, keyed by product and
  citation URL, and records the outcome, timestamps, ETag, Last-Modified, body
  hash, TOC revision, document ID, and the next eligible time.
* **Freshness rules:**
  * A URL that succeeded within 24 hours is skipped without a request.
  * If the TOC revision is unchanged since the last good fetch, no request is
    made.
  * Otherwise the worker sends a conditional GET with `If-None-Match` and
    `If-Modified-Since`.
  * An identical body is not re-normalized or re-embedded. The indexing service
    also skips embedding when the canonical content hash is unchanged.
* **Second guard against lost state.** If the state record is missing but the
  canonical document's `fetched_at` is within the freshness window, the page is
  skipped and the state record is rebuilt. Search index updates happen before
  the canonical document write, so an interrupted indexing step is retried
  rather than skipped.
* **Fail-fast rules:**
  * Permanent failures (401, 403, login redirects or content, other 3xx/4xx,
    `robots.txt` disallow, oversized responses, normalization failures) back
    off for 30 days.
  * Transient failures (5xx, network errors, rate limiting, indexing errors)
    back off 1, 2, then 4 days, capped at 7.
  * Three consecutive page failures stop the product for this run and back the
    product off as a unit. The product backoff is 30 days if all three failures
    were permanent, otherwise the transient schedule.
  * A seed failure backs off the product.
  * A 429 response, a `Retry-After` longer than 60 seconds, or an unreachable
    `robots.txt` abandons that host for the run. Other hosts continue.
* **Bounded politeness:**
  * A per-run request budget, 400 by default, counts every attempt including
    `robots.txt`.
  * At least 1 second between requests to a host.
  * At most 2 attempts per page.
  * An identifying User-Agent.
  * `robots.txt` is fetched once per host per run. Only a 404 or 410 means
    "allow all"; any other non-2xx response, including 401 and 403, fails closed.
* **Single-runner lease.** The runner script takes a 6-hour MongoDB lease, so
  overlapping scheduled runs exit instead of doubling the request load.
* **Selection changes are reconciled.** After a complete product pass, pages
  that dropped out of the selection have their canonical documents deleted.
* **Search stays in step with MongoDB.** By default the runner uses
  `DocumentIndexingService`: it writes chunks and vectors to the versioned
  Search index before it commits the canonical document, and it deletes both
  when a page leaves the selection. `--repository-only` (and `--discover-only`)
  use `RepositoryOnlyIndexer` and skip embeddings and Search.
  `scripts/index_documents.py` remains available to rebuild the index from
  MongoDB, for example after an embedding model change.
* **Coverage is derived from fetch state.** `GET /catalog/coverage` combines the
  manifest, the source map, and fetch state into a per-product status. The UI
  lists indexed products first and labels every other product as not covered.
  If MongoDB cannot be read, products are reported as pending, never as
  indexed.

## Consequences

* A weekly run against an unchanged corpus costs about one TOC or sitemap
  request per product, plus `robots.txt` and conditional page requests.
  A rerun within 24 hours costs no requests.
* Fresh-state skips do not reset the consecutive-failure counter, so a product
  that is failing still fails fast after a resume.
* A changed source map entry changes its configuration hash, which forces
  rediscovery.
* Running with `--force` ignores freshness and backoff. Use it only after an
  explicit reset decision.
* The source map is a curated, biased subset of the random manifest. The home
  page discloses which products are covered.

## Alternatives considered

* Use the run log to decide what to skip. Rejected: it is written at the end of
  a run and is lost when the worker crashes.
* Crawl from the product pages. Rejected: they are client-rendered and lead to
  login-gated hosts.
* Follow sitemap indexes or in-page links. Rejected: it would create an
  unbounded crawl and make page selection non-reproducible.

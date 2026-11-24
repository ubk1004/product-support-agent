---
title: ADR-0004 Data Ownership and Privacy
description: System of record, derived data, and what is never stored
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - data ownership
  - privacy
---

## Status

Accepted.

## Context

The system holds catalog data, source content, ingestion state, a search index,
queue messages, and telemetry. The brief also asks to retain every user query
and response for later review, which requires a purpose, notice, access
control, retention period, and deletion process before it can be built.

## Decision

* **System of record.** The Mongo-compatible store owns canonical documents and
  chunks, per-URL fetch state, the ingestion lease, ingestion runs, and
  per-product outcomes.
* **Configuration.** The manifest and source map are versioned, reviewed JSON
  files in `docs/operations/`.
* **Derived data.** The Azure AI Search index holds chunks, vectors, and
  provenance, and can be rebuilt from the store at any time.
* **Queue messages** carry only a run ID and a product reference.
* **Coverage** is exposed as product-level metadata only: status, counts, and
  timestamps, never page content or page URLs.
* **User content.** Questions and answers are sent to Foundry and Azure AI
  Search to produce an answer and are not stored. The conversation lives only
  in the browser tab, and the interface never shows past sessions.
* **Retention** of questions and answers is not built. A disabled setting
  (`PRODUCT_SUPPORT_QUERY_RESPONSE_RETENTION_ENABLED`) exists and cannot be
  enabled without a reviewer role.
* **Telemetry** carries status, timing, identifiers, counts, and error
  categories only. Secrets and personal identifiers are redacted before output.

## Rationale

Keeping one system of record makes the index disposable and re-creatable, and
keeping user content out of storage avoids privacy obligations that the demo
cannot meet yet.

## Alternatives considered

* Retain all questions and answers by default: not selected; the privacy
  controls it needs are not in place.
* Use the search index as the source of truth: rejected; it cannot own run
  state and is rebuilt on model changes.

## Consequences

* Past sessions cannot be reviewed, so the brief's requirement to retain them
  is open. The prerequisites are in the
  [privacy impact assessment](../../security/privacy-impact-assessment.md).
* Retention periods for stored source content and run records are not yet
  defined.

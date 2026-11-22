---
title: ADR-0004 Data Ownership and Privacy
description: Proposed data ownership and telemetry minimization policy for the MVP
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: decision
keywords:
  - ADR
  - privacy
  - data ownership
---

## Status

Phase 0 data-ownership direction approved. The retention policy remains subject
to Phase 0b approval before collecting real user query content.

## Context

The requested design includes MongoDB/Cosmos DB Mongo API, a queue, Azure AI
Search, operational logs, and OpenTelemetry. The original requirements also ask
to retain user queries and responses, but no purpose, notice, access, retention,
or deletion policy is approved.

## Proposed decision

* Use MongoDB as the proposed system of record for ingestion run status,
  product outcomes, canonical documents and chunks, per-URL source fetch state
  (`source_fetch_state`), and the ingestion run lease (`ingestion_leases`).
* Keep the approved manifest and the documentation source map as versioned,
  reviewed JSON files in `docs/operations/`. They are configuration and review
  artifacts, not runtime state.
* Expose coverage to the UI as product-level metadata only: status, counts, and
  timestamps. Do not include page URLs or page content.
* Treat Azure AI Search as a derived index containing searchable chunks and
  provenance, not as the operational system of record.
* Keep queue messages limited to product references and run identifiers.
* Do not retain user queries or responses in logs, traces, or stored telemetry
  until privacy approval. The requested demo feature will have a global kill
  switch defaulting off and a per-session opt-out. Keep the UI's search history
  disabled.
* Minimize operational telemetry to status, timing, component, correlation/run
  ID, and error category. Redact secrets and sensitive test values.

## Alternatives considered

* Retain all query and response content by default: not selected because the
  required privacy controls and approval are not in place.
* Use Azure AI Search as the source of truth for ingestion state: rejected
  because it is a retrieval index and does not own run lifecycle state.

## Consequences

The user requests query/response retention for demo review, but retention is not
enabled until the privacy impact assessment is approved. The assessment must
specify the notice, access list, redaction behavior, retention period, and
deletion process. Source freshness is defined by ADR-0006: a 24-hour freshness window,
conditional refresh, and deletion of pages that leave the source selection.
Retention periods for canonical source content after a product is removed,
run records, and operational telemetry remain open decisions.

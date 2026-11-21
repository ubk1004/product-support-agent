---
title: ADR-0004 Data Ownership and Privacy
description: Proposed data ownership and telemetry minimization policy for the MVP
author: Product Support Agent Team
ms.date: 2026-11-21
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

* Use MongoDB as the proposed system of record for the local manifest, ingestion
  run status, product outcomes, and canonical documents.
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
deletion process. Retention and deletion periods for canonical source content,
run records, and operational telemetry remain open decisions.

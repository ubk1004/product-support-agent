---
title: Product Support Agent Requirements Traceability
description: Maps the numbered requirements in Instructions.md to planned components, phases, and verification
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: reference
keywords:
  - requirements
  - traceability
  - testing
estimated_reading_time: 7
---

## Status

The Phase 0 direction is approved. Phase ownership and verification below are
planning assignments, not evidence that a requirement has been implemented.
Source numbering refers to [Instructions.md](../../Instructions.md).

## Traceability matrix

| # | Requirement summary | Planned component or artifact | Phase | Verification evidence |
|---:|---|---|---:|---|
| 1 | Discover public products/resources; parameterized hard cap of 100; disclose products successfully indexed | Catalog, manifest, source map, source ingestion worker, `GET /catalog/coverage`, Next.js coverage view | 0, 2, 3, 5 | Stubbed catalog/worker tests; approved manifest; `test_phase_three_coverage.py`; the coverage view renders the summary, table, and unavailable states; a bounded live run is pending authorization |
| 2 | Handle empty catalogs, 429, and exponential backoff | Catalog, ingestion workers, fetch state | 2, 3 | Unit tests for empty results, `Retry-After`, retry caps, backoff, host abort on 429, product fail-fast, and resume after restart without refetching |
| 3 | Normalize canonical documents for idempotent and delta updates | Canonical document schema, indexer, fetch state | 3 | Schema, hash, update, and deletion tests; tests for unchanged revisions and bodies, conditional GETs, and removed pages |
| 4 | Support keyword, metadata, and semantic search | Azure AI Search retrieval adapter | 3 | Dedicated index integration and reviewed relevance set |
| 5 | Preserve source URLs in results | Canonical provenance and retrieval response | 3, 4 | Source ID/URL preservation and citation-binding tests |
| 6 | Use structured tool calling and RAG | Agent Framework agent and retrieval tool | 4 | Tool schema, fake gateway, grounded answer end-to-end tests |
| 7 | Ground output; defend against injection; redact sensitive telemetry | Agent, response validation, telemetry | 0b, 4, 6 | Abuse tests, citation checks, synthetic secret/PII redaction tests |
| 8 | Hide prior searches in UI; retain demo queries/responses only after privacy approval, with a selective off control | Next.js and privacy-controlled telemetry store | 0, 0b, 5, 6 | UI no-history tests; retention flag defaults off; notice, access, redaction, TTL, and deletion verified before enabling |
| 9 | Put chat and embedding models behind a replaceable gateway | LiteLLM and gateway contract | 0, 4, 6 | Fake gateway contract tests; approved Foundry deployment configuration |
| 10 | Bind every claim to retrieved source ID/URL; prohibit invented links | Retrieval response and server-side citation renderer | 3, 4 | Citation provenance and unsupported-claim end-to-end tests |
| 11 | OpenTelemetry tracing, logging, and metrics | Instrumented services and approved collector | 6 | Trace inspection plus no-sensitive-content checks |
| 12 | Offline evaluation dataset | Versioned evaluation fixtures | 2, 6 | Deterministic evaluation run against agreed thresholds |
| 13 | Gateway, identity, CI, deployment, SAST/DAST/IAST | Phase 7 design and separately gated deployment work | 0, 7, 8 | CI security checks; infrastructure validation; deployment checks only after approval |
| 14 | Production path includes usefulness and accessibility validation | Usability plan, accessibility checks, production gap register | 0, 5, 9 | Moderated task evidence, manual accessibility review, approved gap register |
| 15 | End-to-end testability and phase-specific tests | Unit, integration, end-to-end, and evaluation suites | 0-7 | Applicable phase gates and deterministic routine tests |
| 16 | Readable repository, ADRs, architecture documents, Mermaid diagrams | `docs/architecture/` and approved project layout | 0, 1 | Link/diagram review and clean-checkout documentation checks |
| 17 | Python, FastAPI, React/Next.js, Agent Framework, Mongo-compatible data, Azure AI Search, LiteLLM, Podman | Application and local service architecture | 0, 1-6 | Dependency/config checks and integrated local run |
| 18 | Bicep, network isolation, monitoring, and secure Azure service layout | `infra/bicep/` conceptual design | 7 | L0-L3 static validation; network-slice validation only after approval |
| 19 | Build UI, API, and agent code | GitHub Actions validation/build workflow | 1, 7 | CI build and quality checks without Azure |
| 20 | Deploy UI, API, and agent code | Guarded application deployment workflow | 7, 8 | Workflow remains disabled until a separate deployment approval |
| 21 | Host backend on Azure Container Apps | Cloud architecture and Bicep | 7, 8 | Static design checks; cloud runtime validation deferred |
| 22 | Use GitHub Actions for build and deployment | GitHub Actions workflows | 1, 7, 8 | Action linting, SHA pinning, permission review, protected-environment checks |

## Traceability constraints

* Item 8 requests query and response retention for the demo. The retention
  feature must remain disabled until the Phase 0b privacy policy and its
  controls are approved; the operator must be able to disable retention
  globally and per session.
* Items 13, 18, 20, and 21 do not authorize deployment. The MVP's application
  stack remains local; the cloud design is validated statically.
* Item 17's Mongo-compatible local metadata store is the proposed choice.
  Azure AI Search is used for search locally and in the cloud design, as stated
  in the [implementation plan](../implementation-plan.md).

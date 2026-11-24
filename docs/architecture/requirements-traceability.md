---
title: Product Support Agent Requirements Traceability
description: Maps every requirement in the original brief to the component that implements it, how it is verified, and its status
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - requirements
  - traceability
  - testing
estimated_reading_time: 8
---

## Purpose

[Instructions.md](../../Instructions.md) is the original brief. This page
shows, for each numbered item, where it is implemented, how to check it, and
where the result differs from the brief. Items are labelled **G1–G4** for the
Goal section and **AC1–AC22** for the Architecture Considerations.

Status values: **Done**, **Done with a difference** (explained in the last
column), **Partly done**, and **Not done**.

## Goal

| # | Requirement | Where it is met | Status |
|---|---|---|---|
| G1 | Build an agent that answers questions about OpenText products and their resources from the product list, search API, or feed, using anonymous access only | [Solution architecture](architecture-overview.md), [ADR-0002](decisions/adr-0002-source-access-and-manifest.md); `src/product_support_agent/catalog.py`, `chat.py` | Done with a difference: the product-page URLs hold no documentation text, so content comes from an explicit source map of public documentation sites, covering 10 of the 100 sampled products |
| G2 | Future expansion to OpenText Service Management | [Service management expansion](service-management-expansion.md) | Done: staged design only; nothing is built |
| G3 | Concise architecture: components, identity and access, data flow, model interaction, trust boundaries, deployment, monitoring, support ownership | [Solution architecture](architecture-overview.md), [support ownership](support-ownership.md) | Done |
| G4 | Decisions, security and privacy, assumptions, risks, trade-offs, production gaps, and a phased path to production | [Decision register](decision-register.md), [ADRs](decisions/), [security posture](../security/security-posture.md), [privacy impact assessment](../security/privacy-impact-assessment.md), [risks and assumptions](risk-assumptions.md), [trade-offs and phased path](architecture-overview.md#trade-offs), [production gap register](../operations/production-gap-register.md) | Done |

## Architecture considerations

| # | Requirement | Implemented by | How to verify | Status |
|---|---|---|---|---|
| AC1 | Decoupled ingestion, retrieval, and orchestration; controlled pagination; skip protected content and record why; queue with one product per message; one worker taking one message; embed and store; record success or failure; 100 random products surfaced in the chat | `scripts/create_manifest.py`, `src/product_support_agent/catalog.py`, `queue_ingestion.py`, `source_ingestion.py`, `GET /catalog/coverage`; [ADR-0002](decisions/adr-0002-source-access-and-manifest.md), [ADR-0009](decisions/adr-0009-queue-driven-ingestion.md) | `tests/unit/test_phase_two_*.py`, `test_queue_ingestion.py`, `test_phase_three_coverage.py`; the run status endpoint | Done with a difference: all 100 products are queued and recorded, but only 10 have an anonymous documentation source; the other 90 are recorded as skipped and shown as not covered |
| AC2 | Stop on an empty product list; on HTTP 429 read the retry time and back off exponentially | `catalog.py`, `http_fetch.py`, `fetch_state.py` | Unit tests for empty results, `Retry-After`, retry caps, backoff, and host abort | Done |
| AC3 | Canonical document schema; idempotent and delta updates | `documents.py`, `document_store.py`, `indexing.py`, `fetch_state.py` | Schema, hash, update, deletion, conditional-request, and unchanged-page tests | Done |
| AC4 | Hybrid search over keywords, metadata, and meaning | Azure AI Search index (text and vector fields, product filter); `search.py`, `scripts/apply_search_index.py` | `test_phase_three_documents_search.py`, `test_phase_three_retrieval_evaluation.py`; evaluation | Done: semantic ranking is off by choice ([ADR-0001](decisions/adr-0001-search-and-model-gateway.md)) |
| AC5 | Keep source URLs and show them with answers | Canonical documents carry the URL; citations are resolved to it on the server | Citation-binding tests | Done |
| AC6 | LLM with structured tool calling and RAG | Microsoft Agent Framework agent with `search_documentation` and `list_products` (`chat.py`) | `tests/unit/test_chat.py` with a fake model | Done |
| AC7 | Strict grounding, prompt-injection defence, and redaction of PII, SPI, and secrets from logs | Citation binding, history sanitising, content-filter refusal, redacting log filter | `test_chat.py`, `test_logging.py`, `test_telemetry.py`; evaluation refusal cases | Done with a limit: redaction is pattern-based and claim support is screened by a model, not guaranteed |
| AC8 | Do not show past searches to the end user; retain all logs, traces, queries, and responses for later review | The browser keeps only the current tab's conversation. No past session is shown | Manual check of the interface | Partly done: past searches are hidden. Retention of queries and responses is **not built** and is blocked on the decisions in the [privacy impact assessment](../security/privacy-impact-assessment.md). Logs and traces are kept without question or answer text |
| AC9 | Embedding and chat models behind a gateway so models can change without code changes | Models are addressed only through configuration (endpoint, key, deployment names) of an OpenAI-compatible Foundry endpoint | `test_config.py`, `test_phase_four_embeddings.py`; swap by changing `.env` | Done with a difference: no LiteLLM or API Management in front of the models. A model change is a configuration change; central model governance is a production gap ([ADR-0001](decisions/adr-0001-search-and-model-gateway.md)) |
| AC10 | Every claim maps to a retrieved source URL or ID; the model never invents a link | Server-side evidence binding | Forged-ID, unknown-ID, and injected-URL tests; evaluation citation validity (17 of 17) | Done for links. Whether each claim is supported by its source is screened by a model judge (71–83% across runs) |
| AC11 | OpenTelemetry tracing, logging, and metrics to a product such as Aspire or Arize Phoenix | `src/product_support_agent/telemetry.py`, `apps/web/src/instrumentation.ts`; Aspire in Compose; [ADR-0008](decisions/adr-0008-opentelemetry.md) | `tests/unit/test_telemetry.py`; the Aspire dashboard | Done |
| AC12 | Offline evaluation dataset for grounding and citation accuracy | `tests/evaluation/questions-v2.json`, `scripts/run_evaluation.py` | [Evaluation report](../operations/phase-6-evaluation-v2.md) | Done: 21 questions. Latest run: expected page in the top five for 12 of 15, valid citations 17 of 17, claim support 10 of 12, refusals 6 of 6 |
| AC13 | AI gateway, managed identity, automated build and deployment, code-quality analysis, SAST, DAST, IAST | API Management; managed identities; `.github/workflows/`; Ruff, mypy, Biome, Bandit, CodeQL | Workflow tests; the CI run | Partly done: API Management fronts the API but not the models; Search and Foundry use keys; **no DAST or IAST** |
| AC14 | A phased path to production with usability and accessibility validation | [Path from proof of concept to production](architecture-overview.md#path-from-proof-of-concept-to-production); [production gap register](../operations/production-gap-register.md) | — | Done as a plan. The usability study and accessibility audit are not performed |
| AC15 | End-to-end testability: unit, integration, and end-to-end tests | `tests/unit/` (offline), `tests/evaluation/` and `scripts/run_evaluation.py` against the running stack, tests marked `live` for real services | `pytest`; `pytest -m live`; the evaluation | Done with a limit: there is no automated browser test suite |
| AC16 | Readable repository, ADRs, architecture documents, Mermaid diagrams | `docs/`, [README](../../README.md) | Review | Done |
| AC17 | Next.js and TypeScript front end; FastAPI; Agent Framework; MongoDB locally and Cosmos DB for MongoDB in the cloud; user-provided Azure AI Search for both; LiteLLM locally and API Management in the cloud as model gateways; system-assigned managed identity; Key Vault; no caching; Azurite locally and Storage Queue in the cloud; Podman | `apps/web`, `src/product_support_agent`, `compose.yaml`, `infra/bicep` | Local run; Bicep build | Done with differences: no LiteLLM or model gateway; **user-assigned** identities are used so roles exist before the apps start; Search and Foundry use keys; DocumentDB Free is an optional alternative to Cosmos DB |
| AC18 | Bicep for the entire cloud: virtual network with subnets, API Management in external mode with VNet integration, backend services, agents, data stores, and queue inside the network, Log Analytics and Azure Monitor | `infra/bicep/`; [ADR-0010](decisions/adr-0010-azure-platform-and-api-management.md) | `az bicep build` and lint in CI; what-if in the infrastructure workflow | Done: the template has been deployed to an isolated test environment. Foundry keeps a public endpoint |
| AC19 | Build pipeline for the UI, API, and agents | `.github/workflows/validate.yml`, `app.yml` | `tests/unit/test_workflows.py`; actionlint | Done: authored and tested offline; has not run on GitHub |
| AC20 | Deployment pipeline for the UI, API, and agents | `.github/workflows/app.yml`, `infra.yml` | Same | Done: authored and tested offline; has not run on GitHub |
| AC21 | Host the backend on Azure Container Apps | `infra/bicep/modules/container-apps.bicep` | Bicep build; deployed test environment | Done |
| AC22 | GitHub Actions for build and deployment | `.github/workflows/` | Same as AC19 | Done |

## Where the delivered solution differs from the brief

1. **Source content.** The product pages are rendered in the browser and hold
   no documentation, and the search API needs authentication. The agent
   therefore indexes public documentation sites named in a versioned source
   map, for 10 of the 100 sampled products.
2. **Model gateway.** The brief asks for LiteLLM locally and API Management in
   the cloud as model gateways. The models are called directly through
   configuration. API Management is deployed as the gateway for the application
   API.
3. **Retention.** Past queries and responses are not retained, pending the
   privacy decisions that the brief's retention request requires.
4. **Identity.** Managed identity is used for Key Vault, the queue, telemetry,
   and registry pulls, but Search and Foundry are called with keys.
5. **DAST and IAST.** Not set up.

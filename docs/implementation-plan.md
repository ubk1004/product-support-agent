---
title: Product Support Agent Implementation Plan
description: Review-gated implementation plan for a local-first product-support AI agent with a conceptual, statically validated Azure design in Canada Central
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: concept
keywords:
  - product support
  - AI agent
  - architecture
  - implementation plan
estimated_reading_time: 12
---

## Purpose and approval model

This plan turns the requirements in [Instructions.md](../Instructions.md) into a staged, testable delivery path. Phase 0, Phase 0b, and Phase 1 have been approved; implementation is limited to the current approved phase. No cloud resources or application deployments are authorized.

Each phase is a separate review gate. We will not begin a phase until you approve its scope, decisions, and exit criteria. A phase is complete only after its deliverables and relevant tests pass and you approve moving on.

## Confirmed scope decisions

* **Local-first demo.** The working demonstration runs locally on Podman. The MVP is complete at Phase 6.
* **Cloud is conceptual plus IaC.** The Azure architecture (APIM, VNet, private endpoints, managed identity) exists to show the intended security posture. It is expressed as Bicep that is authored and statically validated for Canada Central (`canadacentral`). The full stack is not deployed, because APIM, AI Search, and private networking carry significant monthly cost.
* **Network slice is deployable.** A separately deployable subset of the IaC (VNet, subnets, NSGs, egress, private DNS, and low-cost private-endpoint services) is deployed to the user-provided Azure subscription to validate routing and DNS.
* **Models.** Chat and embedding models are Microsoft Foundry deployments supplied by the user (endpoint and deployment names), reached through LiteLLM locally. No local models are used. Credentials are never committed.
* **Search.** Local and cloud both use the user-provided Azure AI Search service. There is no local vector store (no PostgreSQL/pgvector), which removes the local-versus-cloud adapter mismatch. The local demo therefore depends on network access to Azure.
* **IaC modules.** Use pinned Azure Verified Modules (AVM) where available, with thin composition modules otherwise.
* **Subscription.** The user provides an Azure subscription for `validate`, `what-if`, and the network slice.

## Product outcome

Deliver a demonstrable support assistant that answers questions about a documented, explicitly selected set of 100 OpenText products. Responses must be grounded in anonymously accessible source material, cite the source URL for each product or resource claim, and clearly disclose the limited demo catalog. The architecture should provide a safe path to later customer validation and production without representing the MVP as a production service.

The longer-term OpenText Service Management expansion is an architectural consideration, not MVP scope.

The demo runs locally. The Azure design is presented as a validated blueprint, with an explicit statement of which security controls are demonstrated locally and which are designed only.

## Approved repository structure

Use a Python `src` layout for the backend and keep application code, tests, documentation, infrastructure, and automation distinct.

```text
product-support-agent/
├── docs/
│   ├── architecture/
│   │   └── decisions/
│   ├── security/
│   ├── operations/
│   └── implementation-plan.md
├── apps/
│   └── web/
│       ├── package.json
│       ├── package-lock.json
│       └── src/
│           └── app/
├── src/
│   └── product_support_agent/
│       └── api/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── end_to_end/
│   ├── evaluation/
│   └── fixtures/
├── infra/
│   └── bicep/
│       ├── modules/
│       └── environments/
├── .github/
│   ├── CODEOWNERS
│   └── workflows/
├── pyproject.toml
├── uv.lock
├── compose.yaml
├── .env.example
├── README.md
└── Instructions.md
```

Keep test data synthetic or explicitly approved. Do not commit credentials, customer data, scraped source content, generated secrets, or local state. Use `docs/architecture/decisions/` for accepted architecture decision records (ADRs), and retain Mermaid diagrams as text in architecture documentation.

## Target architecture to validate

The proposed flow is:

1. A scheduled or manually started catalog process obtains the product list, selects and records a stable 100-product demo manifest, and publishes one product reference per queue message.
2. An ingestion worker fetches only approved public URLs, observes HTTP status and retry headers, skips authentication-protected material, normalizes permitted content, chunks it, creates embeddings through a gateway, and updates the search index idempotently.
3. The retrieval layer combines keyword, metadata, and semantic signals and returns source IDs, URLs, and relevant excerpts with each result.
4. A FastAPI service coordinates retrieval and a Microsoft Agent Framework agent. A model gateway provides a replaceable interface for embedding and chat models.
5. A React/Next.js frontend provides the user-facing chat experience, clearly identifies the demo catalog, and renders citations supplied by retrieval rather than invented by the model.
6. OpenTelemetry-compatible traces, metrics, and appropriately minimized logs support evaluation and operations. Production cloud resources use managed identity where supported; GitHub Actions uses federated identity for deployment.

The exact trust boundaries, component placement, and network paths must be approved in Phase 0. Mermaid context, container, data-flow, and deployment diagrams are Phase 0 deliverables.

## Architecture gaps and decisions for review

The requirements identify desired technologies but leave behavior and ownership decisions open. The proposed defaults below are recommendations for review, not approved choices.

| Topic | Gap or tension | Proposed default for review |
|---|---|---|
| Customer value | The requirements define a working demo but not target users, top tasks, or evidence that answers are useful. | Identify target personas and priority support questions before implementation; agree on a small usability study and success measures. |
| Source access | Public pages, search API, product feed, robots/terms, and page links may behave differently or change. | Confirm permitted automated access and define an allowlist, request limits, response-size limits, timeouts, and parser behavior before crawling. Never bypass authentication. |
| API fallback | The feed is described as a fallback, but fallback triggers and whether it is equivalent to the product listing are unspecified. | Use the feed only for defined availability/empty-result cases; treat network, parse, and authorization failures distinctly and surface them in run status. |
| Product sampling | “Random 100” could change on every run, making the visible catalog and evaluation irreproducible. | Select randomly once per approved manifest version, persist the exact product IDs/names/source URLs, and reuse it for normal reruns. Require an explicit action to replace the sample. |
| Pagination and limits | Pagination termination, maximum pages, and total request budget are unspecified. | Define validated page limits, a request budget, duplicate handling, and stop conditions. Use bounded retries with jitter and honor `Retry-After` on HTTP 429. |
| Protected resources | Skip behavior is specified, but the record format, reporting destination, and distinction between 401, 403, and other failures are not. | Record a minimal structured outcome with product ID, URL, status/reason category, timestamp, and run ID. Do not persist protected content or credentials. |
| Ingestion correctness | Queue delivery semantics, duplicate messages, poison items, delta detection, deletion, and stale documents are unspecified. | Make processing idempotent by stable source/document IDs and content hashes; define retry limits, dead-letter handling, index deletion, and reprocessing policy. |
| Canonical data | Required metadata, chunk identity, provenance, schema evolution, and source freshness are unspecified. | Version a canonical document/chunk schema with source URL, product ID, timestamps, content hash, access outcome, and parser/version provenance. Decide what content is retained and for how long. |
| Search stores | Local and cloud now share Azure AI Search, so adapter and ranking parity are no longer a concern. New concerns: the local demo needs Azure connectivity and a running search service; the tier determines cost, storage, and feature limits (for example semantic ranker and private endpoints); indexes cannot be created by Bicep; and developer machines reach the service over its public endpoint, unlike the private-endpoint cloud design. | Use one provider behind a thin retrieval interface so tests can use a fake. Version the index definition as code (schema, analyzers, vector profile, semantic configuration) and create it with a script or the SDK. Choose the tier from the data volume and feature needs, with a cost estimate. Use separate indexes or aliases for demo, test, and reindex runs. Authenticate with Entra ID (`DefaultAzureCredential`) where possible, and restrict the public endpoint by IP. Define the hybrid fusion and semantic ranking configuration explicitly. |
| Data ownership | MongoDB/Cosmos DB Mongo API, Azure AI Search, and the queue each have possible overlap. The system of record for manifests, run status, and normalized content is unclear. | Assign ownership per data type. Confirm which store holds product manifests, operational state, canonical content, and searchable chunks; avoid storing the same data without a consistency reason. |
| Caching | A cache is listed for review, but cache targets, TTLs, invalidation, and privacy boundaries are undefined. | Defer caching until baseline measurements show a need. If approved, cache only safe, versioned data with bounded TTLs and explicit invalidation; do not cache user-specific responses by default. |
| User data and telemetry | The UI must not show past searches, while all queries and responses are requested to be retained. This creates privacy, security, and retention obligations. | Treat UI history and server-side telemetry as separate features. Before retaining content, define notice/consent, purpose, access, redaction, retention/deletion, and incident procedures; prefer minimized or redacted telemetry. |
| Model and gateway | LiteLLM and Azure API Management are not necessarily equivalent in model routing, identity, policy, or telemetry. | Specify the gateway contract, model/version configuration, credentials, safety policy, quotas, and failure behavior. Chat and embedding calls target user-provided Foundry deployments. Changing the embedding model changes vector dimensions and requires reindexing, so record the embedding model and dimension in the index schema and use versioned indexes or aliases. Verify APIM’s role relative to model-provider endpoints and avoid hard-coding provider-specific behavior in the agent. |
| Authentication | Runtime system-assigned managed identity does not by itself define end-user authentication or GitHub Actions deployment authentication. | Decide whether the demo is public, access-restricted, or organization-only. Use workload identity federation for CI/CD and runtime managed identity for Azure resource access where supported. |
| Network topology | “APIM external mode with VNET integration,” Container Apps, and “all backend services under the VNET” need a concrete supported topology and subnet plan. | Validate the chosen APIM SKU/network model, Container Apps environment networking, private endpoints, DNS, egress, and subnet sizing against current Azure capabilities before Bicep is approved. Do not assume every managed service can be placed inside a VNet. Design-only for the MVP; resolved in Phase 7. |
| Hosting boundaries | It is unclear whether the Next.js frontend, FastAPI, and worker are separate deployables or one service. | Keep UI/API/worker boundaries explicit in code. Choose separate Container Apps or a smaller MVP deployment only after operational, security, and scaling trade-offs are documented. |
| Evaluation | “Factual grounding” and “citation accuracy” lack dataset ownership, thresholds, and release-blocking criteria. | Create versioned, reviewed question/answer/source cases and agree on measurable thresholds for citation validity, groundedness, relevance, refusal, latency, and cost before model release gates. |
| Pipeline security | SAST, DAST, and IAST are requested without tools, pipeline stages, environments, or vulnerability thresholds. | Define quality/security gates, dependency and container scanning, secret detection, IaC validation, artifact provenance, and safe test environments in Phase 0/1. Apply DAST/IAST where the selected stack and hosting model support them. |
| Production readiness | Scale, availability, support ownership, accessibility target, service objectives, and incident response are not defined. | Treat production as a later decision gate. Establish customer validation, accessibility testing, SLOs, alert ownership, retention, recovery, and support readiness before any production launch. |
| Region and model availability | Canada Central is mandated. Some services, SKUs, availability zones, and Foundry model deployments may be unavailable or quota-limited there. | Verify each service/SKU and the user's Foundry deployments in Canada Central during Phase 7. If a model is hosted in another region, record the data-residency impact in an ADR. |
| APIM SKU and network model | Classic VNet injection (external mode) and v2 VNet integration behave differently, and Premium costs thousands per month. | Parameterize the SKU and design for the intended posture. Document the production-like SKU. Do not deploy APIM in the MVP. |
| Egress path | The worker must reach public OpenText hosts from inside the VNet. | Design a NAT Gateway or firewall egress with a stable IP, a host allowlist, and an identifying User-Agent. |
| Identity bootstrap | A system-assigned identity on a Container App does not exist until the app does, so it cannot pull from ACR on first deploy. Cosmos DB for MongoDB data-plane auth may not support Entra ID in every model. | Decide user- versus system-assigned identity per component in an ADR. Verify Cosmos Mongo auth. If keys are required, store them in Key Vault and record the posture trade-off. |
| IaC naming and validation | No naming, tagging, or static-validation standard exists. | Adopt the naming standard and validation levels L0-L3 plus the network slice defined in Phase 7. |
| Demo data snapshot | The demo should not depend on live OpenText availability, but scraped content must not be committed. | Keep a pre-ingested snapshot of the canonical documents (and their stored embeddings, so the index can be rebuilt without re-calling the embedding model) as a local MongoDB backup outside git, plus the populated Azure AI Search demo index, after confirming acceptable use. Live ingestion remains an optional path. |

### Decision classification

* **Blocking before Phase 1 or 2:** source access, API fallback, product sampling (including eligibility: whether a sampled product must have at least one anonymously accessible resource), pagination, protected resources, ingestion correctness, canonical data, data ownership, user data and telemetry, model and gateway, evaluation, hosting boundaries (code level), search stores, and the demo data snapshot.
* **Design-only, decided in Phase 7 (does not block the local demo):** authentication for a cloud deployment, network topology, APIM SKU, egress path, identity bootstrap, region and model availability, cloud pipeline security, and IaC naming and validation. The local demo has no end-user authentication.
* **Deferred:** caching (ADR default: no cache in the MVP, with explicit revisit conditions) and production readiness.

## Phased implementation plan

### Phase 0: Product discovery and architecture decisions

**Goal:** Resolve decisions that would otherwise cause rework or create unacceptable risk.

**Scope and deliverables:**

* Confirm personas, priority tasks, sample user questions, user access model, and demo success measures.
* Verify source access rules, endpoint behavior, pagination semantics, fallback conditions, and acceptable request volume without building the crawler. Run a time-boxed, read-only probe script, kept outside product code and within the approved request budget, to confirm status codes, redirects to login pages, JavaScript rendering, and content types.
* Agree on the 100-product manifest behavior, protected-content skip policy, data retention, and source freshness expectations.
* Define the system of record for catalog manifest, ingestion runs, canonical documents, and search index.
* Decide whether the UI, API, and worker are separate deployables; define the gateway/provider contract and the local/cloud data adapters (MongoDB/Cosmos DB and Azurite/Storage Queue; search uses Azure AI Search in both).
* Create architecture context, container, data-flow, trust-boundary, and deployment diagrams in Mermaid.
* Create ADRs for the decisions above, including the rejected alternatives and consequences.
* Define security boundaries, evaluation metrics, and production-readiness constraints. The threat model and privacy impact assessment are delivered in Phase 0b.
* Create a requirement traceability matrix from the numbered items in [Instructions.md](../Instructions.md), a risk and assumptions register, and a support-ownership (RACI) outline.
* Record the local-to-cloud component mapping (LiteLLM to APIM, MongoDB to Cosmos DB, Azurite to Storage Queue, Redis to Azure Cache; Azure AI Search is used in both) with known behavior differences, including that local code reaches Azure AI Search over its public endpoint while the cloud design uses a private endpoint. Add a security-posture matrix of controls demonstrated locally versus designed only.
* Maintain the current Phase 0 artifacts in [the architecture overview](./architecture/architecture-overview.md), [decision register](./architecture/decision-register.md), [requirements traceability matrix](./architecture/requirements-traceability.md), [risk and assumptions register](./architecture/risk-assumptions.md), [support-ownership outline](./architecture/support-ownership.md), and [security-posture matrix](./security/security-posture.md). Record remaining approvals and safe deferrals in the decision register.
* Record individual proposed architecture decisions as [ADRs](./architecture/decisions/), with status and consequences visible to reviewers.

**Verification and exit gate:**

* Requirements map to components, risks, tests, and an owning phase.
* Every blocking row in “Architecture gaps and decisions for review” has an approved decision or a documented deferral with a safe MVP default.
* You approve the user problem, MVP boundary, data handling, architecture diagrams, and ADRs before Phase 0b.

**Depends on:** None.

### Phase 0b: Threat modelling and privacy impact assessment

**Goal:** Identify and rate security and privacy threats against the approved design, before implementation, and establish the register that later phases update.

**Scope and deliverables:**

* Build a data-flow diagram from the Phase 0 architecture, covering the local components and their cloud counterparts, with every trust boundary marked: external users, the Next.js UI, the API, the agent, LiteLLM and the Foundry endpoints, the worker, the public OpenText sources, the queue, the data stores, and telemetry.
* Create an asset and data inventory: scraped content, user queries and responses, the manifest, embeddings, model credentials, run status, and telemetry. State classification, owner, storage location, and retention for each.
* Analyze threats with STRIDE per trust boundary plus AI-specific threats from the OWASP Top 10 for LLM Applications and MITRE ATLAS. At minimum, assess:
  * indirect prompt injection through scraped content
  * data exfiltration through rendered markdown, images, or links
  * citation spoofing or invented sources
  * denial-of-wallet against the Foundry quota
  * poisoned or stale index content
  * sensitive data in retained queries and telemetry
  * the crawler being abused against OpenText
  * SSRF through ingested URLs
  * secret exposure in configuration and logs
  * unauthorized access to or tampering with the Azure AI Search index, and credential exposure on developer machines
  * supply-chain risk in dependencies and container images
  * XSS in the React/Next.js rendering path
* Maintain a threat register. Each entry records an ID, description, affected boundary or asset, rating and rationale, mitigation, owning phase, verifying test, and status (mitigated, accepted, or deferred), plus the cloud control it maps to.
* Write a privacy impact assessment for retained queries and responses: purpose, lawful basis or approval, notice text, access control, redaction approach, retention and deletion, reviewer roles for malicious-attempt detection, and incident handling.
* Define abuse-case and red-team test requirements for the prompt-injection and exfiltration threats, so they feed the Phase 4 and Phase 6 test and evaluation suites.
* Maintain the [threat register](./security/threat-register.md) and [privacy impact assessment](./security/privacy-impact-assessment.md) as Phase 0b drafts until their approval gate.

**Verification and exit gate:**

* Every trust boundary and asset in the diagrams appears in the register.
* Every high-rated threat has a mitigation with an owning phase and a verifying test, or a formal acceptance by an accountable owner.
* The privacy impact assessment is approved before any phase captures real user queries.
* You approve the threat register and privacy impact assessment before Phase 1.

**Depends on:** Phase 0 approval, because the data-flow diagram and decisions it analyzes come from there.

### Phase 1: Repository foundation and local development

**Status:** Implementation and automated verification are complete; phase-exit review is pending.

**Goal:** Establish a consistent, testable project foundation before implementing product behavior.

**Scope and deliverables:**

* Create the approved repository structure using Python `src` layout, a TypeScript Next.js app, and the selected package boundaries. Add CODEOWNERS and an ADR template. Branch protection remains a repository-host setting that must be enabled by an authorized maintainer.
* Document supported Python version, dependency management, formatting, linting, type checking, configuration, and local run commands.
* Define configuration and secret handling for local development; use Podman-compatible local service orchestration.
* Establish test conventions, fixture policy, structured logging defaults, and correlation/run identifiers.
* Add an initial GitHub Actions validation workflow for formatting, linting, typing, unit tests, dependency checks, and secret scanning. Pin every external action to a verified full commit SHA.
* Add a local development guide and a concise architecture overview.

**Verification and exit gate:**

* A clean checkout can install dependencies and run the documented checks using the approved local toolchain.
* A small test demonstrates that configuration, logging redaction hooks, and service health checks work without real source or model credentials.
* The validation workflow blocks merge on required checks and does not expose secrets in logs.
* You approve the structure, developer workflow, and baseline quality gates.

**Depends on:** Phase 0 and Phase 0b approval.

### Phase 2: Source catalog and resilient ingestion

**Goal:** Reliably discover the catalog and enqueue exactly the approved 100 products without exceeding source limits.

**Scope and deliverables:**

* Implement catalog retrieval with explicit API/feed fallback rules, response validation, controlled pagination, deduplication, and empty-catalog handling.
* Create versioned, reproducible selection of 100 products and make the manifest available to the chat experience.
* Enqueue one product reference per message; keep queue payloads minimal and avoid embedding content in messages.
* Implement a worker with source host allowlisting, safe URL validation, bounded downloads, status-aware handling, `Retry-After` support, bounded exponential backoff with jitter, and dead-letter reporting.
* Skip authenticated/protected content without attempting to bypass access controls; record a minimal reason and outcome.
* Store run-level and product-level ingestion status with enough provenance to diagnose success, skip, retry, and failure.
* Treat 3xx redirects to login pages and 200 responses that contain login content as protected outcomes, not only 401 and 403. Azure Storage Queue has no built-in dead-letter queue, so implement a poison queue using the dequeue count, and add run-completion tracking and partial-failure semantics.
* Start a versioned golden evaluation set tied to the manifest version; it grows in each later phase.

**Verification and exit gate:**

* Unit tests cover pagination, fallback decisions, empty results, duplicate products, URL validation, status handling, retry limits, and manifest reproducibility.
* Integration tests use a local HTTP stub and queue emulator; they do not depend on OpenText availability.
* A controlled end-to-end run proves no more than the approved manifest is processed and no protected content is stored.
* You approve the resulting manifest and ingestion outcome report.

**Depends on:** Phase 1 approval; Phase 0 source-access and manifest decisions.

### Phase 3: Canonical documents, indexing, and hybrid retrieval

**Goal:** Turn permitted source material into traceable, updateable search results.

**Scope and deliverables:**

* Define and version canonical document and chunk schemas, stable IDs, content hashes, provenance, and update/delete behavior.
* Implement parsing and normalization for approved public source formats; reject unsupported or oversized content safely.
* Define chunking, metadata filters, embedding model/version, and index schema.
* Implement the Azure AI Search provider behind a thin retrieval/indexing interface, plus an in-memory fake used by routine unit tests. Create and version the index definition as code and apply it with a script or the SDK.
* Implement hybrid keyword, metadata, and semantic retrieval with configurable ranking and return source IDs, URLs, and excerpts.
* Add index reconciliation and reprocessing for changed/deleted source content.

**Verification and exit gate:**

* Unit tests cover normalization, canonical identity, chunk provenance, schema evolution, and idempotent updates.
* Integration tests verify indexing, metadata filters, hybrid retrieval, source URL preservation, and deletion/reindex behavior. They run against a dedicated Azure AI Search test index as controlled live tests; routine unit tests use the in-memory fake, and CI does not require Azure Search unless approved.
* A reviewed retrieval test set meets agreed relevance and citation-source thresholds against Azure AI Search, using a dedicated test index separate from the demo index.
* You approve schema, freshness behavior, and retrieval quality before agent integration.

**Depends on:** Phase 2 approval; Phase 0 data ownership and retrieval decisions.

### Phase 4: FastAPI and grounded agent orchestration

**Goal:** Answer product-support questions with bounded tools and verifiable citations.

**Scope and deliverables:**

* Implement FastAPI endpoints for health, catalog availability, and chat requests using validated request/response schemas.
* Implement the Microsoft Agent Framework orchestration and structured retrieval tool/function calling behind the approved gateway interface. Verify the framework's release status and pin its version. Chat and embedding calls go through LiteLLM to the user-provided Microsoft Foundry deployments.
* Enforce grounding: product/resource claims must map to retrieved source IDs and URLs; do not allow the model to create or alter citations.
* Define behavior for no results, unsupported products, ambiguous requests, model/gateway failures, and inaccessible sources.
* Treat retrieved documents as untrusted input; apply prompt-injection defenses, tool allowlisting, output validation, and safe error handling.
* Add request limits, timeouts, concurrency controls, and provider-independent configuration.

**Verification and exit gate:**

* Unit tests cover tool input/output validation, citation binding, refusal/no-result behavior, prompt-injection cases, and model/gateway failure handling.
* Integration tests use a deterministic fake model/gateway and search provider; no live model is required for routine tests.
* End-to-end tests prove every factual product/resource response contains valid retrieved citations and unsupported claims are not presented as facts.
* Abuse-case tests defined in Phase 0b pass for prompt injection, exfiltration through rendered output, citation spoofing, and quota abuse, and each threat-register entry owned by this phase has its verifying test.
* You approve representative answers and the failure/refusal experience.

**Depends on:** Phase 3 approval; Phase 0 gateway, identity, and safety decisions.

### Phase 5: Next.js interface and customer usefulness validation

**Goal:** Deliver a usable demo experience and test whether it helps target users complete real support tasks.

**Scope and deliverables:**

* Implement the Next.js chat flow, visible demo limitations, supported-product names, source citations, and clear empty/error states.
* Do not display past search history in the MVP. Define whether browser/session state is transient and what is sent to backend telemetry.
* Add accessible interaction patterns, keyboard navigation, screen-reader labels, readable citations, and responsive layouts.
* Run moderated usability walkthroughs of the local demo with representative users using realistic support questions. The telemetry and privacy policy must be approved before any session captures user queries.
* Record usability findings, answer failure modes, and prioritized product changes; do not treat successful HTTP responses as proof of product usefulness.

**Verification and exit gate:**

* UI tests cover catalog disclosure, chat submissions, citation navigation, errors, and no-history behavior.
* Accessibility checks include automated scans and manual keyboard/screen-reader review against the agreed target.
* User validation meets agreed task-completion and usefulness criteria, or findings are converted into approved changes before advancing.
* You approve the demo UX and the evidence that the MVP is useful for its intended audience.

**Depends on:** Phase 4 approval; Phase 0 persona, usability, privacy, and accessibility decisions.

### Phase 6: Local integrated MVP and evaluation

**Goal:** Prove the full local product flow and establish repeatable quality evidence. This phase is the MVP completion gate.

**Scope and deliverables:**

* Integrate UI, API, agent, worker, queue emulator, and metadata store with LiteLLM using Podman, and connect them to the user-provided Azure AI Search and Foundry endpoints. No local vector store runs.
* Create a versioned offline evaluation dataset with approved questions, expected evidence/source IDs, and known failure cases.
* Add evaluation for retrieval relevance, factual grounding, citation correctness, unsupported requests, injection resistance, latency, and cost.
* Add OpenTelemetry traces, metrics, and structured logs with sensitive-content redaction and correlation across ingestion and chat.
* Define a telemetry data policy for user queries and responses, including notice, access, retention, deletion, and redaction before enabling content retention.
* Publish a reproducible local demo runbook and an ingestion/evaluation report format.
* Package the demo: a pre-ingested snapshot (a MongoDB backup kept outside git) plus the populated Azure AI Search demo index with a documented rebuild procedure, the minimum machine requirements (WSL2, `podman machine`, memory), a connectivity checklist for Azure AI Search and Foundry (credentials, IP allowlist, quota), service health-check ordering, and a live-source path that is optional rather than required.
* Demonstrate the locally enforceable security controls (URL allowlist, protected-content skip, citation validation, prompt-injection defenses, log redaction, LiteLLM budgets and rate limits, segmented Podman networks) and show where each maps to a cloud control.

**Verification and exit gate:**

* A clean local run exercises catalog-to-index and chat-to-citation paths end to end using approved fixtures or a controlled source run.
* Unit, integration, end-to-end, and evaluation suites pass their agreed thresholds.
* Trace inspection confirms useful spans and metrics while logs do not reveal configured secret/PII test values.
* The threat register shows every threat owned by Phases 2-6 as mitigated and tested, or formally accepted, and the red-team set runs as part of the evaluation suite.
* You approve local MVP behavior, evaluation thresholds, and telemetry policy.

**Depends on:** Phases 2, 3, 4, and 5 approval.

### Phase 7: Cloud architecture and infrastructure as code (design-only)

**Goal:** Define the Azure target architecture for Canada Central and produce statically validated Bicep that shows the intended security posture, without deploying the application stack.

**Scope and deliverables:**

* Verify first, using current Microsoft documentation and Azure tooling, and record results in ADRs:
  * Canada Central availability and quota for every service and SKU, and for the user's Foundry model deployments.
  * The APIM SKU and VNet model (classic injection versus v2 integration), and HTTP streaming or WebSocket behavior through APIM for the Next.js UI if used.
  * Cosmos DB for MongoDB authentication modes, the AI Search tier required for private endpoints, Container Apps networking requirements, and the private DNS zone name for each service.
* Write a naming and tagging standard: pattern `{type}-{workload}-{env}-{region}-{instance}` with Cloud Adoption Framework abbreviations and a region code (`cac`), a per-resource constraint table (length, allowed characters, global uniqueness for Storage, Key Vault, Cosmos DB, ACR, APIM, and Container Apps), a `uniqueString` suffix where needed, and mandatory tags (owner, environment, data classification, cost center, demo).
* Author Bicep with a subscription-scope entry point that creates the resource group, followed by resource-group-scope modules. Use pinned AVM modules where available and thin composition modules otherwise; parameterize SKUs and keep per-environment parameter files. Cover:
  * VNet, subnets (APIM, Container Apps, private endpoints), NSGs, NAT Gateway egress, and private DNS zones with VNet links.
  * Key Vault, Storage (queue), Log Analytics, Application Insights, and ACR.
  * Identities and least-privilege RBAC.
  * Container Apps environment and apps (UI, API, worker, agents), with KEDA queue scaling.
  * Cosmos DB (Mongo API), AI Search, Azure Cache for Redis only if justified, APIM with policy files, and a reference to the existing Foundry deployments (endpoint and deployment names as parameters, never secrets).
* Define a separately deployable **network slice** entry point containing the VNet, subnets, NSGs, egress, private DNS zones and links, and low-cost private-endpoint services (Key Vault, Storage queue, Log Analytics). Deploy it to the user's subscription to validate routing, private endpoint DNS resolution, and egress. Use a short-lived diagnostic workload (for example a container instance in a delegated subnet) to test name resolution and reachability, and delete it afterward. Include a teardown script and a budget alert.
* Author the GitHub Actions workflows without enabling application deployment:
  * IaC validation on pull request.
  * IaC deployment by `workflow_dispatch` only, with a protected environment and reviewers, defaulting to the network slice.
  * Application build (UI, API, worker, agents), which runs without Azure.
  * Application deployment, authored but guarded off.
  * Pin actions by SHA and use OIDC federated credentials. Document the one-time Entra app registration and federated-credential bootstrap, because Bicep does not cover it.
* Produce a cost estimate for Canada Central with a SKU ladder (APIM tier, AI Search tier, Cosmos mode, NAT Gateway, private endpoints, Log Analytics), stating the currency.
* Map every threat in the Phase 0b threat register to its local control and its cloud resource in the IaC, such as an NSG, private endpoint, APIM policy, or RBAC role. Update the register for threats introduced by the cloud design.

**Verification and exit gate:**

* **L0 syntax:** `bicep build` and `bicep build-params` pass.
* **L1 lint and policy:** `bicep lint` with a `bicepconfig.json`, PSRule for Azure, a configuration scanner (Checkov or Trivy), and `actionlint` pass.
* **L2 structure:** a custom script verifies module nesting, naming constraints, mandatory tags, subnet CIDR non-overlap, private endpoint to DNS zone pairing, output-to-input wiring, and the absence of secrets in parameter files.
* **L3 ARM preflight:** `az deployment sub validate` and `what-if` run cleanly against the user's subscription for both the full template and the network slice.
* **L4-lite:** the network slice deploys, name resolution and egress checks pass, and teardown completes.
* The plan states what these checks do not prove: APIM provisioning requirements, quota and capacity, Azure Policy denials, global name collisions, and the full stack's runtime behavior.
* You approve the cloud design, the cost envelope, the identity model, and the validation evidence.

**Depends on:** Phase 0 approval and Phase 1 repository foundation. It may run in parallel with Phases 2-6 and is reconciled with the Phase 6 container inventory before approval.

### Phase 8: Cloud deployment and pilot (deferred, not in MVP)

**Goal:** Deploy the application stack to a controlled Azure environment and run a limited pilot.

This phase is out of scope for the MVP. Entry criteria before it is scheduled:

* Budget approval and a chosen APIM SKU.
* Phase 7 approved and the network slice validated.
* Telemetry, privacy, and support-ownership policies approved.

Planned scope when started: deploy immutable, scanned UI/API/worker/agent artifacts through protected environments, run cloud integration, load, accessibility, and security tests (SAST, DAST, and IAST where tooling supports the stack), validate rollback, and measure pilot task success, citation quality, latency, cost, and support burden.

### Phase 9: Production-readiness gap register (deferred)

**Goal:** Document what separates the demo from a production service so the gaps are explicit.

**Scope and deliverables:**

* Carry forward every accepted or deferred threat from the threat register as residual risk with an owner.
* Record gaps and owners for service-level objectives, capacity, support hours, incident response, privacy and legal source-use review, accessibility, retention and deletion, disaster recovery and index rebuild, model and provider outage handling, credential rotation, continuous evaluation, and manifest and content update processes.
* Reassess the deferred OpenText Service Management expansion as a separate discovery and architecture decision.

**Verification and exit gate:**

* The register is reviewed and accepted. A production launch requires a separate decision with named business and technical owners; completing this register does not imply approval.

**Depends on:** Phase 6 approval. A production launch would also require Phase 8.

## Cross-phase quality gates

* Every phase defines unit, integration, end-to-end, and evaluation tests relevant to its behavior. External systems are stubbed in routine tests; controlled live tests are separately approved.
* Keep tests deterministic and independently runnable where practical. Do not make a phase pass solely because a manual happy-path demo succeeds.
* Each release candidate must preserve source provenance and citation validity, enforce approved data handling, and pass applicable security and accessibility gates.
* Record test evidence, known limitations, and deferred risks with the phase review. A failed gate blocks phase completion until corrected or explicitly accepted.
* Keep build, infrastructure, and application deployment workflows separated enough to apply distinct permissions and approvals.
* At every phase gate, review the threat register: identify new data flows, trust boundaries, dependencies, or assets introduced by the phase, add or re-rate threats, and confirm each mitigation owned by the phase has a passing test. A phase cannot close with an untested mitigation for a high-rated threat unless an accountable owner formally accepts it.

## Review checklist for Phase 0

Before implementation begins, review and approve:

1. Target users, priority questions, and measurable demo success criteria.
2. Public-source access policy, endpoint behavior, request limits, and fallback rules.
3. Stable 100-product selection and catalog-update policy.
4. Data ownership, canonical schema direction, deletion/freshness policy, and storage responsibilities.
5. Azure AI Search as the single search provider for local and cloud (tier, index design, access method) and the model-gateway contract.
6. User authentication, telemetry notice/retention, and protected-content reporting.
7. Hosting boundaries, Azure network topology, identity, and deployment model.
8. Evaluation thresholds, security gates, accessibility target, and production-readiness criteria.
9. Proposed repository structure and documentation/ADR ownership.
10. Canada Central service and Foundry model availability, and the APIM SKU/network model to design against.
11. Naming and tagging standard, AVM module policy, and IaC validation levels.
12. The security-posture matrix (demonstrated locally versus designed only).
13. The threat register and data-flow diagram (Phase 0b), including ratings, mitigations, owning phases, and accepted risks.
14. The privacy impact assessment for retained queries and responses.

## Scope explicitly deferred from the MVP

* Authenticated access to OpenText customer resources or any attempt to bypass access controls.
* Full OpenText Service Management integration.
* Unbounded crawling, indexing the entire product catalog, or increasing the 100-product limit without explicit review.
* Retaining user search history in the interface.
* Production launch before Phase 9 approval.
* Deploying APIM, AI Search, Cosmos DB, Container Apps applications, or any application workload to Azure (Phase 8 is deferred).
* Local models; the demo uses user-provided Microsoft Foundry deployments only.

---
title: Product Support Agent Threat Register
description: Phase 0b threat assessment across the local MVP trust boundaries
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: reference
keywords:
  - threat modeling
  - STRIDE
  - AI security
estimated_reading_time: 9
---

## Status and method

The user approved this register with conditions at the Phase 0b gate. Ratings
are qualitative pre-mitigation assessments. Mitigations are planned unless the
[Phase 1 review](#phase-1-review) records implemented evidence. The register uses STRIDE across the architecture trust boundaries and
includes AI-specific risks from the
[OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
and [MITRE ATLAS](https://atlas.mitre.org/).

## Assets and data inventory

| ID | Asset or data | Classification | Owner | Location and flow | Proposed retention |
|---|---|---|---|---|---|
| A-01 | Product manifest, product names/IDs/URLs, and per-product ingestion outcomes | Internal demo metadata | Product owner | MongoDB to API and Next.js UI | Retain only the current approved manifest and run outcomes; deletion policy pending |
| A-02 | Public-source content, canonical documents, chunks, and embeddings | Untrusted source material | Ingestion/data owner | Worker, MongoDB, Azure AI Search | Store only permitted public content; freshness and deletion period pending |
| A-03 | User queries and assistant responses | Potentially sensitive user content | Privacy owner, TBD | Browser, Next.js, FastAPI, agent, LiteLLM, Foundry; optional restricted MongoDB collection | Retention is disabled until the privacy policy and provider handling are approved; if enabled, redacted content only for the configured TTL |
| A-04 | Source IDs, URLs, and retrieval excerpts | Public provenance plus untrusted text | Search/data owner | Azure AI Search, agent, API, Next.js | Retain with indexed content; never accept model-authored source URLs |
| A-05 | Foundry, Azure AI Search, MongoDB, and gateway credentials/configuration | Secret | Application maintainer | Developer environment or approved secret store | Do not commit, log, trace, or include in fixtures |
| A-06 | Queue messages, run IDs, status, timestamps, retry/dequeue counts | Internal operational metadata | Ingestion owner | Azurite/Storage Queue, worker, MongoDB | Retention and deletion period pending |
| A-07 | Logs, traces, and metrics | Internal operational telemetry | Application/security owner | Local collector or selected destination | Minimized metadata only; no query/response content before policy approval |

## Trust boundaries

| Boundary | Crossing data or action | Main concern |
|---|---|---|
| TB-01 External user/browser to Next.js | User input, rendered answer, links, optional retention choice | Malicious input, unsafe rendering, unintended retention |
| TB-02 Next.js to FastAPI and agent | Chat request, session metadata, response | Schema bypass, resource exhaustion, session mix-up |
| TB-03 Agent/LiteLLM to Foundry | Prompt, retrieved evidence, model output | Prompt injection, provider data handling, quota abuse |
| TB-04 Worker to OpenText | Anonymous catalog/page requests and returned content | SSRF, protected content, source load, hostile content |
| TB-05 Catalog/worker to queue and MongoDB | Product references, run status, canonical records | Replay, tampering, duplicate work, excessive retention |
| TB-06 Worker/agent to Azure AI Search | Documents, embeddings, queries, results | Unauthorized access, index tampering, stale/poisoned data |
| TB-07 Services to telemetry | Operational events; optionally retained content only after approval | Secret/content leakage and excessive access |
| TB-08 Developer machine to user-provided services | Authentication tokens, keys, configuration | Local credential exposure and unintended service access |
| TB-09 Cloud application boundary, design-only | APIM, Container Apps, managed identities, private services | Incorrect network, identity, or policy assumptions |

The [architecture overview](../architecture/architecture-overview.md) contains
the corresponding data-flow and deployment diagrams.

## Threat register

| ID | Threat and boundary | STRIDE / AI risk | Rating and rationale | Planned mitigation and verifying test | Owner and phase | Cloud mapping | Status |
|---|---|---|---|---|---|---|---|
| T-01 | Indirect prompt injection in source text (TB-03, TB-04, TB-06) | Tampering; LLM prompt injection | High: retrieved content can steer the model or tools | Treat source text as data; restrict tools; test malicious instructions in source fixtures and verify no unauthorized action or unsupported answer | Agent owner, Phase 4 | APIM policy and monitoring supplement, but do not replace application validation | Planned |
| T-02 | SSRF or unsafe redirect through catalog/page URLs (TB-04) | Spoofing, information disclosure | High: a crafted URL could reach internal or non-allowlisted services | Allowlist scheme/host; validate every redirect; reject private, loopback, link-local, and unexpected hosts; test hostile URLs and redirects | Ingestion owner, Phase 2 | Worker egress allowlist, NSGs, firewall/NAT | Planned |
| T-03 | Crawler abuse, excessive requests, or rate-limit disregard (TB-04) | Denial of service | High: source load or blocked access | Enforce product/request/page/download/concurrency/time budgets; honor `Retry-After`; stop on 401/403; test request cap and 429 behavior | Ingestion owner, Phase 2 | Stable egress IP and egress controls | Planned |
| T-04 | Protected content stored after 401/403, login redirect, or login page (TB-04) | Information disclosure | High: authenticated material is outside the anonymous MVP | Treat protected responses as skips; store only minimal status; test all protected outcomes and assert no content reaches MongoDB or Search | Ingestion owner, Phase 2 | Same application rule; network controls are not authorization bypasses | Planned |
| T-05 | Citation spoofing, altered URLs, or unsupported product claims (TB-02, TB-03, TB-06) | Tampering; LLM misinformation | High: users may trust fabricated support guidance | Bind source IDs to retrieved records; resolve URLs server-side; validate every cited ID; test forged IDs/URLs and unsupported questions | Agent owner, Phase 4 | APIM does not replace citation validation | Planned |
| T-06 | Unsafe markdown, external image loads, or script injection in rendered content (TB-01, TB-02) | Information disclosure, elevation of privilege; LLM output handling | High: rendering can execute or disclose data in a user's browser | Sanitize rendered text; restrict schemes and link targets; disallow remote images/active HTML; test XSS payloads and outbound image/link behavior | UI owner, Phase 5 | WAF/APIM may add defense in depth; output encoding remains required | Planned |
| T-07 | Query/response retention exposes personal or sensitive content (TB-01, TB-07) | Information disclosure; privacy risk | High: requested demo retention still lacks final policy/provider approval | Keep the global flag off until approval; use the 7-day configurable TTL; show notice and per-session opt-out; redact before persistence and fail closed; restrict access to the configured reviewer role; test off modes and synthetic sensitive values | Privacy owner, TBD; Phase 0b/6 | Managed identity, RBAC, Key Vault, monitored retention controls | Pending policy approval |
| T-08 | Denial-of-wallet or quota exhaustion from chat/embedding use (TB-02, TB-03) | Denial of service; resource abuse | High: unbounded requests can create cost or starve the user's deployments | Rate-limit, bound input/tokens/time/concurrency, apply gateway budgets, return explicit errors; test quota and timeout behavior | AI owner, Phase 4/6 | APIM quotas/rate limits and Azure Monitor alerts | Planned |
| T-09 | Poisoned or stale index content survives source updates/deletions (TB-04, TB-06) | Tampering, repudiation | Medium: stale evidence can produce incorrect answers | Store source hash, timestamps, parser version, and stable IDs; reconcile updates/deletions; test replay, changed content, and removed sources | Search/data owner, Phase 3 | Search RBAC, private endpoint, index separation | Planned |
| T-10 | Credentials or sensitive content leak through config, logs, traces, or test output (TB-07, TB-08) | Information disclosure | High: a leak can expose models, search data, or user content | Keep secrets outside git; use redaction; exclude content from spans; run secret scanning and synthetic canary checks; test logs/traces | Application/security owner, Phases 1/6 | Key Vault, managed identity, OIDC, RBAC | Partially mitigated: Phase 1 log controls in place; trace controls Phase 6 |
| T-11 | Unauthorized access to or tampering with Azure AI Search, including developer credential exposure (TB-06, TB-08) | Spoofing, tampering, information disclosure | High: index access can expose or alter evidence | Prefer Entra ID and least privilege; isolate test/demo indexes; protect developer credentials; review public endpoint/IP restrictions; use controlled access tests | Search owner, Phases 1/3/7 | Private endpoint, RBAC, private DNS, NSGs | Planned: no Search access exists yet; Phase 1 secret handling applies |
| T-12 | Queue replay or poison messages cause duplicate work or repeated source requests (TB-05) | Denial of service, tampering | Medium: queue delivery can repeat and exhaust limits | Make handlers idempotent; cap dequeue attempts; move poison items to a poison queue; track run completion; test duplicates and exhausted retries | Ingestion owner, Phase 2 | Storage Queue and scoped identity | Planned |
| T-13 | Dependency, action, or container-image compromise (TB-08, TB-09) | Tampering, elevation of privilege | Medium: build artifacts can introduce malicious code | Lock dependencies; pin GitHub Actions by SHA; scan dependencies/images; review provenance and permissions; test CI policy gates | Build/security owner, Phases 1/7 | OIDC, protected environments, ACR scanning and RBAC | Partially mitigated: Phase 1 locking, audits, and SHA pins in place; CI and image scanning not yet verified |
| T-14 | Sensitive or malicious input crosses session/user boundaries in a no-auth local demo (TB-01, TB-02) | Spoofing, information disclosure | Medium: local access is not equivalent to authenticated user isolation | Bind locally; avoid shared/public exposure; isolate session state; test concurrent sessions and UI history behavior | API/UI owner, Phases 4/5 | User authentication and authorization are design-only for Phase 7 | Planned |
| T-15 | Cloud identity, network, or private DNS assumptions permit unintended access (TB-09) | Spoofing, tampering, information disclosure | High: design assumptions can create an exposed or misrouted service | Verify SKU/network support, identity scope, private DNS, and egress paths; run static IaC checks and approved network-slice tests | Cloud owner, Phase 7 | Managed identity, RBAC, NSGs, private endpoints, private DNS | Planned |

## Approval and tracking

* Each high-rated threat must have a mitigation and test owner before the phase
  that implements it begins.
* Phase owners must attach test evidence and update status to mitigated,
  accepted, or deferred before their phase gate.
* A high-rated residual risk requires explicit acceptance by an accountable
  owner. No such acceptance is recorded yet.

## Phase 1 review

Reviewed on 2026-11-21 at the Phase 1 gate. Phase 1 added no new external data
flow, trust boundary, or user-content store. It added local MongoDB and Azurite
containers bound to loopback, a FastAPI health endpoint, a Next.js placeholder
page, and a GitHub Actions validation workflow. No threats were added or
re-rated.

| Threat | Phase 1 scope | Evidence | Remaining before closure |
|---|---|---|---|
| T-10 | Keep secrets out of git; redact logs; scan for secrets | `.gitignore` excludes `.env*` except the example. Redaction covers root handlers and uvicorn server/access loggers. `tests/unit/test_logging.py` checks labeled secrets, credentialed URIs, SAS signatures, bearer tokens, JWTs, cookies, email addresses, exception text, and access-log query strings. Gitleaks runs in CI. | First GitHub-hosted Gitleaks run; trace and span redaction plus canary checks in Phase 6. Redaction is pattern-based, so query and response content must never be logged. |
| T-11 | Developer credential handling only | No Azure AI Search credentials or client exist. Credentials stay in local environment configuration outside git. | Entra ID access, index isolation, and IP restriction tests in Phase 3; private endpoint design in Phase 7. |
| T-13 | Dependency and workflow supply chain | `uv.lock` and `package-lock.json` installed with `--locked` and `npm ci`. `pip-audit` and `npm audit` are clean locally. Actions are pinned to full SHAs, verified against upstream release tags. The workflow uses `contents: read` and `persist-credentials: false`. | First GitHub-hosted CI run, branch protection ([OPS-001](../operations/backlog.md)), the `uv` bootstrap is installed without a hash, and container image scanning when application images exist. |

Each threat's Phase 1 portion has the evidence listed above. The remaining
items belong to later phases or to the first GitHub-hosted CI run. The user
decides at the Phase 1 gate whether any of them must block closure.

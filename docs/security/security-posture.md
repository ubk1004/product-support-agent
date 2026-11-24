---
title: Product Support Agent Security Posture
description: Distinguishes controls planned for the local MVP from cloud controls that are design-only
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: concept
keywords:
  - security posture
  - local-first
  - Azure architecture
estimated_reading_time: 5
---

## Status

The Phase 0 direction is approved. Phase 1 implemented the baseline controls
listed under [Phase 1 implemented controls](#phase-1-implemented-controls);
every other local control remains planned and requires verification in Phases
2-6. Cloud controls are design-only unless a separately approved Phase 7
network-slice test explicitly exercises them.

## Phase 1 implemented controls

| Control | Implementation | Local evidence | Not yet verified |
|---|---|---|---|
| Log redaction | `RedactingFilter` and `JsonLogFormatter` on root handlers; uvicorn server and access loggers routed through them | Unit tests for labeled secrets, credentialed URIs, SAS signatures, bearer tokens, JWTs, cookies, email addresses, exception text, and uvicorn access logs; a live access-log check redacted query-string secrets | Not a general PII detector; traces are not instrumented until Phase 6 |
| Dependency locking and audit | `uv.lock` with `uv sync --locked`; `package-lock.json` with `npm ci`; `pip-audit` and `npm audit --audit-level=high` | Local runs reported no known vulnerabilities on 2026-11-21 | GitHub-hosted CI has not run |
| Static analysis | Ruff, strict mypy, Bandit, Biome, and TypeScript checks | Local and clean-clone runs pass | GitHub-hosted CI has not run |
| Secret scanning | Gitleaks in the validation workflow | Workflow authored | GitHub-hosted CI has not run |
| Workflow hardening | Actions pinned to full commit SHAs verified against release tags; `contents: read`; `persist-credentials: false` | SHAs checked against upstream tags on 2026-11-21 | Branch protection is pending ([OPS-001](../operations/backlog.md)) |
| Local exposure | MongoDB and Azurite ports bound to `127.0.0.1`; the API run command binds to `127.0.0.1` | Podman listener check on 2026-11-21 | MongoDB runs without authentication and relies on loopback binding |
| Retention off by default | `query_response_retention_enabled=false`; enabling it requires a reviewer role | Configuration unit tests | No retention feature exists yet |

## Phase 3 implemented controls

| Control | Implementation | Local evidence | Not yet verified |
|---|---|---|---|
| Source scope | Versioned source map; seeds validated against the host allowlist; no link or sitemap-index following | `test_phase_three_sources.py` | Live run pending authorization |
| robots.txt | RFC 9309 matcher with wildcards; fetched once per host per run; fails closed except on 404/410 | Robots and worker tests | Live hosts |
| Request limits | Per-run budget, 1-second spacing per host, 2 attempts per page, `Retry-After` cap, host abort on 429 | `test_phase_three_source_ingestion.py` | Live hosts |
| Idempotent refresh | Durable fetch state, 24-hour freshness skip, conditional GETs, body hash, single-runner lease | Resume, lost-state, ETag, and lease tests | MongoDB under concurrent runs |
| Protected content | Login-wall heuristic; protected pages skipped with a 30-day backoff and not stored | Heuristic and worker tests | Live pages |
| XML parsing | `defusedxml` with DTDs forbidden | Sitemap tests; Bandit clean | — |
| Coverage disclosure | Metadata-only API; server-side fetch from Next.js; fails safe to "assume nothing is covered" | Coverage tests; manual render of the available and unreachable states | Accessibility review in Phase 5 |

## Demo delivery mode

Per [ADR-0007](../architecture/decisions/adr-0007-demo-delivery-mode.md), the
demo enforces the guardrails in that ADR (no secrets in git, anonymous access
only, the source map with `robots.txt` and budgets, citation binding, retention
off, loopback binding, offline routine tests). Controls in the "Cloud target"
column below, and the production-only items in each phase of the
[implementation plan](../implementation-plan.md), are designed but not
performed. API keys from `.env` stand in for Entra ID, and public endpoints
stand in for private endpoints, for the local demo only.

## Control posture

| Control area | Local MVP: planned to demonstrate | Cloud target: design-only |
|---|---|---|
| Source access | Host allowlist, versioned source map, `robots.txt`, URL validation, no authentication, no redirects, bounded requests and downloads, durable fetch state | Scheduled Container Apps job; worker egress through approved NAT Gateway or firewall; host allowlist and stable egress |
| Protected resources | Skip 401/403, login redirects, and login-content responses; record minimal reason | Same application behavior plus private network controls where applicable |
| Retrieval and citations | Server-side evidence IDs and source URLs; reject citations not bound to retrieval | APIM and service identity controls do not replace application citation validation |
| Prompt injection | Treat retrieved text as data; restrict tools; validate tool inputs and model output | Same application controls with policy and monitoring integration |
| Secrets | Local environment/configuration outside source control; no credentials in fixtures, logs, or traces | Key Vault references and user-assigned managed identities, deployed and verified in an isolated test; GitHub Actions OIDC |
| Network isolation | Segmented Podman networks if validated; local demo bound to local access | VNet, subnets, NSGs, private endpoints/DNS, and NAT egress, deployed and verified in an isolated test; APIM is optional and was tested at the Developer tier |
| Search/data access | User-provided Azure AI Search; least-privilege Entra ID where supported; no shared production data | Cosmos DB or DocumentDB, Storage Queue, Search, Key Vault, and ACR private endpoints with private DNS, deployed and verified in an isolated test |
| Telemetry | OpenTelemetry-compatible, minimized metadata; query/response content is not retained | Azure Monitor and Log Analytics with approved retention and access controls |
| Supply chain | Dependency lock and scans, secret scanning, container scanning in CI | Pinned GitHub Actions, protected deployment environment, artifact provenance |
| User access | Local-only demo with no end-user authentication; no public exposure | User authentication and authorization remain a Phase 7 design decision |
| Cloud deployment | No application stack deployment | IaC and CI/CD definitions authored and validated; the stack was deployed once to an isolated test group |

## Required evidence

* Unit and integration tests must prove protected content is skipped, URLs are
  validated, citations resolve only to retrieved sources, and sensitive test
  values do not appear in logs or traces.
* Phase 0b must map each trust boundary and asset to a rated threat, mitigation,
  owner, and verifying test.
* Phase 7 checks must distinguish static IaC validation from deployed network
  evidence. The application stack remains undeployed.
* Live source, Foundry, Azure AI Search, and subscription tests require explicit
  approval and isolated resources. Routine CI uses fakes or emulators.

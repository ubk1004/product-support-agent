---
title: Product Support Agent Security Posture
description: Distinguishes controls planned for the local MVP from cloud controls that are design-only
author: Product Support Agent Team
ms.date: 2026-11-21
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

## Control posture

| Control area | Local MVP: planned to demonstrate | Cloud target: design-only |
|---|---|---|
| Source access | Host allowlist, URL validation, no authentication, redirect checks, bounded requests and downloads | Worker egress through approved NAT Gateway or firewall; host allowlist and stable egress |
| Protected resources | Skip 401/403, login redirects, and login-content responses; record minimal reason | Same application behavior plus private network controls where applicable |
| Retrieval and citations | Server-side evidence IDs and source URLs; reject citations not bound to retrieval | APIM and service identity controls do not replace application citation validation |
| Prompt injection | Treat retrieved text as data; restrict tools; validate tool inputs and model output | Same application controls with policy and monitoring integration |
| Secrets | Local environment/configuration outside source control; no credentials in fixtures, logs, or traces | Key Vault and managed identity where supported; GitHub Actions OIDC |
| Network isolation | Segmented Podman networks if validated; local demo bound to local access | VNet, subnets, NSGs, private endpoints/DNS, controlled egress, APIM |
| Search/data access | User-provided Azure AI Search; least-privilege Entra ID where supported; no shared production data | Private endpoint, RBAC, network restrictions, environment separation |
| Telemetry | OpenTelemetry-compatible, minimized metadata; `QUERY_RESPONSE_RETENTION_ENABLED` defaults off, with per-session opt-out and no content retention before privacy approval | Azure Monitor and Log Analytics with approved retention and access controls |
| Supply chain | Dependency lock and scans, secret scanning, container scanning in CI | Pinned GitHub Actions, protected deployment environment, artifact provenance |
| User access | Local-only demo with no end-user authentication; no public exposure | User authentication and authorization remain a Phase 7 design decision |
| Cloud deployment | No application stack deployment | IaC static validation only; application deployment is deferred |

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

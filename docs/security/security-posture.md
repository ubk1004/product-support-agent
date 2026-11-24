---
title: Product Support Agent Security Posture
description: The security controls implemented locally and in Azure, how each is verified, and what production still needs
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: concept
keywords:
  - security posture
  - Azure architecture
  - AI security
estimated_reading_time: 6
---

## Summary

The application treats every input it does not produce itself (documentation
pages, user questions, earlier conversation turns, and model output) as
untrusted. Its security rests on four things: anonymous, bounded access to an
explicit list of public sources; citations that the server, not the model,
controls; no storage of user content; and private networking with managed
identities in Azure.

The demo has no end-user sign-in. Locally it binds to `127.0.0.1`; in Azure the
web app is public. Do not expose either to real users or customer data until
the production controls at the end of this page are in place.

Threats and their ratings are in the [threat register](threat-register.md);
data handling is in the [privacy impact assessment](privacy-impact-assessment.md).

## Application controls

| Area | Control | Verified by |
|---|---|---|
| Source access | Anonymous HTTPS requests to allowlisted hosts from the versioned source map; redirects never followed; table-of-contents and sitemap links validated against the allowlist; sitemap indexes not followed | `tests/unit/test_phase_three_sources.py`, `test_phase_two_worker.py` |
| `robots.txt` | RFC 9309 matcher, fetched once per host per run; fails closed except on 404 or 410 | Robots and worker tests |
| Request limits | Run budget, 1-second spacing per host, two attempts per page, `Retry-After` cap, host abort on 429, product fail-fast, one run at a time | `test_phase_three_source_ingestion.py` |
| Protected content | 401, 403, sign-in redirects, and sign-in pages are skipped with a 30-day backoff and never stored | Heuristic and worker tests |
| Untrusted XML and size | `defusedxml` with DTDs forbidden; 4 MiB document limit; 512 KiB `robots.txt` limit | Sitemap and normalisation tests; Bandit |
| Prompt injection | Retrieved text and history handled as data; two read-only tools; citation markers and URLs stripped from history; content-filter responses become the standard refusal | Agent and chat tests, including an injected "print this link" case |
| Citations | Evidence IDs resolved to stored URLs on the server; unknown and forged IDs dropped; model URLs removed; no valid citation means refusal | Citation-binding tests and the offline evaluation |
| Input limits | Web route: 48,000-character body, 35-second timeout. API: 2,000-character question, 8 earlier turns of up to 4,000 characters, 4 tool calls, 30-second timeout, 4 concurrent requests | API validation tests (`test_chat.py`); the web route is checked by TypeScript and Biome only |
| Rendering | Answers shown as plain text; links only from the citations array | Code review and the recorded demo; the web app has no unit tests |
| Product filter | Product IDs must be in the demo catalog | Chat tests |
| Logging | One redaction filter on console and exported logs for secrets, credentialed URIs, SAS signatures, bearer tokens, JWTs, cookies, and e-mail addresses; access-log query strings redacted | `tests/unit/test_logging.py` |
| Telemetry | Prompt and response capture forced off; client address and user agent removed from spans; health checks not traced | Telemetry tests |
| Retention | Query and response retention is not built; the setting defaults to off and enabling it requires a reviewer role | Configuration tests |

## Platform controls

| Area | Local | Azure |
|---|---|---|
| Exposure | All ports bound to `127.0.0.1` | Web app public; API internal ingress only; API Management public with a subscription key when deployed |
| Network | Compose network | Virtual network with NSG per subnet; NAT gateway egress; private endpoints and private DNS for the Mongo-compatible store, Storage, Azure AI Search, Key Vault, and the registry, all with public access disabled |
| Secrets | `.env`, git-ignored | Key Vault (RBAC, public access disabled), read by managed identity through Container Apps secret references |
| Service identity | Keys and connection strings in `.env`; MongoDB without authentication on loopback | User-assigned identities for the API, the ingestion job, and image pulls, each with roles scoped to one resource; Storage shared keys disabled |
| AI services | Keys for Foundry and Search | Keys from Key Vault. Search is private; Foundry keeps its public endpoint and is reached through the NAT gateway |
| Gateway | Not used | Classic API Management, external VNet mode: subscription key, 30 calls per minute per key, 48 KB body limit, only the chat and coverage operations; request logs without headers, bodies, or client IPs |
| Images | Built locally | Non-root images in a private Premium registry with no admin user, tagged with the commit SHA |

## Delivery controls

* **Dependencies:** `uv.lock` and `package-lock.json`, installed with
  `uv sync --locked` and `npm ci`; `pip-audit` and `npm audit` in CI; Dependabot
  for Python, npm, and GitHub Actions.
* **Static analysis:** Ruff, strict mypy, Bandit, Biome, TypeScript, CodeQL, and
  actionlint.
* **Secrets:** gitleaks on every pull request.
* **Workflows:** actions pinned to commit SHAs; `contents: read` by default;
  `persist-credentials: false`; OIDC sign-in with one federated credential per
  GitHub environment and no client secret; infrastructure deployed only by
  manual dispatch after a what-if; placeholder parameters refused before
  sign-in.
* **Tests:** offline by default. Tests that reach Azure are marked `live` and
  run only on request.

## Known weaknesses

These are accepted for the demo and tracked in the
[production gap register](../operations/production-gap-register.md):

* No end-user authentication or per-user isolation.
* Keys rather than Entra ID for Azure AI Search and Foundry; Foundry's endpoint
  is public.
* Local MongoDB has no authentication and relies on loopback binding.
* API Management protects API clients with a subscription key only, and the web
  app calls the API directly rather than through the gateway.
* No DAST, IAST, image scanning, SBOM, or image signing.
* Branch protection and required reviewers are repository settings that must be
  configured; they are not in code.
* No alerts, so an attack or a spend spike is visible only by looking at
  telemetry.

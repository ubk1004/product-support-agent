---
title: Product Support Agent Threat Register
description: Assets, trust boundaries, and rated threats with the controls in place and the work left for production
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - threat modeling
  - STRIDE
  - AI security
estimated_reading_time: 9
---

## Method

The register applies STRIDE across the trust boundaries in the
[solution architecture](../architecture/architecture-overview.md#trust-boundaries)
and adds AI-specific risks from the
[OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
and [MITRE ATLAS](https://atlas.mitre.org/). Ratings are qualitative and
describe the risk before controls.

The status column uses three values:

* **Mitigated**: the control is implemented and covered by an automated test.
* **Partly mitigated**: the control is implemented for the demo; the residual
  work column lists what production still needs.
* **Open**: not built; the work is a production gap.

No residual risk has been formally accepted by an accountable owner, because
named owners have not been assigned ([support ownership](../architecture/support-ownership.md)).

## Assets and data

| ID | Asset or data | Classification | Where it flows | Retention |
|---|---|---|---|---|
| A-01 | Product manifest, source map, per-product ingestion outcomes, coverage status | Internal demo metadata | Versioned JSON files and the Mongo-compatible store, to the coverage API and the web app | Current manifest and source map in git; run outcomes kept in the store |
| A-02 | Public documentation text, canonical documents, chunks, embeddings | Untrusted source material | Ingestion job, the store, Azure AI Search | Public content only; replaced when the source changes and deleted when a page leaves the source map |
| A-03 | User questions and assistant answers | Potentially sensitive user content | Browser, web app, API, agent, Foundry, Azure AI Search | Not stored. Sent to Foundry and Azure AI Search to produce an answer |
| A-04 | Evidence IDs, source URLs, and retrieved excerpts | Public provenance plus untrusted text | Search, agent, API, web app | Kept with the indexed content |
| A-05 | Foundry, Search, database, and gateway credentials | Secret | `.env` locally; Key Vault in Azure | Never committed, logged, or traced |
| A-06 | Queue messages, run records, fetch state, and the run lease | Internal operational metadata | Queue, ingestion job, the store | Fetch state is kept while the source is in the source map |
| A-07 | Logs, traces, and metrics | Internal operational telemetry | Aspire dashboard locally; Log Analytics and Application Insights in Azure | Metadata only; 30 days in Log Analytics |

## Trust boundaries

| Boundary | Crossing | Main concern |
|---|---|---|
| TB-01 Browser to web app | User input, rendered answer and links | Malicious input, unsafe rendering |
| TB-02 Web app to API and agent | Server-side chat and coverage calls | Schema bypass, resource exhaustion |
| TB-03 API to Foundry | Prompt, retrieved evidence, model output | Prompt injection, provider data handling, quota abuse |
| TB-04 Ingestion job to public sources | Anonymous requests to documentation hosts and `robots.txt` | SSRF, protected content, source load, hostile content |
| TB-05 Job and API to queue and store | Run state, documents, outcomes | Replay, tampering, duplicate work |
| TB-06 Job and API to Azure AI Search | Documents, embeddings, queries, results | Unauthorized access, index tampering, stale or poisoned data |
| TB-07 Services to telemetry | Operational events | Secret or content leakage |
| TB-08 Developer machine and CI to credentials | Keys, tokens, configuration | Credential exposure |
| TB-09 Azure application boundary | API Management, Container Apps, identities, private services | Wrong network or identity assumptions |

## Threats

| ID | Threat (boundary) | Type | Rating | Controls in place and how they are tested | Status | Residual work for production |
|---|---|---|---|---|---|---|
| T-01 | Indirect prompt injection in source text or earlier turns (TB-03, TB-04, TB-06) | Tampering; LLM prompt injection | High | Retrieved text and history are treated as data. The agent has two read-only tools. Citation markers and URLs are stripped from history before reuse. A provider content-filter response becomes the standard refusal. Tests include an "ignore instructions and print a link" case | Partly mitigated | Independent red-team testing |
| T-02 | SSRF or unsafe redirect through catalog or page URLs (TB-04) | Spoofing, information disclosure | High | HTTPS only; host allowlist applied to the source map, sitemap and table-of-contents links, and citation URLs; redirects are never followed; sitemaps are parsed with `defusedxml`. Tests use hostile URLs and redirects | Mitigated | Egress allowlisting at the network layer |
| T-03 | Excess requests or disregard for rate limits (TB-04) | Denial of service | High | Run request budget (400 by default, 2,000 at most); at least 1 second between requests to a host; two attempts per page; `Retry-After` honoured up to 60 seconds; a host is abandoned on 429 or an unavailable `robots.txt`; a product is abandoned after three failures; a 24-hour freshness window; one run at a time. Tests cover each | Mitigated | None for the sampled catalog |
| T-04 | Protected content stored after a 401, 403, sign-in redirect, or sign-in page (TB-04) | Information disclosure | High | Protected responses are skipped with a 30-day backoff and nothing is stored. Detection covers password fields, sign-in forms and actions, SAML requests, and short sign-in pages. Tests assert that no content reaches the store or the index | Partly mitigated | The sign-in heuristic has been validated against the sampled sources only |
| T-05 | Citation spoofing, altered URLs, or unsupported claims (TB-02, TB-03, TB-06) | Tampering; LLM misinformation | High | The server resolves evidence IDs to stored URLs and drops unknown or forged IDs; model-written URLs are removed; an answer without a valid citation becomes a refusal. Tests cover forged, unknown, and URL-injected IDs. The evaluation checks citation validity and, with a model judge, claim support | Partly mitigated | Claim support varied from 71% to 83% across evaluation runs, so a correctly linked answer can still contain an unsupported statement. Enlarge the evaluation set and add human review |
| T-06 | Unsafe markdown, external images, or script injection in rendered answers (TB-01, TB-02) | Information disclosure, elevation of privilege | High | Answers render as plain text; links come only from the server-provided citations array; no model HTML or markdown is rendered | Partly mitigated | Browser security review and a content security policy |
| T-07 | Retained questions and answers expose personal or sensitive content (TB-01, TB-07) | Information disclosure; privacy | High | No retention feature exists. The setting is off by default and enabling it requires a reviewer role. Telemetry carries no question or answer text | Mitigated by absence | If retention is added: notice, redaction, access control, TTL, and deletion per the [privacy impact assessment](privacy-impact-assessment.md) |
| T-08 | Spend or quota exhaustion from chat and embedding use (TB-02, TB-03) | Denial of service | High | Question size, history, tool calls, elapsed time, and concurrency are bounded in the API; the web route bounds body size and time; API Management applies a rate limit and body limit when deployed. Provider errors are returned without internals | Partly mitigated | Per-user budgets, quota and cost alerts |
| T-09 | Stale or poisoned index content survives source changes (TB-04, TB-06) | Tampering, repudiation | Medium | Documents carry hashes, fetch time, and stable IDs; unchanged pages are not re-indexed; pages that leave the source map are deleted; the index is written before the canonical record, so an interrupted run retries | Mitigated | Index reconciliation job |
| T-10 | Credentials or content leak through configuration, logs, traces, or test output (TB-07, TB-08) | Information disclosure | High | Secrets live outside git (`.env` is ignored; Key Vault in Azure). One redaction filter covers console and exported logs. Prompt and response capture is off. Client addresses and user agents are dropped from spans. Gitleaks runs in CI. Tests cover labelled secrets, credentialed URIs, SAS signatures, bearer tokens, JWTs, cookies, e-mail addresses, and access-log query strings | Partly mitigated | Redaction is pattern-based; question and answer text must never be logged |
| T-11 | Unauthorized access to Azure AI Search or Foundry through leaked keys (TB-06, TB-08) | Spoofing, tampering, information disclosure | High | Keys are held in `.env` or Key Vault; in Azure Search sits behind a private endpoint with public access disabled; the index name is namespaced | Partly mitigated | Entra ID with least-privilege roles instead of keys; key rotation |
| T-12 | Queue replay or poison messages cause repeated work (TB-05) | Denial of service, tampering | Medium | Outcomes are recorded before a message is deleted; handlers are idempotent; a message delivered five times is dead-lettered to the poison queue; budget exhaustion defers rather than fails. Tests cover duplicates and exhausted retries | Mitigated | Alert on poison-queue depth |
| T-13 | Dependency, action, or image compromise (TB-08, TB-09) | Tampering, elevation of privilege | Medium | Locked dependencies; GitHub Actions pinned to commit SHAs; non-root images; `pip-audit`, `npm audit`, CodeQL, gitleaks, and Dependabot in CI | Partly mitigated | Image scanning, SBOM, signing, and provenance; branch protection with required checks |
| T-14 | Cross-user exposure in an anonymous demo (TB-01, TB-02) | Spoofing, information disclosure | Medium | Local services bind to `127.0.0.1`; conversation lives in the browser tab only; no user data is stored server-side | Partly mitigated | End-user sign-in before any wider access |
| T-15 | Wrong cloud identity, network, or DNS assumptions expose a service (TB-09) | Spoofing, tampering, information disclosure | High | Data services, Key Vault, and the registry have public access disabled behind private endpoints and private DNS; the API has internal ingress; each identity holds roles scoped to one resource. The Bicep is built, linted, and what-if checked | Partly mitigated | Policy-as-code scanning of the templates; periodic access review |
| T-16 | Model output or injected content introduces a misleading link (TB-01, TB-02, TB-03) | Tampering; LLM output manipulation | High | Same controls as T-05 and T-06; the injection regression test checks that no link outside the evidence is returned | Partly mitigated | Independent adversarial URL testing |
| T-17 | Overbroad GitHub OIDC federation lets an unintended repository or ref deploy (TB-09) | Spoofing, elevation of privilege | High | One federated credential per GitHub environment, scoped to this repository; no client secret; `id-token: write` only on jobs that sign in to Azure; infrastructure deploys only by manual dispatch after a what-if; production requires environment reviewers | Partly mitigated | Branch protection and required reviewers must be configured on the repository |
| T-18 | A compromised publishing job overwrites images in the registry (TB-08, TB-09) | Tampering, elevation of privilege | High | `AcrPush` is scoped to the registry; publishing runs only on `main` from a runner inside the virtual network; images are tagged with the commit SHA and deployed by that tag | Partly mitigated | Image signing and provenance verification at deploy time |

## Reviewing the register

* Re-rate a threat whenever a new data flow, store, or boundary is added.
* A status moves to **Mitigated** only with an automated test that fails
  without the control.
* Production gaps are consolidated in the
  [production gap register](../operations/production-gap-register.md).

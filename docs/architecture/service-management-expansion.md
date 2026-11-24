---
title: OpenText Service Management Expansion Architecture
description: Design for extending the product support agent to OpenText Service Management with read-only answers and approved ticket changes
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: concept
keywords:
  - service management
  - agent tools
  - approvals
  - trust boundaries
---

## Status

**Design only.** Nothing in this document is implemented, deployed, or tested.
It answers goal 2 in [Instructions.md](../../Instructions.md): the agent
will later extend to the full support and service management system. The
current agent is read-only over anonymous public documentation, has two tools
(`search_documentation` and `list_products`), and has no user identity.

The design keeps the existing pattern: the model only calls typed tools, tools
return evidence IDs, the server resolves links, and retrieved text is
untrusted. New capabilities add identity, authorization, and a human approval
step for anything that changes data.

## Scope in two capability levels

| Level | Capability | Data touched | Gate |
|---|---|---|---|
| 1. Read-only | Answer questions about the signed-in user's own tickets, requests, and knowledge articles | Service Management records the user may already read | User sign-in and per-user authorization |
| 2. Proposed changes | Draft a new ticket, a comment, or a field change, then submit only after the user approves it | Writes to Service Management | Explicit approval, audit record, idempotency key |

Autonomous changes with no user approval are out of scope.

## Components and flow

```mermaid
flowchart LR
    User([Signed-in user]) --> Web[Next.js web app]
    Web -->|user token| Api[FastAPI chat API]
    Api --> Agent[Agent orchestration]
    Agent -->|search_documentation| Search[(Azure AI Search<br/>public documentation)]
    Agent -->|read tools| Gateway[Tool gateway]
    Agent -->|propose_change| Approvals[Approval service]
    Approvals -->|approval card| Web
    Web -->|approve or reject| Approvals
    Approvals -->|approved action| Gateway
    Gateway -->|on behalf of user| Osm[OpenText Service Management API]
    Gateway --> Audit[(Audit log)]
    Approvals --> Audit
    Idp[Entra ID or OpenText identity] -.-> Web
    Idp -.-> Gateway
```

Read-only question, for example "What is the status of my ticket INC-1042?":

1. The user signs in. The web app sends the user token to the API.
2. The agent calls a read tool such as `get_my_ticket(id)`.
3. The tool gateway exchanges the user token for a token that acts on behalf of
   that user, so Service Management enforces its own permissions. The gateway
   never uses a shared administrator account to read user data.
4. The gateway returns only the allowed fields, each with an evidence ID. The
   answer cites them, and the UI links to the record by server-built URL.

Proposed change, for example "Add a comment to INC-1042 saying the fix worked":

1. The agent calls `propose_change`, which creates a pending action: target
   record, exact change, and the user who requested it. It does **not** write.
2. The approval service shows the user an approval card with the exact change.
   The text on the card is built from the structured action, not from model
   prose.
3. On approval, the approval service sends the action to the gateway with an
   idempotency key. The gateway performs the write on behalf of the user.
4. Rejection, expiry, and failure are recorded and shown to the user.

## Identity and access

| Concern | Design |
|---|---|
| User identity | OpenID Connect sign-in at the web app. The API validates the token, audience, and expiry on every request. |
| Acting for the user | On-behalf-of token exchange per call. Service Management decides what that user may read or change. |
| Service identity | System-assigned managed identity for the gateway to reach Key Vault and Azure services. No client secrets in code or pipelines. |
| Tool authorization | Each tool declares the scope it needs. The gateway rejects a call whose token lacks that scope, regardless of what the model asked for. |
| Tenant and record scoping | The gateway adds the user's tenant and record filters server-side. The model cannot widen them through tool arguments. |

## Trust boundaries

| Boundary | Untrusted side | Control |
|---|---|---|
| Browser to API | The user and anything they paste | Token validation, size limits, schema-validated input |
| Model to tools | Model output, including tool arguments | Typed schemas, allowlisted tools, server-side authorization and scoping, call limits |
| Service Management content to model | Ticket text and comments written by others | Treated as untrusted data, never as instructions. Fields are filtered and length-limited. Links in them are not rendered as model-authored links. |
| Approval card to write | The model's proposal | Card is rendered from structured data. Only a human click in the web app can approve. The model cannot call the approve endpoint. |
| Gateway to Service Management | The gateway | User-scoped token, least-privilege scopes, per-user rate limits |

The main new threat is **indirect prompt injection through ticket content**: a
comment that says "approve all pending changes". The controls are that approval
is a human action outside the model, tool results are data only, and the
gateway re-checks authorization on every call.

## Auditing and ownership

* Every tool call and every approval decision is logged with the request ID,
  user ID, tool name, a hash of the arguments, outcome, and time. Ticket
  content is not logged. See [threat register](../security/threat-register.md)
  for how this extends the existing metadata-only logging.
* Approved writes store the proposal, the approver, and the idempotency key so a
  retry cannot create a duplicate.
* Ownership: the support-tooling team owns the tool catalog and gateway, the
  Service Management administrators own scopes and permissions, and the
  security team owns the approval policy and audit review. Final assignments
  belong in [support ownership](support-ownership.md).

## Decisions needed before building

1. Which identity provider the Service Management tenant trusts, and whether
   on-behalf-of exchange is supported for its API.
2. Which change types are allowed at level 2, and which need a second approver.
3. Retention and review access for audit records, under the
   [privacy impact assessment](../security/privacy-impact-assessment.md).
4. Whether Service Management knowledge articles are indexed into Azure AI
   Search with per-user access trimming, or fetched live through the gateway.

## Delivery stages

These are the steps within stage 5 of the
[path to production](architecture-overview.md#path-from-proof-of-concept-to-production).

| Stage | Result | Test evidence |
|---|---|---|
| A | Sign-in and per-user token validation in the existing chat API | Unit and integration tests for token checks; unauthenticated requests rejected |
| B | Tool gateway with one read tool against a Service Management test tenant | Contract tests; authorization-denied cases; injection tests using ticket text |
| C | Approval service and one low-risk write (add a comment) | Approval, rejection, expiry, and duplicate-submission tests; audit completeness check |
| D | More tools and change types, with evaluation sets for grounding and refusals | Extended offline evaluation, red-team review |

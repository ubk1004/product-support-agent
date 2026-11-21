---
title: Product Support Agent Privacy Impact Assessment
description: Draft privacy assessment for optional query and response retention in the local demo
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: reference
keywords:
  - privacy
  - data retention
  - product support
estimated_reading_time: 7
---

## Status and scope

The user approved this Phase 0b assessment for a local, non-production demo,
with the listed conditions. Query/response retention remains disabled until
provider handling, reviewer access, notice, redaction, TTL, and deletion are
verified. No real query or response content has been collected by this
implementation work.

## Purpose and data flow

The proposed purpose is limited to reviewing demo answer quality, investigating
reported failures, and identifying abuse attempts. It is not approval for
production analytics, marketing, user profiling, or unrelated model training.

When enabled after approval, a restricted MongoDB collection may contain:

* A redacted query and assistant response
* A pseudonymous session/run identifier and timestamp
* Retrieved evidence IDs and source URLs needed to verify citations
* Model deployment identifier and non-sensitive operational status

Do not store secrets, credentials, raw retrieved source text, browser identifiers,
or personal identifiers beyond what is necessary for the approved purpose.
OpenTelemetry logs and traces remain content-free.

The query may also be sent to the user's LiteLLM and Foundry deployments to
generate an answer. Their data handling, location, and retention settings must
be verified separately. Local application retention controls do not control
provider-side processing.

## Proposed controls

| Control | Proposed behavior | Approval status |
|---|---|---|
| Global feature flag | `QUERY_RESPONSE_RETENTION_ENABLED` defaults to `false`; an operator may enable it only after policy and provider-handling approval. Setting it to `false` immediately stops new retention writes. | Proposed |
| Session choice | When global retention is enabled, show a clear notice before each session. Retention is on for the session unless the user opts out. | User-selected; implementation pending |
| Purpose limitation | Use retained content only for the demo-quality, troubleshooting, and safety-review purposes stated in the notice. | Proposed |
| Redaction | Redact detected secrets and sensitive personal data before persistence. If redaction fails or its result is uncertain, do not retain the content; record only a non-sensitive failure reason. | User-selected; implementation pending |
| Access | Restrict the local store to a parameterized reviewer role, `QUERY_REVIEWER_ROLE`, and local database/operating-system access. Do not expose retained content through the chat API or public network. The role-to-identity binding is still required. | User-selected role model; identity binding pending |
| Retention period | Set `QUERY_RESPONSE_RETENTION_DAYS` to a default of 7 days. Validate it as a positive integer; changing the approved duration requires a policy update. Apply an automatic TTL and a documented deletion command. | User-selected; implementation pending |
| Deletion | Support deletion by session/run identifier and deletion of all retained demo content. Turning the flag off stops future writes but does not by itself delete prior records. | Proposed |
| Provider handling | Verify Foundry/LiteLLM service settings and disclose that requests are sent to the user's configured deployments. Keep retention disabled until provider handling and residency are verified. | User-selected; verification required |
| Incident response | Disable the global flag, preserve only necessary security metadata, restrict access, notify the accountable owner, and delete affected content when instructed. Named owners and escalation contacts are not assigned. | Owner assignment required |

## Draft user notice

> This local demo may retain a redacted copy of your question and the assistant's
> answer for demo quality and safety review for up to **[configured number of
> days]** days. Do not enter personal information, customer information,
> credentials, or confidential content. Retention is on for this session unless
> you opt out. Your question is also sent to the configured Microsoft Foundry
> deployment to generate an answer.

The notice must be reviewed and finalized before retention is enabled. Confirm
whether an explicit consent action is required for the intended demo audience.

## Data subject, access, and retention decisions

* Data subjects are people using the local demo; the exact audience is not yet
  named.
* No end-user authentication is planned for the local MVP. Restrict access at
  the operating-system and database boundary and do not expose the demo beyond
  local use.
* The user selected a parameterized 7-day retention period and a
  parameterized reviewer role. A role-to-identity binding, legal/privacy
  approval, final notice wording, and deletion service level remain open.
* Do not use retained content to train or fine-tune models.
* Use synthetic or explicitly approved test content until all required policy
  approvals are recorded.

## Risk and residual limitations

Redaction can miss sensitive content. A local demo can still be accessed by
other users of the same machine or by a configured provider. The opt-out and
global flag do not replace notice, access control, TTL enforcement, deletion
tests, or provider data-handling review. Retention remains disabled until these
controls are specified and approved.

## User approval checklist

Before enabling retention, approve:

1. Approve the 7-day default, parameter behavior, and deletion timing
2. Bind `QUERY_REVIEWER_ROLE` to approved reviewer identities and database access
3. Approve the notice and opt-out behavior
4. Approve redaction scope and fail-closed behavior
5. Verify Foundry/LiteLLM data-handling and residency settings
6. Assign the incident owner and user-contact process

The assessment must be approved before any real user query or response content
is retained.

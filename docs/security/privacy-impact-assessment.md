---
title: Product Support Agent Privacy Impact Assessment
description: What personal data the demo handles, where it goes, and what must be decided before any retention of user content
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - privacy
  - data retention
  - product support
estimated_reading_time: 5
---

## Summary

The demo does not store questions or answers. It sends them to two Azure
services to produce an answer, and it keeps nothing afterwards. Telemetry
contains no question or answer text. The original brief asks for all queries
and responses to be retained for later review; that feature is **not built**
and is blocked until the decisions below are made.

## Data the system handles

| Data | Personal data? | Where it goes | Kept? |
|---|---|---|---|
| Question typed by the user | Possibly, if the user types it | Browser, web app, API, Azure AI Search (as the search query and its embedding), Microsoft Foundry | No |
| Answer and citations | Not unless echoed from the question | Same path back to the browser | No |
| Conversation so far (up to 8 earlier turns) | Possibly | Held in the browser tab and sent with each question; discarded when the tab closes | No |
| Documentation text, product names, URLs | No; public content | Mongo-compatible store, Azure AI Search | Yes |
| Run records, fetch state, coverage | No; product IDs, public URLs, counts, outcomes, timestamps | Store, queue | Yes |
| Logs, traces, metrics | No question or answer text; request IDs, outcomes, durations, token counts | Aspire locally; Log Analytics and Application Insights in Azure (30-day retention) | Yes, as metadata |

The web app and API set no cookies and keep no user identifier. Client
addresses and user agents are removed from server spans, and API Management
logs omit headers, bodies, and client IPs.

## Processing by Azure services

A question is processed by Azure AI Search and by Foundry in the configured
region. In Azure the Foundry deployments use the GlobalStandard SKU, which can
process prompts in any Azure region, so it gives no data-residency guarantee. A
deployment type with a regional or data-zone boundary is needed where residency
matters. Provider-side logging and retention follow the settings of the
customer's Foundry and Search resources, and the application does not control
them.

The application tells users nothing about this today. Before real users:
publish a notice that states what is sent to the model provider, ask users not
to enter personal, customer, or confidential data, and confirm the provider's
data-handling terms.

## Retention of questions and answers (not built)

Settings exist so that the feature can be added safely
(`PRODUCT_SUPPORT_QUERY_RESPONSE_RETENTION_ENABLED`, `PRODUCT_SUPPORT_QUERY_RESPONSE_RETENTION_DAYS`
defaulting to 7, and `PRODUCT_SUPPORT_QUERY_REVIEWER_ROLE`, which is required
when retention is enabled). No code writes or reads retained content.

Do not build it until all of the following are decided and recorded:

| Decision | Requirement |
|---|---|
| Purpose | Limited to reviewing answer quality, investigating failures, and detecting abuse; no profiling, marketing, or model training |
| Notice and choice | A notice before the first question and a per-session opt-out; confirm whether explicit consent is required for the audience |
| Content | Redacted question and answer, a pseudonymous session ID, timestamp, evidence IDs and URLs, deployment name, and outcome. No secrets, raw retrieved text, or browser identifiers |
| Redaction | Applied before persistence; if redaction fails or is uncertain, store nothing and record only a failure reason |
| Access | A named reviewer role bound to identities, through an access-controlled collection that the chat API cannot read |
| Retention period | A positive period with automatic expiry (the setting defaults to 7 days) |
| Deletion | By session or run, and for all retained content; turning the flag off stops new writes but does not delete existing records |
| Provider handling | Foundry and Search retention and residency settings reviewed |
| Incident handling | A named owner and a contact process |

Until then, use only synthetic or explicitly approved content in testing.

## Residual risks

* Users can type personal data into a question. It reaches the model provider
  even though the application stores nothing.
* Redaction is pattern-based and can miss sensitive content; the safeguard is
  that question and answer text are never logged or traced.
* A person with access to the demo machine or the Azure subscription can see
  what those systems keep, such as the Foundry provider's own logs.
* Named privacy and incident owners are not assigned
  ([support ownership](../architecture/support-ownership.md)).

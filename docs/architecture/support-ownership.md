---
title: Product Support Agent Support Ownership
description: Proposed responsibility and escalation outline for the MVP and later cloud design
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: reference
keywords:
  - support ownership
  - RACI
  - operations
estimated_reading_time: 4
---

## Status

This Phase 0 RACI outline is proposed. Named owners, coverage hours, escalation
targets, and production support commitments have not been approved. The local
demo is not a production service.

## Roles

| Role | Proposed responsibility |
|---|---|
| Product owner / demo sponsor | Approves user outcomes, scope, data handling, phase gates, and demo catalog |
| Application maintainer | Owns code, local runbook, release checks, and defect triage |
| Ingestion and data owner | Owns source policy, manifest, ingestion outcomes, schema, and index freshness |
| AI and evaluation owner | Owns gateway configuration, answer quality, citations, evaluation set, and model limits |
| Privacy and security reviewer | Approves telemetry and retention, reviews threat register, and confirms incident handling |
| Cloud platform owner | Owns Azure subscription, network-slice approval, IaC, and cloud identity/security design |
| Demo operator | Confirms local prerequisites, service health, access to user-provided services, and demo readiness |

All roles except the product owner / demo sponsor are unassigned. One person may
hold multiple roles for the MVP, but the responsibilities must remain explicit.

## Responsibility outline

| Activity | Accountable | Responsible | Consulted |
|---|---|---|---|
| Approve product tasks, 100-product sample, and phase gates | Product owner | Product owner | Application maintainer, AI owner |
| Approve source access and request budgets | Product owner | Ingestion and data owner | Privacy/security reviewer |
| Maintain ingestion and search index | Ingestion and data owner | Application maintainer | AI owner |
| Maintain the source map and weekly ingestion schedule; review run reports | Ingestion and data owner | Demo operator | Product owner |
| Approve resets with `--force` and changes to the source map | Product owner | Ingestion and data owner | Privacy/security reviewer |
| Review answer quality and evaluation thresholds | Product owner | AI and evaluation owner | Application maintainer |
| Approve query/response telemetry policy | Privacy owner, TBD | Application maintainer | Product owner, security reviewer |
| Triage local demo failures | Product owner | Application maintainer and demo operator | Ingestion/data owner, AI owner |
| Approve Azure network-slice deployment | Cloud subscription owner, TBD | Cloud platform owner | Security reviewer, product owner |
| Respond to a production incident | Not assigned | Not assigned | Production readiness is deferred |

## Escalation limits

* Stop ingestion on unexpected authentication, redirect, rate-limit, or
  response-size behavior. Do not work around access restrictions. The worker
  backs off automatically. Do not clear its fetch state or use `--force` to
  retry a protected or rate-limited source without approval.
* Stop the demo if source citations cannot be resolved to retrieved evidence or
  if logs expose secrets or user content.
* Escalate quota, credential, service availability, and network issues to the
  owner of the user-provided service; do not alter subscriptions or credentials.
* No on-call, uptime, incident response, or production support commitment exists
  until a later phase assigns owners and approves operating procedures.

---
title: ADR-0005 User Interface and Backend Technology
description: Records the approved React and Next.js frontend and Python backend choices
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: decision
keywords:
  - ADR
  - Next.js
  - Python
  - Microsoft Agent Framework
---

## Status

Accepted by the user for Phase 1.

## Context

The project needs a maintainable chat interface and a backend that hosts the
API, ingestion services, and agent orchestration. The user selected React with
Next.js and TypeScript instead of Chainlit. Python was selected for FastAPI and
Microsoft Agent Framework.

## Decision

* Build the user interface with React, Next.js App Router, and TypeScript.
* Build the API and agent services in Python, using FastAPI and Microsoft Agent
  Framework.
* Keep the UI and backend as separate applications that communicate through an
  explicit API contract. Read-only views such as demo coverage are rendered by
  Next.js Server Components that call FastAPI from the server, using
  `PRODUCT_SUPPORT_API_BASE_URL`. The browser does not call FastAPI directly for
  these views, so the API needs no CORS policy and stays on loopback. The chat
  transport is decided in Phase 5.
* Keep UI state transient and do not display past searches. Query/response
  retention remains disabled until its privacy and provider-handling gates pass.
* Use Node.js 20.9 or later for the Next.js toolchain. Pin JavaScript
  dependencies in the npm lockfile and Python dependencies in `uv.lock`.

## Rationale

The user explicitly chose React/Next.js over Chainlit. The Chainlit repository
was archived and made read-only by its owner on October 15, 2026. Next.js
supplies a TypeScript-capable application framework with an App Router,
linting, build, and server-start workflows. Its official installation guide
sets Node.js 20.9 as the minimum, which adds a separate runtime and
package-management workflow to the Python backend.

Microsoft Agent Framework supports both .NET and Python. Python is selected
because it matches the approved FastAPI API and ingestion-service language and
keeps agent code in the same backend ecosystem. This is a consistency choice,
not a claim that C# is unsupported or incapable.

## Alternatives considered

* Chainlit: not selected after the user chose React/Next.js. Its upstream
  repository is archived and read-only, increasing maintenance risk for a new
  UI foundation.
* Streamlit: provides chat messages, chat input, status containers, and
  streaming, but the user selected a TypeScript React frontend rather than a
  Python-rendered UI.
* C# with ASP.NET Core and Microsoft Agent Framework: technically viable, but
  it would diverge from the approved Python FastAPI and ingestion stack.

## Consequences

* Frontend and backend require independent dependency manifests, lockfiles,
  tests, linting, and build checks.
* Node.js is required in addition to Python and Podman for local development.
* The browser-facing UI and API boundary must be secured and tested separately.
* Microsoft Agent Framework and model integration remain outside the Phase 1
  foundation. Their package and API usage will be selected and verified when
  the approved agent phase begins.
* No application service is deployed to Azure as part of this decision.

## References

* [Next.js installation and system requirements](https://nextjs.org/docs/app/getting-started/installation)
* [Microsoft Agent Framework overview](https://learn.microsoft.com/agent-framework/overview/)
* [Chainlit upstream repository](https://github.com/Chainlit/chainlit)
* [Streamlit chat elements](https://docs.streamlit.io/develop/api-reference/chat)

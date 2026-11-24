---
title: ADR-0005 User Interface and Backend Technology
description: Next.js with TypeScript for the interface; Python, FastAPI, and Microsoft Agent Framework for the backend
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - Next.js
  - FastAPI
  - Microsoft Agent Framework
---

## Status

Accepted.

## Context

The brief asks for a TypeScript React/Next.js chat interface, a Python FastAPI
backend, and agents built with Microsoft Agent Framework.

## Decision

* Build the interface with React, the Next.js App Router, and TypeScript.
* Build the API and the agent in Python with FastAPI and Microsoft Agent
  Framework.
* Keep the interface and the API as separate applications with an explicit
  contract. The browser talks only to Next.js:
  * The home page is a Server Component that calls `GET /catalog/coverage`.
  * The chat panel posts to the Next.js route `POST /api/chat`, which validates
    the request and calls `POST /chat` on the API from the server.
  * The API URL (`PRODUCT_SUPPORT_API_BASE_URL`) is server-side only, so the API
    needs no CORS policy and is never exposed to the browser.
* Keep chat state in the browser tab only; never show past sessions.
* Pin JavaScript dependencies in `package-lock.json` and Python dependencies in
  `uv.lock`. Node.js 22 is used for builds (the minimum supported is 20.9).

## Rationale

Next.js gives a typed, server-rendered interface with a built-in server route
for proxying. Python keeps the API, the agent, and ingestion in one language
and one dependency set.

## Alternatives considered

* Chainlit or Streamlit: Python-rendered chat interfaces; not selected because
  the brief asks for TypeScript and React.
* C# with ASP.NET Core and Agent Framework: viable, but it would split the
  backend across two languages.

## Consequences

* Two toolchains, each with its own lockfile, linting, type checks, tests, and
  container image.
* The web route and the API both validate input, so a malformed request is
  rejected before it reaches the model.

## References

* [Next.js](https://nextjs.org/docs)
* [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/overview/)

---
title: Local Development
description: Set up and validate the local product support agent foundation
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: how-to
keywords:
  - local development
  - Podman
  - Next.js
  - FastAPI
---

## Prerequisites

* Python 3.11 or later
* `uv` 0.13.9 or later
* Node.js 20.9 or later and npm
* Podman with a working `podman compose` provider for local MongoDB and Azurite

The local application stack is not deployed to Azure. Product ingestion,
Azure AI Search, model calls, and query/response retention are not enabled in
this foundation phase.

## Configure the Python environment

Copy `.env.example` to `.env` only if you need to change local settings. Do not
commit `.env` or put user content in it, tests, or logs. Keep provider
credentials in approved local environment configuration outside source control.

```powershell
uv sync --all-groups
uv run uvicorn product_support_agent.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

The process health endpoint is available at
`http://127.0.0.1:8000/healthz`. It reports API process health only; it does not
validate databases, queues, search, or model-provider connectivity.
The health response includes a generated `X-Request-ID`. Application log
records use JSON fields for timestamp, level, logger, message, and request ID.

## Run the frontend

```powershell
Set-Location apps/web
npm ci
npm run dev
```

Open `http://localhost:3000`. The Phase 1 page is a foundation placeholder and
does not offer chat or product coverage claims.

## Start local data services

From the repository root, start the emulated services when needed:

```powershell
podman compose up -d mongodb azurite
```

The services bind only to loopback. `podman compose down` stops them, and
`podman compose down --volumes` removes their local data.

## Validate changes

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src/product_support_agent
uv run pytest
uv run bandit -q -r src
uv run pip-audit --skip-editable
```

```powershell
Set-Location apps/web
npm run lint
npm run typecheck
npm run build
npm audit --audit-level=high
```

`npm run lint` runs Biome's formatting and lint checks on frontend source.

Query and response retention defaults to off. Do not enable it until the
privacy notice, reviewer identity, redaction behavior, deletion, TTL, and
provider-handling approvals are complete. The Phase 1 app does not persist
queries or responses.

The logging filter redacts common labeled secrets and email addresses. It is
not a general-purpose PII detector, so never log query or response content.

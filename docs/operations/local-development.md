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

The services bind only to loopback. Stop and start them gracefully to preserve
emulator metadata:

```powershell
podman compose stop --timeout 30 mongodb azurite
podman compose start mongodb azurite
```

Azurite has a 30-second shutdown grace period in Compose. During verification,
a bare `podman restart` lost newly written Azurite metadata; explicit graceful
stop/start preserved it. Do not use a forced stop or bare restart for emulator
data you need to keep. This emulator does not provide production durability.

`podman compose down --timeout 30` stops and removes the project containers
while preserving their named volumes. Adding `--volumes` removes their local
data.

### Podman verification record

Local verification passed on 2026-11-21 with Podman 5.6.2, a running WSL
machine, and Docker Compose 2.34.0 as the external provider:

* Compose validation, image pulls, and startup of MongoDB and Azurite passed.
* Host listeners for ports 27017, 10000, and 10001 bound only to `127.0.0.1`.
* MongoDB ping, synthetic document write/read, and restart persistence passed.
* Authenticated Azurite queue and blob write/read through the host ports passed.
* Azurite graceful stop/start preserved the message and blob. Message receipt,
  acknowledgement, and an empty-queue check passed.
* Synthetic databases, queues, and blob containers were removed after testing.

Only this project's containers were stopped after verification; named volumes
and unrelated workloads were preserved. No OpenText or cloud services were
accessed. GitHub-hosted CI and repository branch protection remain separate
verification items in the [operations backlog](./backlog.md).

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

The logging filter redacts common labeled secrets (for example `api_key`,
`client_secret`, `AccountKey`, and SAS `sig`), credentials in connection-string
URIs, bearer tokens, JWTs, cookies, and email addresses. It also applies to the
uvicorn server and access logs, which include request query strings. It is
pattern-based and not a general-purpose PII detector, so never log query or
response content.

`npm run typecheck` runs `next typegen` first, so it works on a clean checkout
before any `next build`. The repository's `.gitattributes` keeps LF line endings
on Windows so that Biome and Ruff formatting checks match CI.

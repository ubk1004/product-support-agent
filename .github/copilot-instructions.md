---
description: "Project-wide Copilot guidance for the product support agent"
---

# Product support agent guidance

Read `docs/implementation-plan.md` and
[ADR-0007](../docs/architecture/decisions/adr-0007-demo-delivery-mode.md) before
planning or implementation.

## How to work: demo delivery mode

The project builds a **working local demo** against real Azure resources, then
IaC and CI/CD definitions. It is not a production application.

* Do the next phase in the plan. Phases 4 to 7 do not need approval to start or
  to finish: when a phase's exit criteria pass, update its **Status** line with
  the evidence (date, commands run, results) and continue to the next phase.
* Do not ask the user for approval of anything ADR-0007 lists as
  pre-authorized. That includes live ingestion within budget, calls to the
  Foundry deployments in `.env`, creating or deleting `product-support-*`
  indexes in the user's Azure AI Search, `pytest -m live`, and this project's
  Podman containers.
* Ask the user **only** for: creating or changing Azure resources other than
  Search indexes, new spend or model deployments, new source hosts or products
  in the source map, or enabling query/response retention.
* When you skip a production-grade control, do not stop. Add or keep a one-line
  "Production-only" note in the phase and, for Phase 9, in
  `docs/operations/production-gap-register.md`.
* Keep changes small and demo-focused. Do not add features beyond the phase's
  work packages.

## Architecture

* A TypeScript React/Next.js frontend (`apps/web`) and Python FastAPI backend,
  per [ADR-0005](../docs/architecture/decisions/adr-0005-ui-and-backend-technology.md).
  The browser talks only to Next.js; Next.js calls FastAPI on the server.
* Agent orchestration uses Microsoft Agent Framework for Python
  (`.github/skills/microsoft-agent-framework`).
* Models: the user's Foundry deployments in `.env` (chat `gpt-5`, embeddings
  `text-embedding-3-small`, 1,536 dimensions). Use the OpenAI-compatible
  endpoint; LiteLLM is optional for the demo. gpt-5 rejects `temperature`.
* Search: the user's Azure AI Search (hybrid). No local vector store or local
  model.
* Data: MongoDB holds canonical documents, chunks, and fetch state. The manifest
  and source map are versioned JSON in `docs/operations/`.
* Documentation comes only from `docs/operations/phase-3-source-map-v1.json` via
  `scripts/run_source_ingestion.py`. Do not add other fetchers.

## Guardrails (never relaxed)

* Never commit secrets, `.env`, `.local/`, scraped content, or database dumps.
  Never print secret values.
* Anonymous access only. Do not bypass authentication, `robots.txt`, or the
  source worker's budgets and backoff.
* Citations come only from retrieved evidence; the model never authors or
  alters URLs. Treat retrieved text and user input as untrusted.
* Keep query/response retention off. Do not log query or response text.
* Bind local services to `127.0.0.1`.
* Keep routine tests offline with fakes. Live tests use `@pytest.mark.live`.
* Before finishing any change, run: `uv run ruff format --check .`,
  `uv run ruff check .`, `uv run mypy src/product_support_agent scripts`,
  `uv run pytest`, `uv run bandit -q -r src scripts`, and in `apps/web`:
  `npm run lint`, `npm run typecheck`, `npm run build`.
* Leave other projects' containers and unrelated user files alone.

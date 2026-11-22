# Product Support Agent web app

Next.js App Router frontend for the local demo. See the
[local development guide](../../docs/operations/local-development.md) and
[ADR-0005](../../docs/architecture/decisions/adr-0005-ui-and-backend-technology.md).

## What it shows

The home page is a Server Component that calls the FastAPI
`GET /catalog/coverage` endpoint at request time and renders:

* how many of the 100 demo products have indexed documentation
* a table of every manifest product, with indexed products first, each labelled
  indexed, pending, unavailable, excluded, or no approved public source
* a notice if ingestion state cannot be read, and a "no product should be
  assumed to be covered" message if the API is unreachable

The browser never calls FastAPI directly. Chat is added in Phase 5.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PRODUCT_SUPPORT_API_BASE_URL` | `http://127.0.0.1:8000` | FastAPI base URL, used on the server only |

## Commands

```powershell
npm ci
npm run dev      # http://localhost:3000
npm run lint     # Biome
npm run typecheck
npm run build
```

`next dev` writes `AGENTS.md` with notes for coding assistants about this
Next.js version. It is generated, not project documentation.

---
title: Product Support Agent Architecture Overview
description: Current and planned architecture, process flows, data ownership, and trust boundaries for the local-first product support demo
author: Product Support Agent Team
ms.date: 2026-11-22
ms.topic: concept
keywords:
  - product support
  - architecture
  - trust boundaries
  - ingestion
estimated_reading_time: 12
---

## Status

Each diagram marks components as **implemented** (code and tests exist) or
**planned** (later phase). Implemented components are tested offline unless the
[implementation plan](../implementation-plan.md) records a live verification.

| Area | State on 2026-11-22 |
|---|---|
| Catalog discovery, manifest, queue contract, Phase 2 worker | Implemented (Phase 2, approved) |
| Source map, periodic source worker, fetch state, coverage API and UI | Implemented, tested offline ([ADR-0006](decisions/adr-0006-periodic-resumable-source-ingestion.md)) |
| Canonical documents and chunks in MongoDB | Implemented; no live content ingested |
| Azure AI Search index, hybrid retrieval provider | Implemented; test-index definition applied, no documents uploaded |
| Embeddings through LiteLLM | Interface only; no deployment configured |
| Agent, chat API, citations, chat UI | Planned (Phases 4 and 5) |
| Telemetry, evaluation, query/response retention | Planned and gated (Phase 6, privacy approval) |
| Azure deployment | Design-only (Phase 7) |

Legend: solid lines and boxes are implemented; dashed lines or boxes marked
*planned* are not built yet.

## System context

```mermaid
flowchart LR
    User([Demo user])
    Operator([Demo operator])

    subgraph App["Product Support Agent: local Podman host"]
        UI[Next.js UI]
        API[FastAPI]
        Ingest[Source ingestion job]
    end

    Catalog[(my.opentext.com<br/>product feed)]
    Docs[(docs.microfocus.com<br/>admhelp.microfocus.com)]
    Search[(Azure AI Search<br/>user-provided)]
    Foundry[(Microsoft Foundry<br/>user-provided)]

    User -->|"Views coverage, asks questions (planned)"| UI
    UI --> API
    Operator -->|Weekly schedule or manual run| Ingest
    API -.->|One-time manifest creation| Catalog
    Ingest -->|Anonymous, allowlisted, robots-checked GET| Docs
    Ingest -.->|Chunks and vectors, planned| Search
    API -.->|Hybrid retrieval, planned| Search
    API -.->|Chat via LiteLLM, planned| Foundry
    Ingest -.->|Embeddings via LiteLLM, planned| Foundry
```

The OpenText product pages are a catalog source only. They render in the
browser and lead to login-gated knowledge bases. Product documentation comes
from the explicitly listed seeds in the
[source map](../operations/phase-3-source-map-v1.json).

## Containers and components

```mermaid
flowchart TB
    subgraph Local["Local Podman environment, loopback-bound"]
        subgraph Web["apps/web: Next.js"]
            Page["Home page, server component<br/>coverage summary and table"]
            ChatUI["Chat view, planned"]
        end

        subgraph Backend["src/product_support_agent: FastAPI"]
            Health["GET /healthz"]
            ManifestAPI["GET /catalog/manifest"]
            CoverageAPI["GET /catalog/coverage"]
            RunsAPI["GET /ingestion/runs/run_id"]
            Agent["Agent and retrieval tool, planned"]
        end

        subgraph Jobs["Ingestion"]
            CatalogSvc["Catalog client and manifest<br/>catalog.py, orchestration.py"]
            Phase2Worker["Queue worker<br/>worker.py"]
            SourceWorker["Source ingestion worker<br/>source_ingestion.py"]
            Runner["scripts/run_source_ingestion.py"]
        end

        Azurite[(Azurite queue<br/>product-ingestion and poison)]
        Mongo[(MongoDB)]
        LiteLLM["LiteLLM gateway, planned"]
    end

    Files[["Versioned files in docs/operations:<br/>manifest and source map"]]
    Search[(Azure AI Search)]

    Page -->|Server-side fetch| CoverageAPI
    ChatUI -.-> Agent
    CoverageAPI --> Files
    CoverageAPI -->|Read fetch state| Mongo
    CatalogSvc --> Files
    CatalogSvc --> Azurite
    Azurite --> Phase2Worker
    Runner --> SourceWorker
    SourceWorker --> Files
    SourceWorker -->|Fetch state, lease, canonical documents| Mongo
    SourceWorker -.->|DocumentIndexingService| LiteLLM
    SourceWorker -.-> Search
    Agent -.-> Search
    Agent -.-> LiteLLM
```

The browser talks only to Next.js. The home page fetches `/catalog/coverage` on
the server, using `PRODUCT_SUPPORT_API_BASE_URL` (default
`http://127.0.0.1:8000`), so the API needs no CORS configuration and stays on
loopback.

## Documentation ingestion process

A run processes each enabled source map entry in order. Every request is
counted against the run's budget and spaced at least 1 second apart per host.

```mermaid
flowchart TD
    Start([Scheduled or manual run]) --> Lease{Acquire MongoDB lease}
    Lease -->|Held by another run| Exit3([Exit code 3])
    Lease -->|Acquired| Next{Next enabled source?}
    Next -->|None| Report([Write metadata-only report, release lease])

    Next -->|Source| ProductBackoff{Product in fail-fast backoff?}
    ProductBackoff -->|Yes| Next
    ProductBackoff -->|No| HostAborted{Host aborted this run?}
    HostAborted -->|Yes| Next
    HostAborted -->|No| SeedFresh{Seed fetched within 24 h<br/>and config unchanged?}
    SeedFresh -->|Yes| Cached[Use stored page list]
    SeedFresh -->|No| Robots[robots.txt once per host]
    Robots -->|5xx or unreachable| AbortHost[Abort host for the run]
    AbortHost --> Next
    Robots --> SeedGet[Conditional GET of TOC JSON or sitemap]
    SeedGet -->|Failure| SeedBackoff[Record failure and backoff]
    SeedBackoff --> Next
    SeedGet -->|200 or 304| Discover[Parse and filter candidates]
    Discover --> Select
    Cached --> Select[Rank and cap pages, max 30]

    Select --> Page{Next page?}
    Page -->|None| Reconcile[Delete documents for pages<br/>no longer selected]
    Reconcile --> Next
    Page -->|Page| Fresh{Success within 24 h?<br/>or revision unchanged?}
    Fresh -->|Yes| Skip[Skip without a request]
    Skip --> Page
    Fresh -->|No| Allowed{robots.txt allows fetch<br/>and citation URL?}
    Allowed -->|No| Disallowed["Record robots_disallowed, 30-day backoff"]
    Disallowed --> Page
    Allowed -->|Yes| Get[Conditional GET, at most 2 attempts]
    Get -->|304 or same body hash| Unchanged[Record unchanged]
    Unchanged --> Page
    Get -->|429| AbortHost
    Get -->|Protected, 4xx, oversized| Permanent["30-day backoff"]
    Get -->|5xx, network, indexing error| Transient["Backoff 1, 2, 4, then 7 days"]
    Permanent --> Streak{3 consecutive failures?}
    Transient --> Streak
    Streak -->|Yes| FailFast[Fail product fast, back it off]
    FailFast --> Next
    Streak -->|No| Page
    Get -->|200, new content| Extract[Extract HTML from JSON or main content]
    Extract --> Normalize[Normalize, chunk, persist with fetched_at]
    Normalize --> Record[Record indexed state]
    Record --> Page
```

Each request's state is written to `source_fetch_state` as soon as the request
finishes. A restarted run therefore skips URLs that succeeded within the
freshness window. If that write was lost, the canonical document's `fetched_at`
is a second guard.

## Restart and resume sequence

```mermaid
sequenceDiagram
    autonumber
    participant Sched as Scheduler
    participant Run as Source worker
    participant State as MongoDB source_fetch_state
    participant Docs as MongoDB canonical_documents
    participant Site as Documentation host

    Sched->>Run: Run 1
    Run->>Site: robots.txt, TOC, page 1, page 2
    Run->>State: Indexed: page 1, then page 2
    Run->>Docs: Upsert page 1 and page 2 documents
    Note over Run: Crash before page 3

    Sched->>Run: Run 2, minutes later
    Run->>State: Read seed: fresh, use stored page list
    Run->>State: Page 1 and page 2: success within 24 h
    Note over Run,Site: No requests for pages 1 and 2
    Run->>State: Page 3: no record
    Run->>Docs: Page 3 fetched_at? none
    Run->>Site: GET page 3
    Run->>Docs: Upsert page 3
    Run->>State: Record page 3 indexed

    Sched->>Run: Weekly run
    Run->>Site: Conditional GET TOC, If-None-Match
    Site-->>Run: 200 with revisions
    Note over Run: Unchanged revisions skip without a request
    Run->>Site: Conditional GET changed pages only
```

## Coverage disclosure flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Next as Next.js server component
    participant API as FastAPI /catalog/coverage
    participant Files as Manifest and source map files
    participant State as MongoDB source_fetch_state

    User->>Next: GET /
    Next->>API: GET /catalog/coverage, 5 s timeout, no cache
    API->>Files: Load approved manifest and source map
    alt Files missing or invalid
        API-->>Next: 503 coverage data unavailable
        Next-->>User: Notice, assume nothing is covered
    else Files valid
        API->>State: List fetch state
        alt MongoDB unavailable
            API-->>Next: Report with state_available false, sources pending
        else State readable
            API-->>Next: Per-product status and counts, no page URLs or content
        end
        Next-->>User: Summary and table, indexed products first
    end
```

Product statuses are `indexed`, `pending` (approved source, nothing indexed
yet), `unavailable` (the seed or the product is backing off), `excluded`
(disabled in the source map), and `no_public_source`.

## Planned grounded chat flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Next.js chat, planned
    participant API as FastAPI chat, planned
    participant Agent as Agent Framework, planned
    participant Search as Azure AI Search
    participant GW as LiteLLM to Foundry

    User->>UI: Question
    UI->>API: Validated request, no history stored
    API->>Agent: Question and covered product IDs
    Agent->>GW: Tool-calling chat request
    GW-->>Agent: Call retrieval tool
    Agent->>Search: Hybrid query, product filter
    Search-->>Agent: Chunks with evidence ID and source URL
    Agent->>GW: Answer using evidence IDs only
    GW-->>Agent: Draft answer
    Agent-->>API: Answer and cited evidence IDs
    API->>API: Resolve IDs to stored URLs, reject unknown IDs
    API-->>UI: Answer with server-rendered citations
```

Retrieved text is untrusted data. The model may cite only evidence IDs; the
server resolves them to canonical URLs.

## Data ownership

```mermaid
erDiagram
    MANIFEST ||--o{ MANIFEST_PRODUCT : selects
    SOURCE_MAP ||--o{ PRODUCT_SOURCE : lists
    MANIFEST_PRODUCT ||--o| PRODUCT_SOURCE : "covered by"
    PRODUCT_SOURCE ||--o{ FETCH_STATE : "seed, product, page"
    FETCH_STATE }o--o| CANONICAL_DOCUMENT : "document_id"
    CANONICAL_DOCUMENT ||--o{ CANONICAL_CHUNK : "split into"
    CANONICAL_CHUNK ||--o| SEARCH_CHUNK : "derived, planned"

    MANIFEST {
        string manifest_version
        string seed
        string selection_method
    }
    PRODUCT_SOURCE {
        string product_id
        string kind
        string seed_url
        int max_pages
    }
    FETCH_STATE {
        string key
        string kind
        string last_outcome
        datetime last_success_at
        datetime next_eligible_at
        string etag
        string body_hash
        string revision
    }
    CANONICAL_DOCUMENT {
        string document_id
        string source_url
        string content_hash
        datetime fetched_at
    }
    CANONICAL_CHUNK {
        string chunk_id
        int chunk_index
        string content_hash
    }
```

| Data | Owner and location | Notes |
|---|---|---|
| Manifest, source map | Versioned JSON in `docs/operations/`, reviewed in git | Changing either requires a new version |
| Fetch state, run lease | MongoDB `source_fetch_state`, `ingestion_leases` | Decides what to fetch; never contains page content |
| Canonical documents and chunks | MongoDB `canonical_documents`, `canonical_chunks` | System of record; not committed to git |
| Searchable chunks and vectors | Azure AI Search, versioned index | Derived; rebuilt from MongoDB |
| Queue messages | Azurite | Product references only |
| Run and coverage reports | JSON output, API responses | Outcomes and counts only |

## Trust boundaries

Edge labels use the boundary IDs from the
[threat register](../security/threat-register.md#trust-boundaries).

```mermaid
flowchart LR
    Browser[User browser]

    subgraph Local["Local application, loopback-bound"]
        UI[Next.js]
        API[FastAPI]
        Agent["Agent, planned"]
        Worker[Source and queue workers]
        Mongo[(MongoDB)]
        Queue[(Azurite)]
        Gateway["LiteLLM, planned"]
        Retention[("Retention collection, off by default")]
    end

    subgraph Public["Untrusted public sources"]
        Docs[Documentation hosts]
        Catalog[OpenText catalog feed]
    end

    subgraph Microsoft["User-provided Microsoft services"]
        Search[Azure AI Search]
        Foundry[Foundry deployments]
    end

    Telemetry["Telemetry collector, not selected"]
    DevCreds["Developer credentials and config"]

    Browser -->|"TB-01: HTML only, no history"| UI
    UI -->|"TB-02: server-side fetch"| API
    API -.-> Agent
    Agent -.->|"TB-03: prompts and evidence"| Gateway
    Gateway -.-> Foundry
    Worker -->|"TB-04: allowlist, robots, no redirects, limits"| Docs
    API -.->|"TB-04: one-time manifest"| Catalog
    Worker -->|"TB-05: state, documents, references"| Mongo
    Worker --> Queue
    API -->|"TB-05: read fetch state"| Mongo
    Worker -.->|"TB-06: chunks and vectors"| Search
    Agent -.->|"TB-06: hybrid queries"| Search
    API -.->|"TB-07: content-free events"| Telemetry
    API -.->|"Only after privacy approval and opt-in"| Retention
    DevCreds -.->|"TB-08"| Search
```

Source text, user input, and model output are untrusted. TB-09, the cloud
application boundary, is design-only and is shown in the deployment view.

## Deployment view

```mermaid
flowchart TB
    subgraph Dev["Developer machine"]
        subgraph Podman["Podman compose, implemented"]
            Mongo[(MongoDB 8)]
            Azurite[(Azurite)]
        end
        subgraph Processes["Host processes today; containerized in Phase 6"]
            NextJS["Next.js on 127.0.0.1:3000"]
            FastAPI["FastAPI on 127.0.0.1:8000"]
            Job["Source ingestion job<br/>weekly task"]
        end
        LiteLLM["LiteLLM, planned"]
    end
    Search[(User-provided Azure AI Search)]
    Foundry[(User-provided Foundry)]
    Docs[(Public documentation hosts)]

    NextJS --> FastAPI
    FastAPI --> Mongo
    Job --> Mongo
    Job --> Docs
    Job -.-> Search
    FastAPI -.-> Search
    LiteLLM -.-> Foundry

    subgraph Cloud["Conceptual Azure design, not deployed"]
        APIM[APIM]
        ACA["Container Apps: UI, API, scheduled ingestion job"]
        Data[Cosmos DB for MongoDB, Storage queue, AI Search]
        Egress[NAT Gateway egress with allowlist]
        Obs[Azure Monitor]
        APIM --> ACA
        ACA --> Data
        ACA --> Egress
        ACA --> Obs
    end
```

The application stack is not deployed to Azure. A network slice is a distinct,
later-approved activity described in Phase 7 of the
[implementation plan](../implementation-plan.md).

## Local-to-cloud component mapping

| Local MVP | Conceptual Azure counterpart | Important difference or limit |
|---|---|---|
| Next.js UI | Container App | Application deployment is deferred; cloud user authentication is not yet decided. |
| FastAPI and agent | Container App | Cloud identity and APIM behavior require Phase 7 validation. |
| Source ingestion job, weekly task | Container Apps job on a cron schedule | Egress must be allowlisted; the MongoDB lease keeps runs single-instance. |
| Catalog process and queue worker | Container App with queue-based scaling | Used for manifest creation; not needed for weekly documentation refresh. |
| LiteLLM | Azure API Management | Not assumed to be behaviorally equivalent; needs an ADR. |
| MongoDB | Cosmos DB for MongoDB | Authentication, `tz_aware` datetimes, and atomic upserts for the lease must be verified. |
| Azurite Queue | Azure Storage Queue | Poison-message and completion tracking need application-level handling. |
| Azure AI Search | Azure AI Search | Same provider. Local access uses the public endpoint; the cloud design uses a private endpoint. |
| No response cache | Azure Cache for Redis only if justified | Source fetch state is an idempotency control, not a cache. |
| Collector not selected | Azure Monitor and Log Analytics | Query and response content is excluded until privacy approval. |

## References

* [ADR-0002 Source access and manifest](decisions/adr-0002-source-access-and-manifest.md)
* [ADR-0006 Periodic, resumable documentation ingestion](decisions/adr-0006-periodic-resumable-source-ingestion.md)
* [Microsoft Agent Framework overview](https://learn.microsoft.com/agent-framework/overview/)
* [Azure AI Search hybrid search](https://learn.microsoft.com/azure/search/hybrid-search-overview)
* [RFC 9309 Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309)

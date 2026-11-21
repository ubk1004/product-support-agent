---
title: Product Support Agent Architecture Overview
description: Proposed logical architecture and trust boundaries for the local-first product support demo
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: concept
keywords:
  - product support
  - architecture
  - trust boundaries
estimated_reading_time: 8
---

## Status

The Phase 0 direction is approved. These diagrams reflect the approved local
MVP direction and Phase 0b privacy request; they are not implementation or
deployment evidence. See the [decision register](./decision-register.md).

## System context

```mermaid
flowchart LR
    User[Demo user] -->|Question| UI[Next.js UI]
    UI -->|Validated request| API[FastAPI]
    API --> Agent[Microsoft Agent Framework]
    Agent -->|Bounded retrieval request| Search[Azure AI Search]
    Search -->|Evidence with source ID and URL| Agent
    Agent -->|Chat completion| Gateway[LiteLLM]
    Gateway -->|User-provided deployments| Foundry[Microsoft Foundry]
    Agent -->|Answer with evidence IDs| API
    API <-->|Manifest and product outcomes| Mongo
    API -->|Answer, server-bound citations, and indexed-product status| UI
    UI -->|Source links| User
    UI -->|Successful product names and demo coverage| User

    Catalog[Catalog process] --> Queue[Azurite queue]
    Queue --> Worker[Ingestion worker]
    Worker -->|Anonymous, allowlisted GET| OpenText[OpenText public sources]
    OpenText -->|Permitted public content| Worker
    Worker -->|Embedding request| Gateway
    Worker -->|Canonical document and run status| Mongo[MongoDB]
    Worker -->|Versioned searchable chunks| Search
    Catalog -->|Manifest and run status| Mongo
```

## Proposed logical containers

The boxes below describe logical responsibilities. They do not decide whether
the UI, API, and worker run as separate local processes or deployment units.

```mermaid
flowchart TB
    subgraph Local["Local Podman environment"]
        UI[Next.js UI]
        API[FastAPI endpoints]
        Agent[Agent orchestration and retrieval tool]
        Catalog[Catalog and manifest process]
        Worker[Ingestion worker]
        Queue[Azurite queue]
        Mongo[MongoDB metadata and canonical records]
        Gateway[LiteLLM gateway]
        UI --> API
        API --> Agent
        Agent --> Gateway
        Catalog --> Queue
        Catalog --> Mongo
        Queue --> Worker
        Worker --> Mongo
        Worker --> Gateway
    end

    Search[(User-provided Azure AI Search)]
    Foundry[(User-provided Foundry deployments)]
    Sources[(Allowlisted OpenText public URLs)]
    Agent --> Search
    Worker --> Search
    Gateway --> Foundry
    Worker --> Sources
```

## Data flow and trust boundaries

```mermaid
flowchart LR
    subgraph UserBoundary["External user boundary"]
        Browser[User browser]
    end
    subgraph LocalBoundary["Local application boundary: Podman"]
        UI[Next.js]
        API[FastAPI]
        Agent[Agent Framework]
        Worker[Ingestion worker]
        Queue[Azurite]
        Mongo[MongoDB]
        Gateway[LiteLLM]
        Retention[(Restricted MongoDB retention collection)]
        RetentionGate[Global flag off by default; per-session opt-out]
    end
    subgraph OpenTextBoundary["Untrusted public-source boundary"]
        Catalog[Catalog and product URLs]
    end
    subgraph MicrosoftBoundary["User-provided Microsoft services"]
        Search[Azure AI Search]
        Foundry[Foundry model deployments]
    end
    subgraph TelemetryBoundary["Telemetry destination: not selected"]
        OTel[OpenTelemetry-compatible collector]
    end

    Browser -->|Question; no history by default| UI
    UI --> API
    API --> Agent
    API --> RetentionGate
    RetentionGate -.->|Redacted content only after policy approval and opt-in| Retention
    Agent -->|Query| Search
    Search -->|Retrieved text is untrusted data| Agent
    Agent --> Gateway
    Gateway --> Foundry
    Agent -->|Evidence IDs, not model-authored URLs| API
    API --> UI
    Catalog -->|Bounded anonymous requests| Worker
    Worker --> Queue
    Worker --> Mongo
    Worker --> Search
    UI -.->|Minimized, redacted telemetry only| OTel
    API -.->|No query/response retention before approval| OTel
    Worker -.-> OTel
```

Retrieved text, user input, model output, and external source instructions are
untrusted. The application must validate URLs and tool arguments, bind citations
to retrieved evidence, and exclude query/response content from telemetry until a
privacy policy is approved.

## Deployment view

```mermaid
flowchart TB
    subgraph Developer["Developer machine"]
        Podman[Podman local environment]
        NextJS[Next.js]
        FastAPI[FastAPI and agent]
        Ingestion[Catalog and worker]
        Azurite[Azurite]
        Mongo[MongoDB]
        LiteLLM[LiteLLM]
        Podman --> NextJS
        Podman --> FastAPI
        Podman --> Ingestion
        Podman --> Azurite
        Podman --> Mongo
        Podman --> LiteLLM
    end
    Search[(User-provided Azure AI Search)]
    Foundry[(User-provided Foundry deployments)]
    NextJS --> FastAPI
    FastAPI --> Search
    Ingestion --> Search
    LiteLLM --> Foundry

    subgraph CloudDesign["Conceptual Azure application design; not deployed"]
        APIM[APIM]
        ACA[Container Apps]
        VNet[VNet, private endpoints, DNS, egress]
        CloudData[Storage queue, Cosmos DB, AI Search]
        CloudObs[Azure Monitor and Log Analytics]
        APIM --> ACA
        ACA --> CloudData
        ACA --> CloudObs
        VNet --- APIM
        VNet --- ACA
        VNet --- CloudData
    end
    NetworkSlice[Separately gated network slice]
    NetworkSlice -.-> VNet
```

The local demo uses Azure AI Search and Foundry supplied by the user. The
application stack is not deployed to Azure. A network slice is a distinct,
later-approved activity described in Phase 7 of the
[implementation plan](../implementation-plan.md).

## Local-to-cloud component mapping

| Local MVP | Conceptual Azure counterpart | Important difference or limit |
|---|---|---|
| Next.js UI | Container App | Application deployment is deferred; cloud user authentication is not yet decided. |
| FastAPI and agent | Container App | Cloud identity and APIM behavior require Phase 7 validation. |
| Ingestion worker | Container App with queue-based scaling | External-source egress must be allowlisted and bounded. |
| LiteLLM | Azure API Management | Not assumed to be behaviorally equivalent; model routing, policy, identity, and telemetry need an ADR. |
| MongoDB | Cosmos DB for MongoDB | Authentication and feature compatibility must be verified for the selected API/model. |
| Azurite Queue | Azure Storage Queue | Poison-message and completion tracking need application-level handling. |
| Azure AI Search | Azure AI Search | Same provider in both environments. Local access uses the service's public endpoint; the cloud design uses a private endpoint. |
| No cache in the MVP | Azure Cache for Redis only if justified | Caching is deferred until measurements show a need. |
| Local OpenTelemetry-compatible collector, not selected | Azure Monitor and Log Analytics | Local destination and retention remain open; query/response content is excluded until privacy approval. |

## References

* [Microsoft Agent Framework overview](https://learn.microsoft.com/agent-framework/overview/)
* [Azure AI Search hybrid search](https://learn.microsoft.com/azure/search/hybrid-search-overview)
* [Azure AI Search vector quickstart](https://learn.microsoft.com/azure/search/search-get-started-vector)

---
title: ADR-0001 Search Provider and Model Access
description: Azure AI Search for hybrid retrieval and direct Foundry calls for chat and embeddings
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - Azure AI Search
  - Microsoft Foundry
---

## Status

Accepted.

## Context

The agent needs keyword and semantic retrieval with metadata filters, and chat
and embedding models that can be replaced without code changes. The brief asks
for Azure AI Search in every environment, with no local vector store, and for
models behind a gateway.

## Decision

* Use Azure AI Search as the only search provider, locally and in Azure.
* Use hybrid retrieval: full-text and vector queries in one request, combined
  by Azure AI Search with Reciprocal Rank Fusion, filtered by product ID. HNSW
  with cosine similarity; top 5 results by default, with vector candidates
  widened to four times the requested count. Semantic ranking is off.
* Put indexing and retrieval behind a small interface (`search.py`) with an
  in-memory implementation for offline tests.
* Version the index name by schema, parser, embedding model, and dimensions, so
  a model change creates a new index instead of corrupting the current one.
* Call Foundry's OpenAI-compatible endpoint directly for chat (`gpt-5`) and
  embeddings (`text-embedding-3-small`, 1,536 dimensions). Endpoint, key, and
  deployment names are configuration, so the models or the endpoint can change
  without code changes.

## Rationale

One search provider removes behaviour differences between local and cloud
runs. Because the client only needs an OpenAI-compatible base URL, a model
gateway can be put in front of Foundry later without touching code. For a demo
with one model provider, a gateway adds a component to run and secure without
adding a capability.

## Alternatives considered

* PostgreSQL with pgvector locally and Azure AI Search in the cloud: rejected,
  because retrieval would behave differently in each environment.
* LiteLLM locally and API Management in the cloud as model gateways: not
  adopted for this version. API Management is deployed in front of the
  application API instead ([ADR-0010](adr-0010-azure-platform-and-api-management.md)).
  Adding a model gateway is a configuration change and is listed in the
  [production gap register](../../operations/production-gap-register.md).
* Semantic ranking: not enabled. It needs a tier and billing decision and an
  evaluation against a reviewed question set.

## Consequences

* Local development needs network access to Azure AI Search and Foundry.
* Changing the embedding model requires re-indexing into a new index
  (`scripts/index_documents.py`).
* Model access, quotas, and keys are not centrally governed by a gateway.

## References

* [Azure AI Search hybrid search](https://learn.microsoft.com/azure/search/hybrid-search-overview)
* [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/overview/)

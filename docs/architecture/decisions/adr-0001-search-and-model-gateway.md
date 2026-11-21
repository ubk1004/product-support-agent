---
title: ADR-0001 Search and Model Gateway
description: Proposed search and model-provider boundaries for the product support agent
author: Product Support Agent Team
ms.date: 2026-11-21
ms.topic: decision
keywords:
  - ADR
  - Azure AI Search
  - LiteLLM
---

## Status

Phase 0 direction approved; protocol verification remains in Phase 4.

## Context

The local and cloud designs need hybrid retrieval and replaceable chat and
embedding deployments. The approved project direction names Azure AI Search for
both environments and LiteLLM as the local gateway to user-provided Foundry
deployments.

## Proposed decision

* Use Azure AI Search as the sole search provider in local and cloud designs.
* Put indexing and retrieval behind a thin application interface and use a fake
  provider for routine tests.
* Use hybrid full-text and vector retrieval. Azure AI Search combines these
  result sets with Reciprocal Rank Fusion; semantic reranking and ranking
  thresholds require evaluation before approval.
* Route chat and embedding requests through LiteLLM locally to the user's
  Foundry deployments. Do not add a local model or local vector store.
* Keep provider credentials outside source control and user-facing content.

## Alternatives considered

* Local PostgreSQL/pgvector with an Azure AI Search cloud adapter: rejected in
  the plan because it creates local/cloud retrieval differences.
* Direct model-provider calls from the agent: rejected because the gateway
  boundary is needed for model replacement and policy.

## Consequences

The local demo requires network access and valid configuration for the user's
Azure AI Search and Foundry services. Embedding model changes can require a new
index and re-embedding. Protocol compatibility between Agent Framework,
LiteLLM, and the Foundry deployments must be verified before Phase 4.

## References

* [Azure AI Search hybrid search](https://learn.microsoft.com/azure/search/hybrid-search-overview)
* [Microsoft Agent Framework overview](https://learn.microsoft.com/agent-framework/overview/)

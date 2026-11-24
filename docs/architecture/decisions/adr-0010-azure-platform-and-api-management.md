---
title: ADR-0010 Azure Platform, Network Isolation, and API Management
description: Container Apps in a virtual network with private data services, classic API Management in external mode, and two-stage Bicep deployment
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - Azure
  - Bicep
  - API Management
---

## Status

Accepted.

## Context

The brief asks for Bicep for the whole cloud estate; a virtual network with
subnets for the backend services, agents, data stores, and queue; API
Management in external mode with VNet integration; Container Apps for the
backend; Log Analytics and Azure Monitor; managed identity where supported; Key
Vault for secrets; and GitHub Actions for build and deployment.

## Decision

* **Template.** One subscription-scoped template, `infra/bicep/main.bicep`, with
  modules for network, platform, data, identity, Foundry, secret bootstrap,
  Container Apps, and API Management, and one parameter file per environment
  (`dev`, `tst`, `prd`).
* **Network.** A `10.20.0.0/16` virtual network with a Container Apps subnet, a
  private-endpoint subnet, and, when API Management is deployed, an undelegated
  API Management subnet. Each subnet has an NSG. Container Apps leave through a
  NAT gateway.
* **Private data.** The Mongo-compatible store, the Storage queue, Azure AI
  Search, Key Vault, and the container registry have public access disabled and
  are reached through private endpoints and private DNS zones.
* **Compute.** The web app has external ingress; the API has internal ingress
  only; ingestion is a Container Apps job.
* **API Management.** Classic tier in external VNet mode: Developer for `dev` and
  `tst`, Premium for `prd`. It exposes the chat and coverage operations with a
  subscription key, a rate limit, and a body-size limit, and logs requests
  without headers, bodies, or client IP addresses. `deployApim` turns it off,
  as in `dev`.
* **Identity.** Separate user-assigned identities for the API, the ingestion job,
  and image pulls, each with roles scoped to one resource. GitHub Actions signs
  in with OpenID Connect.
* **Store.** Azure Cosmos DB for MongoDB by default; Azure DocumentDB Free with
  `useDocumentDbFreeTier=true`, which needs an administrator password supplied
  as a secure parameter.
* **Foundry.** An existing endpoint by default; a new account, project, and model
  deployments with `deployFoundry=true`, which also writes the three Key Vault
  secrets the apps read.
* **Two stages.** Deploy the platform with `deployWorkloads=false`, publish images
  to the private registry, then deploy again with `deployWorkloads=true`. The
  infrastructure workflow runs both stages and refuses template placeholders
  before signing in to Azure.

## Rationale

Private endpoints and internal ingress leave only the web app and the gateway
reachable from the internet. The brief prefers system-assigned identities;
user-assigned identities are used instead so that their role assignments exist
before the apps first start and pull images or read Key Vault secrets, which a
system-assigned identity cannot have until the app is created. Classic API Management is the tier family that
supports external VNet injection. Two stages are needed because Container Apps
cannot start until their images exist in a registry that only the virtual
network can reach.

## Alternatives considered

* API Management v2 tiers: different VNet model and not the classic external
  mode the brief describes.
* API Management Consumption: cannot join a virtual network.
* A public container registry: simpler publishing, but exposes the images.
* One-stage deployment with public sample images: deploys, but leaves the apps
  running sample images until a second deployment.

## Consequences

* Publishing and deploying images need a runner inside the virtual network.
* API Management Developer has no SLA and one unit; Premium is costly; first
  creation in VNet mode can take 45 minutes or more.
* Azure AI Search and Foundry are still reached with keys stored in Key Vault.
* Region availability must be checked per service: DocumentDB Free and the
  GPT-5 GlobalStandard deployment are not offered in every region.
* The web app calls the API directly inside the environment; API Management is
  a separate entry point for API clients.

## References

* [Cloud environment setup guide](../../../infra/README.md)
* [API Management in an external virtual network](https://learn.microsoft.com/azure/api-management/api-management-using-with-vnet)

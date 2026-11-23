---
title: Azure Infrastructure Design
description: Design-only Bicep architecture and CI/CD bootstrap for the local-first demo
author: Udaybhanu Karmakar
ms.date: 2026-11-22
ms.topic: reference
keywords:
  - Azure
  - Bicep
  - infrastructure
  - GitHub Actions
---

Scope note: this IaC is validated by build, lint and static review only and has not been deployed. It shows the intended Azure architecture. Production gates (policy scanning, structural checks, cost estimate, APIM SKU choice, branch protection) are recorded in the Phase 7 "Production-only" note and in `docs/operations/production-gap-register.md`. The focus was a working local application first.

## Azure infrastructure design

The subscription-scope template creates the resource group, then provisions the
network, platform, data, identity, and Container Apps modules in Canada Central.
`deployApim` defaults to `false`. The web app has external ingress, the API has
internal ingress, private endpoints are linked to the VNet through private DNS,
and the Container Apps subnet uses a NAT Gateway for outbound traffic. Foundry
remains a public endpoint configured with parameters.

The Container Apps templates reference these Key Vault secret names; create
their values separately before running workloads. No secret values belong in
Bicep or parameter files:

* `mongodb-connection-string`
* `azure-ai-search-api-key`
* `azure-openai-api-key`

The cloud image references and Foundry parameter values in
`bicep/parameters/dev.bicepparam` are placeholders. The full template is
design-only and is not a separately deployable network slice.

## Naming

Use `{type}-psa-{env}-cac-{nn}` for resource names where Azure permits it.
Resources with restricted character sets or shorter maximum lengths preserve
the same project, environment, region, and instance tokens in a compact name.
Global resource names include a short deterministic suffix.

| Name segment | Meaning | Example |
|---|---|---|
| `{type}` | Azure resource type abbreviation | `vnet`, `cae`, `pe` |
| `psa` | Product Support Agent | `psa` |
| `{env}` | Environment | `dev` |
| `cac` | Canada Central | `cac` |
| `{nn}` | Two-digit instance number | `01` |

## Mandatory tags

| Tag | Purpose | Template value |
|---|---|---|
| `application` | Workload identification | `product-support-agent` |
| `costCenter` | Cost attribution | `costCenter` parameter (`TBD` placeholder) |
| `environment` | Environment isolation | `environment` parameter |
| `managedBy` | Infrastructure ownership | `bicep` |
| `owner` | Operational ownership | `owner` parameter (`team-placeholder`) |

## One-time GitHub OIDC bootstrap

1. Register an Entra application and service principal for this repository's
   deployment workflows. Create a federated credential with issuer
   `https://token.actions.githubusercontent.com`, audience
   `api://AzureADTokenExchange`, and subject
   `repo:<OWNER>/<REPO>:environment:dev`. Do not create a client secret.
2. Grant the application only the permissions required to create the target
   resource group and deploy into the subscription. For image publishing, grant
   `AcrPush` at the ACR scope only. Review and narrow deployment permissions
   before production.
3. Configure the GitHub `dev` environment and add these repository secrets by
   name; do not put their values in this file:
   `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.
4. Add these repository variables by name for the application workflow:
   `ACR_NAME`, `RESOURCE_GROUP_NAME`, `API_CONTAINER_APP_NAME`,
   `WEB_CONTAINER_APP_NAME`.

The `dev` environment protects image publication, what-if, and manual
deployment. The `infra` workflow deploys only on `workflow_dispatch`; the
`app` workflow deploys Container Apps only on `workflow_dispatch` and publishes
images only from `main`. Its publish job requires a self-hosted Linux runner
labelled `dev-vnet`, with Docker and private VNet access; a hosted GitHub runner
cannot push to the private ACR. Configure environment reviewers and the
federated subject to match the repository before enabling OIDC.

## Validation boundary

Run `az bicep build --file infra/bicep/main.bicep`,
`az bicep build-params --file infra/bicep/parameters/dev.bicepparam`, and
`az bicep lint --file infra/bicep/main.bicep` before review. The workflows
repeat static checks. Deployment and resource changes are outside this
validation boundary.

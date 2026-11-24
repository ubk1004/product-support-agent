---
title: Azure Infrastructure Design
description: Bicep architecture, live Azure verification results, and CI/CD bootstrap for the local-first demo
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: reference
keywords:
  - Azure
  - Bicep
  - infrastructure
  - GitHub Actions
---

The Bicep in this directory was deployed to an isolated Azure resource group
and exercised with the real application images, cloud ingestion, and chat.
Production gates remain recorded in the Phase 7 "Production-only" note and
the [production gap register](../docs/operations/production-gap-register.md).

## Status: written, validated, deployed

| Item | Written | Validated | Deployed |
|---|---|---|---|
| Network and platform | Yes | Bicep build, lint, parameter compilation, provider validation, and what-if | Yes, in the isolated test group |
| Foundry account, project, GPT-5 and embeddings | Yes, optional (`deployFoundry`) | Chat and embedding calls succeeded; embeddings return 1,536 dimensions | Yes |
| Data services | Yes | DocumentDB Free ready; five private endpoints approved; private DNS records present | Yes |
| Identity and secret bootstrap | Yes | Three identities, seven scoped role assignments, and three secret names verified (metadata only) | Yes |
| Container Apps | Yes | Real API and web revisions healthy; web to API to DocumentDB, Search, and Foundry verified | Yes |
| Ingestion job (Container Apps job) | Yes. Runs `run_queue_ingestion.py run` against the private Storage Queue with managed identity; ingestion and poison queues are declared in Bicep | Executed in Azure: 10 of 10 products with an approved source succeeded | Yes |
| API Management | Classic tier in external VNet mode: Developer for `dev` and `tst`, Premium for `prd`. Dedicated subnet, NSG, and static public IP; off in `dev` (`deployApim`) | Succeeded; gateway rejects missing keys with 401; policy and no-body diagnostics verified | Yes, Developer |
| `infra`, `app`, and `validate` GitHub workflows | Yes | Checked offline by `tests/unit/test_workflows.py` (pinned actions, permissions, triggers, deployment gates); actionlint runs in CI; hosted runs not verified | No |

## Live verification

The test environment is the resource group `rg-psa-tst-cae-23` (`tst`,
instance `23`) in Canada East, with DocumentDB Free in Canada Central.

Verified:

* The full stack deploys, including Foundry, both model deployments, Search,
  Key Vault, ACR, storage, telemetry, networking, Container Apps, and APIM.
* Both images build from the repository Containerfiles, pull from the private
  registry, and run healthy with API port 8000 and web port 3000.
* Cloud ingestion on the approved source map finished with 10 of 10 products
  that have an approved source succeeded and 90 skipped as `no_public_source`,
  with no failures or dead-lettered messages.
* Through the deployed web route, chat returns grounded answers with citations
  to the approved documentation host, handles a follow-up, refuses an off-topic
  question and a fictional product with no citations, and returns HTTP 400 for
  malformed input. Product coverage renders on the home page.
* Retention stayed off, and no query or response text was stored.

Not verified:

* An APIM request with a subscription key through to the API. The web app calls
  the API directly and does not use APIM.
* Retrieval and answer quality thresholds (`scripts/run_evaluation.py`).
* A browser session. Checks used the deployed web route and rendered page.
* Alerts and telemetry retention policy.

Lessons that still apply:

* Provider validation and what-if do not prove regional tier availability.
  Canada East rejected DocumentDB Free at creation despite passing both, so
  `documentDbLocation` places the Free cluster in Canada Central. There is no
  paid fallback. The subscription also lacked Cosmos DB RU access in Canada East.
* Updating the Foundry project and model deployments concurrently conflicts on
  the parent account, so the template serializes those writes.
* A Container Apps Consumption workload profile does not accept node
  `minimumCount` or `maximumCount`.
* The application accepts `local`, `test`, or `production` as its environment.
  The template maps `prd` to `production` and every other environment to `test`.
* Model capacity is a tokens-per-minute rate limit on pay-per-token
  deployments. Capacity 1 allows 1,000 tokens per minute, which throttles chat
  and ingestion with HTTP 429. The module defaults are 10 for GPT-5 and 20 for
  embeddings; raise them for heavier use.
* The registry is private, so images must be pushed from a runner or builder with
  VNet access. Do not enable public access permanently.
* Stopping an ingestion execution leaves its 6-hour lease in the
  `ingestion_leases` collection (`source-ingestion`). Delete that document, or
  wait for it to expire, before the next run.
* GlobalStandard permits global model processing; locating the account in Canada
  does not guarantee Canadian processing residency.

> [!WARNING]
> The test resources are retained and continue to incur charges. A budget is not
> an Azure spending cap. Obtain explicit approval before deleting them.

### Known gaps

* API Management Developer was used for this isolated test only. The classic
  Developer tier has no SLA and one unit; Premium is the production tier and is
  billed per unit. Other environments still need a cost decision before enabling
  it. First creation in VNet mode can take 45 minutes or more.
  Callers authenticate with a subscription key; Entra ID sign-in (`validate-jwt`)
  is a production gate.
* When `deployFoundry=true`, the ARM secret bootstrap creates
  `mongodb-connection-string`, `azure-ai-search-api-key`, and
  `azure-openai-api-key` without exposing values as outputs. With an existing
  Foundry endpoint (`deployFoundry=false`), provision these secret values
  separately.
* The ingestion job indexes into Search as it runs, so it receives the
  embedding model version and dimensions (`embeddingModelVersion`,
  `embeddingDimensions`) and the Foundry and Search settings. These must match
  the embedding deployment or the index name will not match what the API reads.
* Image publishing needs a self-hosted runner. The private registry is not
  reachable from a GitHub-hosted runner. The workflow requires a runner labelled
  `dev-vnet`; it has not been created.
* The default Mongo-compatible store is RU-based Azure Cosmos DB for MongoDB.
  `useDocumentDbFreeTier=true` selects Azure DocumentDB Free instead, requiring
  a secure `documentDbAdministratorPassword` parameter and an available region.
  This path has no paid fallback.
* The API and ingestion job send OpenTelemetry traces to Application Insights
  with their managed identities (Monitoring Metrics Publisher role), and API
  Management logs requests without bodies. Alerts and a retention policy are not
  configured.

## Azure infrastructure design

The subscription-scope template creates the resource group, then provisions the
network, platform, data, identity, and Container Apps modules in Canada Central
by default. The separate smoke parameters target Canada East.
`deployApim` defaults to `false`. The web app has external ingress, the API has
internal ingress, private endpoints are linked to the VNet through private DNS,
and the Container Apps subnet uses a NAT Gateway for outbound traffic. Foundry
remains a public endpoint, either configured with parameters or created with
`deployFoundry=true`.

The Container Apps templates reference these Key Vault secret names. Use the
optional ARM bootstrap or populate them separately before running workloads.
Never commit secret values in Bicep or parameter files:

* `mongodb-connection-string`
* `azure-ai-search-api-key`
* `azure-openai-api-key`

The cloud image references and Foundry parameter values in
`bicep/parameters/dev.bicepparam` are placeholders. The full template is
not a separately deployable network slice.

### Staged deployment test

The [smoke parameters](./bicep/smoke.bicepparam) select `tst`, instance `23`,
Canada East, a new Foundry account, DocumentDB Free in Canada Central, APIM
Developer, port 80 hello-world images, and a Manual ingestion job.
`documentDbLocation` defaults to the stack's region, so the existing environment
parameter files retain their behavior. Do not remove the Canada Central override
without rechecking tier availability.

The hello-world images test resource creation only and cannot run the ingestion
command. To test the application, override `apiImage` and `webImage` with images
pushed to the private registry and set `apiTargetPort` to 8000 and
`webTargetPort` to 3000. Keep `scheduleIngestion=false` so ingestion runs only
when started manually.

Compile and validate before deploying:

```powershell
az bicep build --file infra\bicep\main.bicep --outfile .azure\smoke.template.json
az bicep build-params --file infra\bicep\smoke.bicepparam --outfile .azure\smoke.parameters.json
az bicep lint --file infra\bicep\main.bicep
```

Supply `documentDbAdministratorPassword` through a secure local parameter
source, never command-line plaintext or committed files. Preserve the same
credential across redeployments. The `.azure` directory is git-ignored; keep
compiled templates and parameter files with credentials there.

```powershell
$subscription = '<subscription-id>'
az deployment sub validate --subscription $subscription --location canadaeast --template-file .azure\smoke.template.json --parameters .azure\smoke.parameters.json deployWorkloads=false
az deployment sub what-if --subscription $subscription --location canadaeast --template-file .azure\smoke.template.json --parameters .azure\smoke.parameters.json deployWorkloads=false
az deployment sub create --subscription $subscription --location canadaeast --name '<unique-platform-deployment-name>' --template-file .azure\smoke.template.json --parameters .azure\smoke.parameters.json deployWorkloads=false
```

After the platform succeeds, secret metadata checks pass, and scoped roles
propagate, validate, review what-if, and deploy again with
`deployWorkloads=true`. Verify revisions, network access, and APIM separately.

## Naming

Use `{type}-psa-{env}-{region}-{nn}` for resource names where Azure permits it.
Resources with restricted character sets or shorter maximum lengths preserve
the same project, environment, region, and instance tokens in a compact name.
Global resource names include a short deterministic suffix.

| Name segment | Meaning | Example |
|---|---|---|
| `{type}` | Azure resource type abbreviation | `vnet`, `cae`, `pe` |
| `psa` | Product Support Agent | `psa` |
| `{env}` | Environment | `dev` |
| `{region}` | Region token; `cac` for Canada Central, `cae` for Canada East | `cae` |
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
   `WEB_CONTAINER_APP_NAME`, `INGESTION_JOB_NAME`.

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
repeat static checks. Provider validation and what-if are necessary but do not
prove regional tier availability, as the live database attempt demonstrated.
Further deployment and resource changes require the applicable user approval.

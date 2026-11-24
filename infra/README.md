---
title: Cloud Environment Setup and Testing Guide
description: How to create, deploy, test, and remove an Azure environment for the Product Support Agent with Bicep and GitHub Actions
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: how-to
keywords:
  - Azure
  - Bicep
  - Container Apps
  - GitHub Actions
  - API Management
estimated_reading_time: 14
---

This guide takes you from an empty Azure subscription to a running environment
that you can test. It covers what the template creates, what you must prepare,
how to deploy by pipeline or by command line, how to test the result, and how
to remove it. The design and its reasons are in the
[solution architecture](../docs/architecture/architecture-overview.md) and
[ADR-0010](../docs/architecture/decisions/adr-0010-azure-platform-and-api-management.md).

## What gets created

One resource group per environment (`dev`, `tst`, or `prd`), named
`rg-psa-<env>-<region>-<nn>`, containing:

| Layer | Resources |
|---|---|
| Network | Virtual network `10.20.0.0/16` with subnets for Container Apps, private endpoints, and API Management; an NSG per subnet; a NAT gateway for outbound traffic; private DNS zones |
| Platform | Key Vault, Azure Container Registry (Premium, private), Log Analytics, Application Insights |
| Data | Cosmos DB for MongoDB (or Azure DocumentDB Free), a Storage account with the `product-ingestion` and `product-ingestion-poison` queues, Azure AI Search (Basic), all with private endpoints |
| Identity | User-assigned identities for the API, the ingestion job, and image pulls, with role assignments scoped to single resources |
| AI (optional) | With `deployFoundry=true`: a Foundry account and project with `gpt-5` and `text-embedding-3-small` GlobalStandard deployments, and the three Key Vault secrets the apps read |
| Workloads | A Container Apps environment with the web app (public), the API (internal), and the ingestion job (weekly, Sundays 02:00 UTC, or manual) |
| Gateway (optional) | Classic API Management in external VNet mode: Developer for `dev` and `tst`, Premium for `prd` (`deployApim`) |

Resource names follow `{type}-psa-{env}-{region}-{nn}`, with a short
deterministic suffix on globally unique names. Every resource is tagged with
`application`, `costCenter`, `environment`, `managedBy`, and `owner`.

## Before you start

### Tools

* Azure CLI with Bicep (`az bicep install`) and permission to run
  `az deployment sub`.
* Python 3.11 or later, to run `scripts/prepare_deployment.py`.
* A GitHub repository with Actions enabled, if you deploy by pipeline.

### Azure access

The identity that deploys needs to create a resource group, resources, and role
assignments at subscription scope. `Owner`, or `Contributor` plus
`Role Based Access Control Administrator`, is enough. Narrow it for
production.

### Capacity and region checks

Provider validation and what-if do **not** prove that a service is offered in a
region. Check these before you deploy:

* **Models.** `gpt-5` (2025-08-07) and `text-embedding-3-small` with the
  GlobalStandard SKU, in the `location` you choose. GlobalStandard can process
  prompts in any region, so it is not a data-residency control.
* **Model capacity.** The defaults are 10 for `gpt-5` and 20 for embeddings (in
  units of 1,000 tokens per minute). Capacity 1 throttles chat and ingestion
  with HTTP 429.
* **Cosmos DB for MongoDB** in the region. If your subscription cannot create
  it there, or you want the free option, use `useDocumentDbFreeTier=true`
  and a `documentDbLocation` where Azure DocumentDB Free is offered. That mode
  has no paid fallback.
* **API Management** (classic Developer or Premium) and **Container Apps** in
  the region.
* **Region token.** The names use `cac` for `canadacentral` and `cae` for
  `canadaeast`. For any other region, set `locationAbbreviation` in the
  parameter file.

### Parameter files

Each environment has `infra/bicep/parameters/<env>.bicepparam`. The committed
files contain placeholders so that nothing deploys by accident. Replace at
least:

| Parameter | Meaning |
|---|---|
| `owner`, `costCenter` | Tag values |
| `location` | Azure region |
| `deployFoundry` | `true` to create Foundry and the model deployments; otherwise set `foundryEndpoint`, `foundryChatDeployment`, and `foundryEmbeddingDeployment` for an existing Foundry resource |
| `useDocumentDbFreeTier`, `documentDbLocation` | Optional free Mongo-compatible store |
| `deployApim`, `apimPublisherEmail`, `apimPublisherName` | Optional gateway and its publisher contact |
| `instance` | Two-digit suffix, so that several copies of an environment can coexist |

`scripts/prepare_deployment.py` refuses to continue while any required value is
still a placeholder. The image parameters are set by the script from the commit
SHA and are not edited by hand.

### Secrets

* `documentDbAdministratorPassword` (only with DocumentDB Free): keep the same
  value for every deployment of the environment. Supply it as the
  `DOCUMENTDB_ADMIN_PASSWORD` environment variable; never put it in a parameter
  file or on a command line.
* With `deployFoundry=false`, create the three Key Vault secrets yourself:
  `mongodb-connection-string`, `azure-ai-search-api-key`, and
  `azure-openai-api-key`. The vault is private after the platform stage, so
  create them from a machine inside the virtual network or while you
  temporarily allow your own address.

## Deploy in two stages

The apps cannot start until their images are in the container registry, and the
registry is reachable only from inside the virtual network. So the template
deploys twice with `deployWorkloads` switched off, then on:

1. **Platform** (`deployWorkloads=false`): network, platform, data, identity,
   and optionally Foundry, the secrets, and the model deployments.
2. **Publish images** from a runner inside the virtual network.
3. **Workloads** (`deployWorkloads=true`): Container Apps, the ingestion job,
   and, if enabled, API Management. API Management in VNet mode can take 45
   minutes or more to create the first time.

### Option A: GitHub Actions

#### One-time setup per environment

1. **Federated identity.** Create an Entra application and service principal
   with a federated credential:

   | Field | Value |
   |---|---|
   | Issuer | `https://token.actions.githubusercontent.com` |
   | Audience | `api://AzureADTokenExchange` |
   | Subject | `repo:<owner>/<repo>:environment:<env>` |

   Create no client secret. Grant it the roles above on the subscription for
   infrastructure deployment, and `AcrPush` and `Contributor` on the resource
   group for application deployment, once the group exists.
2. **GitHub environment.** Create a GitHub environment named `dev`, `tst`, or
   `prd`. Add required reviewers to `prd`, and restrict deployment branches to
   `main`.
3. **Environment secrets:** `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
   `AZURE_SUBSCRIPTION_ID`, and, with DocumentDB Free,
   `DOCUMENTDB_ADMIN_PASSWORD`.
4. **Environment variables**, after the platform stage has created the
   resources: `ACR_NAME`, `RESOURCE_GROUP_NAME`, `API_CONTAINER_APP_NAME`,
   `WEB_CONTAINER_APP_NAME`, and `INGESTION_JOB_NAME`. The names are in the
   deployment outputs.
5. **A self-hosted runner** inside the virtual network, with Docker and the
   labels `self-hosted`, `linux`, `x64`, and `<env>-vnet` (for example
   `tst-vnet`). The publish and deploy jobs run on it because the registry is
   private. Provisioning the runner is outside this repository.
6. **Branch protection** on `main` with the `Validate` checks required.

The registry name and the runner cannot exist until the platform stage has run,
so the first platform deployment can be done from the command line (Option B)
or from the workflow before steps 4 and 5.

#### Pipelines

| Workflow | Runs | What it does |
|---|---|---|
| `validate.yml` | Every pull request, and called by `app.yml` | Python 3.11 and 3.13 checks (Ruff, mypy, pytest, Bandit, `pip-audit`), web lint, type-check, build, and `npm audit`, actionlint, CodeQL, and gitleaks |
| `infra.yml` | Pull requests and pushes that touch `infra/`, and manual runs | Builds and lints the Bicep for `dev`, `tst`, and `prd`. A manual run from `main` takes an environment and a stage, refuses placeholders, signs in with OIDC, runs a what-if, and then deploys. Deployment waits for the what-if to succeed and for any environment reviewers |
| `app.yml` | Pushes to `main`, and manual runs | Validates, builds both images and checks that they run as non-root, then publishes images tagged with the commit SHA on a VNet runner. A manual run also updates the API, web app, and ingestion job to one image tag and checks that the API is running |

Run them in this order for a new environment:

1. Run **Infrastructure**: environment `<env>`, stage `platform`.
2. Run **Application** from `main` with environment `<env>`: this builds and
   publishes the images (on a push to `main` it publishes to `dev`).
3. Run **Infrastructure**: stage `workloads`, with `image-tag` set to the commit
   SHA that was published (the default is the current commit).
4. Run **Application** with `image-tag` for later releases.

### Option B: command line

From the repository root, in a shell with `az` signed in:

```bash
ENV=tst
STAGE=platform
mkdir -p .azure/deploy
az bicep build --file infra/bicep/main.bicep --outfile .azure/deploy/main.json
az bicep build-params --file infra/bicep/parameters/$ENV.bicepparam --outfile .azure/deploy/compiled.json

# Writes parameters.json, and secure.parameters.json when DocumentDB Free is used.
# Refuses placeholders. For the workloads stage add:
#   --image-tag <40-character commit SHA> --registry <registry name>
export DOCUMENTDB_ADMIN_PASSWORD='<only with useDocumentDbFreeTier>'
python scripts/prepare_deployment.py --compiled .azure/deploy/compiled.json \
  --stage $STAGE --output-dir .azure/deploy

LOCATION=<value printed as location=...>
az deployment sub what-if --location $LOCATION --template-file .azure/deploy/main.json \
  --parameters @.azure/deploy/parameters.json
az deployment sub create  --location $LOCATION --name psa-$ENV-$STAGE \
  --template-file .azure/deploy/main.json --parameters @.azure/deploy/parameters.json
```

When the script reports `secure_parameters=true`, add
`@.azure/deploy/secure.parameters.json` as a second `--parameters` argument.
The `.azure/` directory is git-ignored; delete the secure file when you finish.

Publish the images from a machine that can reach the private registry:

```bash
REGISTRY=<registry name>.azurecr.io
TAG=$(git rev-parse HEAD)
az acr login --name <registry name>
docker build -f Containerfile -t $REGISTRY/product-support-api:$TAG .
docker build -f apps/web/Containerfile -t $REGISTRY/product-support-web:$TAG apps/web
docker push $REGISTRY/product-support-api:$TAG
docker push $REGISTRY/product-support-web:$TAG
```

Then run the `workloads` stage with `--image-tag $TAG --registry <registry name>`.

## Test the environment

Use the deployment outputs for names (`az deployment sub show --name <name>
--query properties.outputs`).

1. **Resources are healthy.** All deployments report `Succeeded`; the API and
   web revisions are `Running`:

   ```bash
   az containerapp show -g <rg> -n <api-app> --query properties.runningStatus -o tsv
   az containerapp show -g <rg> -n <web-app> --query properties.configuration.ingress.fqdn -o tsv
   ```
2. **Run ingestion** and wait for it to finish:

   ```bash
   az containerapp job start -g <rg> -n <ingestion-job>
   az containerapp job execution list -g <rg> -n <ingestion-job> -o table
   ```

   The job creates the Search index on first use. A complete run reports 10
   products `success` and 90 `skipped` with `no_public_source`. Status is also
   available from the API (`GET /ingestion/runs/latest`) from inside the
   network.
3. **Use the web app.** Open the web app's address. The home page lists the 100
   catalog products with the indexed ones first. Ask a documentation question
   about an indexed product and check that the answer has citations that open
   public documentation pages. Ask about an uncovered product, or an off-topic
   question, and check for the standard refusal.
4. **Check telemetry.** In Application Insights, search for traces from the web
   app and API; one chat request is one trace across both services. Confirm
   that no span contains question or answer text.
5. **Test API Management** (when `deployApim=true`). The API requires a subscription key but the template does not create one.
   In the portal, add a subscription scoped to the `Product Support API`, then:

   ```bash
   curl -s -X POST "https://<gateway-host>/product-support/chat" \
     -H "Ocp-Apim-Subscription-Key: <key>" -H "Content-Type: application/json" \
     -d '{"message": "What does <product> support?"}'
   ```

   A request without the key must return 401. Exceeding 30 calls per minute per
   key must return 429.
6. **Run the evaluation** (optional). The runner calls the API's `/chat`
   directly and also queries Search and Foundry with the keys in `.env`, so run
   it from a machine inside the virtual network:
   `python scripts/run_evaluation.py --api-url <internal API URL> --report <file>`.
   Pass `--report` so that the committed report is not overwritten.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Deployment succeeds in validation but fails creating DocumentDB Free or a model deployment | Validation does not check regional availability. Choose a supported `documentDbLocation` or `location`, or use Cosmos DB for MongoDB |
| Chat or ingestion returns 429 or a 502 | Model capacity is too low. Raise the `gpt-5` and embedding capacity |
| `workloads` stage fails: image not found | The images for that tag are not in the registry. Publish first and use the same tag |
| Publish job waits for a runner | No runner has the `<env>-vnet` label |
| Ingestion exits with "another ingestion run holds the lease" | A stopped run left its lease. See the [runbook](../docs/architecture/support-ownership.md#runbooks) |
| Concurrent Foundry project and model deployment errors | The template already serialises them; re-run the stage |
| Container Apps Consumption profile rejects node counts | Do not set `minimumCount` or `maximumCount` on the Consumption profile |
| The API rejects its environment | The application accepts `local`, `test`, or `production`; the template maps `prd` to `production` and everything else to `test` |
| Key Vault or Foundry names are "in use" after a delete | Soft-deleted resources hold the name. Purge them (below) |

## Cost

Resources that bill while they exist include API Management (Developer is
about the cost of a small VM; Premium is far higher), Azure AI Search Basic,
the Premium registry, the NAT gateway, Container Apps replicas, and Foundry
usage. Check current prices for your region and set a budget with alerts. An
Azure budget is not a spending cap.

## Remove an environment

```bash
az group delete --name <rg> --yes --no-wait
```

Then purge soft-deleted resources so the names can be reused:

```bash
az keyvault purge --name <key-vault-name>
az cognitiveservices account purge --location <location> --resource-group <rg> --name <foundry-account>
az apim deletedservice purge --service-name <apim-name> --location <location>
```

## Validate the templates offline

Run these before a review. They need no Azure sign-in:

```bash
az bicep build --file infra/bicep/main.bicep --stdout > /dev/null
az bicep build-params --file infra/bicep/parameters/dev.bicepparam --stdout > /dev/null
az bicep lint --file infra/bicep/main.bicep
python -m pytest tests/unit/test_workflows.py tests/unit/test_prepare_deployment.py
```

The `infra.yml` workflow repeats the Bicep checks for all three environments.

## Smoke parameters

`infra/bicep/smoke.bicepparam` is a ready-made parameter set for testing the
template itself: `tst`, a new Foundry account, DocumentDB Free, API Management,
public hello-world images on port 80, and a manual ingestion job. Use it only
for template tests. To test the application, deploy with real images and
`apiTargetPort` 8000 and `webTargetPort` 3000, as the pipelines do.

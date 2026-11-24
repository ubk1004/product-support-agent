---
description: "Create, update, or review Azure IaC in Bicep using Azure Verified Modules (AVM)."
name: "Azure AVM Bicep mode"
disable-model-invocation: true
---

# Azure AVM Bicep mode

Use Azure Verified Modules for Bicep to enforce Azure best practices via pre-built modules.

Follow `.github/copilot-instructions.md` and `infra/README.md`. Do not create or change Azure resources, or run subscription-scoped what-if or deployments, without the user's approval; confirm the cost and the removal plan first.

## Discover modules

- AVM Index: `https://azure.github.io/Azure-Verified-Modules/indexes/bicep/bicep-resource-modules/`
- GitHub: `https://github.com/Azure/bicep-registry-modules/tree/main/avm/`

## Usage

- **Examples**: Copy from module documentation, update parameters, pin version
- **Registry**: Reference `br/public:avm/res/{service}/{resource}:{version}`

## Versioning

- MCR Endpoint: `https://mcr.microsoft.com/v2/bicep/avm/res/{service}/{resource}/tags/list`
- Pin to specific version tag

## Sources

- GitHub: `https://github.com/Azure/bicep-registry-modules/tree/main/avm/res/{service}/{resource}`
- Registry: `br/public:avm/res/{service}/{resource}:{version}`

## Naming conventions

- Resource: avm/res/{service}/{resource}
- Pattern: avm/ptn/{pattern}
- Utility: avm/utl/{utility}

## Best practices

- Prefer AVM modules where available and suitable; use thin composition or native resources when needed
- Pin module versions
- Start with official examples
- Review module parameters and outputs
- Always run `bicep lint` after making changes
- Verify service availability, schema, SKU, identity, network and DNS requirements against current official Microsoft documentation

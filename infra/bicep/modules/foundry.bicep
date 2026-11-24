@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region with GlobalStandard quota for both models.')
param location string

@description('Short region token used in resource names.')
@minLength(3)
@maxLength(3)
param locationAbbreviation string

@description('Mandatory resource tags.')
param tags object

@description('GPT-5 GlobalStandard capacity in 1,000 tokens-per-minute units. Pay-per-token; this is a rate limit, not a reservation.')
@minValue(1)
param chatCapacity int = 10

@description('Embedding GlobalStandard capacity in 1,000 tokens-per-minute units. Pay-per-token; this is a rate limit, not a reservation.')
@minValue(1)
param embeddingCapacity int = 20

var accountName = 'aif-psa-${environment}-${locationAbbreviation}-${instance}-${substring(uniqueString(resourceGroup().id), 0, 8)}'
var projectName = 'product-support'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: false
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Product Support Agent'
    description: 'Isolated product-support deployment.'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: 'gpt-5'
  sku: {
    name: 'GlobalStandard'
    capacity: chatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5'
      version: '2025-08-07'
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
  // Project and deployment writes share the account lock during redeployment.
  dependsOn: [
    project
  ]
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: 'text-embedding-3-small'
  sku: {
    name: 'GlobalStandard'
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
  dependsOn: [
    chatDeployment
  ]
}

output accountName string = account.name
output openAiEndpoint string = 'https://${account.name}.openai.azure.com/'
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output chatDeploymentName string = chatDeployment.name
output embeddingDeploymentName string = embeddingDeployment.name

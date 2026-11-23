targetScope = 'subscription'

@description('Deployment environment used in resource names and tags.')
@minLength(3)
@maxLength(3)
@allowed([
  'dev'
  'tst'
  'prd'
])
param environment string = 'dev'

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string = '01'

@description('Azure region for the deployment.')
param location string = 'canadacentral'

@description('Non-secret owner tag value.')
@minLength(2)
@maxLength(64)
param owner string = 'platform-team'

@description('Non-secret cost center tag value.')
@minLength(1)
@maxLength(32)
param costCenter string = 'TBD'

@description('Public Microsoft Foundry endpoint used by the demo.')
@minLength(1)
@maxLength(255)
param foundryEndpoint string = 'https://<foundry-resource>.openai.azure.com/'

@description('Name of the existing Microsoft Foundry chat deployment.')
@minLength(1)
@maxLength(64)
param foundryChatDeployment string = 'chat-deployment-placeholder'

@description('Name of the existing Microsoft Foundry embeddings deployment.')
@minLength(1)
@maxLength(64)
param foundryEmbeddingDeployment string = 'embedding-deployment-placeholder'

@description('Container image reference for the API.')
@minLength(1)
@maxLength(512)
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Container image reference for the web application.')
@minLength(1)
@maxLength(512)
param webImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Deploy the optional API Management service. Keep false for the demo.')
param deployApim bool = false

var resourceGroupName = 'rg-psa-${environment}-cac-${instance}'
var tags = {
  application: 'product-support-agent'
  costCenter: costCenter
  environment: environment
  managedBy: 'bicep'
  owner: owner
}

module resourceGroup 'br/public:avm/res/resources/resource-group:0.4.4' = {
  name: 'create-resource-group'
  params: {
    name: resourceGroupName
    location: location
    tags: tags
    enableTelemetry: false
  }
}

resource deploymentResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' existing = {
  name: resourceGroupName
}

module network 'modules/network.bicep' = {
  name: 'network'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    tags: tags
  }
  dependsOn: [
    resourceGroup
  ]
}

module platform 'modules/platform.bicep' = {
  name: 'platform'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    tags: tags
  }
  dependsOn: [
    resourceGroup
  ]
}

module data 'modules/data.bicep' = {
  name: 'data'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    virtualNetworkId: network.outputs.virtualNetworkId
    keyVaultId: platform.outputs.keyVaultId
    registryId: platform.outputs.registryId
    tags: tags
  }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    keyVaultName: platform.outputs.keyVaultName
    registryName: platform.outputs.registryName
    tags: tags
  }
}

module containerApps 'modules/container-apps.bicep' = {
  name: 'container-apps'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    tags: tags
    containerAppsSubnetId: network.outputs.containerAppsSubnetId
    logAnalyticsWorkspaceId: platform.outputs.logAnalyticsWorkspaceId
    logAnalyticsCustomerId: platform.outputs.logAnalyticsCustomerId
    logAnalyticsSharedKey: platform.outputs.logAnalyticsSharedKey
    keyVaultUri: platform.outputs.keyVaultUri
    registryLoginServer: platform.outputs.registryLoginServer
    apiIdentityId: identity.outputs.apiIdentityId
    ingestionIdentityId: identity.outputs.ingestionIdentityId
    registryPullIdentityId: identity.outputs.registryPullIdentityId
    searchEndpoint: data.outputs.searchEndpoint
    foundryEndpoint: foundryEndpoint
    foundryChatDeployment: foundryChatDeployment
    foundryEmbeddingDeployment: foundryEmbeddingDeployment
    apiImage: apiImage
    webImage: webImage
  }
}

module apim 'modules/apim.bicep' = if (deployApim) {
  name: 'optional-apim'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    tags: tags
  }
  dependsOn: [
    resourceGroup
  ]
}

output resourceGroupName string = resourceGroupName
output virtualNetworkId string = network.outputs.virtualNetworkId
output containerAppsEnvironmentName string = containerApps.outputs.environmentName
output apiContainerAppName string = containerApps.outputs.apiAppName
output webContainerAppName string = containerApps.outputs.webAppName
output ingestionJobName string = containerApps.outputs.ingestionJobName

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

@description('Short region token used in resource names.')
@minLength(3)
@maxLength(3)
param locationAbbreviation string = location == 'canadaeast' ? 'cae' : 'cac'

@description('Create a Foundry account, project and pay-per-token model deployments instead of using an existing endpoint.')
param deployFoundry bool = false

@description('Deploy application resources after platform provisioning and workload role propagation.')
param deployWorkloads bool = true

@description('Use Azure DocumentDB Free tier instead of the RU-based Cosmos DB for MongoDB account.')
param useDocumentDbFreeTier bool = false

@description('Azure region for the optional DocumentDB Free cluster; private endpoints remain in the deployment region.')
param documentDbLocation string = location

@description('DocumentDB native administrator password, supplied securely only when useDocumentDbFreeTier is true.')
@secure()
param documentDbAdministratorPassword string = ''

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

@description('Embedding model version used to name the Azure AI Search index.')
@minLength(1)
@maxLength(64)
param embeddingModelVersion string = 'text-embedding-3-small'

@description('Embedding vector dimensions for the deployment and the Search index.')
@minValue(1)
param embeddingDimensions int = 1536

@description('Container image reference for the API.')
@minLength(1)
@maxLength(512)
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Container image reference for the web application.')
@minLength(1)
@maxLength(512)
param webImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('API container listening port. Use 80 for the public infrastructure smoke-test image.')
@minValue(1)
@maxValue(65535)
param apiTargetPort int = 8000

@description('Web container listening port. Use 80 for the public infrastructure smoke-test image.')
@minValue(1)
@maxValue(65535)
param webTargetPort int = 3000

@description('Run ingestion on its weekly schedule. Disable for infrastructure-only smoke tests.')
param scheduleIngestion bool = true

@description('Deploy the classic API Management service in external VNet mode. Off by default; it adds a Developer or Premium instance with a monthly cost.')
param deployApim bool = false

@description('Premium scale units; ignored for Developer.')
@minValue(1)
@maxValue(10)
param apimSkuCapacity int = 1

@description('API Management publisher e-mail. Replace the placeholder before deploying.')
param apimPublisherEmail string = 'apim-owner@example.invalid'

@description('API Management publisher name.')
param apimPublisherName string = 'Product Support Agent'

var resourceGroupName = 'rg-psa-${environment}-${locationAbbreviation}-${instance}'
var resolvedApimSku = environment == 'prd' ? 'Premium' : 'Developer'
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
    locationAbbreviation: locationAbbreviation
    tags: tags
    deployApim: deployApim
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
    locationAbbreviation: locationAbbreviation
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
    locationAbbreviation: locationAbbreviation
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    virtualNetworkId: network.outputs.virtualNetworkId
    keyVaultId: platform.outputs.keyVaultId
    registryId: platform.outputs.registryId
    useDocumentDbFreeTier: useDocumentDbFreeTier
    documentDbLocation: documentDbLocation
    documentDbAdministratorPassword: documentDbAdministratorPassword
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
    locationAbbreviation: locationAbbreviation
    keyVaultName: platform.outputs.keyVaultName
    registryName: platform.outputs.registryName
    applicationInsightsName: platform.outputs.applicationInsightsName
    storageAccountName: data.outputs.storageAccountName
    tags: tags
  }
}

module foundry 'modules/foundry.bicep' = if (deployFoundry) {
  name: 'foundry'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    locationAbbreviation: locationAbbreviation
    tags: tags
  }
  dependsOn: [
    resourceGroup
  ]
}

module secrets 'modules/secrets.bicep' = if (deployFoundry) {
  name: 'bootstrap-secrets'
  scope: deploymentResourceGroup
  params: {
    keyVaultName: platform.outputs.keyVaultName
    cosmosAccountName: data.outputs.cosmosAccountName
    searchServiceName: data.outputs.searchServiceName
    foundryAccountName: foundry!.outputs.accountName
    useDocumentDbFreeTier: useDocumentDbFreeTier
    documentDbClusterName: data.outputs.documentDbClusterName
    documentDbAdministratorPassword: documentDbAdministratorPassword
  }
}

module containerApps 'modules/container-apps.bicep' = if (deployWorkloads) {
  name: 'container-apps'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    locationAbbreviation: locationAbbreviation
    tags: tags
    containerAppsSubnetId: network.outputs.containerAppsSubnetId
    logAnalyticsWorkspaceId: platform.outputs.logAnalyticsWorkspaceId
    logAnalyticsCustomerId: platform.outputs.logAnalyticsCustomerId
    logAnalyticsSharedKey: platform.outputs.logAnalyticsSharedKey
    applicationInsightsConnectionString: platform.outputs.applicationInsightsConnectionString
    apiIdentityClientId: identity.outputs.apiIdentityClientId
    ingestionIdentityClientId: identity.outputs.ingestionIdentityClientId
    keyVaultUri: platform.outputs.keyVaultUri
    registryLoginServer: platform.outputs.registryLoginServer
    apiIdentityId: identity.outputs.apiIdentityId
    ingestionIdentityId: identity.outputs.ingestionIdentityId
    registryPullIdentityId: identity.outputs.registryPullIdentityId
    searchEndpoint: data.outputs.searchEndpoint
    queueServiceUrl: data.outputs.queueServiceUrl
    ingestionQueueName: data.outputs.queueName
    foundryEndpoint: deployFoundry ? foundry!.outputs.openAiEndpoint : foundryEndpoint
    foundryChatDeployment: deployFoundry ? foundry!.outputs.chatDeploymentName : foundryChatDeployment
    foundryEmbeddingDeployment: deployFoundry ? foundry!.outputs.embeddingDeploymentName : foundryEmbeddingDeployment
    embeddingModelVersion: embeddingModelVersion
    embeddingDimensions: embeddingDimensions
    apiImage: apiImage
    webImage: webImage
    apiTargetPort: apiTargetPort
    webTargetPort: webTargetPort
    scheduleIngestion: scheduleIngestion
  }
  dependsOn: [
    secrets
  ]
}

module apim 'modules/apim.bicep' = if (deployApim && deployWorkloads) {
  name: 'optional-apim'
  scope: deploymentResourceGroup
  params: {
    environment: environment
    instance: instance
    location: location
    locationAbbreviation: locationAbbreviation
    tags: tags
    skuName: resolvedApimSku
    skuCapacity: apimSkuCapacity
    subnetId: network.outputs.apimSubnetId
    publicIpAddressId: network.outputs.apimPublicIpId
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    applicationInsightsId: platform.outputs.applicationInsightsId
    applicationInsightsConnectionString: platform.outputs.applicationInsightsConnectionString
    logAnalyticsWorkspaceId: platform.outputs.logAnalyticsWorkspaceId
    backendUrl: 'https://${containerApps!.outputs.apiAppFqdn}'
  }
}

output resourceGroupName string = resourceGroupName
output virtualNetworkId string = network.outputs.virtualNetworkId
output containerAppsEnvironmentName string = deployWorkloads ? containerApps!.outputs.environmentName : ''
output apiContainerAppName string = deployWorkloads ? containerApps!.outputs.apiAppName : ''
output webContainerAppName string = deployWorkloads ? containerApps!.outputs.webAppName : ''
output ingestionJobName string = deployWorkloads ? containerApps!.outputs.ingestionJobName : ''
output apimSku string = deployApim && deployWorkloads ? resolvedApimSku : 'not deployed'
output foundryAccountName string = deployFoundry ? foundry!.outputs.accountName : ''
output foundryProjectEndpoint string = deployFoundry ? foundry!.outputs.projectEndpoint : ''
output foundryOpenAiEndpoint string = deployFoundry ? foundry!.outputs.openAiEndpoint : foundryEndpoint

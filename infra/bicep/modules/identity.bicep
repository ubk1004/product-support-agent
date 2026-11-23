@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region for identity resources.')
param location string

@description('Key Vault name used for the secret-reader role scope.')
@minLength(3)
@maxLength(24)
param keyVaultName string

@description('Container registry name used for the image-pull role scope.')
@minLength(5)
@maxLength(50)
param registryName string

@description('Application Insights name used for the telemetry-publisher role scope.')
param applicationInsightsName string

@description('Storage account that holds the ingestion queue, for the queue data role scope.')
param storageAccountName string

@description('Mandatory resource tags.')
param tags object

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var monitoringMetricsPublisherRoleId = '3913510d-42f4-4e42-8a64-420c390055eb'
// Storage Queue Data Message Processor reads and deletes; Sender adds messages. The ingestion
// job both enqueues a run and processes it, so it needs both. Shared keys stay disabled.
var queueMessageProcessorRoleId = '8a0f0c08-91a1-4084-bc3d-661d67233fed'
var queueMessageSenderRoleId = 'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-api-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
}

resource ingestionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-ingest-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
}

resource registryPullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-acr-pull-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource apiTelemetryPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(applicationInsights.id, apiIdentity.id, monitoringMetricsPublisherRoleId)
  scope: applicationInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisherRoleId)
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ingestionTelemetryPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(applicationInsights.id, ingestionIdentity.id, monitoringMetricsPublisherRoleId)
  scope: applicationInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisherRoleId)
    principalId: ingestionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource apiKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, apiIdentity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ingestionKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, ingestionIdentity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: ingestionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource ingestionQueueProcessor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, ingestionIdentity.id, queueMessageProcessorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueMessageProcessorRoleId)
    principalId: ingestionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource ingestionQueueSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, ingestionIdentity.id, queueMessageSenderRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueMessageSenderRoleId)
    principalId: ingestionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource registryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, registryPullIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: registryPullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output apiIdentityId string = apiIdentity.id
output apiIdentityPrincipalId string = apiIdentity.properties.principalId
output apiIdentityClientId string = apiIdentity.properties.clientId
output ingestionIdentityId string = ingestionIdentity.id
output ingestionIdentityPrincipalId string = ingestionIdentity.properties.principalId
output ingestionIdentityClientId string = ingestionIdentity.properties.clientId
output registryPullIdentityId string = registryPullIdentity.id
output registryPullIdentityPrincipalId string = registryPullIdentity.properties.principalId
output apiKeyVaultRoleAssignmentId string = apiKeyVaultSecretsUser.id
output ingestionKeyVaultRoleAssignmentId string = ingestionKeyVaultSecretsUser.id
output registryPullRoleAssignmentId string = registryPull.id

@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region for Container Apps resources.')
param location string

@description('Mandatory resource tags.')
param tags object

@description('Container Apps infrastructure subnet resource ID.')
param containerAppsSubnetId string

@description('Log Analytics workspace resource ID.')
param logAnalyticsWorkspaceId string

@description('Log Analytics workspace customer ID.')
param logAnalyticsCustomerId string

@description('Log Analytics workspace shared key. This is an internal secure module output.')
@secure()
param logAnalyticsSharedKey string

@description('Key Vault URI used for secret references; no secret values are parameters.')
param keyVaultUri string

@description('Private ACR login server.')
param registryLoginServer string

@description('API workload managed identity resource ID.')
param apiIdentityId string

@description('Ingestion workload managed identity resource ID.')
param ingestionIdentityId string

@description('ACR image-pull managed identity resource ID.')
param registryPullIdentityId string

@description('Azure AI Search private endpoint address.')
param searchEndpoint string

@description('Microsoft Foundry public endpoint parameter.')
@minLength(1)
@maxLength(255)
param foundryEndpoint string

@description('Microsoft Foundry chat deployment name parameter.')
@minLength(1)
@maxLength(64)
param foundryChatDeployment string

@description('Microsoft Foundry embeddings deployment name parameter.')
@minLength(1)
@maxLength(64)
param foundryEmbeddingDeployment string

@description('API container image reference.')
@minLength(1)
@maxLength(512)
param apiImage string

@description('Web container image reference.')
@minLength(1)
@maxLength(512)
param webImage string

var environmentName = 'cae-psa-${environment}-cac-${instance}'
var apiAppName = 'ca-api-psa-${environment}-cac-${instance}'
var webAppName = 'ca-web-psa-${environment}-cac-${instance}'
var ingestionJobName = 'job-ingest-psa-${environment}-cac-${instance}'
var apiKeyVaultUrl = '${keyVaultUri}secrets/azure-openai-api-key'
var searchKeyVaultUrl = '${keyVaultUri}secrets/azure-ai-search-api-key'
var mongoKeyVaultUrl = '${keyVaultUri}secrets/mongodb-connection-string'
var apiContainerIdentity = {
  '${apiIdentityId}': {}
  '${registryPullIdentityId}': {}
}
var ingestionContainerIdentity = {
  '${ingestionIdentityId}': {}
  '${registryPullIdentityId}': {}
}
var registryContainerIdentity = {
  '${registryPullIdentityId}': {}
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: containerAppsSubnetId
      internal: false
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
        minimumCount: 0
        maximumCount: 3
      }
    ]
    zoneRedundant: false
  }
}

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: apiContainerIdentity
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryLoginServer
          identity: registryPullIdentityId
        }
      ]
      secrets: [
        {
          name: 'mongodb-connection-string'
          keyVaultUrl: mongoKeyVaultUrl
          identity: apiIdentityId
        }
        {
          name: 'azure-ai-search-api-key'
          keyVaultUrl: searchKeyVaultUrl
          identity: apiIdentityId
        }
        {
          name: 'azure-openai-api-key'
          keyVaultUrl: apiKeyVaultUrl
          identity: apiIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'PRODUCT_SUPPORT_MONGODB_URI'
              secretRef: 'mongodb-connection-string'
            }
            {
              name: 'AZURE_AI_SEARCH_ENDPOINT'
              value: searchEndpoint
            }
            {
              name: 'AZURE_AI_SEARCH_API_KEY'
              secretRef: 'azure-ai-search-api-key'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: foundryEndpoint
            }
            {
              name: 'AZURE_OPENAI_CHAT_DEPLOYMENT'
              value: foundryChatDeployment
            }
            {
              name: 'AZURE_OPENAI_EMBEDDING_ENDPOINT'
              value: foundryEndpoint
            }
            {
              name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
              value: foundryEmbeddingDeployment
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'azure-openai-api-key'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
      }
    }
  }
}

resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: webAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: registryContainerIdentity
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 3000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryLoginServer
          identity: registryPullIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'PRODUCT_SUPPORT_API_BASE_URL'
              value: 'https://${apiApp.properties.configuration.ingress.fqdn}'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
      }
    }
  }
}

resource ingestionJob 'Microsoft.App/jobs@2024-03-01' = {
  name: ingestionJobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: ingestionContainerIdentity
  }
  properties: {
    environmentId: containerAppsEnvironment.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 3600
      replicaRetryLimit: 0
      registries: [
        {
          server: registryLoginServer
          identity: registryPullIdentityId
        }
      ]
      secrets: [
        {
          name: 'mongodb-connection-string'
          keyVaultUrl: mongoKeyVaultUrl
          identity: ingestionIdentityId
        }
        {
          name: 'azure-ai-search-api-key'
          keyVaultUrl: searchKeyVaultUrl
          identity: ingestionIdentityId
        }
        {
          name: 'azure-openai-api-key'
          keyVaultUrl: apiKeyVaultUrl
          identity: ingestionIdentityId
        }
      ]
      scheduleTriggerConfig: {
        cronExpression: '0 0 2 * * 0'
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [
        {
          name: 'ingestion'
          image: apiImage
          command: [
            'python'
            'scripts/run_source_ingestion.py'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'PRODUCT_SUPPORT_MONGODB_URI'
              secretRef: 'mongodb-connection-string'
            }
            {
              name: 'PRODUCT_SUPPORT_SOURCE_MAP_PATH'
              value: '/app/docs/operations/phase-3-source-map-v1.json'
            }
            {
              name: 'AZURE_AI_SEARCH_ENDPOINT'
              value: searchEndpoint
            }
            {
              name: 'AZURE_AI_SEARCH_API_KEY'
              secretRef: 'azure-ai-search-api-key'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: foundryEndpoint
            }
            {
              name: 'AZURE_OPENAI_CHAT_DEPLOYMENT'
              value: foundryChatDeployment
            }
            {
              name: 'AZURE_OPENAI_EMBEDDING_ENDPOINT'
              value: foundryEndpoint
            }
            {
              name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
              value: foundryEmbeddingDeployment
            }
            {
              name: 'AZURE_OPENAI_API_KEY'
              secretRef: 'azure-openai-api-key'
            }
          ]
        }
      ]
    }
  }
}

output environmentName string = containerAppsEnvironment.name
output apiAppName string = apiApp.name
output apiAppFqdn string = apiApp.properties.configuration.ingress.fqdn
output webAppName string = webApp.name
output webAppFqdn string = webApp.properties.configuration.ingress.fqdn
output ingestionJobName string = ingestionJob.name
output logAnalyticsWorkspaceId string = logAnalyticsWorkspaceId

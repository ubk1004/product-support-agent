@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region for data resources.')
param location string

@description('Private endpoint subnet resource ID.')
param privateEndpointSubnetId string

@description('Virtual network resource ID for private DNS links.')
param virtualNetworkId string

@description('Key Vault resource ID for its private endpoint.')
param keyVaultId string

@description('Container registry resource ID for its private endpoint.')
param registryId string

@description('Mandatory resource tags.')
param tags object

var nameHash = substring(uniqueString(resourceGroup().id), 0, 8)
var cosmosAccountName = 'cosmos-psa-${environment}-cac-${instance}-${nameHash}'
var storageAccountName = 'psa${environment}${instance}${substring(uniqueString(resourceGroup().id), 0, 13)}'
var searchServiceName = 'search-psa-${environment}-cac-${instance}-${nameHash}'
var queueName = 'product-ingestion'
var dnsNames = [
  'privatelink.mongo.cosmos.azure.com'
  'privatelink.queue.${az.environment().suffixes.storage}'
  'privatelink.search.windows.net'
  'privatelink.vaultcore.azure.net'
  'privatelink.azurecr.io'
]

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosAccountName
  location: location
  tags: tags
  kind: 'MongoDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableMongo'
      }
    ]
    enableFreeTier: false
    publicNetworkAccess: 'Disabled'
    networkAclBypass: 'None'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
    }
  }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource ingestionQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: queueName
}

// Messages delivered too many times are moved here by the worker for investigation.
resource poisonQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: '${queueName}-poison'
}

resource searchService 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchServiceName
  location: location
  tags: tags
  sku: {
    name: 'basic'
  }
  properties: {
    disableLocalAuth: false
    publicNetworkAccess: 'disabled'
    partitionCount: 1
    replicaCount: 1
    semanticSearch: 'disabled'
  }
}

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' = [for dnsName in dnsNames: {
  name: dnsName
  location: 'global'
  tags: tags
}]

resource privateDnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (dnsName, index) in dnsNames: {
  parent: privateDnsZones[index]
  name: 'link-${environment}-${instance}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}]

resource cosmosPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-cosmos-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'cosmos-mongodb'
        properties: {
          privateLinkServiceId: cosmosAccount.id
          groupIds: [
            'MongoDB'
          ]
        }
      }
    ]
  }
}

resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-queue-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'storage-queue'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'queue'
          ]
        }
      }
    ]
  }
}

resource searchPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-search-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'azure-ai-search'
        properties: {
          privateLinkServiceId: searchService.id
          groupIds: [
            'searchService'
          ]
        }
      }
    ]
  }
}

resource keyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-keyvault-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'key-vault'
        properties: {
          privateLinkServiceId: keyVaultId
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource registryPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-acr-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'container-registry'
        properties: {
          privateLinkServiceId: registryId
          groupIds: [
            'registry'
          ]
        }
      }
    ]
  }
}

resource cosmosDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: cosmosPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cosmos-mongodb'
        properties: {
          privateDnsZoneId: privateDnsZones[0].id
        }
      }
    ]
  }
}

resource storageDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: storagePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'storage-queue'
        properties: {
          privateDnsZoneId: privateDnsZones[1].id
        }
      }
    ]
  }
}

resource searchDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: searchPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'azure-ai-search'
        properties: {
          privateDnsZoneId: privateDnsZones[2].id
        }
      }
    ]
  }
}

resource keyVaultDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: keyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'key-vault'
        properties: {
          privateDnsZoneId: privateDnsZones[3].id
        }
      }
    ]
  }
}

resource registryDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: registryPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'container-registry'
        properties: {
          privateDnsZoneId: privateDnsZones[4].id
        }
      }
    ]
  }
}

output cosmosAccountName string = cosmosAccount.name
output storageAccountName string = storageAccount.name
output queueName string = ingestionQueue.name
output queueServiceUrl string = storageAccount.properties.primaryEndpoints.queue
output queueId string = ingestionQueue.id
output searchServiceName string = searchService.name
output searchEndpoint string = searchService.properties.endpoint
output privateDnsZoneNames array = dnsNames
output cosmosPrivateEndpointName string = cosmosPrivateEndpoint.name
output storagePrivateEndpointName string = storagePrivateEndpoint.name
output searchPrivateEndpointName string = searchPrivateEndpoint.name
output keyVaultPrivateEndpointName string = keyVaultPrivateEndpoint.name
output registryPrivateEndpointName string = registryPrivateEndpoint.name

@description('Key Vault receiving workload secrets through the ARM control plane.')
@minLength(3)
@maxLength(24)
param keyVaultName string

@description('New Cosmos DB for MongoDB account name.')
param cosmosAccountName string

@description('New Azure AI Search service name.')
param searchServiceName string

@description('New Foundry account name.')
param foundryAccountName string

@description('Read native DocumentDB credentials instead of Cosmos DB account keys.')
param useDocumentDbFreeTier bool = false

@description('DocumentDB cluster name when useDocumentDbFreeTier is true.')
param documentDbClusterName string = ''

@description('DocumentDB native administrator password. Never output this value.')
@secure()
param documentDbAdministratorPassword string = ''

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosAccountName
}

resource searchService 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource documentDbCluster 'Microsoft.DocumentDB/mongoClusters@2026-06-01' existing = {
  name: documentDbClusterName
}

resource mongoSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'mongodb-connection-string'
  properties: {
    value: useDocumentDbFreeTier
      ? replace(
          replace(documentDbCluster.properties.connectionString, '<user>', uriComponent(documentDbCluster.properties.administrator.userName)),
          '<password>',
          uriComponent(documentDbAdministratorPassword)
        )
      : cosmosAccount.listConnectionStrings().connectionStrings[0].connectionString
  }
}

resource searchSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'azure-ai-search-api-key'
  properties: {
    value: searchService.listAdminKeys().primaryKey
  }
}

resource foundrySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'azure-openai-api-key'
  properties: {
    value: foundryAccount.listKeys().key1
  }
}

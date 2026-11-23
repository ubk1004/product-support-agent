using '../main.bicep'

param environment = 'prd'
param instance = '01'
param location = 'canadacentral'
param owner = 'team-placeholder'
param costCenter = 'TBD'
param foundryEndpoint = 'https://<foundry-resource>.openai.azure.com/'
param foundryChatDeployment = 'chat-deployment-placeholder'
param foundryEmbeddingDeployment = 'embedding-deployment-placeholder'
param embeddingModelVersion = 'text-embedding-3-small'
param embeddingDimensions = 1536
param apiImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param webImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param deployApim = true
param apimSkuCapacity = 1
param apimPublisherEmail = 'apim-owner@example.invalid'
param apimPublisherName = 'Product Support Agent'

using '../main.bicep'

param environment = 'dev'
param instance = '01'
param location = 'canadacentral'
param owner = 'team-placeholder'
param costCenter = 'TBD'
param foundryEndpoint = 'https://<foundry-resource>.openai.azure.com/'
param foundryChatDeployment = 'chat-deployment-placeholder'
param foundryEmbeddingDeployment = 'embedding-deployment-placeholder'
param apiImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param webImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param deployApim = false

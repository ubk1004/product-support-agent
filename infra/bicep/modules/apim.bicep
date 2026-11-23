@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region for API Management.')
param location string

@description('Mandatory resource tags.')
param tags object

var apiManagementName = 'apim-psa-${environment}-cac-${instance}-${substring(uniqueString(resourceGroup().id), 0, 8)}'

resource apiManagement 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apiManagementName
  location: location
  tags: tags
  sku: {
    name: 'Consumption'
    capacity: 0
  }
  properties: {
    publisherEmail: 'cloud-owner@example.invalid'
    publisherName: 'Product Support Agent'
    publicNetworkAccess: 'Enabled'
    virtualNetworkType: 'None'
  }
}

output apiManagementName string = apiManagement.name

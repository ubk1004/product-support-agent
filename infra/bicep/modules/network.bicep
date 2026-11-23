@description('Deployment environment used in resource names.')
@minLength(3)
@maxLength(3)
param environment string

@description('Two-digit resource instance number.')
@minLength(2)
@maxLength(2)
param instance string

@description('Azure region for the network resources.')
param location string

@description('Mandatory resource tags.')
param tags object

var virtualNetworkName = 'vnet-psa-${environment}-cac-${instance}'
var containerAppsNsgName = 'nsg-aca-psa-${environment}-cac-${instance}'
var privateEndpointsNsgName = 'nsg-pe-psa-${environment}-cac-${instance}'

resource containerAppsNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: containerAppsNsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowOutboundHttps'
        properties: {
          access: 'Allow'
          direction: 'Outbound'
          priority: 100
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource privateEndpointsNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: privateEndpointsNsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowVnetInbound'
        properties: {
          access: 'Allow'
          direction: 'Inbound'
          priority: 100
          protocol: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-nat-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource natGateway 'Microsoft.Network/natGateways@2024-05-01' = {
  name: 'nat-psa-${environment}-cac-${instance}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    idleTimeoutInMinutes: 10
    publicIpAddresses: [
      {
        id: publicIp.id
      }
    ]
  }
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: virtualNetworkName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.20.0.0/16'
      ]
    }
  }
}

resource containerAppsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'snet-container-apps'
  properties: {
    addressPrefix: '10.20.0.0/23'
    delegations: [
      {
        name: 'containerAppsEnvironment'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
    networkSecurityGroup: {
      id: containerAppsNsg.id
    }
    natGateway: {
      id: natGateway.id
    }
  }
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'snet-private-endpoints'
  properties: {
    addressPrefix: '10.20.2.0/24'
    privateEndpointNetworkPolicies: 'Disabled'
    networkSecurityGroup: {
      id: privateEndpointsNsg.id
    }
  }
}

output virtualNetworkId string = virtualNetwork.id
output virtualNetworkName string = virtualNetwork.name
output virtualNetworkAddressSpace string = '10.20.0.0/16'
output containerAppsSubnetId string = containerAppsSubnet.id
output containerAppsSubnetName string = containerAppsSubnet.name
output privateEndpointSubnetId string = privateEndpointSubnet.id
output privateEndpointSubnetName string = privateEndpointSubnet.name
output containerAppsNsgName string = containerAppsNsg.name
output privateEndpointsNsgName string = privateEndpointsNsg.name
output natGatewayName string = natGateway.name
output publicIpName string = publicIp.name
